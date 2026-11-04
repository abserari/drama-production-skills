# -*- coding: utf-8 -*-
"""台词 ASR 自动比对：VAD 定位语声段 → whisper 转写 → 与 <d> 原文比对。
用法：
  $PY check_dialogue_asr.py --file 成片/seg02.mp4 --text "<d>撑住！</d>"
  $PY check_dialogue_asr.py --seg seg02          （自动读 segments/seg02.txt 的 <d> 与成片/）
判定：相似度 ≥0.65 PASS / 0.40-0.65 WARN（听一遍人工确认）/ <0.40 FAIL（错字重抽依据）。
说明：走 H3_TTS_HOME venv 的 whisper（模型 small，CPU 可跑，不与 ComfyUI 抢显存）。
"""
import os
import re
import sys
import json
import subprocess
import difflib
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TTS_PY = os.environ.get("H3_ASR_PY") or (os.path.join(os.environ["H3_TTS_HOME"], ".venv", "Scripts", "python.exe") if os.environ.get("H3_TTS_HOME") else sys.executable)
FFMPEG = os.environ.get("H3_FFMPEG") or "ffmpeg"
PASS_MIN, WARN_MIN = 0.65, 0.40


def extract_dialogues(text):
    return [d.strip() for d in re.findall(r"<d>(.*?)</d>", text, re.S) if d.strip()]


def _norm(s):
    """去空白/标点，小写——比对只看字。"""
    return re.sub(r"[\s，。！？!?.,、…—·「」『』（）()：:；;~～]+", "", s).lower()


def detect_lang(text):
    """从 <d> 原文推 whisper 语言。auto 对短喊叫会误判（实测「撑住！」→韩语）。"""
    if re.search(r"[\u3040-\u30ff]", text):   # 假名
        return "ja"
    if re.search(r"[\u4e00-\u9fff]", text):   # 汉字（无假名）
        return "zh"
    if re.search(r"[a-zA-Z]", text):
        return "en"
    return "auto"


def transcribe_segments(wav, events, language, dialogues):
    """venv python + whisper 转写每个语声事件，返回 [text, ...]。
    whisper 导入重，放子进程跑，主进程保持轻快。
    language 由 <d> 原文推导（auto 对短喊叫会误判）；原文作 initial_prompt 引导。"""
    model_path = os.environ.get("H3_WHISPER_MODEL") or os.path.expanduser("~/.cache/whisper/small.pt")
    if not os.path.isfile(model_path):
        raise RuntimeError("ASR model unavailable; set H3_WHISPER_MODEL to a local model file. No automatic download.")
    code = r'''
import sys, json
import whisper
wav, events_json, language, prompt = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
events = json.loads(events_json)
model = whisper.load_model(sys.argv[5], device="cpu")
kw = {"fp16": False}
if language and language != "auto":
    kw["language"] = language
if prompt:
    kw["initial_prompt"] = prompt
out = []
for st, en in events:
    r = model.transcribe(wav, **kw, condition_on_previous_text=False)
    # 只保留落在本事件时间窗内的片段
    txt = "".join(s["text"] for s in r["segments"]
                  if s["end"] > st - 0.2 and s["start"] < en + 0.2)
    out.append(txt.strip())
print(json.dumps(out, ensure_ascii=False))
'''
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(FFMPEG) + os.pathsep + env.get("PATH", "")  # whisper.load_audio 要调 ffmpeg
    r = subprocess.run([TTS_PY, "-c", code, wav, json.dumps(events), language or "auto",
                        "、".join(dialogues), model_path],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600, env=env)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def extract_wav(mp4, out_wav):
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", mp4, "-ac", "1", "-ar", "16000",
                    out_wav], check=True, capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="成片 mp4")
    ap.add_argument("--text", help="含 <d> 的提示词文本（或 --seg 自动读）")
    ap.add_argument("--seg", help="段名：自动取 segments/<seg>.txt 与 成片/<seg>.mp4")
    ap.add_argument("--language", default="auto", help="whisper 语言（默认 auto）")
    a = ap.parse_args()

    import paths
    paths.force_utf8_stdio()
    if a.seg:
        seg_txt = os.path.join(paths.SEG_DIR, a.seg + ".txt")
        a.text = open(seg_txt, encoding="utf-8").read()
        a.file = a.file or os.path.join(paths.FINISH_DIR, a.seg + ".mp4")
    if not (a.file and a.text):
        raise SystemExit("需要 --file + --text，或 --seg")
    dialogues = extract_dialogues(a.text)
    if not dialogues:
        print("[asr] 该段无台词，跳过")
        return

    import h3vad
    events = [(e["start"], e["end"]) for e in h3vad.speech_events(a.file, merge_gap=0.6)]
    if not events:
        raise SystemExit("[asr][FAIL] 全片无语声事件——台词没生成")
    print(f"[asr] 台词 {len(dialogues)} 句 | 语声事件 {len(events)} 个")

    tmp_wav = os.path.join(paths.tmp_audio(), "_asr_seg.wav")
    extract_wav(a.file, tmp_wav)
    lang = a.language if a.language != "auto" else detect_lang(a.text)
    print(f"[asr] 语言={lang}")
    asr_texts = transcribe_segments(tmp_wav, events, lang, dialogues)
    os.remove(tmp_wav)

    verdicts, used = [], set()
    for i, d in enumerate(dialogues):
        ref = _norm(d)
        best, bi = -0.1, -1
        for j, t in enumerate(asr_texts):
            if j in used:
                continue
            r = difflib.SequenceMatcher(None, ref, _norm(t)).ratio()
            if r > best:
                best, bi = r, j
        if bi >= 0:
            used.add(bi)
        tag = "PASS" if best >= PASS_MIN else ("WARN" if best >= WARN_MIN else "FAIL")
        verdicts.append(tag)
        print(f"  [{tag}] 相似度 {best:.2f} | 台词: {d[:20]}")
        print(f"        ASR : {(asr_texts[bi] if bi >= 0 else '(未匹配)')[:40]}")
    n_fail, n_warn = verdicts.count("FAIL"), verdicts.count("WARN")
    print(f"[asr] 总判定: {'FAIL 需重抽/换 seed' if n_fail else ('WARN 请人耳复核' if n_warn else 'PASS')}")
    return 1 if n_fail else (2 if n_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
