# -*- coding: utf-8 -*-
"""音轨清理 v3（audio gate）：去掉「持续床音」，保留「对白 + 动作拟音」。

v2 的目标是「只留台词」，用谱减把非对白全部压掉 —— 副作用是脚步声、
珠子落入石槽、布料摩擦这些**由画面动作直接产生的拟音也被削薄**。

v3 改判据：音频里只有两类东西是坏的 ——
  ① 持续床音（环境风声/空间长混响/低频音乐垫）：跨段无法对齐，拼接必断层 → 清零
  ② 点状瞬态（脚步/碰撞/摩擦）：由动作产生，时长 50-400ms，不延续 → 原样保留

技术上靠「每频点时间低分位」估床音：床音在任何时刻都存在，所以它在每个频点
的时间轴上占满，低分位 ≈ 它自身电平；瞬态只占少数帧，低分位几乎看不到它。
这样减掉的只有「一直在响的东西」，不碰「响一下的东西」。

逐时频点用过减因子区分：接近床音的（snr≈1）狠减，显著高于床音的（对白/拟音）轻减。
再叠一层帧级判定：整帧都没有显著高于床音的点 → 该帧整体强压（真静音）。

用法:
  python audio_gate.py --in seg17.mp4 --out seg17_clean.mp4        # 清轨后与画面 mux
  python audio_gate.py --in seg17.mp4 --out seg17.wav --audio-only  # 只出音轨
"""
import argparse
import json
import os
import subprocess
import sys
import wave

import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import FFMPEG as FF  # noqa: E402
SR = 48000
NFFT = 1024       # 21ms
HOP = 256         # 5.3ms


def decode(path):
    tmp = os.path.splitext(path)[0] + "_gate_tmp.wav"
    subprocess.run([FF, "-y", "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", str(SR), "-f", "wav", tmp], check=True)
    with wave.open(tmp, "rb") as w:
        nch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    os.remove(tmp)
    if nch > 1:
        x = x.reshape(-1, nch)
    return x


def stft(sig):
    win = np.hanning(NFFT)
    n = 1 + max(len(sig) - NFFT, 0) // HOP
    frames = np.zeros((n, NFFT))
    for i in range(n):
        frames[i] = sig[i * HOP:i * HOP + NFFT] * win
    return np.fft.rfft(frames, axis=1), win


def istft(spec, win, length):
    frames = np.fft.irfft(spec, n=NFFT, axis=1)
    y = np.zeros(length + NFFT)
    wsum = np.zeros(length + NFFT)
    for i in range(len(frames)):
        y[i * HOP:i * HOP + NFFT] += frames[i] * win
        wsum[i * HOP:i * HOP + NFFT] += win ** 2
    y = y[:length]
    wsum = wsum[:length]
    y = y / np.maximum(wsum, 0.3)          # 钳制尾部欠覆盖，防末端能量放大
    edge = min(int(0.03 * SR), length // 4)
    ramp = np.linspace(0, 1, edge)
    y[:edge] *= ramp
    y[-edge:] *= ramp[::-1]
    return y


def bed_spectrum(spec, q=15, smooth=3, frame_sel=30):
    """估计「持续床音」谱。

    优先只在**低能量帧**（frame_sel 分位以下）上取每频点中位数 —— 这些帧里
    只有床音、没有对白与拟音，估计最干净；台词密集段（对白占一半时长）用全局
    分位会被语声污染、导致过减。低能量帧不足时回退到全局低分位。
    """
    mag = np.abs(spec)
    fe = np.sqrt(np.mean(mag ** 2, axis=1))
    thr = np.percentile(fe, frame_sel)
    sel = mag[fe <= thr]
    if len(sel) >= 10:
        bed = np.percentile(sel, 50, axis=0)
    else:
        bed = np.percentile(mag, q, axis=0)
    if smooth > 1:
        bed = np.convolve(bed, np.ones(smooth) / smooth, mode="same")
    return np.maximum(bed, 1e-6)


def suppress_bed(x, bed_q=15, alpha_bed=6.0, alpha_fx=1.0,
                 fx_snr=4.0, quiet_gain=0.03, smooth_ms=25, frame_sel=40):
    """床音抑制。返回 (处理后音频, 统计)。"""
    mono = x.mean(axis=1) if x.ndim > 1 else x
    spec_m, win = stft(mono)
    bed = bed_spectrum(spec_m, bed_q, frame_sel=frame_sel)

    out = np.zeros_like(x)
    nch = x.shape[1] if x.ndim > 1 else 1
    for ch in range(nch):
        sig = x[:, ch] if x.ndim > 1 else x
        s, _ = stft(sig)
        mag = np.abs(s)
        snr = mag / bed[None, :]
        # 2 倍(=6dB) 以下按床音狠减；6 倍(=15.6dB) 以上按瞬态/对白轻减；中间线性过渡
        w = np.clip((snr - 2.0) / 4.0, 0.0, 1.0)
        alpha_tf = alpha_bed + (alpha_fx - alpha_bed) * w
        clean = np.maximum(mag - alpha_tf * bed[None, :], 0.0)
        mask = clean / np.maximum(mag, 1e-9)

        # 帧级：整帧都没有显著高于床音的点 → 真静音，整体强压（利于跨段拼接）
        frame_snr = snr.max(axis=1)
        gate = np.where(frame_snr < fx_snr, quiet_gain, 1.0).astype(np.float32)
        # 平滑开关，避免抽气式咔哒（约 25ms）
        k = max(1, int(smooth_ms / (HOP / SR * 1000)))
        if k > 1:
            gate = np.convolve(gate, np.ones(k) / k, mode="same")

        out[:, ch] = istft(s * mask * gate[:, None], win, len(sig))
    if x.ndim == 1:
        out = out[:, 0]

    def floor_db(sig):
        m = sig.mean(axis=1) if sig.ndim > 1 else sig
        n = len(m) // NFFT
        if n < 4:
            return -120.0
        fr = np.sqrt(np.mean(m[:n * NFFT].reshape(n, NFFT) ** 2, axis=1))
        v = float(np.percentile(fr, 15))
        return -120.0 if v <= 1e-9 else 20 * np.log10(v)

    return np.clip(out, -1, 1), dict(
        floor_before_db=round(floor_db(x), 1),
        floor_after_db=round(floor_db(out), 1),
        level_change_db=round(20 * np.log10(max(float(np.sqrt(np.mean(out ** 2))), 1e-9)
                                           / max(float(np.sqrt(np.mean(x ** 2))), 1e-9)), 1),
        bed_bins_over_1k=int(np.sum(bed[: len(bed) // 3] > 1e-4)),
    )


def write_wav(path, y):
    y16 = (np.clip(y, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1 if y.ndim == 1 else y.shape[1])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(y16.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bed-q", type=float, default=15, help="回退时用的每频点低分位百分位")
    ap.add_argument("--frame-sel", type=float, default=40,
                    help="只用能量低于该分位的帧估计床音（避开对白/拟音）")
    ap.add_argument("--alpha-bed", type=float, default=6.0, help="床音过减因子")
    ap.add_argument("--alpha-fx", type=float, default=1.0, help="对白/拟音过减因子（越小越保留）")
    ap.add_argument("--fx-snr", type=float, default=4.0, help="帧级静音判定：最大 snr 低于此值即视为无内容")
    ap.add_argument("--quiet-gain", type=float, default=0.03, help="静音帧增益")
    ap.add_argument("--audio-only", action="store_true")
    a = ap.parse_args()

    x = decode(a.src)
    y, info = suppress_bed(x, a.bed_q, a.alpha_bed, a.alpha_fx, a.fx_snr,
                           a.quiet_gain, frame_sel=a.frame_sel)

    if a.audio_only:
        out = a.out
        write_wav(out, y)
    else:
        wav = os.path.splitext(a.out)[0] + "_clean.wav"
        write_wav(wav, y)
        subprocess.run([FF, "-y", "-v", "error", "-i", a.src, "-i", wav,
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", a.out], check=True)
        os.remove(wav)
        out = a.out

    print(json.dumps(dict(**{"in": a.src}, out=out, dur_s=round(len(x) / SR, 2), **info),
                     ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
