# -*- coding: utf-8 -*-
"""
《欺诈之地》全十集（EP01~EP10）80 分镜结构化提示词与 plan.json 自动化工程生成器
严格对标 MiniMax H3 v2.2 七段式骨架与《倒腾电子表》短剧工业标准：
1. 100% 对白零缺失（80 段分镜全覆盖），段首 <d>...</d> 标签先声夺人；
2. 175 帧时序（7.29s @ 24fps），段尾严格预留 1.2 秒（约 29 帧）闭嘴凝视缓冲；
3. 严格遵循 180° 绝对视轴正反打与防削头撑桌构图；
4. 明确标注中远景 (MLS/LS) 与近景特写 (CU/MCU/ECU)，供远景修脸管线精准识别。
"""

import os
import re
import sys
import json
from pathlib import Path

# Windows UTF-8 控制台兼容
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE_ROOT = Path(r"c:\Users\34903\Documents\短剧试做")
EPISODES_ROOT = WORKSPACE_ROOT / "欺诈之地_全十集"

# ==============================================================================
# 角色定义注册表 (S1 ~ S8)
# ==============================================================================
CHARACTER_REGISTRY = {
    "S1": {
        "name": "萨儿 (Sal)",
        "role": "26岁女性赏金猎人",
        "subject_en": "<Subject 1> Sal, 26-year-old female bounty hunter, 1.75m",
        "features": "auburn cropped hair, right eye cybernetic tactical monocle glowing with faint blue crosshairs, weathered desert duster coat, charcoal high-collar leather armor, dual high-frequency vibration alloy daggers holstered at waist",
        "audio_card": "<Audio 1> Sal's voice (26yo female, medium-low vocal register, tight vocal cords, controlled breath, cold and sharp articulation, Mandarin Chinese, no crying or sighing)"
    },
    "S2": {
        "name": "酒保菲兹 (Fiz)",
        "role": "45岁半机械义体酒保",
        "subject_en": "<Subject 2> Fiz, 45-year-old cyborg bartender, 1.80m",
        "features": "gaunt pale face, tarnished brass cybernetic mechanical right arm with exposed gears and servos, stained oil-soaked heavy leather apron, scarred cybernetic red eye lens",
        "audio_card": "<Audio 2> Fiz's voice (45yo male, gravelly low tone with mechanical filter resonance, relaxed cords, deliberate tempo, Mandarin Chinese)"
    },
    "S3": {
        "name": "考希欧 (Kashio)",
        "role": "35岁狂妄军阀首领",
        "subject_en": "<Subject 3> Kashio, 35-year-old ruthless warlord, 2.10m",
        "features": "massive muscular build, matte-black heavy powered exoskeleton armor, dual high-pressure exhaust vents on shoulders, wielding a two-meter high-frequency vibration broadsword",
        "audio_card": "<Audio 3> Kashio's voice (35yo male, arrogant aggressive tone with heavy mechanical loudspeaker resonance, punchy word onset, Mandarin Chinese)"
    },
    "S4": {
        "name": "狂欢帮打手 / 刺客 / 卫兵 (Spree Enforcer / Assassin / Guard)",
        "role": "30岁荒原强盗刺客或重装卫兵",
        "subject_en": "<Subject 4> Spree Enforcer, 30-year-old wasteland outlaw assassin, 1.82m",
        "features": "bald head with tribal gang tattoos, studded spiked leather vest, wielding poisoned serrated combat dagger or blaster pistol, predatory ferocious glare",
        "audio_card": "<Audio 4> Spree Enforcer's voice (30yo male, raspy gritty sneering tone with provocative breathiness, fast-paced, Mandarin Chinese)"
    },
    "S5": {
        "name": "鱼人中介富什 (Fssh)",
        "role": "40岁两栖鱼人黑市情报贩子",
        "subject_en": "<Subject 5> Foosh, 40-year-old amphibious alien fishman broker, 1.68m",
        "features": "flaring gills on face sides, greasy dark-green wool trench coat, electronic abacus around neck, shrewd calculating eyes",
        "audio_card": "<Audio 5> Foosh's voice (40yo alien male, moist slick timbre with subtle bubble undertones, fast calculating merchant tempo, Mandarin Chinese)"
    },
    "S6": {
        "name": "卡兰德拉军官 (Officer Kalandra)",
        "role": "38岁火花男爵高级治安长官",
        "subject_en": "<Subject 6> Officer Kalandra, 38-year-old Spark Baron high security officer, 1.78m",
        "features": "stern aristocratic features, tailored silver-gray baron military uniform, holstered plasma saber pistol, icy authoritative demeanor",
        "audio_card": "<Audio 6> Kalandra's voice (38yo female, crisp commanding aristocratic tone, steady breath, precise icy diction, Mandarin Chinese)"
    },
    "S7": {
        "name": "拍卖会主事人 / 拍卖师 (Auctioneer)",
        "role": "50岁上流社会司仪",
        "subject_en": "<Subject 7> Auctioneer, 50-year-old elite master of ceremonies, 1.75m",
        "features": "mechanical top hat, velvet tailcoat, glowing cybernetic monocle, gilded auction gavel",
        "audio_card": "<Audio 7> Auctioneer's voice (50yo theatrical male, flamboyant booming orator timbre, formal cadence, Mandarin Chinese)"
    },
    "S8": {
        "name": "男爵最高特使 (Baron's Envoy)",
        "role": "55岁特使贵族",
        "subject_en": "<Subject 8> Baron's Envoy, 55-year-old imperial envoy noble, 1.85m",
        "features": "lavish velvet gold-trimmed cape, floating ceremonial orb, imposing icy aristocratic posture, golden baron sigil sash",
        "audio_card": "<Audio 8> Baron's Envoy's voice (55yo male, resonant cold imperial cadence, heavy authoritative pauses, Mandarin Chinese)"
    }
}

# ==============================================================================
# 场景空间注册表 (EP01 ~ EP10)
# ==============================================================================
SCENE_REGISTRY = {
    "EP01": {
        "space": "Pearl Tavern Bar (tavern_bar)",
        "desc": "grimy industrial tavern interior with cast-iron drainage floor grates, flickering green luminescent lanterns, rusted pipes overhead, worn iron bar counter",
        "particles": "fine yellow wasteland dust motes drifting across dim lantern beams",
        "lighting": "gritty sci-fi noir lighting with cool green fluorescent key light on bar counter, warm amber rim light on characters, dark contrasty shadows",
        "key_dir": "screen-top overhead",
        "rim_dir": "screen-left rim"
    },
    "EP02": {
        "space": "Foosh's Black Market Chamber (black_market_chamber)",
        "desc": "cramped clandestine backroom behind pearl tavern, beaded door curtains, wooden table cracked with abacus, flickering holographic blueprints",
        "particles": "dense damp cigar smoke and electric blue holographic spark dust",
        "lighting": "dim atmospheric under-lighting with cyan holographic projection key light, warm amber desk lamp fill, deep dramatic vignette shadows",
        "key_dir": "table center hologram",
        "rim_dir": "doorway background rim"
    },
    "EP03": {
        "space": "Mud Swamp Toxic Ruins (mud_swamp_ruins)",
        "desc": "rotting Derrida swamp wasteland, gnarled petrified black trees, bubbling corrosive mud puddles, rusted abandoned drilling rig in background",
        "particles": "toxic greenish swamp fog rolling across water surface, firefly embers",
        "lighting": "eerie nocturnal swamp illumination, crimson torchlight key light, sickly green bioluminescent water surface reflection",
        "key_dir": "torch screen-right",
        "rim_dir": "swamp fog back-rim"
    },
    "EP04": {
        "space": "Red Mine Security Checkpoint (red_mine_checkpoint)",
        "desc": "Spark Baron fortified mining perimeter, barbed electrified fence, high-purity crimson crystal transport haulers, armored barricades",
        "particles": "glittering airborne red crystal dust particles suspended in heavy air",
        "lighting": "harsh industrial searchlights with blood-red crystal back-glow, high-contrast authoritarian cool white spotlighting",
        "key_dir": "guard tower searchlight",
        "rim_dir": "red ore hopper edge"
    },
    "EP05": {
        "space": "Grand Auction Hall (auction_grand_hall)",
        "desc": "decadent subterranean aristocratic auction palace, crimson velvet draperies, gilded brass chandeliers, circular tiered gallery packed with oligarchs",
        "particles": "fine gold dust and cigar haze swirling through cathedral-high ceiling beams",
        "lighting": "theatrical high-key chandelier brilliance over velvet stage, deep shadow pockets in spectator stalls, golden specular highlights",
        "key_dir": "grand chandelier above",
        "rim_dir": "gallery balcony edge"
    },
    "EP06": {
        "space": "Safehouse Night Ambush (safehouse_night)",
        "desc": "rain-soaked reinforced brick safehouse, reinforced iron blast shutters, sparking EMP tripwires on wet pavement, shattered window mullions",
        "particles": "diagonal torrential rain streaks and electrical blue arc sparks dancing on puddle ripples",
        "lighting": "stormy nocturnal chiaroscuro with jagged white lightning flashes, blue electric discharge rim light, deep impenetrable pitch-black shadows",
        "key_dir": "window storm flash",
        "rim_dir": "tripwire electric arc"
    },
    "EP07": {
        "space": "Derrick Fortress Drainage Canal (iron_fortress_canal)",
        "desc": "subterranean fortress sewer conduit, massive spinning ventilation fans, humming red laser tripwire grids, dripping hydraulic pipes",
        "particles": "steamy aerosol mist plumes and hot orange plasma torch cutting sparks",
        "lighting": "ominous subterranean crimson laser cross-beams intersecting with blinding blue plasma cutting glare and wet concrete specular sheen",
        "key_dir": "plasma cutter torch",
        "rim_dir": "laser grid reflection"
    },
    "EP08": {
        "space": "Baron Council High Chamber (baron_council_chamber)",
        "desc": "top-floor executive fortress tribunal hall, floor-to-ceiling panoramic blast glass overlooking storm clouds, polished obsidian round table",
        "particles": "pristine filtered air with holographic neon trade route charts hovering in center",
        "lighting": "sleek cold corporate sci-fi lighting, blue holographic table key light, stormy exterior daylight rim from panoramic window",
        "key_dir": "holographic table projector",
        "rim_dir": "panoramic window rim"
    },
    "EP09": {
        "space": "Fortress Rooftop Storm Arena (rooftop_arena_rain)",
        "desc": "wind-swept steel arena platform atop Derrick fortress, torrential rain pounding metal flooring, violent thunderstorm, heavy mech exhaust clouds",
        "particles": "heavy splashing rain droplets, steam exhaust jets, explosive orange and white sword clash sparks",
        "lighting": "apocalyptic storm lighting with fierce continuous lightning bolts illuminating dripping rain armor, blinding electric weapon clashing glows",
        "key_dir": "lightning sky strike",
        "rim_dir": "mech exhaust plume glow"
    },
    "EP10": {
        "space": "Fortress Ruins and Wasteland Dawn (wasteland_dawn)",
        "desc": "smoking shattered battle platform giving way to endless Havaria desert horizon, collapsed mech wreckage smoldering with faint smoke plumes",
        "particles": "golden morning dust motes rising into clear sky, thin smoke trails from cooling metal",
        "lighting": "breathtaking cinematic sunrise lighting with warm golden orange dawn light flooding across characters, soft warm ground fill, crisp long shadows",
        "key_dir": "rising sun on horizon",
        "rim_dir": "golden sky rim"
    }
}

# ==============================================================================
# 解析与生成核心逻辑
# ==============================================================================

def clean_dialogue(raw_dialogue: str) -> str:
    """提取纯净台词文本，去除引号与字数统计"""
    text = raw_dialogue.strip()
    # 提取 “...” 内部
    m = re.search(r'“([^”]+)”', text)
    if m:
        text = m.group(1).strip()
    else:
        # 去除外层引号
        text = re.sub(r'^[“"\'`]+|[”"\'`]+$', '', text).strip()
    # 去除结尾 (XX字) 或 （XX字）
    text = re.sub(r'[\(（]\s*\d+\s*字?\s*[\)）]$', '', text).strip()
    return text


def determine_shot_type(camera_desc: str) -> str:
    """
    根据分镜机位描述精确判定景别分类：
    中远景/全景 -> MLS / LS (触发修脸管线)
    近景/特写/微距 -> CU / MCU / ECU (安全穿透)
    """
    s = camera_desc.upper()
    # 明确特写/近景/微距优先归类
    if any(k in s for k in ["EXTREME CLOSE-UP", "EXTREME CLOSE UP", "ECU", "微距"]):
        return "ECU"
    if any(k in s for k in ["CLOSE-UP PUSH", "CU PUSH", "CLOSE-UP", "CLOSE UP", "CU", "特写"]):
        # 特例：若为由远及近全景推进，则视为主体在中远景建立
        if "CU -> MEDIUM" in s or "特写平滑推进至中景" in s:
            return "MLS"
        return "CU"
    if any(k in s for k in ["MEDIUM CLOSE-UP", "MEDIUM CLOSE UP", "MCU", "近景", "中近景"]):
        return "MCU"
    if any(k in s for k in ["OVER THE SHOULDER", "OTS", "过肩"]):
        return "OTS"
    
    # 中远景 / 全景类
    if any(k in s for k in ["EXTREME LONG SHOT", "ELS", "大远景", "超大远景", "LONG SHOT", "LS", "远景", "全景", "WIDE SHOT", "WS", "WIDE", "FS"]):
        return "LS"
    if any(k in s for k in ["MEDIUM LONG SHOT", "MLS", "中远景", "MEDIUM SHOT", "MS", "中景", "TWO-SHOT", "MEDIUM"]):
        return "MLS"
    
    return "MLS"


def parse_storyboard_file(ep_dir: Path) -> list:
    """解析 EPXX 下的 分镜表.md"""
    sb_file = ep_dir / "分镜表.md"
    if not sb_file.exists():
        raise FileNotFoundError(f"未找到分镜表: {sb_file}")

    content = sb_file.read_text(encoding="utf-8")
    lines = content.splitlines()
    segs = []

    for line in lines:
        l = line.strip()
        if not l.startswith("| **seg"):
            continue
        parts = [p.strip() for p in l.split("|")[1:-1]]
        if len(parts) < 11:
            continue
        
        seg_id = parts[0].replace("*", "").strip()
        length_str = parts[1].replace("帧", "").strip()
        length = int(length_str) if length_str.isdigit() else 175
        
        speaker_raw = parts[2]
        collab_raw = parts[3]
        camera_raw = parts[4]
        axis_raw = parts[5]
        dialogue_raw = parts[6]
        action_raw = parts[7]
        buffer_raw = parts[8]
        sfx_raw = parts[9]
        hook_raw = parts[10]

        # 提取说话人 S1 ~ S8
        spk_m = re.search(r'(S\d+)', speaker_raw)
        speaker_id = spk_m.group(1) if spk_m else "S1"

        # 提取协同人 S1 ~ S8
        collab_m = re.search(r'(S\d+)', collab_raw)
        collab_id = collab_m.group(1) if collab_m else None

        # 清理台词
        plain_dialogue = clean_dialogue(dialogue_raw)
        dialogue_tag = f"<d>{plain_dialogue}</d>"

        # 判定景别
        shot_type = determine_shot_type(camera_raw)

        segs.append({
            "seg": seg_id,
            "length": length,
            "speaker_id": speaker_id,
            "speaker_raw": speaker_raw,
            "collab_id": collab_id,
            "collab_raw": collab_raw,
            "camera_raw": camera_raw,
            "shot_type": shot_type,
            "axis_raw": axis_raw,
            "dialogue_plain": plain_dialogue,
            "dialogue_text": dialogue_tag,
            "action_raw": action_raw,
            "buffer_raw": buffer_raw,
            "sfx_raw": sfx_raw,
            "hook_raw": hook_raw
        })

    return segs


def generate_v22_prompt(ep_id: str, seg: dict) -> str:
    """严格根据规范构建 v2.2 7 段式语义骨架提示词"""
    speaker_id = seg["speaker_id"]
    char_info = CHARACTER_REGISTRY.get(speaker_id, CHARACTER_REGISTRY["S1"])
    scene_info = SCENE_REGISTRY.get(ep_id, SCENE_REGISTRY["EP01"])

    # 1. [Shot 1]
    shot_type = seg["shot_type"]
    camera_move = seg["camera_raw"]
    shot_section = f"[Shot 1] {shot_type} framing, 35mm-50mm anamorphic lens, {camera_move}."

    # 2. [Subject 1]
    axis_desc = seg["axis_raw"]
    if "screen-left" not in axis_desc and "screen-right" not in axis_desc:
        if seg["speaker_id"] in ["S1", "S7"]:
            axis_desc = f"{axis_desc} on screen-left facing right"
        else:
            axis_desc = f"{axis_desc} on screen-right facing left"

    collab_clause = ""
    if seg["collab_id"] and seg["collab_id"] in CHARACTER_REGISTRY:
        collab_char = CHARACTER_REGISTRY[seg["collab_id"]]
        collab_clause = f" Interaction counterpart: {collab_char['subject_en']}, {collab_char['features']}."

    subject_section = (
        f"[Subject 1] {char_info['subject_en']} positioned as {axis_desc}, "
        f"clothing and gear: {char_info['features']}, retention: fully_preserved.{collab_clause}"
    )

    # 3. [Action 1]
    dialogue_tag = seg["dialogue_text"]
    action_desc = seg["action_raw"]
    action_section = (
        f"[Action 1] Speaks sharply {dialogue_tag}, accompanied by precise physical dynamics: {action_desc}. "
        f"At conclusion, both hold a tense silent glare with mouths closed严格预留1.2秒（约29帧）闭嘴凝视缓冲，严禁张嘴残影."
    )

    # 4. [Environment 1]
    env_section = (
        f"[Environment 1] {scene_info['space']}: {scene_info['desc']}. "
        f"Micro dynamic atmosphere: {scene_info['particles']}."
    )

    # 5. [Lighting 1]
    lighting_section = (
        f"[Lighting 1] {scene_info['lighting']}. "
        f"Key light oriented from {scene_info['key_dir']}, edge rim light grazing from {scene_info['rim_dir']}."
    )

    # 6. [Audio 1]
    sfx_clean = seg["sfx_raw"].replace("，禁BGM", "").replace("，段尾数字静音", "")
    audio_section = (
        f"[Audio 1] {char_info['audio_card']}. "
        f"Discrete physical sound effects: {sfx_clean}. "
        f"Digital silence between dialogue intervals, absolute zero background music, zero continuous room rumble."
    )

    # 7. [Quality 1]
    quality_section = (
        "[Quality 1] 8k raw footage, photorealistic, cinematic movie still, master grade, 24fps, "
        "no CGI blur, no morphing, no subtitles, no watermark, no extra limbs, stable facial anatomy."
    )

    prompt_text = "\n".join([
        shot_section,
        subject_section,
        action_section,
        env_section,
        lighting_section,
        audio_section,
        quality_section
    ])
    return prompt_text


def build_episode_prompts_and_plan(ep_dir: Path):
    """为单集构建 plan.json 与 8 个分镜 prompt 文本"""
    ep_name_full = ep_dir.name  # 例如 EP01_归来与旧账
    ep_id = ep_name_full.split("_")[0]  # EP01
    ep_title = ep_name_full.split("_")[1] if "_" in ep_name_full else ep_name_full

    segs = parse_storyboard_file(ep_dir)
    if len(segs) != 8:
        raise ValueError(f"{ep_name_full} 分镜数异常: {len(segs)} != 8")

    # 目标输出目录
    prod_dir = ep_dir / "生产"
    prompts_dir = prod_dir / "prompts"
    refs_dir = prod_dir / "references"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    refs_dir.mkdir(parents=True, exist_ok=True)

    plan_segs = []

    for seg in segs:
        seg_id = seg["seg"]
        prompt_content = generate_v22_prompt(ep_id, seg)

        # 写入 prompts/segXX.txt
        prompt_file = prompts_dir / f"{seg_id}.txt"
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_content)

        plan_segs.append({
            "seg": seg_id,
            "length": seg["length"],
            "dialogue": True,
            "speaker": seg["speaker_id"],
            "speaker_name": CHARACTER_REGISTRY.get(seg["speaker_id"], {}).get("name", seg["speaker_raw"]),
            "collaborator": CHARACTER_REGISTRY.get(seg["collab_id"], {}).get("name", seg["collab_raw"]) if seg["collab_id"] else "-",
            "shot_type": seg["shot_type"],
            "camera_move": seg["camera_raw"],
            "screen_axis": seg["axis_raw"],
            "dialogue_text": seg["dialogue_text"],
            "dialogue_plain": seg["dialogue_plain"],
            "event": seg["action_raw"],
            "buffer_clause": "both hold a tense silent glare with mouths closed 严格预留 1.2 秒（约 29 帧）闭嘴凝视缓冲，严禁张嘴残影",
            "sfx": True,
            "sfx_desc": seg["sfx_raw"],
            "hook": seg["hook_raw"],
            "prompt_file": f"{seg_id}.txt"
        })

    plan_data = {
        "project": "欺诈之地_全十集",
        "episode": ep_id,
        "episode_name": ep_title,
        "fps": 24.0,
        "standard": "v2.2",
        "frame_length": 175,
        "total_segments": len(plan_segs),
        "segs": plan_segs
    }

    # 双写 plan.json 确保顶层与生产子目录兼容
    root_plan = ep_dir / "plan.json"
    prod_plan = prod_dir / "plan.json"

    with open(root_plan, "w", encoding="utf-8") as f:
        json.dump(plan_data, f, ensure_ascii=False, indent=2)

    with open(prod_plan, "w", encoding="utf-8") as f:
        json.dump(plan_data, f, ensure_ascii=False, indent=2)

    print(f"  [✓] {ep_name_full}: 8 分镜提示词已生成 -> {prompts_dir.relative_to(WORKSPACE_ROOT)}, plan.json 已交付")


def build_all_ten_episodes():
    """全自动遍历 EP01 ~ EP10 完成全部 80 分镜交付"""
    print("=" * 70)
    print(" 《欺诈之地》全十集 (EP01~EP10) 80 分镜提示词工程与 plan.json 批量构建器")
    print("=" * 70)

    ep_dirs = sorted([d for d in EPISODES_ROOT.iterdir() if d.is_dir() and d.name.startswith("EP")])
    if len(ep_dirs) != 10:
        print(f"[警告] 找到 {len(ep_dirs)} 个 EP 目录 (预期 10 个)！")

    total_segs = 0
    for ep_dir in ep_dirs:
        build_episode_prompts_and_plan(ep_dir)
        total_segs += 8

    print("=" * 70)
    print(f" 全十集构建完成！总计成功生成 {len(ep_dirs)} 集，{total_segs} 个分镜提示词与 plan.json 结构体。")
    print("=" * 70)


if __name__ == "__main__":
    build_all_ten_episodes()
