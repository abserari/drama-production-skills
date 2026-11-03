# -*- coding: utf-8 -*-
"""
MiniMax H3 工业级导演提示词与视听调度引擎 v3.0
Director Engine v3.0 for MiniMax H3 Video Producer

核心解决 7 大工业落地痛点：
1. 【首帧垫图前置】：提供分镜级场景/角色/道具定帧提示词编译规范；
2. 【单人发言锁定】：强制指定唯一说话人，其余全员严格闭嘴抑制 (Strict Mouth Suppression)；
3. 【全局风格锚点】：严格继承全局 Style Bible，杜绝画风漂移；
4. 【短剧紧凑语速】：字数密度控制在 20~28 字/7.3s，配合 rapid delivery 提示词；
5. 【多元动态运镜】：提供 6 大电影级镜头调度模板，严禁呆板站桩面对面正反打；
6. 【纯正普通话纯净化】：纯汉字归一化（数字大写、去英文符号），强制 Mandarin 语言锁定；
7. 【工程化 Skill 规范】：标准化输出 plan.json 与 7 段式提示词。
"""

import re
from typing import Dict, List, Any, Optional

# ==============================================================================
# 1. 全局风格母卡预设 (Style Bible Presets)
# ==============================================================================
STYLE_PRESETS = {
    "griftlands_dieselpunk_noir": {
        "style_name": "欺诈之地·暗黑柴油朋克电影质感",
        "visual_genre": "Cinematic retro-future dieselpunk graphic novel style, mature neo-noir tone",
        "environment_base": "gritty industrial sci-fi textures, weathered rust and scuffed brass, neon glare reflecting on damp asphalt, atmospheric smog",
        "lighting_base": "heavy chiaroscuro lighting, harsh directional rim light, high contrast dramatic shadows, volumetric light rays",
        "quality_base": "35mm film grain, Panavision anamorphic lens flare, shallow depth of field, 8k resolution, photorealistic cinematic masterpiece, photorealistic textures",
        "color_palette": "desaturated amber and deep teal contrast, rusty bronze highlights, rich shadow details"
    },
    "cyberpunk_neon_crime": {
        "style_name": "赛博罪案·高对比霓虹电影感",
        "visual_genre": "High-budget cyberpunk crime thriller, cinematic realistic film style",
        "environment_base": "dense futuristic backalleys, holographic advertisements, flickering neon tubes, wet reflections",
        "lighting_base": "vibrant neon rim lighting, deep shadows, moody wet street illumination",
        "quality_base": "Arri Alexa LF footage, crisp focus, anamorphic bokeh, 4k master",
        "color_palette": "electric cyan, hot magenta, midnight blue"
    }
}

# ==============================================================================
# 2. 6 大电影级动态镜头调度模板 (Director Staging & Camera Presets)
# ==============================================================================
CAMERA_STAGING_MODES = {
    "cross_walking_tracking": {
        "name": "动线交错慢推",
        "shot_desc": "Slow forward tracking shot following character walking briskly through the room, camera pushing in steadily, dynamic background movement, continuous tension.",
        "pacing": "high_tension"
    },
    "prop_to_face_rack_focus": {
        "name": "道具特写变焦至人脸",
        "shot_desc": "Extreme close-up starting on the prop (slammed on table/held in hands), rapid rack focus up to the speaker's intense glaring eyes, shallow depth of field, dramatic depth shift.",
        "pacing": "climax"
    },
    "dutch_angle_tilt": {
        "name": "荷兰角斜切逼迫",
        "shot_desc": "15-degree Dutch angle tilted low shot, looking up at the dominant character stepping forward intimidatingly, creating extreme psychological pressure and cinematic unease.",
        "pacing": "threat"
    },
    "back_turned_reveal": {
        "name": "背身转头回眸",
        "shot_desc": "Character begins with their back turned towards camera speaking coldly, suddenly pivots their head 90 degrees to deliver the punchline with an icy stare, dramatic rim lighting catches their jawline.",
        "pacing": "reveal"
    },
    "close_whisper_threat": {
        "name": "贴耳逼近压迫",
        "shot_desc": "Tight medium close-up, speaker leans in uncomfortably close towards the listener's ear, whispered menacing intensity, listener flinches slightly while speaker holds cold direct gaze.",
        "pacing": "interrogation"
    },
    "side_profile_confrontation": {
        "name": "侧光剪影交错",
        "shot_desc": "Cinematic two-shot in profile, characters not looking directly into each other's eyes but glaring past each other, split lighting separating them, smoke drifting between them.",
        "pacing": "standoff"
    }
}

# ==============================================================================
# 3. 台词文本纯净化（纯正中文发音规约）
# ==============================================================================
NUMBER_MAP = {
    "0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
    "5": "五", "6": "六", "7": "七", "8": "八", "9": "九"
}

def normalize_chinese_dialogue(raw_dialogue: str) -> str:
    """
    纯净化台词：
    1. 剥离已有的 <d></d> 标签；
    2. 数字转为纯中文汉字；
    3. 去除一切英文、特殊代码符号；
    4. 规范标点符号为标准中文标点。
    """
    text = re.sub(r'</?d>', '', raw_dialogue).strip()
    
    # 替换简单数字
    def replace_num(match):
        n = match.group(0)
        return "".join(NUMBER_MAP.get(c, c) for c in n)

    text = re.sub(r'\d+', replace_num, text)

    # 去除外文字符与特殊非法符号
    text = re.sub(r'[a-zA-Z_#@$%^&*+=\\]', '', text)

    # 规范化标点
    text = text.replace(",", "，").replace("!", "！").replace("?", "？").replace(":", "：").replace(";", "；")

    # 再次修剪
    text = re.sub(r'\s+', '', text)
    return f"<d>{text}</d>"


def check_dialogue_pacing_density(dialogue_text: str, duration_sec: float = 7.29) -> Dict[str, Any]:
    """
    台词语速密度校验：
    - 7.3s 标准时序黄金字数：20~28 汉字（语速 3.2~4.0 字/秒）
    - 少于 15 字：判定为语速过慢（会导致拉长音发呆）
    - 超过 32 字：判定为语速过密（会导致吐词不清吞字）
    """
    clean_chars = re.sub(r'</?d>|[，。！？：；…“”‘’]', '', dialogue_text)
    char_count = len(clean_chars)
    cps = round(char_count / duration_sec, 2)

    status = "OPTIMAL"
    warning = ""
    if char_count < 16:
        status = "TOO_SLOW"
        warning = f"台词仅 {char_count} 字，语速偏慢 ({cps} 字/秒)，建议扩充动作描述或补齐对白至 20~26 字，防止拉长音。"
    elif char_count > 30:
        status = "TOO_FAST"
        warning = f"台词达 {char_count} 字，语速过快 ({cps} 字/秒)，建议精简至 28 字以内，防止吞音。"

    return {
        "char_count": char_count,
        "chars_per_sec": cps,
        "status": status,
        "warning": warning
    }


# ==============================================================================
# 4. 单人发音与闭嘴抑制指令构建器 (Speaker Lock & Mouth Suppression)
# ==============================================================================
def build_speaker_action_prompt(
    speaker_name: str,
    speaker_action: str,
    other_characters: List[str],
    other_action: str = "standing motionlessly, showing cold alert glance"
) -> str:
    """
    强制单人说话与全员闭嘴协议：
    在 [Action] 中严格分离说话人与旁观者，彻底消除全员动嘴的木偶剧惨状。
    """
    speaker_directive = (
        f"Only {speaker_name} is actively speaking with natural, synchronized Mandarin lip movement, "
        f"{speaker_action}. "
    )

    if other_characters:
        others_str = " and ".join(other_characters)
        suppression_directive = (
            f"Crucial requirement: {others_str} remain strictly silent with lips tightly sealed and mouths completely closed, "
            f"neither speaking nor making any mouth motions, {other_action}. "
        )
    else:
        suppression_directive = "All other figures in the scene maintain strictly closed mouths without any lip movement. "

    # 句尾死条款：最后 1.2 秒全员闭嘴凝视
    climax_buffer = "In the final 1.2 seconds, all characters firmly close their mouths, ending on a tense silent glare."

    return speaker_directive + suppression_directive + climax_buffer


# ==============================================================================
# 5. 纯正普通话语音指令构建器 (Mandarin Purity Directive)
# ==============================================================================
def build_mandarin_audio_prompt(
    speaker_name: str,
    dialogue_clean: str,
    emotion_tone: str = "firm, aggressive and theatrical",
    speed_tag: str = "spoken rapidly and crisply without dragging syllables"
) -> str:
    """
    构建包含强语言约束的 [Audio] 块：
    1. 锁定标纯普通话标准发音；
    2. 明确情绪基调与高密度紧凑语速；
    3. 规范包裹 <d>纯中文台词</d>。
    """
    audio_prompt = (
        f"Strict Mandarin Chinese dialogue only, standard native Chinese accent with clear articulation, "
        f"zero foreign tone, zero English words. {speaker_name} speaks with a {emotion_tone} vocal delivery, "
        f"{speed_tag}. Ambient room tone with subtle mechanical hum: {dialogue_clean}"
    )
    return audio_prompt


# ==============================================================================
# 6. 七段式工业级提示词完整装配器 (Full 7-Section Prompt Assembler)
# ==============================================================================
def compile_director_prompt(
    style_key: str,
    camera_mode: str,
    speaker_name: str,
    speaker_appearance: str,
    speaker_action: str,
    other_characters: List[Dict[str, str]],  # [{"name": "Merchant", "desc": "fat man in dirty coat"}]
    dialogue_raw: str,
    environment_detail: str,
    prop_detail: str = "",
    emotion_tone: str = "threatening and decisive",
    custom_lighting: str = ""
) -> Dict[str, Any]:
    """
    完整装配单段分镜的七段式提示词及质检报告
    """
    style = STYLE_PRESETS.get(style_key, STYLE_PRESETS["griftlands_dieselpunk_noir"])
    camera = CAMERA_STAGING_MODES.get(camera_mode, CAMERA_STAGING_MODES["cross_walking_tracking"])

    # 1. 规范台词与密度分析
    clean_dialogue = normalize_chinese_dialogue(dialogue_raw)
    pacing_check = check_dialogue_pacing_density(clean_dialogue)

    # 2. [Shot 1]
    shot_section = f"[Shot 1] {camera['shot_desc']}"

    # 3. [Subject 1] 角色主体与从属关系
    others_names = [o["name"] for o in other_characters]
    others_desc_list = [f"{o['name']} ({o.get('desc', 'bystander')})" for o in other_characters]
    others_desc_str = ", alongside " + ", ".join(others_desc_list) if others_desc_list else ""
    subject_section = (
        f"[Subject 1] Primary speaker: {speaker_name}, {speaker_appearance}{others_desc_str}. "
        f"Distinct character identities, highly consistent facial bone structure, wearing detailed costumes."
    )

    # 4. [Action 1] 动作与闭嘴抑制
    action_section = f"[Action 1] {build_speaker_action_prompt(speaker_name, speaker_action, others_names)}"

    # 5. [Environment 1] 场景与道具
    prop_clause = f" Key prop in interaction: {prop_detail}." if prop_detail else ""
    env_section = f"[Environment 1] {environment_detail}, {style['environment_base']}.{prop_clause}"

    # 6. [Lighting 1]
    light_desc = custom_lighting if custom_lighting else style["lighting_base"]
    lighting_section = f"[Lighting 1] {light_desc}, color mood: {style['color_palette']}."

    # 7. [Audio 1]
    audio_section = f"[Audio 1] {build_mandarin_audio_prompt(speaker_name, clean_dialogue, emotion_tone)}"

    # 8. [Quality 1]
    quality_section = f"[Quality 1] {style['visual_genre']}, {style['quality_base']}."

    # 拼装完整提示词文本
    full_prompt_text = "\n\n".join([
        shot_section,
        subject_section,
        action_section,
        env_section,
        lighting_section,
        audio_section,
        quality_section
    ])

    return {
        "full_prompt_text": full_prompt_text,
        "clean_dialogue": clean_dialogue,
        "pacing_check": pacing_check,
        "camera_mode_used": camera["name"],
        "speaker_locked": speaker_name,
        "suppressed_characters": others_names
    }


if __name__ == "__main__":
    # 测试用例：Sal 与受贿商人的对抗
    res = compile_director_prompt(
        style_key="griftlands_dieselpunk_noir",
        camera_mode="prop_to_face_rack_focus",
        speaker_name="Sal",
        speaker_appearance="badass female bounty hunter with short spiky hair, cybernetic eye patch, dark leather vest",
        speaker_action="slams a heavy iron dagger onto the wooden desk, leaning forward aggressively",
        other_characters=[{"name": "Merchant", "desc": "terrified corrupt merchant in greasy coat"}],
        dialogue_raw="你想用这几块破骨币打发我？把账本拿出来！",
        environment_detail="Dimly lit subterranean black market stall, shelves packed with forbidden scrap tech and leaking oil cans",
        prop_detail="sharp serrated hunting dagger vibrating as it sticks into the tabletop",
        emotion_tone="cold, intimidating and razor-sharp"
    )
    print("=== 生成的高保真提示词 ===")
    print(res["full_prompt_text"])
    print("\n=== 质检状态 ===")
    print("台词分析:", res["pacing_check"])
    print("单人说话锁定:", res["speaker_locked"], "| 闭嘴抑制:", res["suppressed_characters"])
