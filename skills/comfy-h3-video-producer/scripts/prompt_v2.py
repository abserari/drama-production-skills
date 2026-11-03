# -*- coding: utf-8 -*-
"""H3 提示词拼装器：Seedance 2.5 细节控制 × MiniMax H3 房规格式。

规范见 ../references/prompt_standard_v2.md；内容生动性见 ../references/vividness.md。

用法：新项目建 `<项目>/prompts.py`，`from prompt_v2 import H3, audio_line`，
用 H3() 拼七段骨架，把结果写进 `<项目>/segments/<seg>.txt`（纯正文）。
preflight 由 `sop_run.py submit` 自动执行，不必单独跑。

V2_SEGS 保留为空字典（历史示例库已删除）：`check_prompt_v2.py --seg` 只为兼容旧命令，
新项目一律用 `--file` / `--dir`。声线卡：`paths.VOICE_CARD`（项目内优先）。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import VOICE_CARD  # noqa: E402

# 惰性加载：避免 import 时强依赖 voice_card.json（《灯》示例 V2_SEGS 引用 S3，
# 新项目换通用声线卡后 import 不应崩。首次调用 audio_line 时才读卡。）
VC = None


def _voice_card():
    global VC
    if VC is None:
        VC = json.load(open(VOICE_CARD, encoding="utf-8"))
    return VC


def audio_line(key, sid):
    """<Audio N> 行（不含前导 "- "，由 H3() 统一加）：文本逐字取自 voice_card.json，禁止就地改写。"""
    return f"<Audio {sid}> {_voice_card()[key]['prompt_text']}"


def H3(subjects, summary, style, light, space, axis, scale, motion,
       beats, end_state, soundscape, negs, time_pos="", emotion_arc=""):
    """按 H3 房规七段骨架拼装提示词。

    subjects: list[str]，subject_definitions 各行（不含前导 "- "）
    beats: list[str]，每项是完整的 "[节拍 N] …" 一行
    emotion_arc: 可选，段级"情感弧线"一句话（节奏骨架 + 景别走向，见 prompt_standard 三-⑥），
                 填入 detailed_description 段首（风格行之后、时间光线之前）
    """
    parts = ["subject_definitions:"]
    parts += [f"- {s}" for s in subjects]
    parts += ["", "summary:", summary, "", "detailed_description:", style]
    if emotion_arc:
        parts.append(f"情感弧线：{emotion_arc}")
    parts.append(f"时间光线：{light}")
    if time_pos:
        parts.append(f"时间位置：{time_pos}")
    parts.append(f"空间环境：{space}")
    parts.append(f"方位参照：{axis}")
    parts.append(f"规模锚点：{scale}")
    parts.append(f"环境次级运动：{motion}")
    parts += beats
    parts.append(f"[结尾状态] {end_state}")
    parts.append("")
    parts.append("overall_soundscape:")
    parts.append(soundscape)
    parts.append("non_diegetic_music:")
    parts.append("禁BGM/字幕/水印/UI/Logo")
    parts.append("防错约束：")
    parts += [f"- {n}" for n in negs]
    return "\n".join(parts)


V2_SEGS = {}
