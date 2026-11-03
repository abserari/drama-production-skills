# -*- coding: utf-8 -*-
"""
生成 90 年代商战风格电影级高保真立体声 BGM (48kHz 24-bit/16-bit WAV)
提供三种情绪主题：
1. business_suspense: 悬疑对峙、暗潮涌动 (D小调，心跳鼓点、模拟低音与复古合成器脉冲)
2. business_climax: 绝地反击、逆袭翻盘 (强劲电子跑马律动、高潮铺垫)
3. business_warmth: 时代温情、深夜沉淀 (温暖合成器弦乐与电钢琴)
"""

import os
import math
import wave
import struct
import numpy as np
from pathlib import Path

BGM_DIR = Path(os.environ.get("DRAMA_WORKSPACE", Path.cwd())) / "assets" / "bgm"
BGM_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_RATE = 48000


def create_suspense_track(duration_sec=70.0) -> Path:
    """生成 90 年代商战悬疑对峙 BGM (70秒无缝循环)"""
    t = np.linspace(0, duration_sec, int(SAMPLE_RATE * duration_sec), endpoint=False)
    
    # 基础心跳鼓点 (BPM = 72)
    bpm = 72.0
    beat_dur = 60.0 / bpm
    kick = np.zeros_like(t)
    
    # 在每拍加入低频心跳 Kick
    num_beats = int(duration_sec / beat_dur)
    for b in range(num_beats):
        start_idx = int(b * beat_dur * SAMPLE_RATE)
        # 心跳是双击: boom-boom (0ms 和 220ms)
        for offset in (0, int(0.22 * SAMPLE_RATE)):
            pos = start_idx + offset
            pulse_len = int(0.18 * SAMPLE_RATE)
            if pos + pulse_len < len(t):
                pt = np.linspace(0, 0.18, pulse_len, endpoint=False)
                # 55Hz 下滑到 35Hz
                freq = 55.0 * np.exp(-12.0 * pt) + 35.0
                env = np.exp(-15.0 * pt)
                sub = np.sin(2 * np.pi * freq * pt) * env * 0.35
                kick[pos:pos+pulse_len] += sub

    # 90年代模拟复古低音 (Moog Bass in D minor: D1=36.7Hz, F1=43.65Hz, G1=49.0Hz, A1=55.0Hz)
    bass = np.zeros_like(t)
    bar_dur = beat_dur * 4 # 1小节约 3.33s
    bass_notes = [36.71, 36.71, 43.65, 41.20] # D, D, F, E
    num_bars = int(duration_sec / bar_dur)
    for bar in range(num_bars):
        note_freq = bass_notes[bar % len(bass_notes)]
        bar_start = int(bar * bar_dur * SAMPLE_RATE)
        bar_len = int(bar_dur * SAMPLE_RATE)
        if bar_start + bar_len <= len(t):
            bt = np.linspace(0, bar_dur, bar_len, endpoint=False)
            # 泛音和谐波
            wave_bass = (
                0.30 * np.sin(2 * np.pi * note_freq * bt) +
                0.15 * np.sin(2 * np.pi * note_freq * 2 * bt) +
                0.08 * np.sin(2 * np.pi * note_freq * 3 * bt)
            )
            # 低频滤波器包络效果
            lfo = 0.8 + 0.2 * np.sin(2 * np.pi * 0.5 * bt)
            bass[bar_start:bar_start+bar_len] += wave_bass * lfo

    # 悬疑氛围 Pad (D小调和弦: D3=146.83, F3=174.61, A3=220.00, C4=261.63)
    pad = (
        0.08 * np.sin(2 * np.pi * 146.83 * t + 0.1) +
        0.06 * np.sin(2 * np.pi * 174.61 * t + 0.5) +
        0.07 * np.sin(2 * np.pi * 220.00 * t + 1.2) +
        0.04 * np.sin(2 * np.pi * 261.63 * t + 2.0)
    )
    # 慢速呼吸 LFO
    pad_lfo = 0.6 + 0.4 * np.sin(2 * np.pi * 0.15 * t)
    pad = pad * pad_lfo

    # 90年代复古高频电子钟摆脉冲 (Ticking / Arp)
    arp = np.zeros_like(t)
    step_dur = beat_dur / 4 # 16分音符
    arp_notes = [293.66, 349.23, 440.0, 523.25, 440.0, 349.23] # D4, F4, A4, C5, A4, F4
    num_steps = int(duration_sec / step_dur)
    for s in range(num_steps):
        freq = arp_notes[s % len(arp_notes)]
        spos = int(s * step_dur * SAMPLE_RATE)
        slen = int(0.08 * SAMPLE_RATE)
        if spos + slen < len(t):
            st = np.linspace(0, 0.08, slen, endpoint=False)
            pulse = np.sin(2 * np.pi * freq * st) * np.exp(-35.0 * st) * 0.06
            arp[spos:spos+slen] += pulse

    # 立体声声相混音 (Left / Right 微小相位延迟营造空间深度)
    left = kick * 0.9 + bass * 0.85 + pad * 0.95 + arp * 0.7
    right = kick * 0.9 + bass * 0.85 + pad * 0.95 + np.roll(arp, int(0.003 * SAMPLE_RATE)) * 0.7

    # 整体动态压限平滑
    left = np.tanh(left * 1.5) * 0.65
    right = np.tanh(right * 1.5) * 0.65

    # 导出 16-bit 48kHz WAV
    out_path = BGM_DIR / "90s_business_suspense.wav"
    left_int = (left * 32767).astype(np.int16)
    right_int = (right * 32767).astype(np.int16)
    stereo = np.empty((left_int.size * 2,), dtype=np.int16)
    stereo[0::2] = left_int
    stereo[1::2] = right_int

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(stereo.tobytes())

    print(f"[成功] 90s 商战悬疑 BGM 已生成: {out_path} ({duration_sec}s, 48kHz 立体声)")
    return out_path


def create_climax_track(duration_sec=70.0) -> Path:
    """生成 90 年代商战绝地反击/胜利高潮 BGM (BPM=118 跑马节奏)"""
    t = np.linspace(0, duration_sec, int(SAMPLE_RATE * duration_sec), endpoint=False)
    bpm = 118.0
    beat_dur = 60.0 / bpm
    
    # 四四拍坚实底鼓
    kick = np.zeros_like(t)
    num_beats = int(duration_sec / beat_dur)
    for b in range(num_beats):
        pos = int(b * beat_dur * SAMPLE_RATE)
        plen = int(0.15 * SAMPLE_RATE)
        if pos + plen < len(t):
            pt = np.linspace(0, 0.15, plen, endpoint=False)
            freq = 65.0 * np.exp(-15.0 * pt) + 40.0
            kick[pos:pos+plen] += np.sin(2 * np.pi * freq * pt) * np.exp(-18.0 * pt) * 0.40

    # 奔腾电子贝斯 (Euro/港风电子 8分音符切分)
    bass = np.zeros_like(t)
    eighth_dur = beat_dur / 2
    num_eighths = int(duration_sec / eighth_dur)
    bass_line = [55.0, 55.0, 65.4, 55.0, 73.4, 73.4, 82.4, 65.4] # A1, C2, D2, E2
    for e in range(num_eighths):
        pos = int(e * eighth_dur * SAMPLE_RATE)
        blen = int(0.12 * SAMPLE_RATE)
        freq = bass_line[e % len(bass_line)]
        if pos + blen < len(t):
            bt = np.linspace(0, 0.12, blen, endpoint=False)
            sound = (np.sin(2*np.pi*freq*bt) + 0.4*np.sin(4*np.pi*freq*bt)) * np.exp(-10.0*bt) * 0.35
            bass[pos:pos+blen] += sound

    # 高昂黄铜质感合成器和弦 (90s Brass Pad)
    chord = (
        0.10 * np.sin(2*np.pi*220.0*t) + 
        0.08 * np.sin(2*np.pi*277.18*t) + 
        0.12 * np.sin(2*np.pi*329.63*t) + 
        0.09 * np.sin(2*np.pi*440.0*t)
    )
    chord_lfo = 0.7 + 0.3 * np.sin(2 * np.pi * 0.25 * t)
    chord = chord * chord_lfo

    left = np.tanh((kick * 0.9 + bass * 0.9 + chord * 0.7) * 1.6) * 0.70
    right = np.tanh((kick * 0.9 + bass * 0.85 + chord * 0.75) * 1.6) * 0.70

    out_path = BGM_DIR / "90s_business_climax.wav"
    left_int = (left * 32767).astype(np.int16)
    right_int = (right * 32767).astype(np.int16)
    stereo = np.empty((left_int.size * 2,), dtype=np.int16)
    stereo[0::2] = left_int
    stereo[1::2] = right_int

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(stereo.tobytes())

    print(f"[成功] 90s 商战高潮 BGM 已生成: {out_path} ({duration_sec}s, 48kHz 立体声)")
    return out_path


if __name__ == "__main__":
    create_suspense_track(75.0)
    create_climax_track(75.0)
