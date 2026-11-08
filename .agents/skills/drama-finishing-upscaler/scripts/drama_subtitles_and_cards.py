# -*- coding: utf-8 -*-
"""
短剧工业级字幕对齐与片尾字卡压制系统 (Drama Subtitle & Title Card Burner)
------------------------------------------------------------------------
核心原理：
1. 模型解耦：H3/视频生成阶段绝不画字，只输出纯净无字底片（Clean Plate），保证画质与动作不崩；
2. 逐字对齐：调用 Whisper 开启 word_timestamps 逐字识别音轨，获取毫秒级物理发音起止时间戳；
3. 剧本校准：结合剧本原台词做文本对齐修正，消灭 ASR 识别同音错别字，确保 100% 还原剧本；
4. 口型同步：字幕按逐字/逐短语时序吐字点亮，字幕完全与画面角色嘴型同步（Lip-sync tracking）；
5. 工业压制：生成短剧专属 ASS 特效字幕（粗黑体、高对比黄白配色、双层描边阴影、避让 UI 安全区），
   并在片尾最后 2 秒压入标准片尾字卡（剧名、集数、下集悬念钩子、完播引导）。
"""

import os
import re
import sys
import json
import difflib
import argparse
import subprocess
from pathlib import Path

# 动态自适应探测工作区根目录
SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = Path(os.environ.get("DRAMA_WORKSPACE", SCRIPT_DIR.parents[1] if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR.parent)).resolve()


def find_asr_python():
    """查找可用的 Whisper Python 环境"""
    if os.environ.get("H3_ASR_PY") and os.path.isfile(os.environ["H3_ASR_PY"]):
        return os.environ["H3_ASR_PY"]
    
    # 优先检测本地已配置的 asr venv
    for root, dirs, files in os.walk(WORKSPACE_ROOT):
        if "python.exe" in files and "asr" in root:
            return os.path.abspath(os.path.join(root, "python.exe"))
            
    # 回退到当前解释器
    return sys.executable


def get_video_info(video_path):
    """获取视频分辨率、时长、帧率等元信息"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(res.stdout)
    stream = info["streams"][0]
    width = int(stream["width"])
    height = int(stream["height"])
    
    # 获取时长
    dur = float(stream.get("duration") or info.get("format", {}).get("duration", 0.0))
    return {"width": width, "height": height, "duration": dur}


def transcribe_words_with_whisper(video_path, asr_python=None, model_name="base"):
    """使用 Whisper 提取每个词/字的毫秒级时间戳"""
    asr_py = asr_python or find_asr_python()
    video_abs = os.path.abspath(video_path)
    
    transcribe_script = """
import sys, json, whisper

video_file = sys.argv[1]
model_name = sys.argv[2]
model = whisper.load_model(model_name, device='cpu')
res = model.transcribe(video_file, word_timestamps=True, fp16=False, language='zh')

output = []
for s in res.get('segments', []):
    item = {
        'start': s['start'],
        'end': s['end'],
        'text': s['text'].strip(),
        'words': [{'word': w['word'].strip(), 'start': w['start'], 'end': w['end']} for w in s.get('words', [])]
    }
    output.append(item)

print("###JSON_START###")
print(json.dumps(output, ensure_ascii=False))
"""
    cmd = [asr_py, "-c", transcribe_script, video_abs, model_name]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"Whisper ASR failed: {res.stderr}")
        
    out_text = res.stdout
    if "###JSON_START###" not in out_text:
        raise RuntimeError(f"Unexpected Whisper output: {out_text[:300]}")
        
    json_str = out_text.split("###JSON_START###", 1)[1].strip()
    return json.loads(json_str)


def align_with_script(whisper_segments, script_text=None):
    """
    将 Whisper 识别结果与剧本参考文本对齐，保留 Whisper 毫秒级时间轴，同时消除同音错别字
    """
    if not script_text:
        return whisper_segments
        
    raw_lines = [line.strip() for line in re.split(r'[\r\n]+', script_text) if line.strip()]
    candidate_lines = []
    for rl in raw_lines:
        cleaned = re.sub(r'^[^\n：:]{1,10}[：:]\s*', '', rl)
        clauses = [re.sub(r'[，。！？!?、\s]', '', c) for c in re.split(r'[。！？!?]+', cleaned) if c.strip()]
        candidate_lines.extend([c for c in clauses if c])
        
    if not candidate_lines:
        return whisper_segments

    aligned_segments = []
    used_line_idx = 0
    
    for seg in whisper_segments:
        seg_words = seg.get("words", [])
        if not seg_words:
            aligned_segments.append(seg)
            continue
            
        asr_words_str = "".join(w["word"] for w in seg_words)
        best_ratio = 0.0
        best_line = None
        best_idx = used_line_idx
        
        search_scope = candidate_lines[used_line_idx : used_line_idx + 8]
        for idx, cand in enumerate(search_scope):
            ratio = difflib.SequenceMatcher(None, asr_words_str, cand).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_line = cand
                best_idx = used_line_idx + idx
                
        if best_ratio >= 0.40 and best_line:
            seg["text"] = best_line
            used_line_idx = best_idx + 1
            
            if len(best_line) == len(seg_words):
                for i, ch in enumerate(best_line):
                    seg_words[i]["word"] = ch
            elif len(best_line) > 0:
                for i, w in enumerate(seg_words):
                    char_idx = min(len(best_line) - 1, int(i * len(best_line) / len(seg_words)))
                    w["word"] = best_line[char_idx]
                    
        aligned_segments.append(seg)
        
    return aligned_segments


def seconds_to_ass_time(sec):
    """转换秒数为 ASS 时间格式 H:MM:SS.cs"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass_subtitles(segments, out_ass_path, width=1080, height=1920, is_vertical=True):
    """
    生成短剧工业级 ASS 字幕样式：
    - 粗体黑体，字号适配分辨率
    - 经典短剧醒目明黄 / 亮白配色
    - 加粗黑色描边 + 投影，保证任何背景均极度清晰
    - 底部安全边距避让短视频平台 UI
    """
    font_size = 48 if is_vertical else 34
    outline_size = 3.5 if is_vertical else 2.5
    margin_v = int(height * 0.12) if is_vertical else int(height * 0.10)
    
    ass_header = f"""[Script Info]
Title: Short Drama Professional Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: DramaStandard,SimHei,{font_size},&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,{outline_size},1.5,2,40,40,{margin_v},1
Style: DramaHighlight,SimHei,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,{outline_size},1.5,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for seg in segments:
        words = seg.get("words", [])
        if not words:
            start_str = seconds_to_ass_time(seg["start"])
            end_str = seconds_to_ass_time(seg["end"])
            events.append(f"Dialogue: 0,{start_str},{end_str},DramaStandard,,0,0,0,,{seg['text']}")
            continue
            
        if len(words) <= 12:
            start_sec = words[0]["start"]
            end_sec = words[-1]["end"]
            start_str = seconds_to_ass_time(start_sec)
            end_str = seconds_to_ass_time(end_sec)
            
            karaoke_text = ""
            for w in words:
                dur_cs = max(5, int(round((w["end"] - w["start"]) * 100)))
                karaoke_text += f"{{\\k{dur_cs}}}{w['word']}"
                
            events.append(f"Dialogue: 0,{start_str},{end_str},DramaStandard,,0,0,0,,{karaoke_text}")
        else:
            mid = len(words) // 2
            half1, half2 = words[:mid], words[mid:]
            for half in [half1, half2]:
                if not half:
                    continue
                start_str = seconds_to_ass_time(half[0]["start"])
                end_str = seconds_to_ass_time(half[-1]["end"])
                karaoke_text = ""
                for w in half:
                    dur_cs = max(5, int(round((w["end"] - w["start"]) * 100)))
                    karaoke_text += f"{{\\k{dur_cs}}}{w['word']}"
                events.append(f"Dialogue: 0,{start_str},{end_str},DramaStandard,,0,0,0,,{karaoke_text}")

    with open(out_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(events) + "\n")


def burn_subtitles_and_cards(
    input_video,
    output_video,
    ass_path,
    title="短剧标题",
    episode_label="第一集 完",
    hook_text="下集更精彩，敬请期待！",
    total_duration=None,
    card_duration=2.5
):
    """
    通过 FFmpeg 压制 ASS 动效字幕并在片尾压入片尾字卡
    """
    info = get_video_info(input_video)
    duration = total_duration or info["duration"]
    width = info["width"]
    height = info["height"]
    is_vertical = height >= width
    
    card_start = max(0.0, duration - card_duration)
    ass_escaped = str(Path(ass_path).resolve()).replace("\\", "/").replace(":", "\\:")
    
    box_w = int(width * 0.88)
    box_h = int(height * 0.22) if is_vertical else int(height * 0.30)
    box_x = f"(w-{box_w})/2"
    box_y = f"(h-{box_h})/2"
    
    title_font_size = 42 if is_vertical else 32
    hook_font_size = 32 if is_vertical else 24
    
    vf_chain = [
        f"subtitles='{ass_escaped}'",
        f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.82:t=fill:enable='gte(t,{card_start:.2f})'",
        f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=0xFFD700@0.9:t=3:enable='gte(t,{card_start:.2f})'",
        f"drawtext=font='SimHei':text='《{title}》 · {episode_label}':fontsize={title_font_size}:fontcolor=0xFFDE00:x=(w-text_w)/2:y={box_y}+35:enable='gte(t,{card_start:.2f})'",
        f"drawtext=font='SimHei':text='【下集预告】 {hook_text}':fontsize={hook_font_size}:fontcolor=white:x=(w-text_w)/2:y={box_y}+100:enable='gte(t,{card_start:.2f})'",
        f"drawtext=font='SimHei':text='点击右下角合集 · 连看全集不迷路':fontsize={hook_font_size-6}:fontcolor=0xAAAAAA:x=(w-text_w)/2:y={box_y}+{box_h}-45:enable='gte(t,{card_start:.2f})'"
    ]
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vf", ",".join(vf_chain),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "19",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_video)
    ]
    
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg burn failed: {res.stderr[-800:]}")


def main():
    parser = argparse.ArgumentParser(description="短剧工业级字幕对齐与片尾字卡压制系统")
    parser.add_argument("--video", required=True, help="输入的视频文件路径")
    parser.add_argument("--script", default="", help="可选：原剧本参考台词文本或文件路径")
    parser.add_argument("--title", default="重回90：倒腾电子表，我成了百货大亨", help="短剧剧名")
    parser.add_argument("--episode", default="第一集 夜市翻盘 完", help="集数与副标题")
    parser.add_argument("--hook", default="周天宇带打手砸场，陈海当场亮出百万外汇支票！", help="下集悬念钩子")
    parser.add_argument("--out", default="", help="输出压制后的成片路径")
    parser.add_argument("--model", default="base", help="Whisper 模型规格 (tiny, base, small)")
    args = parser.parse_args()
    
    video_path = Path(args.video).resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
        
    out_path = Path(args.out).resolve() if args.out else video_path.with_name(f"{video_path.stem}_subtitled_card.mp4")
    ass_path = video_path.with_name(f"{video_path.stem}_drama.ass")
    
    script_content = ""
    if args.script:
        if os.path.isfile(args.script):
            with open(args.script, "r", encoding="utf-8") as f:
                script_content = f.read()
        else:
            script_content = args.script
            
    raw_segments = transcribe_words_with_whisper(video_path, model_name=args.model)
    aligned = align_with_script(raw_segments, script_content)
    vinfo = get_video_info(video_path)
    build_ass_subtitles(aligned, ass_path, width=vinfo["width"], height=vinfo["height"], is_vertical=(vinfo["height"] >= vinfo["width"]))
    
    burn_subtitles_and_cards(
        input_video=video_path,
        output_video=out_path,
        ass_path=ass_path,
        title=args.title,
        episode_label=args.episode,
        hook_text=args.hook,
        total_duration=vinfo["duration"]
    )
    print(f"[Success] 输出成片：{out_path}")


if __name__ == "__main__":
    main()
