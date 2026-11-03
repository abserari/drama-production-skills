# -*- coding: utf-8 -*-
"""audio_gate 回归测试：用合成信号量化「床音清除率」与「拟音保留率」。

构造一段已知内容的音轨：
  · 持续床音：47Hz 谐波列（模拟 H3 的音乐垫）+ 低通白噪声（模拟风声）
  · 动作拟音：脚步（宽带短脉冲 40ms）、珠子落石槽（2.8kHz 衰减音 120ms）
  · 语声：180Hz 谐波列 + 5 个音节包络
然后跑 suppress_bed，比较处理前后：
  · 床音区 RMS 降了多少（目标 <= -50 dBFS）
  · 每个瞬态的峰值掉了多少（目标 <= 3dB，即保留）
  · 语声峰值掉了多少（目标 <= 3dB）

用法: python test_audio_gate.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audio_gate as G  # noqa: E402

SR = 48000
DUR = 9.0
rng = np.random.default_rng(7)


def synth():
    n = int(SR * DUR)
    t = np.arange(n) / SR
    pad = np.zeros(n)
    for k, g in [(1, 1.0), (2, 0.5), (3, 0.33), (5, 0.2), (8, 0.1)]:
        pad += g * np.sin(2 * np.pi * 47 * k * t + k)
    pad *= 10 ** (-40 / 20) / (np.std(pad) + 1e-9) * 0.25

    wind = np.convolve(rng.normal(size=n), np.ones(240) / 240, mode="same")
    wind *= 10 ** (-52 / 20) / (np.std(wind) + 1e-9) * 0.25

    x = np.zeros(n, np.float32)

    def burst(start, dur, lo, hi, peak_db, decay=4.0, tone=None):
        m = int(SR * dur)
        tt = np.arange(m) / SR
        if tone:
            s = np.sin(2 * np.pi * tone * tt)
        else:
            nz = rng.normal(size=m)
            F = np.fft.rfft(nz)
            f = np.fft.rfftfreq(m, 1 / SR)
            F[(f < lo) | (f > hi)] = 0
            s = np.fft.irfft(F, m)
        s = s / (np.max(np.abs(s)) + 1e-9)
        s = s * np.exp(-tt / (dur / decay))
        s = s * 10 ** (peak_db / 20)
        i = int(start * SR)
        x[i:i + m] += s.astype(np.float32)

    burst(2.0, 0.06, 200, 2500, -16)                 # 脚步
    burst(3.0, 0.15, 2000, 3500, -18, tone=2800)     # 珠子落石槽
    # 语声：180Hz 谐波 + 5 个音节
    m = int(SR * 1.6)
    tt = np.arange(m) / SR
    v = sum(np.sin(2 * np.pi * 180 * k * tt) / k for k in range(1, 7))
    syll = np.zeros(m)
    for s0, ln in [(0.0, 0.22), (0.3, 0.16), (0.55, 0.2), (0.85, 0.15), (1.15, 0.3)]:
        i0, i1 = int(s0 * SR), int((s0 + ln) * SR)
        syll[i0:i1] = np.hanning(i1 - i0)
    v = v / (np.max(np.abs(v)) + 1e-9) * syll
    v = v * 10 ** (-17 / 20)
    i = int(5.0 * SR)
    x[i:i + m] += v.astype(np.float32)

    x = x + pad.astype(np.float32) + wind.astype(np.float32)
    return np.stack([x, x], axis=1)


def peak(x, at, win=0.25):
    a, b = int((at - 0.05) * SR), int((at + win) * SR)
    return float(np.max(np.abs(x[a:b])))


def rms_db(x, a, b):
    seg = x[int(a * SR):int(b * SR)]
    return 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9)


def main():
    src = synth()
    marks = [("脚步", 2.0), ("珠声", 3.0), ("语声", 5.0)]
    print("原信号：床音区 %.1f dBFS\n" % rms_db(src, 0.4, 1.8))
    print(f"{'参数':<26}{'床音':>9}{'脚步':>9}{'珠声':>9}{'语声':>9}")
    print(f"{'处理前':<26}{rms_db(src, 0.4, 1.8):>9.1f}"
          + "".join(f"{20 * np.log10(peak(src, at) + 1e-9):>9.1f}" for _, at in marks))
    rows = []
    for fs in (25, 40, 60):
        for ab in (4.0, 6.0):
            y, info = G.suppress_bed(src, alpha_bed=ab, alpha_fx=1.0, frame_sel=fs)
            bed = rms_db(y, 0.4, 1.8)
            deltas = [20 * np.log10((peak(y, at) + 1e-9) / (peak(src, at) + 1e-9)) for _, at in marks]
            label = f"fs={fs} a_bed={ab}"
            print(f"{label:<26}{bed:>9.1f}" + "".join(f"{d:>9.1f}" for d in deltas))
            rows.append((label, bed, deltas))

    print("\n目标：床音 <= -50 dBFS；瞬态/语声跌幅 <= 3dB（负值=被削）")
    good = [r for r in rows if r[1] <= -50 and max(abs(d) for d in r[2]) <= 3.0]
    if good:
        best = min(good, key=lambda r: r[1])
        print("推荐参数:", best[0], "床音 %.1f dBFS" % best[1],
              "跌幅", ["%.1f" % d for d in best[2]])
    else:
        print("无参数同时满足：需要更强的床音抑制或更轻的瞬态过减")


if __name__ == "__main__":
    main()
