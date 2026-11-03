# -*- coding: utf-8 -*-
"""全片配音连续性诊断：逐段抽取音轨，分析
1) 语声基频中位数（跨段声线一致性）
2) 段尾截断风险（末尾 250ms 能量）
3) 段间拼接点能量落差（环境音断层）
4) 静音占比（判断是否含背景音）
输出：diagnose_audio.json + 控制台报告
"""
import json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import FFMPEG as FF, tmp_audio  # noqa: E402

# 用法：python diagnose_audio.py --dir <段目录> --order <顺序txt> [--tmp 缓存目录] [--out 报告json]
# 必须显式给 --dir 与 --order（避免落到旧项目路径）：
#   --order 文件：一行一个段名（不带扩展名，按拼接顺序），例如
#       seg01_高空俯瞰下压
#       seg02a_小女孩追沙跑过
#   order 文件由 h3proj.py concat 自动生成（成片目录 + 顺序）。
def _arg(flag, default=None, required=False):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    if required:
        print(f"缺少必需参数 {flag}（避免默认真空落到旧项目路径）", file=sys.stderr)
        sys.exit(2)
    return default

SRC = _arg('--dir', required=True)
TMP = _arg('--tmp', None) or tmp_audio()
OUT_JSON = _arg('--out', os.path.join(SRC, 'diagnose_audio.json'))
_ORDER = _arg('--order', required=True)
os.makedirs(TMP, exist_ok=True)
SR = 16000

if _ORDER:
    order = [s.strip() for s in open(_ORDER, encoding='utf-8').read().splitlines() if s.strip()]
else:
    # --order 为必需参数，此处不会执行
    print("缺少 --order 顺序文件", file=sys.stderr); sys.exit(2)


def load_audio(name):
    wav = os.path.join(TMP, name + '.wav')
    if not os.path.exists(wav):
        subprocess.run([FF, '-y', '-v', 'error', '-i', os.path.join(SRC, name + '.mp4'),
                        '-ac', '1', '-ar', str(SR), '-f', 'wav', wav], check=True)
    import wave
    with wave.open(wav, 'rb') as w:
        n = w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0
    return x


def frame_rms(x, win=1024, hop=512):
    if len(x) < win:
        return np.array([0.0])
    idx = np.arange(0, len(x) - win + 1, hop)
    return np.array([np.sqrt(np.mean(x[i:i+win]**2)) for i in idx])


def estimate_f0(x, frame=640, hop=320, fmin=80, fmax=400):
    """自相关估计有声帧基频，返回中位数（Hz）。"""
    lo, hi = int(SR/fmax), int(SR/fmin)
    f0s = []
    for i in range(0, len(x) - frame, hop):
        fr = x[i:i+frame]
        if np.sqrt(np.mean(fr**2)) < 0.02:      # 静音/弱能量跳过
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, 'full')[frame-1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        if len(seg) == 0:
            continue
        k = int(np.argmax(seg)) + lo
        if ac[k] / ac[0] > 0.30:                # 周期性可信度
            f0 = SR / k
            if fmin <= f0 <= fmax:
                f0s.append(f0)
    if len(f0s) < 8:
        return None, 0
    return float(np.median(f0s)), len(f0s)


rows = []
for name in order:
    x = load_audio(name)
    dur = len(x) / SR
    r = frame_rms(x)
    rms_all = float(np.sqrt(np.mean(x**2)))
    voiced_ratio = float(np.mean(r > max(0.01, rms_all * 0.45)))
    tail = x[int(-0.25*SR):]
    tail_rms = float(np.sqrt(np.mean(tail**2))) if len(tail) else 0.0
    head = x[:int(0.25*SR)]
    head_rms = float(np.sqrt(np.mean(head**2))) if len(head) else 0.0
    f0, nfr = estimate_f0(x)
    rows.append(dict(seg=name, dur=round(dur, 2), rms=round(rms_all, 4),
                     voiced=round(voiced_ratio, 2), f0=None if f0 is None else round(f0, 1),
                     f0_frames=nfr, head_rms=round(head_rms, 4), tail_rms=round(tail_rms, 4)))

print(f"{'seg':32s} {'时长':>6s} {'RMS':>7s} {'有声占比':>8s} {'F0中位':>7s} {'首250ms':>8s} {'尾250ms':>8s}")
for r in rows:
    print(f"{r['seg'][:30]:32s} {r['dur']:6.2f} {r['rms']:7.4f} {r['voiced']:8.2f} "
          f"{str(r['f0']):>7s} {r['head_rms']:8.4f} {r['tail_rms']:8.4f}")

f0s = [r['f0'] for r in rows if r['f0']]
print(f"\n有语声段数: {len(f0s)}/{len(rows)}  F0 范围 {min(f0s):.0f}-{max(f0s):.0f} Hz  "
      f"标准差 {np.std(f0s):.1f} Hz  变异系数 {np.std(f0s)/np.mean(f0s)*100:.1f}%")

# 段间拼接点能量落差
print("\n段间拼接点（上一段尾 100ms vs 下一段首 100ms）:")
jumps = []
for i in range(len(order) - 1):
    a = load_audio(order[i]); b = load_audio(order[i+1])
    ta = float(np.sqrt(np.mean(a[int(-0.1*SR):]**2)))
    hb = float(np.sqrt(np.mean(b[:int(0.1*SR)]**2)))
    ratio = (max(ta, hb) + 1e-6) / (min(ta, hb) + 1e-6)
    jumps.append((order[i], order[i+1], round(ta, 4), round(hb, 4), round(ratio, 1)))
    flag = '  <== 落差大' if ratio > 6 else ''
    print(f"  {order[i][:14]:16s}→{order[i+1][:14]:16s} 尾{ta:7.4f} 首{hb:7.4f} 比值{ratio:6.1f}{flag}")

json.dump(dict(segments=rows, joints=[dict(a=j[0], b=j[1], tail=j[2], head=j[3], ratio=j[4]) for j in jumps]),
          open(OUT_JSON, 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print(f"\n已写出 {OUT_JSON}")
