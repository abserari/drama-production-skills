# -*- coding: utf-8 -*-
"""语音位置检测（VAD）—— 从 H3 原生音轨里找出"人在何时开口"。

音画分流的对位核心：H3 渲染时台词驱动了口型，所以它的音轨里语声出现的
时间点就是口型开合的时间点。我们把 CosyVoice 合成的台词钉在同一位置，
口型对位天然成立，不需要任何口型同步模型。

口径沿用 skill check_audio_seg 的实测经验：
- RMS 帧检测 + 相对峰值门限，短促闷响靠最小时长滤掉
- 输出 [{start, end, dur}, ...]，按时间排序
"""
import json
import os
import subprocess
import sys

import numpy as np

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import paths as _paths
    FFMPEG = os.environ.get("H3_FFMPEG") or getattr(_paths, "FFMPEG", "ffmpeg")
except Exception:
    FFMPEG = os.environ.get("H3_FFMPEG", "ffmpeg")
SR = 16000


def load_mono(path, sr=SR):
    """ffmpeg 解码为 mono float32。视频/音频文件都吃。"""
    cmd = [FFMPEG, "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr),
           "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 解码失败: {r.stderr.decode('utf-8', 'replace')[-300:]}")
    return np.frombuffer(r.stdout, dtype=np.float32)


def speech_events(path, frame_s=0.05, min_dur=0.18, rel_peak_db=-16.0,
                  rel_bed_db=8.0, merge_gap=0.25):
    """返回语音事件列表。min_dur 滤掉门响/脚步这类短促非语音。"""
    x = load_mono(path)
    if len(x) < SR:
        return []
    n = int(frame_s * SR)
    m = len(x) // n
    frames = x[: m * n].reshape(m, n)
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    bed = float(np.percentile(rms, 15))
    peak = float(np.percentile(rms, 95))
    thr = max(bed * 10 ** (rel_bed_db / 20), peak * 10 ** (rel_peak_db / 20), 1e-4)
    active = rms > thr
    # 合并 gap 内的相邻帧
    events, s = [], None
    gap = 0
    for i, a in enumerate(active):
        if a:
            if s is None:
                s = i
            gap = 0
        elif s is not None:
            gap += 1
            if gap * frame_s >= merge_gap:
                events.append((s * frame_s, (i - gap + 1) * frame_s))
                s, gap = None, 0
    if s is not None:
        events.append((s * frame_s, len(active) * frame_s))
    out = []
    for a, b in events:
        d = b - a
        if d >= min_dur:
            if out and a - out[-1]["end"] < merge_gap:
                out[-1]["end"] = b  # 二次合并
                out[-1]["dur"] = out[-1]["end"] - out[-1]["start"]
            else:
                out.append({"start": round(a, 3), "end": round(b, 3), "dur": round(d, 3)})
    return out


if __name__ == "__main__":
    ev = speech_events(sys.argv[1])
    print(json.dumps(ev, ensure_ascii=False, indent=1))
