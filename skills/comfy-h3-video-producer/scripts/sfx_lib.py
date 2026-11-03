# -*- coding: utf-8 -*-
"""sfx_lib —— 程序化点状动作音效生成（音画分流的拟音侧兜底）。

点状拟音当前首选音效库实录音；找不到合适素材时，用本脚本生成基础款
（whoosh 呼啸 / impact 撞击 / snap 短促弹响）。全部纯 numpy 合成，无依赖。

用法：
  python sfx_lib.py whoosh  --out sfx/whoosh1.wav [--dur 0.8] [--seed 1]
  python sfx_lib.py impact  --out sfx/impact1.wav [--dur 0.6]
  python sfx_lib.py snap    --out sfx/snap1.wav
生成后用 audioprod film/auto 的 --sfx "时刻:路径@增益" 铺进时间轴。
"""
import argparse
import os
import wave

import numpy as np

SR = 24000


def _rng(seed):
    return np.random.default_rng(seed)


def _fft_bandpass(x, lo, hi, sr=SR):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    mask = np.ones_like(f)
    mask[f < lo] = 0.0
    mask[f > hi] = 0.0
    # 软边界
    w = (f >= lo) & (f < lo * 1.5)
    mask[w] = np.linspace(0, 1, w.sum())
    w = (f > hi / 1.5) & (f <= hi)
    mask[w] = np.linspace(1, 0, w.sum())
    return np.fft.irfft(X * mask, len(x))


def whoosh(dur=0.8, seed=1):
    """呼啸：带通噪声，中心频率 300→1800Hz 扫频，包络慢起快收。"""
    r = _rng(seed)
    n = int(dur * SR)
    noise = r.standard_normal(n).astype(np.float32)
    # 分块扫频（50ms 块，中心频率线性上扫）
    blk = int(0.05 * SR)
    out = np.zeros(n, dtype=np.float32)
    for i in range(0, n, blk):
        c = 300 + (1800 - 300) * (i / max(1, n - blk))
        b = _fft_bandpass(noise[i:i + blk], c * 0.6, c * 1.6)
        out[i:i + len(b)] += b[: n - i]
    env = np.hanning(n) ** 0.7  # 慢起快收
    return out * env


def impact(dur=0.6, seed=2):
    """撞击：低频正弦衰减 + 低通噪声冲击。"""
    r = _rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * 85 * t) * np.exp(-t * 9)
    knock = _fft_bandpass(r.standard_normal(n), 80, 400) * np.exp(-t * 18)
    x = (body * 0.8 + knock * 0.6).astype(np.float32)
    fade = int(0.01 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    return x


def snap(dur=0.12, seed=3):
    """弹响：极短高频噪声串，指数衰减。"""
    r = _rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = _fft_bandpass(r.standard_normal(n), 1800, 8000) * np.exp(-t * 60)
    return x.astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preset", choices=["whoosh", "impact", "snap"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    dur = a.dur or {"whoosh": 0.8, "impact": 0.6, "snap": 0.12}[a.preset]
    x = globals()[a.preset](dur, a.seed)
    peak = float(np.abs(x).max()) or 1.0
    x = x / peak * 10 ** (-3 / 20)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with wave.open(a.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    print(f"[sfx] {a.out}（{a.preset} {dur:.2f}s）")


if __name__ == "__main__":
    main()
