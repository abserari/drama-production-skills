# -*- coding: utf-8 -*-
"""audioprod —— 音画分流音轨生产 CLI（v3.4 起为 skill 正式组件）。

架构：视频只管画面（H3 链路出成片），声音全部外部生产。
台词用 CosyVoice2 零样本克隆合成，钉在 H3 原生音轨的语音位置上
（H3 的台词驱动了口型 → 语声位置 = 口型位置 → 对位天然成立）。

TTS 依赖独立环境（与 ComfyUI 完全隔离），布局由 `H3_TTS_HOME`（默认 D:/H3AudioProd）决定：
    CosyVoice/  官方仓库   models/CosyVoice2-0.5B  权重   .venv/  py3.10+torch cu128
`gen` 在缺 torch/cosyvoice 时会自动用该 venv 解释器重入，无需手动切换 python。

用法：
  python audioprod.py parse   --seg seg02.txt                 # 预览台词解析
  python audioprod.py auto    --seg seg02.txt --video seg02.mp4 --out job.json
      # 解析台词 + VAD 定位 → 生成单段 job json（单段验收用）
  python audioprod.py film    --project <生产目录> [--video 全片.mp4] --out job_film.json
      # 全片模式：按 plan 顺序解析所有段台词，按段偏移定位 → 一个 job 覆盖整片
  python audioprod.py bed     --src rain.ogg --preset indoor-glass --out rain_glass.wav
      # 环境床预处理（隔玻璃/室内等预设滤波）
  python audioprod.py gen     --job job.json --voice-card voice_card.json --out track.wav
      # 环境床 + 动作音效 + 台词 → 混出音轨（自动重入 TTS venv）
  python audioprod.py mux     --video seg02.mp4 --track track.wav --out seg02_v2.mp4

job json 里 ambience 支持两种写法：
  dict  {"path","gain_db","fade_in","fade_out"}                        → 铺满全片
  list  [{"path","start","end","gain_db","fade_in","fade_out"}, ...]   → 分时段铺，重叠区即交叉淡化
sfx 为点状音效列表：[{"path","at","gain_db"}, ...]（素材可由 sfx_lib.py 生成）。
"""
import argparse
import json
import os
import re
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TRACK_SR = 24000  # CosyVoice2 原生输出采样率

try:  # skill 环境里复用 paths.py 的 ffmpeg 探测（H3_FFMPEG 优先）
    sys.path.insert(0, HERE)
    import paths as _paths
    FFMPEG = os.environ.get("H3_FFMPEG") or getattr(_paths, "FFMPEG", "ffmpeg")
except Exception:
    FFMPEG = os.environ.get("H3_FFMPEG", "ffmpeg")

# H3_FFMPEG（剪映自带版）是精简构建：无 libx264。mux 需要 h264 转码兜底，
# 候选：H3_FFMPEG → imageio_ffmpeg（workbuddy python 自带完整版）→ PATH
def _pick_ffmpeg():
    cands = [FFMPEG,
             os.path.join(os.path.dirname(sys.executable),
                          "Lib", "site-packages", "imageio_ffmpeg", "binaries",
                          "ffmpeg-win-x86_64-v7.1.exe")]
    try:
        import imageio_ffmpeg
        cands.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    for c in cands:
        if c and os.path.isfile(c):
            r = subprocess.run([c, "-hide_banner", "-encoders"],
                               capture_output=True, text=True, errors="replace")
            if "libx264" in (r.stdout or ""):
                return c, True
    return FFMPEG, False

FFMPEG, FFMPEG_HAS_X264 = _pick_ffmpeg()

TTS_HOME = os.environ.get("H3_TTS_HOME", "D:/H3AudioProd")
TTS_PY = os.path.join(TTS_HOME, ".venv", "Scripts", "python.exe")

# 台词行：<Audio 1> (S1) 说（实声为主｜语速快…）:<d>林晚！</d>
DIA_RE = re.compile(
    r"<Audio\s*\d+>\s*\((S\d+)\)\s*说（(?P<style>[^）]*)）?\s*[:：]\s*<d>(?P<text>.*?)</d>",
    re.DOTALL)


def parse_dialogue(seg_txt):
    """从分镜 txt 提取 [(speaker, text, style), ...]，按出现顺序。"""
    out = []
    for m in DIA_RE.finditer(open(seg_txt, encoding="utf-8").read()):
        out.append({"speaker": m.group(1),
                    "text": m.group("text").strip(),
                    "style": (m.group("style") or "").strip()})
    return out


def style_to_speed(style):
    """粗糙映射：分镜括号里的语速提示 → TTS speed。"""
    s = style or ""
    if "语速快" in s or "偏快" in s or "忽快" in s:
        return 1.12
    if "语速慢" in s or "偏慢" in s or "慢" in s:
        return 0.92
    return 1.0


def ffprobe_dur(path):
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or "")
    if not m:
        raise RuntimeError(f"探测不到时长: {path}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def cut_ref(src, start, end, out):
    """切参考音：mono、轻响度归一（克隆用 3~10s 干净单人说白）。"""
    d = max(1.0, end - start)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    cmd = [FFMPEG, "-y", "-v", "error", "-ss", str(start), "-t", str(d),
           "-i", src, "-ac", "1", "-af", "loudnorm=I=-20:TP=-3",
           "-ar", str(TRACK_SR), out]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(r.stderr[-400:])
    print(f"[ref] {out}（{d:.1f}s）")


# ---------------------------------------------------------------- bed 预设
BED_PRESETS = {
    # 原素材直出（室外）
    "outdoor": "loudnorm=I=-20:TP=-3",
    # 隔了一层玻璃的雨/风：高频全挡，只留中低频闷响（2026-10-31 用户定标）
    "indoor-glass": "highpass=f=60,lowpass=f=1700,lowpass=f=2600,dynaudnorm=p=0.7",
    # 室内房间感：比玻璃多留一点高频空气感
    "room": "highpass=f=80,lowpass=f=3400,dynaudnorm=p=0.7",
}


def cmd_bed(a):
    af = BED_PRESETS.get(a.preset)
    if af is None:
        raise SystemExit(f"[REFUSE] 未知预设 {a.preset}；可选：{', '.join(BED_PRESETS)}")
    cmd = [FFMPEG, "-y", "-v", "error", "-i", a.src, "-af", af,
           "-ar", str(TRACK_SR), "-ac", "1", a.out]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(r.stderr[-400:])
    print(f"[bed] {a.out}（preset={a.preset}）")


# ---------------------------------------------------------------- auto（单段）
def cmd_auto(a):
    """台词解析 + VAD 定位 → job json。lines 按 VAD 事件顺序对号入座。"""
    sys.path.insert(0, HERE)
    import h3vad
    lines = parse_dialogue(a.seg)
    if not lines:
        raise SystemExit("[REFUSE] 这段没有 <d> 台词（无对白段走 ambience-only 流程）")
    for ln in lines:
        ln["speed"] = style_to_speed(ln.pop("style"))
        ln.setdefault("at", None)
    job = {"seg": os.path.splitext(os.path.basename(a.seg))[0], "lines": lines}
    if a.video:
        ev = h3vad.speech_events(a.video, merge_gap=0.8, min_dur=0.35)
        print(f"[vad] 检测到 {len(ev)} 个语声事件: "
              + ", ".join(f"{e['start']}-{e['end']}" for e in ev))
        job["vad"] = ev
        if len(ev) < len(lines):
            print(f"[WARN] 语声事件 {len(ev)} < 台词 {len(lines)} 句——"
                  "多余台词将从段首顺序排布；请人工核对 job 后再 gen")
        elif len(ev) > len(lines):
            print(f"[WARN] 语声事件 {len(ev)} > 台词 {len(lines)} 句——"
                  "取前 N 个事件对号，其余事件是拟音误判或台词漏写")
        for ln, e in zip(lines, ev):
            ln["at"] = round(e["start"] + a.bias, 3)
        job["target_dur"] = round(ffprobe_dur(a.video), 3)
        job["source_video"] = a.video
    if a.ambience:
        job["ambience"] = {"path": a.ambience, "gain_db": a.ambience_gain}
    if a.sfx:
        job["sfx"] = _parse_sfx_args(a.sfx)
    json.dump(job, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[job] {a.out}（{len(lines)} 句台词）")


def _parse_sfx_args(items):
    """--sfx "0.8:whoosh.wav" "2.1:impact.wav@-6" → [{"at","path","gain_db"}]"""
    out = []
    for it in items:
        at, rest = it.split(":", 1)
        gain = 0.0
        if "@" in rest:
            rest, g = rest.rsplit("@", 1)
            gain = float(g)
        out.append({"at": float(at), "path": rest, "gain_db": gain})
    return out


# ---------------------------------------------------------------- film（全片）
def plan_order(project):
    """段顺序：plan.json 的 segs 顺序；没有就退回 progress.json 键序。"""
    pp = os.path.join(project, "plan.json")
    if os.path.isfile(pp):
        plan = json.load(open(pp, encoding="utf-8"))
        return [s["seg"] for s in plan.get("segs", []) if s.get("seg")]
    gp = os.path.join(project, "progress.json")
    if os.path.isfile(gp):
        return sorted(json.load(open(gp, encoding="utf-8")).get("segs", {}))
    raise SystemExit(f"[REFUSE] {project} 里既没有 plan.json 也没有 progress.json")


def cmd_film(a):
    """全片模式：按段序解析全部台词，按段时长偏移定位 → 一个 job 覆盖整片。

    定位口径：VAD 找每段成片（H3 原生音轨）里的开口点，加段偏移与 --bias
    （默认 -0.25s：VAD 按能量起振检测，天然比真实口型晚，实测标定值）。
    """
    sys.path.insert(0, HERE)
    import h3vad
    order = a.order.split(",") if a.order else plan_order(a.project)
    segs_dir = a.segs_dir or os.path.join(a.project, "成片")
    lines_all, offset, total = [], 0.0, 0.0
    for seg in order:
        v = os.path.join(segs_dir, f"{seg}.mp4")
        if not os.path.isfile(v):
            raise SystemExit(f"[REFUSE] 缺成片 {v}——先 finish 完所有段再 film")
        dur = ffprobe_dur(v)
        seg_txt = os.path.join(a.project, "segments", f"{seg}.txt")
        lines = parse_dialogue(seg_txt) if os.path.isfile(seg_txt) else []
        if lines:
            ev = h3vad.speech_events(v, merge_gap=0.8, min_dur=0.35)
            tag = ""
            if len(ev) < len(lines):
                tag = f"[WARN] {seg}: 事件 {len(ev)} < 台词 {len(lines)}，缺的从段首排布"
            elif len(ev) > len(lines):
                tag = f"[WARN] {seg}: 事件 {len(ev)} > 台词 {len(lines)}，取前 N 个对号"
            if tag:
                print(tag)
            for i, ln in enumerate(lines):
                e = ev[i] if i < len(ev) else None
                if e:
                    at = round(offset + e["start"] + a.bias, 3)
                else:  # VAD 没找到（台词没生成/被吞）——段首顺序兜底并醒目告警
                    at = round(offset + 0.5 + i * 1.5, 3)
                    print(f"[FATAL-WARN] {seg} 第{i + 1}句无 VAD 锚点，兜底 @ {at}s——"
                          "若口型位置不对需人工改 job")
                lines_all.append({"speaker": ln["speaker"],
                                  "text": ln["text"],
                                  "speed": style_to_speed(ln.pop("style", "")),
                                  "at": at, "seg": seg})
        total += dur
        offset += dur
        print(f"[film] {seg} {dur:.2f}s（累计 {offset:.2f}s，台词 {len(lines)} 句）")
    if not lines_all:
        print("[film] 全片没有台词——纯环境床流程")
    job = {"seg": "全片", "lines": lines_all}
    job["target_dur"] = round(ffprobe_dur(a.video), 3) if a.video else round(total, 3)
    if a.video:
        job["source_video"] = a.video
    if a.ambience:
        job["ambience"] = {"path": a.ambience, "gain_db": a.ambience_gain}
    if a.sfx:
        job["sfx"] = _parse_sfx_args(a.sfx)
    json.dump(job, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[job] {a.out}（全片 {job['target_dur']:.1f}s，{len(lines_all)} 句台词）")


# ---------------------------------------------------------------- gen（混音）
def _decode_24k_mono(path):
    r = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-ac", "1",
                        "-ar", str(TRACK_SR), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"解码失败 {path}: {r.stderr[-200:]}")
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def _apply_fades(x, fi, fo):
    if fi:
        x[:fi] *= np.linspace(0, 1, fi)
    if fo:
        x[-fo:] *= np.linspace(1, 0, fo)
    return x


def _place(track, arr, at, gain_db=0.0):
    s0 = int(at * TRACK_SR)
    if s0 >= len(track):
        print(f"[WARN] {at}s 超出音轨长度，丢弃")
        return
    arr = arr * (10 ** (gain_db / 20))
    s1 = min(len(track), s0 + len(arr))
    track[s0:s1] += arr[: s1 - s0]


def _needs_tts_venv():
    # 判据：当前解释器是否已是 TTS venv。不能用 import 试探——
    # cosyvoice 依赖 sys.path 注入（tts_engine 里做），venv 里裸 import 也会失败，
    # 会造成"重入后仍判需要重入"的无限递归（2026-10-31 实测 bug）。
    if os.path.normpath(sys.executable) == os.path.normpath(TTS_PY):
        return False
    try:
        import torch  # noqa: F401
        import cosyvoice  # noqa: F401
        return False
    except Exception:
        return True


def cmd_gen(a):
    if _needs_tts_venv():
        if not os.path.isfile(TTS_PY):
            raise SystemExit(f"[FATAL] 找不到 TTS venv 解释器 {TTS_PY}"
                             f"（设 H3_TTS_HOME 指向 H3AudioProd 布局）")
        print(f"[gen] 重入 TTS venv：{TTS_PY}")
        r = subprocess.run([TTS_PY, os.path.abspath(__file__)] + sys.argv[1:])
        raise SystemExit(r.returncode)

    sys.path.insert(0, HERE)
    from tts_engine import get_engine
    job = json.load(open(a.job, encoding="utf-8"))
    card = json.load(open(a.voice_card, encoding="utf-8"))
    dur = job.get("target_dur") or 10.0
    n = int(dur * TRACK_SR)
    track = np.zeros(n, dtype=np.float32)

    # ① 环境床：dict=铺满全片；list=分时段铺（重叠区即交叉淡化）
    amb = job.get("ambience")
    beds = [amb] if isinstance(amb, dict) else (amb or [])
    for amb in beds:
        if not amb or not amb.get("path"):
            continue
        amb_x = _decode_24k_mono(amb["path"])
        gain = amb.get("gain_db", -18)
        s0 = int(amb.get("start", 0.0) * TRACK_SR)
        end = amb.get("end") or dur
        s1 = min(n, int(end * TRACK_SR))
        if s0 >= s1:
            print(f"[WARN] 床时段 {amb.get('start')}-{end}s 无效，跳过")
            continue
        reps = int(np.ceil((s1 - s0) / len(amb_x)))
        bed = np.tile(amb_x, reps)[: s1 - s0] * (10 ** (gain / 20))
        fi, fo = int(amb.get("fade_in", 0.5) * TRACK_SR), int(amb.get("fade_out", 0.5) * TRACK_SR)
        _apply_fades(bed, fi, fo)
        track[s0:s1] += bed
        rng = f"{amb.get('start', 0):.1f}-{end:.1f}s" if isinstance(amb, dict) and "start" in amb else "全片"
        print(f"[amb] {os.path.basename(amb['path'])} @ {gain}dB（{rng}）")

    # ② 点状动作音效
    for s in job.get("sfx", []):
        x = _decode_24k_mono(s["path"])
        peak = float(np.abs(x).max()) or 1.0
        x = x * (10 ** (-3 / 20) / peak)  # 峰值归一 -3dBFS 再按 gain_db 放置
        _place(track, x, s["at"], s.get("gain_db", 0.0))
        print(f"[sfx] {os.path.basename(s['path'])} @ {s['at']}s（{s.get('gain_db', 0)}dB）")

    # ③ 台词：逐句合成 + 定点放置
    eng = get_engine()
    for i, ln in enumerate(job["lines"]):
        spk = card[ln["speaker"]]
        ref_wav, ref_text = spk["ref_wav"], spk["ref_text"]
        if not ref_wav or not os.path.isfile(ref_wav):
            raise SystemExit(f"[FATAL] {ln['speaker']} 没有参考音 {ref_wav}——先 make_refs")
        at = ln.get("at")
        if at is None:
            at = round(0.5 + i * 1.5, 3)  # 兜底：段首顺序排布
        line_wav = os.path.join(os.path.dirname(a.out) or ".",
                                f"_line_{job['seg']}_{i:02d}.wav")
        sr, arr = eng.synthesize(ln["text"], ref_wav, ref_text,
                                 speed=ln.get("speed", 1.0), out_path=line_wav)
        # 每句独立峰值归一到 -3dBFS，避免忽大忽小
        peak = float(np.abs(arr).max()) or 1.0
        arr = arr * (10 ** (-3 / 20) / peak)
        _place(track, arr, at)
        print(f"[tts] {ln['speaker']} #{i + 1}「{ln['text'][:18]}」@ {at}s")

    # ④ 总线限幅 + 写出
    peak = float(np.abs(track).max())
    if peak > 0.999:
        track *= 0.999 / peak
    pcm = (track * 32767).astype(np.int16)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    import wave
    with wave.open(a.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TRACK_SR)
        w.writeframes(pcm.tobytes())
    print(f"[track] {a.out}（{dur:.2f}s @ {TRACK_SR}Hz）")


def _video_codec_name(path):
    """探测首个视频流的编码名（如 h264 / mpeg4）。
    不依赖 ffprobe（imageio_ffmpeg 只带 ffmpeg.exe），解析 `ffmpeg -i` 的
    stderr 里 "Stream #N:M ... Video: <codec>" 行。"""
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", path],
                       capture_output=True, text=True, errors="replace")
    for ln in (r.stderr or "").splitlines():
        if "Video:" in ln and "Stream #" in ln:
            m = re.search(r"Video:\s*(\w+)", ln)
            if m:
                return m.group(1)
    return ""


def cmd_mux(a):
    out = a.out or re.sub(r"\.mp4$", "_配音.mp4", a.video)
    # ComfyUI 合成节点输出 mpeg4 ASP，浏览器/多数手机播放器不出画面（2026-10-31 实测）。
    # 源流已是 h264 → 直接 copy 零转码代；mpeg4 且有 libx264 → 转码；都没有 → WARN 回退 copy。
    vname = _video_codec_name(a.video)
    if vname == "h264":
        vcodec = ["-c:v", "copy"]
    elif FFMPEG_HAS_X264:
        vcodec = ["-c:v", "libx264", "-crf", "18", "-preset", "medium",
                  "-pix_fmt", "yuv420p"]
    else:
        print(f"[mux][WARN] 视频流 {vname or '未知'} 且无 libx264，原样 copy（兼容性差）")
        vcodec = ["-c:v", "copy"]
    cmd = [FFMPEG, "-y", "-v", "error", "-i", a.video, "-i", a.track,
           "-map", "0:v", "-map", "1:a", *vcodec,
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart", "-shortest", out]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(r.stderr[-400:])
    print(f"[mux] {out}")


def cmd_mix_native(a):
    """v3.5 交付主路径：H3 原生音轨全保留 + 低电平环境床（+可选点状音效）叠加。
    视频流已是 h264 则 copy 零转码；mpeg4 才转 h264（浏览器/手机兼容）。"""
    beds = []
    if a.ambience:
        beds.append({"path": a.ambience, "gain_db": a.ambience_gain})
    # 床轨：整片循环铺；不需要 TTS，直接在当前环境做（只用 numpy+ffmpeg）
    dur = ffprobe_dur(a.video)
    n = int(dur * TRACK_SR)
    track = np.zeros(n, dtype=np.float32)
    for b in beds:
        amb_x = _decode_24k_mono(b["path"])
        reps = int(np.ceil(n / len(amb_x)))
        bed = np.tile(amb_x, reps)[:n] * (10 ** (b["gain_db"] / 20))
        _apply_fades(bed, int(0.5 * TRACK_SR), int(0.5 * TRACK_SR))
        track += bed
        print(f"[amb] {os.path.basename(b['path'])} @ {b['gain_db']}dB（全片）")
    for s in _parse_sfx_args(a.sfx or []):
        x = _decode_24k_mono(s["path"])
        peak = float(np.abs(x).max()) or 1.0
        x = x * (10 ** (-3 / 20) / peak)
        _place(track, x, s["at"], s.get("gain_db", 0.0))
        print(f"[sfx] {os.path.basename(s['path'])} @ {s['at']}s（{s.get('gain_db', 0)}dB）")
    bed_wav = (os.path.splitext(a.out)[0] + "_bed.wav") if (beds or a.sfx) else None
    if bed_wav:
        peak = float(np.abs(track).max())
        if peak > 0.999:
            track *= 0.999 / peak
        import wave
        with wave.open(bed_wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(TRACK_SR)
            w.writeframes((track * 32767).astype(np.int16).tobytes())
        mix_in = [("-i", bed_wav), ("-filter_complex",
                  "amix=inputs=2:duration=first:normalize=0[a]")]
        map_args = ["-map", "0:v", "-map", "[a]"]
        print(f"[bed] 床轨 {bed_wav}（{dur:.2f}s）")
    else:
        mix_in, map_args = [], ["-map", "0:v", "-map", "0:a"]
    vname = _video_codec_name(a.video)
    if vname == "h264":
        vcodec = ["-c:v", "copy"]
    elif FFMPEG_HAS_X264:
        print(f"[mux] 视频流 {vname} → 转 h264")
        vcodec = ["-c:v", "libx264", "-crf", "18", "-preset", "medium",
                  "-pix_fmt", "yuv420p"]
    else:
        print(f"[mux][WARN] 视频流 {vname or '未知'} 且无 libx264，原样 copy")
        vcodec = ["-c:v", "copy"]
    cmd = [FFMPEG, "-y", "-v", "error", "-i", a.video] + \
          [x for pair in mix_in for x in pair] + map_args + vcodec + \
          ["-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart", "-shortest", a.out]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(r.stderr[-400:])
    print(f"[mix-native] {a.out}（原生音轨保留{'+低电平床' if bed_wav else ''}，视频 {vname or 'copy'}）")


def cmd_loudnorm(a):
    """全片响度统一（段间响度跳变明显时用一次；不过度处理）。"""
    cmd = [FFMPEG, "-y", "-v", "error", "-i", a.src,
           "-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", a.out]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(r.stderr[-400:])
    print(f"[loudnorm] {a.out}（I=-16 TP=-1.5）")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse", help="预览台词解析")
    p.add_argument("--seg", required=True)

    p = sub.add_parser("auto", help="单段：台词解析+VAD定位 → job json")
    p.add_argument("--seg", required=True, help="分镜 txt 路径")
    p.add_argument("--video", help="该段 H3 成片（VAD 定位 + 段长探测）")
    p.add_argument("--bias", type=float, default=-0.25,
                   help="开口点偏移（负=提前；VAD 能量起振天然滞后，实测标定 -0.25s）")
    p.add_argument("--ambience", help="环境声（bed 预处理过的 wav）")
    p.add_argument("--ambience-gain", type=float, default=-18)
    p.add_argument("--sfx", nargs="*", help='点状音效 "时刻:路径[@增益dB]"，如 "0.8:whoosh.wav@-4"')
    p.add_argument("--out", required=True)

    p = sub.add_parser("film", help="全片：按段序解析全部台词+偏移定位 → job json")
    p.add_argument("--project", required=True, help="生产目录（含 project.json）")
    p.add_argument("--order", help="逗号分隔段序，默认 plan.json 顺序")
    p.add_argument("--segs-dir", help="成片目录，默认 <project>/成片")
    p.add_argument("--video", help="全片 concat 结果（探测总时长；不传则累加各段）")
    p.add_argument("--bias", type=float, default=-0.25)
    p.add_argument("--ambience", help="全片环境床（一床铺到底）")
    p.add_argument("--ambience-gain", type=float, default=-18)
    p.add_argument("--sfx", nargs="*", help='点状音效 "时刻:路径[@增益dB]"（时刻为全片时间轴）')
    p.add_argument("--out", required=True)

    p = sub.add_parser("bed", help="环境床预处理（隔玻璃/室内预设滤波）")
    p.add_argument("--src", required=True)
    p.add_argument("--preset", default="outdoor", choices=sorted(BED_PRESETS))
    p.add_argument("--out", required=True)

    p = sub.add_parser("gen", help="合成音轨（环境床+音效+台词，自动重入 TTS venv）")
    p.add_argument("--job", required=True)
    p.add_argument("--voice-card", required=True)
    p.add_argument("--out", required=True)

    p = sub.add_parser("mix-native",
                       help="v3.5 交付主路径：H3 原生音轨保留 + 低电平环境床叠加")
    p.add_argument("--video", required=True)
    p.add_argument("--ambience", help="环境床素材（ogg/wav，循环铺满全片）")
    p.add_argument("--ambience-gain", type=float, default=-14)
    p.add_argument("--sfx", nargs="*", help='点状音效 "时刻:路径[@增益dB]"（全片时间轴）')
    p.add_argument("--out", required=True)

    p = sub.add_parser("loudnorm", help="全片响度统一（I=-16 TP=-1.5，视频流 copy）")
    p.add_argument("--src", required=True)
    p.add_argument("--out", required=True)

    p = sub.add_parser("mux", help="音轨合到视频")
    p.add_argument("--video", required=True)
    p.add_argument("--track", required=True)
    p.add_argument("--out")

    p = sub.add_parser("cut-ref", help="从素材切角色参考音")
    p.add_argument("--src", required=True)
    p.add_argument("--start", type=float, required=True)
    p.add_argument("--end", type=float, required=True)
    p.add_argument("--out", required=True)

    a = ap.parse_args()
    {"parse": lambda a: print(json.dumps(parse_dialogue(a.seg), ensure_ascii=False, indent=1)),
     "auto": cmd_auto, "film": cmd_film, "bed": cmd_bed,
     "gen": cmd_gen, "mux": cmd_mux,
     "mix-native": cmd_mix_native, "loudnorm": cmd_loudnorm,
     "cut-ref": lambda a: cut_ref(a.src, a.start, a.end, a.out)}[a.cmd](a)


if __name__ == "__main__":
    main()
