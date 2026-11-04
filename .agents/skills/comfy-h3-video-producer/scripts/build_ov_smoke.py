# -*- coding: utf-8 -*-
"""构建冒烟测试覆盖配置 ov_smoke.json：场次4前半（巨像肩部·嵌灯点火），5秒/124帧。"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, "h3_sancai_api.json")
OUT = os.path.join(HERE, "ov_smoke.json")

CLIP = "smoke01"
CHAIN = {"name": "灯_冒烟测试", "clip": CLIP, "shot": CLIP}

PROMPT = """subject_definitions:
- 色彩参考：以 @图片2 的夜色为全片色调基准（冷蓝夜空、星光、暖橘点光源的对撞）；权限=仅约束色调比例与氛围，不干预画面内容元素。
- <Subject 1> 为 @图片1 中的少女穗，14岁，尺度锚点=身高约1.52米，黑色齐耳短发，米色补丁短衫、深色束脚裤，胸前挂一枚琥珀色小珠；权限=锁定面容/发型/服装/配饰与2D赛璐璐手绘画风，不限定姿势与表情。
- <Subject 2> 为 @图片2 中的沉默巨像肩部平台，尺度锚点=石槽平台可容一人站立俯瞰沙海；权限=锁定空间结构、风蚀岩石质感与夜空氛围，不复制原图机位与原图中的小人。
- <Subject 3> 为 @图片3 中的防风油灯，尺度锚点=灯高约30厘米，可双手捧持；权限=锁定灯具造型与锈蚀金属质感，不限定火焰大小；忽略参考图角落水印。

summary:
[参考生成] 深夜，穗独自站在沉默巨像肩部的石槽前，双手捧防风油灯弯腰嵌入石槽，灯芯燃起橘黄色火光；她缓缓直身低头看灯，火光映在她平静的脸上。全程无对白、无背景音乐。

detailed_description:
画面风格：2D赛璐璐动画，吉卜力式手绘质感，与全部参考图风格一致，胶片颗粒轻微。
时间光线：深夜；环境为冷蓝星光夜色，唯一暖光源是油灯橘黄火苗，火光只照亮穗的双手、下颌与近处岩石。
空间环境：<Subject 2>；石槽嵌在肩部平台最高处，远处沙海与低矮山脊隐在夜色里，风卷细沙贴地流动。
镜头：固定机位、缓慢微推，无摇移无跳切。
时序（5秒）：
- 0.0-2.0秒：中景侧面构图，穗双手捧<Subject 3>从画面右下入画至石槽前，弯腰将灯稳稳放入石槽凹处。
- 2.0-3.5秒：灯芯火苗升起并跳动，橘黄光照亮她的双手与下颌，她保持弯腰姿势一瞬确认灯已放稳。
- 3.5-5.0秒：她缓缓直起身，低头注视灯火，火光在眼中跳动，发丝被夜风轻拂；构图收在她与灯的侧面剪影，夜空星光稳定。
声音：全程低风声铺底；2.0秒处灯芯点燃的轻微"噗"声，其后为平稳的火焰燃烧声；无对白、无音乐、无字幕。

防错约束：
- 穗的身份特征全程不变：黑短发、米色补丁短衫、深色裤、胸前琥珀珠清晰可见，不得换脸、换装、改变画风。
- 手部五指正常，无畸形；油灯全程只有一盏，不得复制或消失。
- 夜色与光线稳定，不得昼夜切换或光线闪烁式突变；机位固定，不得出现无规则推拉摇移。
- 忽略参考图角落的"Seko"水印，画面不得出现任何文字、字幕、水印。
- 人物不得瞬移穿模；动作符合物理：弯腰-放灯-直身的重心变化自然。"""

p = json.load(open(WF, encoding="utf-8"))

# --- rack (257)
rack = json.loads(p["257"]["inputs"]["rack_data"])
rack["cur"] = CLIP
rack["segs"] = {CLIP: {"slots": {
    "images": [
        {"file": "cglide/灯/穗.png", "alias": ["穗"]},
        {"file": "cglide/灯/巨像肩部夜-.png", "alias": ["巨像肩部"]},
        {"file": "cglide/灯/粗陶油灯.png", "alias": ["油灯"]},
    ],
    "videos": [], "audios": []}}}
rack["slots"] = {"images": [], "videos": [], "audios": []}

# --- desk (265)
desk = json.loads(p["265"]["inputs"]["desk_data"])
desk["chain"] = CHAIN
desk["global"] = ""
desk["segs"] = {CLIP: PROMPT}
desk["alias"] = False

# --- cast (261)
h3 = json.loads(p["261"]["inputs"]["h3_data"])
h3["chain"] = CHAIN
h3["length"] = 124          # ~5s @24fps，模型训练区间下限
h3["prompt"] = ""

ov = {"257": {"rack_data": json.dumps(rack, ensure_ascii=False)},
      "265": {"desk_data": json.dumps(desk, ensure_ascii=False)},
      "261": {"h3_data": json.dumps(h3, ensure_ascii=False)},
      # 链路 一采→二采→超分：306 超分改吃 285 的二采解码帧（图像口），
      # 删除原「整片」视频口；307 RIFE 不动；308 终片音频补接 286。
      "306": {"视频": None, "图像": ["285", 0]},
      "308": {"音频": ["286", 0]}}
json.dump(ov, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
print("written", OUT)
print("prompt chars:", len(PROMPT))
