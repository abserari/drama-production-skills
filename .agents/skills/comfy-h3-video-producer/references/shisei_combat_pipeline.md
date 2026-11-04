# 高质量打斗与双人姿态管线规范 (Shisei Combat & Duo Pose Pipeline)

> **版本**：v1.0 (2026-10-30)  
> **适用范围**：短剧中近身格斗、兵刃交锋、双人正反打对峙、复杂肢体纠缠分镜。  
> **定位**：解决视频生成模型在激烈打斗中常见的“动作发软、肢体穿模、解剖崩塌、对峙轴线混乱（正对翻成背对）”痛点。

---

## 1. 核心架构与原理

本管线依托已完全本地化的开源多视角姿态库 **`Shisei (姿勢)`**（包含 288 个动作、55 组双人深度交互/对峙姿态，覆盖 5 个摄像机视角的 3,775 张线稿）。

```
                                  [分镜剧本：双人对峙 / 格斗]
                                              │
                     ┌────────────────────────┴────────────────────────┐
                     ▼                                                 ▼
        【方案 A：首帧姿态锚定（主推荐）】               【方案 B：ComfyUI ControlNet】
                     │                                                 │
    1. CLI 检索并导出对应视角的线稿 (Duo Pose)             1. 导出线稿接入 ControlNet / Canny
                     │                                                 │
    2. 结合【角色卡】+【场景卡】生图 (Imagen/Qwen)        2. 约束单帧出图或分镜骨架
                     │                                                 │
    3. 输出准确的首帧 (Keyframe)                                      │
                     └────────────────────────┬────────────────────────┘
                                              ▼
                         [MiniMax H3 ImageToVideo 驱动]
                                              │
                                 高质量连贯动作与空间不变性
```

---

## 2. 本地检索与提取工具 (`shisei_pose.py`)

本地工具路径：`.agents/skills/comfy-h3-video-producer/scripts/shisei_pose.py`  
姿态资产路径：`.agents/skills/comfy-h3-video-producer/assets/shisei/`

### 2.1 常用命令速查

在 PowerShell 终端执行时，必须先设置编码或使用 Python 调用：

```powershell
# 1. 查看前 10 组双人对峙/格斗姿态（D 开头编号）
python .agents/skills/comfy-h3-video-producer/scripts/shisei_pose.py --duo

# 2. 关键词模糊检索（支持中/英/日）
python .agents/skills/comfy-h3-video-producer/scripts/shisei_pose.py --search "匕首"
python .agents/skills/comfy-h3-video-producer/scripts/shisei_pose.py --duo --search "punch"

# 3. 导出指定姿态的特定视角线稿至工程目录
# 视角选项：front(正视), side(侧视), diag(45°斜角), above(俯视), below(仰视)
python .agents/skills/comfy-h3-video-producer/scripts/shisei_pose.py --get D001 --view diag --out references/poses
```

### 2.2 姿态视角与镜头机位对应映射表

| Shisei 视角参数 | 电影机位描述 | 适用戏剧场景 | 180° 正反打搭配 |
|---|---|---|---|
| `front` | 平视正面镜头 / 过肩正打 | 两人正面对视、拔刀前的一触即发 | 搭配反打机位（交换主体前景/背景） |
| `side` | 90° 侧向双人全景 | 两人横向持刃逼近、动作拉扯、踢击 | 严格锁定两人左右朝向（左攻右防） |
| `diag` | 45° 黄金斜角三分景 | 近身缠斗、匕首反握刺击、攻防重心转移 | 极具立体纵深感，最推荐的格斗机位 |
| `above` | 俯拍 / 大角度俯视 | 压制在地、地面扭打、局势失控审判感 | 配合地面血迹或跌落道具锚点 |
| `below` | 仰拍 / 低机位英雄视角 | 格挡反击、机甲/重型敌人步步逼近 | 强化压迫感与力量爆发力 |

---

## 3. 标准生产 SOP（首帧锚定法）

### 第 1 步：段规划标定姿态编号
在 `directing_bridge.md` 输出分镜与段规划时，对近身交锋段落明确打上 `[Pose: ID_视角]` 标签。
例如：
> **分镜 05（近身突袭）**：萨儿滑步持高频震荡匕首直刺，考希欧抬起机械臂外骨骼格挡。  
> **姿态锚点**：`Shisei D012 (diag 45° 斜角)`

### 第 2 步：提取线稿并作为姿态参考
运行 CLI 提取：
```powershell
python .agents/skills/comfy-h3-video-producer/scripts/shisei_pose.py --get D012 --view diag --out 生产/references/poses
```

### 第 3 步：结合资产卡生成首帧基准图
将导出的 `D012_diag.webp` 与萨儿角色卡 (`sal_character_sheet.jpg`)、考希欧角色卡 (`kashio_character_sheet.jpg`) 以及珍珠酒馆 180° 场景卡 (`pearl_tavern_reverse_shot_sheet.jpg`) 输入生图引擎。  
提示词中锁定：
- **构图与骨架**：严格遵照 `D012_diag` 的左右站位、肢体倾斜角与关节重心；
- **材质与服饰**：严格遵照角色卡细节（萨儿的皮背心破损、考希欧的铜锈外骨骼）；
- **视线与轴线**：严格穿透彼此眼部，杜绝视线漂移。

### 第 4 步：视频提示词工程对接
在对应分镜段落（如 `segments/seg05.txt`）的 `[空间构图与摄影机]` 中显式声明姿态拓扑：
```text
[空间构图与摄影机]
- 构图拓扑：45度斜侧机位（承接姿态线稿 D012），画面左侧萨儿身体前倾反握匕首刺出，画面右侧考希欧机械臂抬起格挡。
- 180度轴线关系：两人视线严格交叉对视，机位不越轴，背景酒馆柜台柱位于画面右后方。
```

---

## 4. 故障排除与防错条款

1. **绝对禁止越轴**：
   - 当上一分镜是萨儿在左（面向右）、考希欧在右（面向左）时，反打分镜或姿态切换时**严禁翻转左右关系**，除非镜头内有明确的环绕运镜轨迹。
2. **多视角线稿的线宽匹配**：
   - 提取的线稿为 900px 干净线条，如果使用 ControlNet，建议使用 OpenPose 或 LineArt/Canny 预处理器，权重设置在 `0.65 - 0.85` 之间，避免线条过度僵硬限制了模型的微动态表情。
3. **肢体交叠修复**：
   - 若双人姿态有重度躯干重叠导致生图生成“多余肢体/融合”，启动本地 `Qwen-Image-Edit-2511` 做微创修补（参见 `asset_inpainting_guide.md`）后再送入 H3。
