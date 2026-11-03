---
name: drama-director-staging
description: 短剧工业化管线·第 1 工序：编剧与导演分镜调度。负责将剧情大纲或小说文本转化为符合短剧视听规律的工业级分镜。内置：6 大动态运镜轮换决策树、台词纯中文汉字归一化（数字大写）、短剧快节奏 20~28 字密度调控、单人发言与旁观者闭嘴标注。
---

# Drama Director Staging (编剧与导演分镜调度工序)

> **工序定位**：短剧视听工业化管线第 1 阶段。将文本大纲转化为具备空间动线、演员调度、高密台词的工业级 `plan.json` 与分镜剧本。
> **拒绝通用废话**：不解释什么是景别或镜头，只沉淀**MiniMax H3 强约束下的导演调度判据与防翻车硬核 SOP**。

---

## 1. 运行契约与输入输出

- **输入**：剧情大纲、场景设定、角色对话原文。
- **输出**：
  1. `剧本.md`：标准场次对白文本（含动线与情绪标注）；
  2. `分镜表.md` 与 `plan.json`：包含每镜机位、6 大运镜代码、说话主体、闭嘴旁观者、归一化纯中文台词。

---

## 2. 硬核 SOP：六大电影级动态运镜轮换

> **禁令（反例）**：严禁连续两个分镜使用静态过肩（OTS）正反打面对面交谈！极易造成 AI 人物站桩、视线呆滞、气氛尴尬。

分镜编排必须从以下 6 种动态调度中强制轮换：

| 调度代码 | 模式名称 | 英文提示词原语 | 强制适用场景 |
| :--- | :--- | :--- | :--- |
| `M1_TRACKING` | **动线交错慢推** | `Slow forward tracking shot following character walking briskly through the room, camera pushing in steadily, dynamic background movement, continuous tension.` | 角色边走边说、推门而入、逼向对手时使用，打破静态空间。 |
| `M2_RACK_FOCUS` | **道具特写变焦** | `Extreme close-up starting on the prop (slammed on table/held in hands), rapid rack focus up to the speaker's intense glaring eyes, shallow depth of field, dramatic depth shift.` | 关键道具（刀刃、契约、怀表、筹码）砸在桌上或拿在手中时，视线由物转人。 |
| `M3_DUTCH_TILT` | **荷兰角斜切逼迫** | `15-degree Dutch angle tilted low shot, looking up at the dominant character stepping forward intimidatingly, creating extreme psychological pressure and cinematic unease.` | 反派逼近、暴力威慑、心理失衡或局势反转的紧张节点。 |
| `M4_BACK_REVEAL` | **背身转头回眸** | `Character begins with their back turned towards camera speaking coldly, suddenly pivots their head 90 degrees to deliver the punchline with an icy stare, dramatic rim lighting catches their jawline.` | 吐出关键冷酷决定、反水背叛或重要裁决时使用。 |
| `M5_CLOSE_WHISPER`| **贴耳逼近压迫** | `Tight medium close-up, speaker leans in uncomfortably close towards the listener's ear, whispered menacing intensity, listener flinches slightly while speaker holds cold direct gaze.` | 近身威胁、秘密交易、审讯耳语，距离压缩到极致。 |
| `M6_PROFILE_STAND`| **侧光剪影对峙** | `Cinematic two-shot in profile, characters not looking directly into each other's eyes but glaring past each other, split lighting separating them, smoke drifting between them.` | 高手过招、视线错位、话中有话，绝不直白对视。 |

---

## 3. 硬核 SOP：短剧快节奏台词密度与纯中文归一化

### 3.1 字数密度黄金准则 (7.3 秒时序)
- **标准 175 帧（7.29 秒）台词区间**：严格控制在 **20 ~ 28 个纯汉字**（约 3.5 ~ 4.2 字/秒，快节奏商业短剧语速）；
- **字数与语速判据**：
  - `汉字 < 16 字`：**【判定过慢】** H3 会强行拉长每个字的音节，导致说话拖沓发呆；必须扩充台词冲突或拆解动作；
  - `汉字 > 30 字`：**【判定过密】** H3 吐词会严重吞字、连音、爆音；必须精简到 28 字内；
- **时序前后分割法则**：前 4.5 秒高密吐词，后 2.8 秒切入冷眼凝视、动作反应（握刀、挑眉、冷笑）。

### 3.2 纯中文汉字归一化（防止语言漂移与外国话）
在进入提示词编译器前，必须调用归一化处理器：
1. **阿拉伯数字 100% 转大写汉字**：`100` -> `一百`，`500` -> `五百`，`EP01` -> `第一集`；
2. **严禁英文缩写与外文字母**：`Boss` -> `老大`，`OK` -> `行`，`watch` -> `电子表`；
3. **标点标准化**：严禁出现 `/ \ @ # $ % ^ & * _ [ ]`，全量规范为中文全角标点 `，` `。` `！` `？` `：`。

---

## 4. 硬核 SOP：说话人与旁观者闭嘴标注

在输出 `plan.json` 中，每个分镜必须显式标注：
```json
{
  "seg": "seg01",
  "shot_type": "MLS",
  "camera_mode": "M1_TRACKING",
  "speaker": "Sal",
  "silent_listeners": ["Merchant", "Bystander"],
  "dialogue_text": "<d>这笔账拖了整整三年，今天要么给钱，要么留下你的右手！</d>",
  "pacing_check": {
    "char_count": 27,
    "cps": 3.7,
    "status": "OPTIMAL"
  }
}
```

---

## 5. 专属工具脚本

- **编译器**：`python scripts/director_engine.py --validate plan.json`
- **台词纯净化与测速**：`python scripts/director_engine.py --clean-dialogue "数字100转汉字"`
