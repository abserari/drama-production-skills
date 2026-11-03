---
name: drama-keyframe-forge
description: 短剧工业化管线·第 2 工序：分镜定帧与资产一致性。负责在视频渲染前，建立全局风格母卡 (Style Bible)，并为每个分镜前置生成“场景+人物+道具”三合一的 16:9 高清定帧垫图。彻底根治 T2V 盲跑带来的人脸变形、角色换脸、场景变色与道具软化。
---

# Drama Keyframe Forge (分镜定帧与资产一致性工序)

> **工序定位**：短剧资产与前置定帧工序。
> **核心认知**：把"盲跑 8 分钟 T2V 碰运气、事后质检重抽"的低效做法，升级为"在视频采样前，先用生图模型 5 秒生成分镜定帧图、低成本核验锁定后再喂给 I2V 执行"。

---

## 1. 运行契约与输入输出

- **输入**：
  1. 第 1 工序的 `plan.json` 与分镜表；
  2. 角色基础设计卡（Character Reference Sheet，2+3 头身解耦图）；
  3. 场景设定与关键道具描述。
- **输出**：
  1. `style_bible.json`：全局唯一不可篡改的美术风格母卡；
  2. 各分镜 16:9 高清首帧垫图：`segments/segXX_keyframe.png`；
  3. 首帧闸门质检签字单：`keyframe_qc.json`。

---

## 2. 硬核 SOP：全局风格母卡 (Style Bible) 与前置定风闸门

> **铁律**：整部短剧必须拥有唯一合法的 `style_bible.json`。各分镜提示词严禁自由发挥私自篡改核心风格词！

### 2.1 风格母卡五大核心属性
在开工前必须固化以下 5 个字段：
1. **Visual Genre**（视觉基准）：如 `Cinematic retro-future dieselpunk graphic novel style, mature neo-noir tone`；
2. **Color Palette**（调色情绪）：如 `desaturated amber and deep teal contrast, rusty bronze highlights, rich shadow details`；
3. **Lighting Base**（布光质感）：如 `heavy chiaroscuro lighting, harsh directional rim light, high contrast dramatic shadows`；
4. **Environment Base**（场景物理材质）：如 `weathered rust and scuffed brass, damp asphalt reflections, atmospheric smog`；
5. **Quality & Lens**（光学胶片）：如 `35mm film grain, Panavision anamorphic lens flare, shallow depth of field, 8k resolution`。

### 2.2 前置定风核验清单
开工前由生图模型生成 4 张不同景别的定风样张，人工签字定案：
- [ ] **样张 1（全景场景 LS）**：验证光影、色调、材质氛围是否符合预期；
- [ ] **样张 2（主角中景 MLS）**：验证主角服饰、体态、标志性饰物；
- [ ] **样张 3（主角近景 CU）**：验证眼眸五官、发型、面部质感；
- [ ] **样张 4（关键道具特写 ECU）**：验证道具硬表面细节与机械结构。

---

## 3. 硬核 SOP：分镜级联合定帧垫图生成 (I2V Pre-Generation)

> **反例（严禁操作）**：在没有分镜首帧垫图的情况下，直接给 H3 纯文本跑 T2V！
> 现象：由于 3D 扩散初期潜空间噪声随机，生成的同一角色在镜头切换时发型改变、脸部骨骼漂移（换脸）、衣服款式变样。

### 3.1 联合定帧图生成步骤
对 `plan.json` 中的每一个分镜段落（seg01 ~ seg08）：
1. **装配分镜生图提示词**：
   - 注入主角专属外貌与服装；
   - 注入当前分镜指定的机位（如 `M2_RACK_FOCUS` 道具特写拉焦）；
   - 注入当前分镜发生的具体微观场景与道具（如 `sharp serrated hunting dagger vibrating in tabletop`）；
   - 注入 `style_bible.json` 的风格与布光词。
2. **使用快速生图模型（Flux / SDXL）批量渲染 16:9 静态图**（5~10 秒/张）；
3. **三层质检闸门（Keyframe Gate Check）**：
   - **面部一致性**：特征物（眼罩、发型、伤疤）清晰对齐；
   - **机位服从度**：景别与倾角严格符合分镜要求，无多余手脚；
   - **道具硬表面**：武器、表盘、手提箱边缘锐利无融化；
4. 检验合格后，重命名并落盘为 `segments/{seg_id}_keyframe.png`。

---

## 4. 专属工具脚本

- **定风与分镜首帧生成管理**：`python scripts/keyframe_gate.py --scan`
- **首帧同步至 ComfyUI 仓**：`python scripts/keyframe_gate.py --project <工程名> --sync`
