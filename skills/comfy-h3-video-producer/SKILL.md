---
name: comfy-h3-video-producer
description: 本地 ComfyUI 剧本转视频自动生产管线（MiniMax H3）。用户给剧本要求用 ComfyUI 出分镜视频，或提到"一采二采/超分/班长套件/CSGlide/工作流生成视频"时使用。覆盖：工作流握手（不写死节点号）、导演调度与段规划、H3 提示词、提交与自动监工、一采双检闸门、收片清床音与拼接、断点续产。
agent_created: true
---

# ComfyUI H3 剧本转视频（v5.0 导演级视听语言与工业工程化规范版）

> **v5.0 重大里程碑更新（2026-11，视听语言工业化与七大落地痛点全量攻坚）**
> - **1. 分镜定帧图前置生成工序（I2V 场景/角色/道具联合定帧）**：
>   彻底终结无定帧图下的 T2V 盲跑。每个分镜在视频采样前，先由生图模型结合分镜机位、角色三视图、道具设定生成 16:9 联合首帧定帧图（`keyframe_segXX.png`），质检定案后喂入 I2V 节点，第 0 帧锁死骨骼几何、衣服纹理与道具轮廓。
> - **2. 单人说话锁定与全员闭嘴抑制协议（Speaker Lock & Mouth Suppression）**：
>   彻底消灭“场景里所有人跟着台词一起动嘴”的木偶剧惨状。在 `[Subject 1]` 明确唯一主说话人，在 `[Action 1]` 强制主谓动作分离，非发言角色强制追加闭嘴抑制死条款（`lips tightly sealed, completely silent, showing tense glare without mouth movement`）。
> - **3. 全局风格母卡（Global Style Bible）与前置定风闸门**：
>   拒绝每集随机制图风格漂移。剧作启动前必须确立全局 Style Bible（明确 `visual_genre`, `environment_base`, `lighting_base`, `color_palette`, `quality_base`），生成 4 张不同景别定风样张人工确认后全剧锁定继承。
> - **4. 短剧黄金语速与密度调控（Pacing & Density Normalization）**：
>   解决人物说话拖沓、拉长音发呆问题。175 帧（7.29s）标准时序下，台词严格匹配 **20~28 个纯汉字**（短剧黄金语速 3.2~4.0 字/秒）；并在 `[Audio 1]` 中显式声明 `spoken crisply and rapidly without dragging syllables`；前 4.5s 快速讲完，后 2.8s 切入冷眼凝视与动作反应。
> - **5. 六大电影级动态运镜与动线调度库（Director Camera & Blocking）**：
>   严禁连续出现两人正面站桩交谈！强制引入 6 大动态镜头调度：① 动线交错慢推、② 道具特写拉焦至眼眸、③ 荷兰角斜切逼迫、④ 背身转头冷酷回眸、⑤ 贴耳逼近压迫、⑥ 侧光剪影对峙。
> - **6. 纯正普通话发音规约与 ASR 语种漂移闸门（Mandarin Purity & Language Gate）**：
>   台词全量纯中文归一化（阿拉伯数字转大写汉字、剥离英文缩写与非法符号）；在 `[Audio 1]` 强制添加 `Strict Mandarin Chinese dialogue only, standard native Chinese accent, zero foreign tone`；集成 Whisper ASR 语言检测，自动拦截非中文字幕与语言漂移。
> - **7. 工程化 Master 母调度管线闭环**：
>   沉淀 `scripts/director_engine_v3.py`，实现分镜表、提示词编译、语速密度核算、说话主体锁定的全流程自动化。
>
> **v4.1 更新（2026-11，官方 v2.2 提示词规约与 175 帧时序深化）**
> - **提示词规范升级至 v2.2**：
>   - 接入 MiniMax 官方 Prompt 指南（`references/official/base-en.txt`, `ref-en.txt`）；
>   - 运镜三要素（类型+幅度+速度）以自然句写入镜头内部，严禁拍末 Tag 堆叠；
>   - 素材权限明确声明 `不复制原图机位，不复制占画比例`；
>   - 严格执行复杂度预算：单段（175帧/7.29s）最多 3 主体 + 1 句台词。
> - **段长锁定主力 175 帧（7.29s）**：
>   - 243 帧正式退役，硬上限设为 192 帧（8.00s），生产主力统一锁定 175 帧，段尾留足 1.0~1.2s 闭嘴缓冲；
>   - 调度层服从度禁区（远景只建空间认脸切进中近景、禁用后拉与穿窗）。
> - **Windows UTF-8 全终端防御**：
>   - `force_utf8_stdio()` 统一重置 stdout/stderr 为 UTF-8，杜绝 GBK/CP936 编码异常崩溃。
> - **质检与远景修脸工具链扩容**：
>   - 引入 Whisper ASR 台词质检 (`scripts/check_dialogue_asr.py`)、尾拍光流与接缝质检 (`scripts/sop_check.py`)、续接尾段留白豁免 (`--tail-exempt`) 与中远景自适应修脸 (`scripts/face_refine_pipeline.py`)。
>
> **v4.0 更新（2026-10，工业级首帧锁脸防形变与影视配乐双革命）**
> - **首帧生图核验 + I2V 几何锁脸铁律（根治纯文生视频 T2V 人脸变形与道具软化）**：
>   单张文生图仅需 5-15 秒，不满意秒级重抽；严禁在没定首帧的情况下盲跑 8 分钟 T2V 碰运气！事后自动质检只能亡羊补牢，高代价重抽治标不治本。凡有人物特写、关键道具交互，必须先定首帧，注入 `first_frame` 走 I2V 模式，第 0 帧锁死解剖几何与道具电路，H3 仅负责时序动力学与唇形同步，人脸形变率从 30% 暴跌至 2% 以下。详见 `references/keyframe_i2v_guide.md`。
> - **影视级配乐融合与人声智能避让 (Audio Ducking)**：
>   提示词彻底禁止 H3 自带生成失真床音；清洗对白与动作拟音后，全片统一铺设独立高保真 BGM，采用 FFmpeg 原生 `sidechaincompress` 动态侧链避让：人声开口瞬时下潜 -14dB，台词结束 0.3-0.5s 平滑扬起，打造商业短剧视听爽感。新增工具 `scripts/cinematic_audio_mixer.py`。
> - **新增首帧闸门工具 `scripts/keyframe_gate.py`**：支持工程级首帧状态巡检、ComfyUI 仓同步与 I2V 节点安全注入。
>
> **v3.2 更新（2026-10-25）**
> - 新增 §13 **什么时候更新这个 skill**：六个触发条件、四类不许搬进来的内容、迁移三问、落位规则、改完三步自检
> - 一句话纪律：**只沉淀「换剧本后仍成立」的机制与判据，项目文件一律不进 skill**
>
> **v3.1 更新（2026-10，13 段 / 86 秒成片实测沉淀）**
> - 新增 §4.1 **H3 的服从度边界**（后拉失效、穿窗开门、窗外运动不生成、景别锁死、否定式镜头指令）
> - 新增 §5.1 **显存回收**（曾经让一段从 5 分钟跑成 33 分钟）
> - §8 决策树补 6 条（结尾动作被抢、一拍动作过多、拟音被铺成床音、quiet-gain 副作用、F0 误判）
> - §12 补台词位置四版梯度、`cont off` 的 trim 记账
> - §3 段长推荐改为 **175 帧**（原写 124/243，已过时）
> - **修正了提示词规范里两处会误导的旧示例**：「台词写在节拍末尾」应为**节拍最前**；
>   「胸腔每 2.5 秒起伏」会被当成发声指令生成呼吸声，已删除

把剧本变成成片：**握手 → 导演调度 → 首帧核验(I2V) → 提示词 → 提交 → 监工双检 → 收片 → 避让混音与拼接**。

**v4 的核心认知：把"生成视频碰运气 + 事后质检重抽"升级为"前置低成本控图 + I2V 锁脸执行 + 影视级避让混音"。**

> **一条铁律：一个任务 = 一个本地工程目录 + 一个导演台工程名（`h3_chain/<工程名>`）。**
> 这两样从第一段定下来到 `concat` 结束**都不许换**。换了不是"文件放错地方"，而是**续接直接断**：
> 续拍档按 `chain.order[k-1]` 找上一段，工程名一变就找不着，本段会被静默当成第一段重画，
> 成片还会归位到另一部片子的目录。绑定会写进 `project.json` 的 `chain` 字段，
> `submit` 每次都比对，不一致**直接拒收**（不是警告）。要换只能整体换：新工程 + 新导演台工程名，
> 从第一段重来。完整规则见 §10.1。

## 0. 运行契约（先明确谁干什么）

| 谁 | 负责 |
|---|---|
| **Agent（全自动）** | 读剧本、导演调度、首帧核验、写提示词、preflight、提交、监工、双检、收片、清床音、配乐避让混音、拼接、交付、写台账 |
| **用户（只做三件事）** | ① 打开 ComfyUI 并载入工作流，说一声"就绪" ② 剧本/风格/首帧候选的一次性定调 ③ 看片验收 |

**Agent 不许做的七件事**
1. 不许在工作流没握手（`wf_map.json` 不存在）时提交。
2. 不许跳过 `gate`（一采双检）直接 `finish` —— 脚本会拒收，不要试图绕。
3. 不许把 state/抽帧/临时 wav 写进技能目录（`paths.py` 有硬护栏）。
4. 不许凭"上次的节点号"改接线 —— 只注入三段数据，绝不动超分/终片节点的连线。
5. **不许在有人物特写或关键道具交互时，跳过首帧核验盲跑纯文生视频 (T2V)** —— 静态生图核验只要 5-15 秒，不满意秒级重抽；跑 8 分钟 T2V 再事后质检是高代价自杀。必须先定首帧，注入 `first_frame` 走 I2V 锁脸锁道具！
6. **不许在没抽帧看画面时就提下一段** —— preflight 只管文本结构，不管画面。落盘后先抽 4-6 格拼图看一眼，再提下一段；正好也避开了"两段提交太快导致显存脏态"（见 §5.1）。
7. **不许把当次的项目文件无脑搬进 skill** —— 片名/角色名/段号/`plan.json`/`assets/*.json`/某段提示词原文/当次 trim 账/黑名单 seed，一律留在项目目录。只沉淀「换剧本后仍成立」的机制、判据、写法。判据与落位规则见 §13。

**只有这四种情况才停下来问用户**：剧本有歧义且影响分镜结构 / 风格或画幅定调 / 素材缺失且无法用文字定义 / 同一段重抽 3 次仍不过。

## 1. 核心工具集（完整生产工具链）

| 工具 | 干什么 | 关键子命令 |
|---|---|---|
| `scripts/h3wf.py` | 工作流握手：从 ComfyUI 读**实际执行过**的图，自动认节点角色 | `sync` `show` `doctor` |
| `scripts/sop_run.py` | 生产：提交（内含 preflight）、自动监工、等终片 | `submit` `watch` `final` `abort` |
| `scripts/h3proj.py` | 工程与闸门：台账、一采双检、视觉签字、收片、拼接、残留清理 | `new` `status` `gate` `review` `finish` `concat` `residue` |
| `scripts/keyframe_gate.py` | 首帧核验与 I2V 注入：首帧状态巡检、ComfyUI 仓同步、注入 first_frame | `--project` `--seg` `--sync` |
| `scripts/face_refine_pipeline.py` | 外部远景修脸工作流：中远景条件修脸、音频原样直通、自定义节点缺失平滑降级 | `--input` `--output` `--char-ref` `--dry-run` |
| `scripts/cinematic_audio_mixer.py` | 影视级配乐智能避让混音：外挂独立 BGM，sidechaincompress 自动避让人声 | `--input` `--output` `--bgm` `--volume` |
| `scripts/check_dialogue_asr.py` | 台词 ASR 自动比对：VAD 定位语声段 → Whisper 转写 → 与 `<d>` 原文比对 | `--file` `--text` `--seg` |
| `scripts/sop_check.py` | 尾拍动作能量与接缝相似度质检：8 格联络表、动作光流比率、钉帧比对 | `--video` `--seg` |
| `scripts/shisei_pose.py` | (可选) 打斗/对峙姿态：多视角姿态检索与线稿提取 | `--search` `--duo` `--get` `--view` |

解释器固定用带 cv2 的 venv：
`C:/Users/windows/.workbuddy/binaries/python/envs/default/Scripts/python.exe`（下称 `PY`）

## 2. 第 0 步：工作流握手（每次开工第一件事，不可跳过）

**为什么不能固化**：用户的工作流会更新（加三采、改超分尺寸、换输出前缀），节点号一变，
写死的"接线修复"就会把一条跑得通的链路改坏 —— 这是 v2 每次报错的根因。

**核心口径：用户会随时在画布上调参数（改超分尺寸、换模型、调采样步数），生成必须用他当下的值。**
`submit` 每次都会先核对一遍画布保存版（`h3wf.refresh_if_stale`）：
文件 mtime 变了就重新读图，并把**改了哪些参数**逐条打出来（`[wf  ] 检测到 N 处参数变更`）。
`rack/desk/cast` 的 `h3_data`、`seed`、`filename_prefix` 是运行时注入的，不算用户改动，已排除。

**但有一个 API 层面绕不过的限制，必须主动告知用户**：
ComfyUI 的画布状态只有在**保存工作流（Ctrl+S）**之后才落到
`ComfyUI/user/default/workflows/*.json`，未保存的画布改动任何接口都读不到。
所以每次开工要跟用户说一句：**改了参数请 Ctrl+S**。
如果用户改完还**按过一次 Queue**，那条执行图会进 `/history`，也能被第二条判据捕到。

**动作**：
1. 先提醒用户：**打开 ComfyUI 桌面程序，载入这次要用的工作流**，等他说"好了"。
2. 前提：`sync` 读的是 ComfyUI `/history` 里**最近一次成功跑完的视频任务**。
   - 刚换过工作流 / 刚装好 → 请用户在界面里**手动跑一次**（哪段都行，跑通即可），再 `sync`。
   - 一次都没跑成功过 → 用界面文件兜底：`h3wf.py sync --from-ui "<工作流>.json"`（需要 ComfyUI 在跑）。
3. 探活 + 识别：
   ```bash
   $PY scripts/h3wf.py show      # 只看识别结果
   $PY scripts/h3wf.py sync      # 识别通过后落盘为本次生产依据
   ```
4. 判读输出：`rack/desk/cast/seed/final` 五个必需角色必须全部有值；缺了就是工作流换了节点类名，
   把这行贴给用户看，不要自己猜。`[note]` 里会写多候选是怎么选的。
   同一份输出还会给出三样东西，缺一样都会让后面的环节踩坑：
   - **工程名**（导演台 `chain.name`）：`submit` 用它决定成片归位到 `h3_chain/` 的哪个目录，
     并且第一次 `submit` 就把它写进 `project.json.chain` 当**绑定**。显示「—」说明导演台没填工程名，
     此时 `submit` 会退回技能工程名并告警 —— 那等于另起一部片子（且不会写绑定）。
     绑定之后换名字会被拒收，见 §10.1。
   - **一采前缀**：`watch`/`gate --latest` 靠它只认一采文件。显示「—」时退回全前缀，跑完
     整链后可能把超分/终片当成一采去双检。
   - `[WARN]` 收片链路：缺「段尾归位」或它的「顺序锚」没接线，成片不会回到导演台，下一段接不上。
5. ComfyUI 没开时允许无头启动（端口 8188，不影响桌面程序）：
   ```
   cd "D:/Comfy-Desktop/ComfyUI-Installs/ComfyUI (1)/ComfyUI"
   ".venv/Scripts/python.exe" main.py --port 8188 \
     --input-directory "D:/Comfy-Desktop/ComfyUI-Shared/input" \
     --output-directory "D:/Comfy-Desktop/ComfyUI-Shared/output" \
     --enable-assets --disable-auto-launch
   ```
   但**优先用用户自己开的那份**，节点状态以他的界面为准。

**工作流变了怎么办**：`h3wf.py doctor` 会列出「节点号变了 / 前缀变了 / 工程名变了 / 角色缺失」。
确认是有意更新 → `h3wf.py sync --force` 重新握手，之后所有提交自动用新图。
`submit` 每次都复核指纹，漂移未确认会直接拒收（不会偷偷用旧图跑一夜）。
握手时会记一条 `history_seq` 水位线：比它更早的执行图不算漂移（`/history` 清空前留下的旧记录），
只有**握手之后**新跑出来的图不同才会拒收。

## 3. 第 1 步：导演调度（强制，拿到剧本第一件事）

**不允许拿到剧本直接写提示词。** 先加载 `director-advisor` 技能出完整分镜方案：

1. 拆五要素：情绪基调 / 戏剧节拍 / 人物关系 / 空间 / 动作
2. 定节奏骨架：镜头数、张力曲线（**最高点只有一个**）、开场镜与收尾镜
3. 逐镜设计：景别=情绪距离、运镜=情绪运动、一镜一个动作单元、时长 1-3s（最长 5s），每镜带一行设计理由
4. 挂 1-2 个真实电影案例锚（只从 `director-advisor/references/master_cases.md` 取）

再按 `references/directing_bridge.md` 换算成 H3 的段，并**落盘段规划表**：

```json
{"name": "片名", "segs": [
  {"seg": "seg01", "length": 175, "shots": "1-4", "dialogue": false,
   "hook": "首段：从全景建立空间", "sfx": true, "event": "她走进石屋并放下灯"}
]}
```

- `length`：**175（≈7.29s，3-4 镜）是推荐值**；124（≈5.17s，1-2 镜）/ 243（≈10.13s，2-4 镜）也可用。
  关键公式：**净新画面 = length − cont_frames**。cont_frames=5 时，175 帧净剩 170 帧（7.08s），
  124 帧净剩 85 帧（3.54s）—— 同样的续接开销，175 的净产出翻倍，渲染只要 4–4.5 分钟，是性价比拐点。
  有台词段也用 175，**不要用 243**：段越长台词越容易顶到段末（见 §12 台词时间轴铁律）。
- `hook`：与上段的接续（姿态/视线/光线承接），写不出 hook 说明段拆错了。
- `dialogue/sfx`：决定音频闸门查哪几项（无台词段查静音，无拟音段关掉 `--fx`）。
- 校验：`$PY scripts/h3proj.py plan --check`

**一段 = 一个事件**，段内可多镜（`[节拍 N]` 就是镜头位，写「硬切至…」H3 就照切）；
**不能切空间（地图）和主要事件**。切点必须踩在动作上，不能按秒均分。

写分镜时同时过两道内容关（详见 `references/vividness.md`）：

- **逻辑四问**：人物这一刻想干什么？他在哪、朝向谁？时间/光线是否连续？上一个动作的因果有没有断？
- **生动三件套**：每拍至少给一个"动作起因 + 环境反馈 + 材质触感"，不能只有"站着说话"。

### 3.1 可选增强：高质量打斗与双人对峙姿态管线 (Shisei Pose Guidance)

当剧本涉及**近身打斗、兵刃交锋、双人正反打对峙或复杂肢体纠缠**时，为避免视频模型常见的"动作发软、解剖变形、正对翻背对（180°轴线翻转）"，**挂载本地 Shisei 姿态引导**（详见 `references/shisei_combat_pipeline.md`）：

- **姿态检索**：使用本地检索脚本查询 55 组双人对峙动作及 288 组单人动作：
  ```bash
  python scripts/shisei_pose.py --duo --search "近身"
  ```
- **多视角线稿提取**：根据导演机位导出 5 大视角（`front` 正视 / `side` 侧视 / `diag` 45°斜角 / `above` 俯视 / `below` 仰视）线稿至工程目录：
  ```bash
  python scripts/shisei_pose.py --get D001 --view diag --out references/poses
  ```
- **首帧骨架锚定**：将提取的姿态线稿与角色卡（`sal_character_sheet.jpg` 等）联合喂入生图引擎（Imagen / Qwen），产出 100% 构图严谨的首帧，再注入 MiniMax H3，杜绝空间漂移与动作软趴。

### 3.2 强制工序：分镜首帧生图核验与 I2V 几何锁脸 (Keyframe Gate)

> **工业铁律（最高优先级认知）**：
> 凡是有人物正面/半身特写、关键道具交互（如拆表、握枪、数钱、盖章）的段落，
> **严禁纯文生视频 (T2V) 盲跑**！必须执行「首帧生图核验 ➔ 图生视频 (I2V) 锁脸防变形」。

1. **核心逻辑**：
   - 静态生图仅需 **5 ~ 15 秒/张**，能将全部潜空间分辨率集中在五官发丝与道具微结构上，不满意秒级重抽；
   - 视频渲染单段耗时 **4 ~ 8 分钟**。纯文生视频在无物理锚点下极易发生解剖漂移，事后“自动质检”重抽成本高出 40 倍且治标不治本；
   - 将选定的首帧图注入 `MiniMaxH3ImageToVideo` 的 `first_frame` 端口后，第 0 帧作为几何真值锁死，模型无需脑补结构，注意力全部分配给「驱动动作与对齐口型」，人脸形变率从 30% 暴跌至 2% 以下！
2. **执行流程**：
   - **G0 角色资产卡**：开工前按 `references/character_sheet_standard.md` 准备好 2+3 头身解耦角色设定卡；
   - **G1.5 首帧生图核验**：分镜写毕后，使用生图工具快速生成 16:9 首帧电影剧照，核对五官、眼神聚焦与道具真确性；
   - **定稿落盘**：核验通过后保存至 `<工程>/segments/<seg_id>_keyframe.png`（或 `.jpg`）；
   - **自动识别与 I2V 挂载**：流水线检测到首帧图存在时，通过 `scripts/keyframe_gate.py` 自动同步至 ComfyUI 并连接 `first_frame` 端口。未检测到时自动平滑降级为纯文本驱动。详见 `references/keyframe_i2v_guide.md`。

## 4. 第 2 步：写提示词（标准 = `references/prompt_standard_v2.md`）

- 七段骨架、`[节拍 N]`、`<Audio N>` 声线卡、`overall_soundscape` 三层声音，一个字都不能改段名。
- 提示词写到 `segments/<seg>.txt`（纯提示词正文，不要包代码块）。
- 声线卡：项目里 `voice_card.json` 优先（`h3proj.py new` 已复制模板），**跨段逐字一致**。
- **preflight 不用单独跑**：`submit` 内部会调 `check_prompt_v2.check()`，有 FAIL 直接拒收。
  想提前单独看：`$PY scripts/check_prompt_v2.py --file segments/seg01.txt --length 243`

格式口径速查（细节以规范文档为准）：`<Subject N>` 全部带 `权限=`；情绪词零容忍；
每拍 `音效：` 逐条点名 +「仅此 N 类，无其他声音」封口；台词结束距段末 ≥1.0s；一段一句台词。

**否定词反噬（实测，踩过两次）**：H3 会把禁词里的实体名当正面提示去画。
在 `防错约束` 写「严禁生成水龙卷、水柱、喷泉」，画面里就长出一根白色水柱；
在动作描述里写「头盔前沿向上抬」，主角头上就凭空多一个透明头盔。
规则：**要某个东西别出现，就把它的名字从句子里彻底删掉，改成正面描述你真正要的画面**
（例："垂直向下俯拍，只有圆形下沉凹陷与沉入水中的黑色人影"），而不是写"不是X、不要X"。
`防错约束` 只留抽象约束（无水印/无字幕/无畸形手/不做火焰光效）。

**续接 latent 会把首拍人物带歪（本项目 5 次复现，最贵的一条坑）**：
带 `--cont` 的段落，首拍稳定生成一个**穿黑色长袍、披散长发的高个背影**，即使——
上一段尾帧是"俯拍水面 + 落水黑影"（seg02）还是"陈默面部近景、黑 T 恤"（seg03），
参考图已正确注入（`[rack] 素材 1 件：陈默→陈默.png`）、文案已逐字写清衣物，**全都压不住**。
同一提示词、同一参考图、同一 seed 区间，改 `--cont off` 后**两次全部恢复正常**
（seg02 首拍变回黑 T 恤短发陈默；seg03 首拍变回纯空镜城市俯瞰）。

判定与处置：
- **本项目结论：续接保留，但只钉 5 帧**（`project.json` 的 `cont_frames: 5`，即 0.21 秒）。
  用户要的就是"给几帧保证上下文一致"，39 帧（1.625 秒）太浪费、后期还要逐段掐头。
  纯硬切处（海边 → 门外这类剧本本身的地点跳转）用 `--cont off`。
  锚点污染在 5 帧下是否仍会出现，需要实测记录；一旦首拍人物不对，先试 `--cont off`。
- 通用判据：续接只在「同一空间、同一机位、动作直接延续」时才可能有用；
  一旦发现首拍人物服装/体型/发型不对，**先换 `--cont off` 验一次（一采只要 2 分钟）**，
  比改文案快得多，改文案是无效的。
- 开启续接时会打印 `[cont ] 承接 clip_xxxx（…）`；确认首帧再决定要不要留。

### 4.1 H3 的服从度边界（写提示词前必读）

这些是实测出来的硬边界，**改文案没用、换 seed 也没用**，只能在写法上绕。
全部来自 13 段 / 86 秒成片的连续记录，不是推测。

| 你想让它做的事 | 实测结果 | 换成什么写法 |
|---|---|---|
| **后拉 / 拉远 / 推近（位移式运镜）** | 4 次全败。写「只退到看得见挡杆就停」照样退到窗外、露出另一种内壁 | 改用**纯摇**（同机位只改角度：先向下摇到地板、再向上摇回），或直接硬切 |
| **机位穿过窗 / 洞进入内景** | 会顺手把门打开。写死「门保持关闭、只从空着的窗洞穿入」也没用 | **段内硬切**进内景，组装时把段头裁到刀口；比任何运镜过渡都可靠 |
| **窗外景物在移动（车在行驶）** | 生成不出来。改写「白虚线每秒三条迎面涌来」也没用（窗外区帧间差：静止 1.26 / 写了运动 4.15，肉眼都看不出在走） | 行驶感靠后期引擎声 + 轻微机身抖动补，别指望生成 |
| **「景别不变 / 不推近 / 不推拉」** | 服从度低，后半段照样推近 | 改成正向描述**「画面里始终装得下整个 X（门框上沿到踏板）」**——用「必须包含什么」来控 |
| **「不要出现 X / 不是 X」** | 反向生效，X 反而被画出来（同上面的否定词反噬） | 把 X 的名字从句子里彻底删掉 |
| **同一拍做 2 个以上动作** | 每个只做一半，或直接跳过最「无趣」的那个（关门输给「双手放方向盘」） | 一拍最多两个动作；四个动作就拆拍或删 |
| **「约在第 X 秒说完 / 第 N 拍开头发出」** | 时间描述**完全无效** | H3 的时间轴由**文本事件顺序**决定，只能调整块的先后位置 |
| **单段写多个时间段运镜（0-3s推，3-5s停）** | Qwen3-VL 误以为中途切机位，诱发段内画面闪切 | 单段 `[Shot 1]` 严格只写 1 个贯穿首尾的运镜指令 |
| **中近景写站起 (`rises from chair`)** | 人物头顶冲出画框上边缘，被削掉半个头 | 爆发戏改用 `leans sharply forward across table with veins bulging`（暴怒前倾撑桌） |
| **侧脸戏写复数五官 (brows/eyes) 或否定句** | 模型为画双眼或被否定词反噬，强行转头看镜头 | 严禁复数五官与 turn/camera 词，纯用正向侧脸静态描述，尾端用 TailLock 潜变量夹具锁死 |
| **平静声纹导致高潮戏吼不出来** | 参考音频的平静语调锁死了音频潜空间能量 | 采用 T8mars 协议：台词加咆哮副语言前缀，并在 0.4s 注入物理撞击瞬态拟音拉爆声能 (+10dB) |

**一句话**：H3 听「画面里必须有什么」，不听「镜头不要做什么」；听「事件顺序」，不听「秒数」。

**续接段还有一条专属边界**：续写块结束的那一帧，模型最容易「重置」回参考图构图。
如果这时恰好是一次硬切，它就有了「另起一个镜头」的机会 —— 实测 seg02 首版前 38 帧承接完美，
第 39 帧一结束人物整个消失，跳成参考图里那张无人的大全景。
所以：**续接段不写硬切**，一镜到底 + 同机位最稳；要分镜切换就单独成段。

## 5. 第 3 步：生成、监工、收片（一条命令一件事）

```bash
# ① 提交（preflight + 工程登记 + 续接 + 挑 seed + 记基线）
$PY scripts/sop_run.py submit --seg seg01 --assets 素材.json [--length 243] [--silent]
#    素材.json：{"角色1":"cglide/<项目>/角色1.png", "场景":"cglide/<项目>/场景.png"}
#    --dry-run        只组装不提交（不登记新段、不碰工程档案），并让 ComfyUI 校验图的必填项
#    --chain <工程名>  覆盖握手图里的 chain.name（必须等于已绑定值，否则拒收）
#    --rebind         确实要换导演台工程时才用（改绑，续接从此断开）
#    --cont auto|off|<续拍档路径>   默认 auto=接上一段，off=当第一段
#    --allow-nocont   本段确实要独立开头时用：放行"拿不到续拍档"

# ② 监工（建议后台跑：这一步会一直等到一采落盘，然后立刻双检）
$PY scripts/sop_run.py watch --seg seg01 --timeout 3600

**判失败必须当场让出 GPU**。一采一落盘，二采就开跑；如果等完整质检（抽帧+视觉定量，
十几秒）出结论再 abort，三采/超分往往已经在跑，算力白烧。所以 `watch` 现在分两道：
- **落盘即刻的音频快检**（`_fast_audio_gate`，实测 1.8 秒）：台词超时、留白不足、床音
  清不掉这类高频失败当场掐断，输出 `[fast] 音频快检不过（…）→ 立即中断`。
- 通过后才跑完整 QC（抽帧 + 8 类视觉复核）。
- 两条路径的中止都调 `_kill_queue()`：`/interrupt` **加** `/queue {"clear": true}`。
  只发 interrupt 只停当前节点，队列里 pending 的任务还占着 GPU，下一条要白等。

# ③ 视觉签字（必须真的打开抽帧看，8 类错误逐条过）
$PY scripts/h3proj.py review --seg seg01 --pass
#    不通过：--fail --issues "第2拍左手六指，身份漂移"

# ④ 等终片（超分 → 终片落盘）
$PY scripts/sop_run.py final --seg seg01 --timeout 7200

# ⑤ 收片（自动判断音轨来源 → 清床音 → mux → 复检 → 归档到 成片/）
$PY scripts/h3proj.py finish --seg seg01

# ⑤' 无对白、且 H3 只给了整段乐音的段落：不取 H3 的声音，直接铺数字静音
$PY scripts/h3proj.py finish --seg seg01 --audio-silent
```

**`submit` 除了换三段数据，还做两件以前没做的事**（都为了"下一段接得上"）：

1. **先登记段落**：调班长套件的 `/cglide/chain/add_clip` 把本段登记进 `h3_chain/<工程名>`，
   拿到段落 id 再写进 `h3_data.chain.clip`。执行台拼续接档时要靠这个 id 在 `chain.order`
   里找「上一段」（`order[k-1]`），等执行时再登记就已经晚了 —— 那时 order 里还没有它，
   只能退回"全局最新存档"，串工程就是这么发生的。同 `shot` 重复登记会复用原段，**重抽不会堆段**。
2. **写明续接**：把 `h3_data.cont` 设成 `{mode:"latent", frames:N, latent_file:<上一段的 cont>}`。
   执行台只在 `latent_file` 非空时才续写，否则把本段当第一段（画面与上一段不接）。第一段自动 `cont={}`。

`--dry-run` 会把组装结果和 `graph_problems` 一起打出来；`graph_problems` 非空说明图的必填项有问题，
别急着真跑（真跑会在排队后才报错，白等一次提交）。

**收片有两条轨，别混**：

| 轨 | 落到哪 | 谁写 | 用途 |
|---|---|---|---|
| **段尾归位** | `h3_chain/<工程名>/clip_NNNN.tN.mp4` + `.cont.safetensors` | 图里的「📦 段尾归位」 | 导演台时间轴、下一段续接 |
| **交付片** | `<项目>/成片/<seg>.mp4` | `h3proj.py finish` | 清过床音的成片、拼接、交付 |

归位是生成的最后一步，`finish` 是生产线的最后一步；两者都要有。归位通了但 `finish` 没跑，
成片只有导演台那一份，床音没清、不能直接拼。

如果成片在 `h3_chain/<工程名>/` 里但**不是当前段**（或者根本没出现），先看 `h3wf.py show` 的
`[WARN]`：多半是「📦 段尾归位」的「顺序锚」空着，或者工程名和导演台不一致。

**`watch` 内部做了什么**（这是"一采后必做 SOP"的自动化实现）：
1. 只认"提交前基线里没有的新文件"，不按 mtime 抢别人的片子（踩坑 13）。
2. 文件大小稳定 10s 才算写完 → 立刻跑视觉定量（光流瞬移/直方图突变/首尾相似度）+ 音频四项
   （床音 ≤-50dBFS、台词距段末 ≥1s、段尾留白 ≥0.35s；拟音数量只记录不判定）。
3. **不过就 AUTO_ABORT**：中断队列、seed 进黑名单、重抽计数 +1，不浪费二采/超分的算力。
4. 过了就写台账 `一采待复核`，把 contact_sheet 路径打给你看。
5. 任务报错 / 超时 / 前缀对不上，都有各自的 JSON verdict，不会静默卡死。

**床音不再是一采的否决项（2026-10-19 实测修订）**：H3 对"安静段落"会**稳定垫一层乐音**——
同一段连抽 3 个 seed，床音全部落在 -27.0/-27.5/-27.8 dBFS，频谱是 400Hz 基频加 800/1200/2000Hz
整数倍谐波（是乐音，不是噪声；谱平坦度 0.0027）。换 seed 治不了，它是模型的默认行为。
所以一采判据改成**按动态范围分类**：

| 分类 | 判据 | 处置 |
|---|---|---|
| `clean` | 床音 ≤ -50 dBFS | 无需处理 |
| `music_bed` | 床音超标，但**动态范围 ≥12dB**（人声/拟音与床音拉得开） | **判 PASS**，标记 `needs_bed_clean`，交给 `finish` 的 `audio_gate` 清 |
| `masking` | 床音超标且动态范围 <12dB（床音糊住人声，清完就没声了） | 硬拒 → 换 seed 重抽 |

**拟音（动作拟音）只记录、不判定**：H3 的点状拟音极不稳定（同段三个 seed 分别给出 1/0/0 个），
把它当硬门限等于让每段必然重抽。需要强判时手动 `check_audio_seg.py --fx yes`。
背景氛围音本来就不归 H3 管，走后期铺。

**禁止清单里不要写乐音词汇**：`禁止：任何乐句、和弦、鼓点、低频 drone、pad 音色` 这类写法，
实测会被 H3 当成"要一层乐音"的正面提示。禁止清单保留「背景音乐 / BGM / 配乐 / 持续音 / 混响长尾」
即可，四段式结构（①对白 ②动作拟音 ③数字静音 + 禁止清单）照旧，房规不变。

**`review` 的 8 类严重逻辑错误**（打开 `checks/<seg>_*/frames/` 的联络表 + 首/中/尾帧逐条看）：
身份漂移 / 瞬移穿模 / 动作因果断裂 / 运镜与描述矛盾 / 场景突变 / 首尾断裂（仅 FLF2V）/ 数量突变 / 背离提示词。
**另加第 9 条：画面内叠加文字**——带台词的特写段，H3 有一定概率把中文台词烧成字幕，压在下唇/下巴位置，
像台标一样跟满整句（实测：同一份提示词 5 段干净、1 段中招）。联络表缩略图不一定看得清，
**必须导出 4–7 秒之间的全分辨率帧看下唇**。中招 = 硬伤，换 seed 重抽，不要试图后期擦（贴在脸上）。
**直方图突变 ≠ 失败**：段内多镜头硬切本来就会触发，要拿它的时刻去对段规划的切点，对上就是正常。

### 5.1 显存回收：为什么越跑越慢（曾经从 5 分钟恶化到 33 分钟）

**现象**：正常 45s/步，突然变 300s/步，一段跑 33 分钟。`nvidia-smi` 显示 GPU 100% 利用率，
但功耗只有 **42W**（正常 81W）—— GPU 在空转等数据，不是在算。

**根因**：工作流末尾的显存清理节点（`BanZhang_VRAM_Cleaner` 这类）**只在正常跑完时执行**：

- 中途 `/interrupt` 把执行链砍在第 N 步，清理节点根本没轮到；
- 更常见的是**两段之间提交太快**：上一段刚落盘就提下一段，那些重量级清理
  （清文件缓存 / 进程内存 / DLL，`重试次数=4`）还没跑完，新任务已经启动。

此时显存守卫节点（`VRAM_Guard`，预留 1.0GB）判定可用不足 → **每采一步卸载再重载模型**，
6 步采样就是 6 次热加载。

**三个接口别搞混**（最容易白忙的地方）：

| 接口 | 实际效果 |
|---|---|
| `/interrupt` | 只让采样循环抛异常退出，**模型不动** |
| `/queue {"clear": true}` | 只清未开始的任务 |
| `/free {"unload_models": true, "free_memory": true}` | **只有这个真卸模型** + `empty_cache()` |

顺序必须 **中断 → 等队列空 → free**。运行期间调 `/free` 会被排队到执行结束（等于无效）。
清完残留约 1.7GB 是 CUDA context，属正常，不用管。

**已内置**（不需要手动做）：`scripts/gpu_vram.py`（`--check / --clean / --ensure`）。
`sop_run.py` 三处中断路径（快检失败、质检失败、手动 abort）末尾自动 `free(wait=2.5)`；
`submit` 在登记段之前自动 `ensure_clean()`（队列空且空闲 <1.2GB 才动手，正常态不误伤），dry-run 跳过。

**判据**：`/internal/logs/raw` 里出现 `299.90s/it` 这种量级，或 `Model Initialization complete!`
出现在第 1 步的位置，就是踩上了。随时可查：`$PY scripts/gpu_vram.py --check`。

## 6. 七道闸门（谁拒收什么）

| # | 闸门 | 命令 | 不过的后果 |
|---|---|---|---|
| G0 | 工作流握手 | h3wf.py sync | 没 wf_map.json → submit 拒收 |
| G0.2 | 资产一致性预检 | （设计阶段必审） | 缺 2+3 角色五视图卡 / 关键道具结构卡 / 180° 场景正反打双向卡 → 跨段必漂移，拒收 |
| G0.5 | 任务-工程绑定 | （submit 内置） | 工程名与绑定不一致 → 拒收；该续接却拿不到续拍档 → 拒收 |
| G1 | 段规划表 | h3proj.py plan --check | 有台词却 124 帧 / 缺 hook → 报 FAIL |
| G2 | 提示词 preflight | （submit 内置） | 缺 [场景继承] / 缺人物相对朝向拓扑约束 / 破坏正对站位 / 情绪词未清零 → 拒收 |
| G3 | 一采双检 | sop_run.py watch | 动态范围够的床音只判 WARN（交 finish 清）；masking 级床音/台词截断 → 自动中断 + 换 seed，最多 3 次 |
| G4 | 视觉复核签字 | h3proj.py review | 没签字 → inish 拒收 |
| G5 | 收片复检 | h3proj.py finish | 交付片复检不过 → 退出码 1，要求单独返工该段 |
| G6 | 全片拼接 | h3proj.py concat | 有段未完成 / 分辨率不一 / 各段来自不同导演台工程 → 拒收或自动重编码 |

## 7. 声音：三层模型（已拍板，不再讨论）

| 层 | 内容 | 提示词 | 后处理 |
|---|---|---|---|
| 对白 | 角色台词 | `<Audio N>` 声线卡 + `<d>` | 原样保留 |
| 动作拟音 | 脚步/布料/珠落/拍击 | 每拍 `音效：` 点名 + 封口 | 保留（SNR 自适应轻减） |
| 持续床音 | 风声/沙摩擦/长混响/音乐垫 | `overall_soundscape` ③数字静音 + 禁止清单 | `audio_gate` 清零 |

- 床音是拼接连锁断层的**唯一根因**；拟音是段内点状事件，接缝两边本来就该安静，必须留。
- **不要全片统一降噪**（会重新引入床音并压扁拟音）；哪段不行单独返工那段。
- 台词用 H3 原生台词、BGM 后期统一铺 → H3 端无条件禁 BGM。
- `finish` 自动判断音轨从哪来：终片自带音轨就用终片的；不带就从上游产物里挑（优先成片源前缀），
  所以不管工作流是"超分保留原音"还是"终片无声要靠三采/二采补音"，同一套命令都能走通。
- 参数改动后必须回归：`$PY scripts/test_audio_gate.py`

## 8. 失败处理决策树（自己判断，别问用户）

| 现象 | 判断 | 动作 |
|---|---|---|
| **人脸变形、眼神散焦、五官运动中漂移** | 纯文生视频 (T2V) 缺少解剖几何物理锚点 | **严禁继续盲跑 T2V 抽卡**！用生图工具 10 秒产出 16:9 首帧，确认五官后定稿 `segments/<seg>_keyframe.png`，自动启用 I2V 锁脸 |
| **道具软化变形（表盘/螺丝/电路板融化）** | 视频模型对微观元件缺乏结构先验 | 前置生成首帧道具特写，在静图阶段确认电路板与按键细节，注入 `first_frame` 锁死物理结构 |
| **全片只有干音对白、缺乏商战配乐氛围** | H3 内部生成的 BGM 无法分轨且断层严重 | 提示词严禁生成自带 BGM；拼接后运行 `scripts/cinematic_audio_mixer.py` 铺设独立 BGM 并开启人声避让 (Audio Ducking) |
| 床音超标但动态范围 ≥12dB | **不是问题**，H3 默认垫乐音 | 放行，`finish` 的 `audio_gate` 清（`--frame-sel 55 --alpha-bed 8`） |
| 床音超标且动态范围 <12dB（masking） | 床音糊住人声，清不掉 | 先换 seed；2 次后改声场文案/降台词密度 |
| 段尾留白 0（拟音/台词贴边界） | 概率性 | 直接换 seed 重抽（`submit` 自动换） |
| 动作拟音 0 个 | H3 拟音不稳定，属常态 | **不管**，后期铺氛围；确实要强判才改提示词 |
| 台词贴尾 / 半句被切 | 台词排太靠后 | 先换 seed；连续 2 次仍贴尾 → 前移一拍并写「在本节拍前半段发出」 |
| 光流瞬移 / 穿模 | 多为动作跨度过大或构图冲突 | 先换 seed；2 次后拆动作或换机位 |
| 身份漂移（发型/衣服/年龄） | `@图片` 锁定不可靠 | `subject_definitions` 内联可见特征 + 否定项（"不是红裙不是双马尾"） |
| 场景被重画 | 段内切了空间 | 拆段，不是换 seed 的问题 |
| **结尾该做的动作没做**（该关门却停在门半开、该抬头却在低头） | 被同一句里"更有意思"的动作抢走了全部预算 | **三招并用**：① 删掉一切与结尾主动作竞争的描述；② 把小动作前移一拍，结尾那拍只留两个动作；③ 加**状态型死条款**（「结尾必须是…完成态，不允许停在…」）。状态型比过程描述管用得多 |
| **某个动作整段跳过**（7 秒塞了 4 件事） | 一拍动作超过两个，时间不够，模型砍掉最不起眼的那个 | 删或并：把独立小动作（擦手、转身）并进相邻拍，或整拍删掉，把时间让给主干 |
| 段尾留白不足（0.0x 秒），且改提示词无效 | 拟音写成连续的"一串 / 持续 / 随…变稀"，被铺成床音吃掉了留白 | 拆成离散短点（每声 ≤0.4s，写清时长）；改完仍不过就走静音兜底轨 |
| **清完床音后台词结束点反而更晚**（5.09s → 6.35s，差 0.08s 不过闸门） | `--quiet-gain` 默认 0.03 把清完后残留的微小声放大了，被判成语声 | 加 `--quiet-gain 0.005 --fx-snr 6`。实测可用全参：`finish --frame-sel 55 --alpha-bed 8 --quiet-gain 0.005 --fx-snr 6` |
| **语声 F0 实测偏高**（如 171Hz vs 卡上 130Hz，像是人声跑偏） | 未清床音的测量值不可信，床音会拖高 F0 | **先清床音再判 F0**；实测清后 125Hz，正好落在 130±35 内。别据此重抽 |
| 三次重抽仍不过 | 不是 seed 的锅 | 停下，按上表定位到具体拍，改提示词；报给用户时带三条失败原因 |

重抽上限 3 次由 `watch` 的 `reroll` 计数把关，到 3 会直接提示转人工。

## 9. 断点续产

- 台账：`<项目>/progress.json`，每段状态 = `pending → 生成中 → 一采待复核 → 一采通过 → 待收片 → 完成` / `失败待复核`。
- 恢复：`$PY scripts/h3proj.py status` 看总表（含"下一步该做什么"），从第一个非 `完成` 段继续。
- **任务身份不靠记性**：绑定关系存在 `project.json.chain` 里，重启会话、重启 ComfyUI、换终端都不会丢。
  恢复时一律按绑定名找 `h3_chain/<绑定名>/`，**不要**用"输出目录里最新的工程"去猜 —— 猜错就是串档。
- 台账丢了 / 用户在窗口里自己渲染：`h3proj.py gate --seg <seg> --file <路径>`（或 `--latest`）先补双检，
  `review` 签字，`final --file <终片>` 记文件，再 `finish`。**手动渲染同样要过闸门。**

## 10. 隔离、任务-工程绑定与残留（v3 的结构性修复）

### 10.1 任务 = 工程（续接的唯一前提）

**两级工程，缺一不可，全程不变：**

| 层 | 位置 | 管什么 | 中途变了会怎样 |
|---|---|---|---|
| 本地工程 | `<剧本目录>/生产/`（`project.json`） | 提示词、抽帧、台账、成片、绑定记录 | 台账归零：`status` 看不到已完成段、`finish`/`concat` 找不到片（**可重建，但不该换**） |
| 导演台工程 | `h3_chain/<工程名>/` | `chain.order`（段的顺序）、每段的 `.cont.safetensors` | **续接断**：新段在 order 里找不着上一段 → 当第一段重画；成片归位到另一部片子 |

**续接只认导演台工程这一级。** `chain.order` 是"上一段是谁"的唯一索引，`cont.safetensors` 是画面承接的唯一凭据，
两者都在 `h3_chain/<工程名>/` 里 —— 所以工程名就是续接的名字，改名等于换了一部片子。

**绑定怎么生效**

- 建工程时就能定：`h3proj.py new <剧本>/生产 --name <片名> --chain <导演台工程名>`；
- 不定也行：第一次 `submit` 把握手图里的 `chain.name` 写进 `project.json.chain`（打印 `[bind] …`）；
- 之后每次 `submit` 比对：解析到的工程名 ≠ 绑定值 → **REFUSE**，只给两条路：
  - 接着原来的任务 → `--chain <原工程名>`（或把导演台工程名改回去，再 `h3wf.py sync --force`）；
  - 确实要换 → `--rebind`（旧段留在旧工程；本段起在新工程里按第一段算，续接断开）。
- 查看/改绑：`h3proj.py bind` 看当前绑定，`h3proj.py bind --chain <名字> [--force]` 改绑。

**"该续接没接上"也拒收**：`submit` 解析续拍档返回 `none`（上一段没跑完 / 本段没登记进 order / 存档被清过），
且本段不是全片第一段 → 拒收。以前这里只打印"按第一段处理"就照跑，白烧一次还接不上。
确实要一段独立开头（比如刻意做插叙）才用 `--allow-nocont` 或 `--cont off`。

**一眼看续接还成不成立**：`h3proj.py status` 现在会打印

```
任务工程: <绑定名>
          h3_chain/<绑定名>/：3 段，末段 clip_0003（seg03，take 2），续拍存档 有
归位工程名: <工作流当前 chain.name>   一采前缀=一采_N280
```

绑定与工作流打架时会直接标 `[REFUSE]`；末段"续拍存档 无"说明下一段接不上，要先把末段跑完。
`concat` 也会比对各段台账里记录的工程名，混了工程直接拒拼（G6）。

**中途绝不能做的三件事**（做了续接必断，且没有任何补救能恢复画面连贯）：

1. 在导演台新建一个工程，继续拍同一部片子；
2. 改导演台里的工程名（哪怕只改一个字）；
3. 换一个本地工程目录接着做（台账丢了还能重建，导演台工程丢了就真没了）。

### 10.2 目录隔离与残留

- **一个剧本一个工程目录**：`h3proj.py new <剧本目录>/生产 --name <片名> [--chain <工程名>]`。
  state/抽帧/临时 wav/黑名单/握手图全在工程里，删工程 = 清干净，不会污染下一个项目。
- **技能目录只读**：`paths.py` 检测到项目目录指向技能目录会判定为未就绪，宁可不跑也不写脏。
- 开工前自检：`$PY scripts/h3proj.py residue`（列出技能目录里的残留 + ComfyUI 输入目录各项目素材的闲置天数）。
  归档清理：`$PY scripts/h3proj.py residue --clean`（**移到 `_residue_archive/`，不删除**）。
- 素材按**文件名即别名**放在 `D:/Comfy-Desktop/ComfyUI-Shared/input/cglide/<项目>/`；
  提示词里 `@图片N` 的序号 = `--assets` 里 images 数组的顺序（从 1 起）。

## 11. 环境变量（迁移/并行项目只改这里）

| 变量 | 作用 | 默认 |
|---|---|---|
| `H3_PROJECT_DIR` | 本项目目录（含 project.json） | 从 cwd 向上找 `生产/project.json` |
| `H3_COMFY` | ComfyUI 地址 | `http://127.0.0.1:8188` |
| `H3_OUTPUT_DIR` / `H3_INPUT_DIR` | ComfyUI 输出/输入目录 | `D:/Comfy-Desktop/ComfyUI-Shared/output\|input` |
| `H3_VOICE_CARD` | 声线卡 | `<项目>/voice_card.json` → 技能模板 |
| `H3_FFMPEG` / `H3_FFPROBE` | ffmpeg 工具 | 自动探测 |

`$PY scripts/paths.py` 打印当前解析结果；`$PY scripts/h3proj.py path` 同效。
**所有本地 HTTP 都走无代理 opener**，`HTTP_PROXY` 不会再造成 502。

## 12. 常见故障

| 现象 | 先看 |
|---|---|
| `submit` 说"工作流漂移" | 你改过工作流 → `h3wf.py sync --force`；刚 sync 完还报 → 说明握手之后真跑过别的图，先 `doctor` 看差在哪 |
| `submit` 说"wf_map.json 是旧版握手的" | 握手结构升级过 → `h3wf.py sync --force`（一次性） |
| `submit` 说找不到 rack/desk/cast | `h3wf.py show`，多半是换节点类名了，贴给用户 |
| 成片落进**别的** `h3_chain/` 目录 | 握手图里 `chain.name` 和导演台不一致 → 在导演台填好工程名跑一次再 `sync --force`，或 `submit --chain <名字>` |
| `submit` 说"本任务已绑定…这次解析到…" | 导演台工程名被改了 / 换了工作流 → 接着做用 `--chain <原名字>`；确实换工程才 `--rebind`（续接从此断开） |
| `submit` 说"本该接着上一段，但拿不到续拍档" | `h3proj.py status` 看末段"续拍存档"；上一段没跑完就先跑完；刻意要独立开头才 `--allow-nocont` |
| 一采双检检的是超分/终片 | 认不出一采前缀 → 看 `h3wf.py show` 的「一采前缀」是不是「—」 |
| 终片报"未接入视频文件" | 终片是 `banzhangVideoCombine` 却接在超分后面：它只认有磁盘文件的 VIDEO，超分给的是内存流 → 终片改用 `SaveVideo` 落盘 |
| 归位报"收片后无法确认视频帧数" | 机器上没有 ffprobe（便携包里的常是网盘残片）→ 装 ffprobe，或启用 `banzhang_h3_probe_fallback` 探帧兜底 |
| 整条 prompt 失败在 `H3_LatestFilmPath`（收片归位） | 它扫"output 目录最近 600 秒内的三采成片"，**天生竞态**：298 还没落盘它就执行了 → 终片 306/307/308 一个都没跑。它是叶子节点，不参与渲染 → v3 起提交时**自动摘掉**（`[graph] 摘掉收片归位叶子节点`）；要保留用 `--keep-collector` |
| 抽帧目录空的、`contact_sheet.png` 不存在 | 工程路径含中文，`cv2.imwrite` 在 Windows 上静默失败（返回 False 不抛错）→ 已改走 `imencode + open().write()`；老工程重跑一次 `gate` 补图 |
| 一采里人物嘴部/下巴**烧了一行中文字幕**（就是台词原文） | H3 把中文台词渲染成字幕，和 seed 强相关（同提示词 5 段没有、1 段有）。提示词里 `禁止清单：…字幕` 压不住 → **不要加"不要字幕"**（否定词反噬会加重），直接 `abort --seg X` + `submit --force` 换 seed 重抽。判据：近景+台词段必看 4–7 秒之间的下唇区域；**字幕也可能落在画面底部中央**（门口喊话、全身景最容易中），联络表 8 格逐格看底部 |
| 剧情前后不接（"你还知道回来"直接跳到"高攀不起"） | 段规划阶段把台词砍了。先用 `line_coverage.py` 量：`python line_coverage.py --docx 剧本.docx --from A --to B --build prompts.py`。排入率低于 80% 就是事故，不是"精简" |
| `gate` 报"动作拟音 0 个 FAIL" | 已被 `fx="auto"`（只记录不判定）覆盖；若还报，说明该版本 `cmd_gate` 把 auto 翻成了 yes → 检查 `h3proj.py` 里 `fx = a.fx` |
| **重启 ComfyUI 后 `doctor` 报"没有找到成功执行过的视频任务图"** | `/history` 在进程重启后是空的，握手没有执行图可读。**不要去翻旧快照**，用界面文件兜底：`h3wf.py sync --from-ui "<ComfyUI>/user/default/workflows/<工作流>.json"`。Windows 便携包路径常带空格和序号（`ComfyUI (1)`），整条路径必须加引号。**兜底之后必须做指纹比对**：`sync` 打印的指纹要和上次跑通时的完全一致（本项目 `9a39459af72e`），不一致说明这个文件不是窗口里实际在用的那版，回头找用户确认 |
| 双检报「台词结束点 = 段末 / 段尾留白 0.00s」但台词其实早就说完了 | 段尾的低频闷响（门缝合拢、鞋底、布料传导）被按「能量+时长」误判成第三段台词，把 `speech_end` 顶到段末。判据：人声谱平坦度约 0.002、F0 自相关置信度 ≥0.28；闷响平坦度 0.044、置信度 0.16、主能量在 130Hz 以下。`check_audio_seg.py` 已加 `_looks_like_speech()` 频谱判据（平坦度 <0.02 放行，或 <0.06 且置信度 ≥0.25）。**这类不要换 seed**，先按上面的频谱数自查确认 |
| 改完提示词后双检还是同一项 FAIL（关门声/脚步总贴在段末） | 动作本身就在最后一拍，换 seed 只挪几帧，解决不了。**时间描述无效**（"本拍开头四分之一内完成""9.0 秒前说完"这类字眼 H3 直接忽略）——**H3 的时间轴由文本事件顺序决定**。修法：把该动作/台词整块挪到它应该在的那一拍的**文本最前面**（动作串之前），并在 soundscape 保留时间表「全部拟音在 8.6 秒前发完；8.6 秒之后到段末为纯数字静音」作兜底封口 |
| **台词总顶到段末（speech_end ≥ 9s）且换 seed 无效** | 根因同上：台词 `<Audio 1>…说：<d>…</d>` 写在动作串**之后**，H3 一定等动作演完才开口。实测 5 版：台词块在拍 2 动作后 → 9.8s；前置到拍 2 开头 → 9.3s；前置到拍 1 末尾（与"手僵"同句绑定）→ **4.8s**。铁律：**台词想在什么时候响，文本上就必须排在那个位置之前**；括号里写"约 X 秒内说完""第 N 拍开头发出"全部无效。另外：①"说（"是对白识别动词，写"喊出（"会触发 preflight WARN；②表演词"哭腔、语速快而碎、字尾黏连"会把台词拉长到预估的 1.7 倍（7 字台词标称 1.9s、实测 3.5s），段末预算按 1.7 倍留；③台词块挪动后 reroll 计数要归零——那是"同一提示词重抽次数"，不是"本段累计失败次数" |
| **前置到第 2 拍还不够，仍差 0.3 秒** | 175 帧段实测 4 版梯度：写在动作串后 → **完全没生成**（语声 0 个，该时段无任何事件）；第 3 拍文本最前 → **7.07s** 说完（距段末 0.23s）；第 2 拍文本最前 → **6.64s**（差 0.34s）；**第 1 拍文本最前 → 5.09s**（距段末 2.21s，PASS）。结论：**一段一句，放第 1 拍文本最前面**，动作串整块挪到 `<d>` 之后。附带好处：台词提前后常能把「因果更紧」的表演带出来（如"车还没停稳就开口"），更好用 |
| `cont off` 的段组装后头部少了一小段画面 | `ensure_clip` 每次重抽都会把 `trim_frames` 压回工程默认（5），但 cont off 段头部没有承接帧、**应该记 0** → 组装时按「cont off 段不裁头」手传参数，别信档案；或 `POST /cglide/chain/update` 改回 0 |

**重启后恢复的标准动作**（顺序固定）：

```bash
curl -s "$API/queue"          # running/pending 都应是 0，GPU 应空闲
curl -s "$API/history"        # 条数为 0 → 必须走 --from-ui 兜底
h3wf.py sync --from-ui "<窗口里那个工作流>.json"   # 看指纹是否等于上次跑通的值
h3proj.py status              # 确认段位/续接档还在（导演台目录不受 ComfyUI 重启影响）
sop_run.py submit --seg <段> --chain <工程> [--cont off] --force
```

重启**不影响**导演台的 `h3_chain/<工程>/` 目录（在磁盘上），续接档 `clip_*.cont.safetensors` 都还在，所以恢复后能直接从断点续跑。重启**会丢掉**队列里所有未完成的任务和 `/history`，所以重启前正在跑的那一段必须重新 `submit`，`progress.json` 里那条"生成中"是死记录。
| `No module named 'cv2'` | 用错解释器了：cv2 在 `~/.workbuddy/binaries/python/envs/default/Scripts/python.exe`，裸 `python` 指向的是 versions 目录那个干净的 → 全部脚本用 venv 解释器跑 |
| 无对白段床音清不干净（清完 RMS 还是 -16 dB） | H3 给的是**整段铺满的乐音**，频谱减法把它当"内容"保下来了 → 该段用 `finish --audio-silent` 直接铺数字静音，环境音/配乐留到剪辑期统一铺 |
| 拼接处"声音跳一下" | 某段床音没清 → `h3proj.py finish` 重做该段；调 `audio_gate --alpha-bed` |
| 清完拟音发虚 | `--alpha-bed` 过大或 `--frame-sel` 过小；先跑 `test_audio_gate.py` |
| 拿到上一次的成片 | 一律走 `prompt_id` 归属，别按文件名取最新 |
| 新项目跑到旧数据 | 你八成没用 `h3proj.py new` 建隔离工程 —— 这是 v3 唯一允许的工程方式 |
| **一段突然跑了半小时**（正常 5 分钟），日志 `299.90s/it` | 显存没回收，每一步都在卸载+重载模型。看 `nvidia-smi`：GPU 100% 但功耗只有 42W（正常 81W）就是它。已内置自愈（`gpu_vram.py` + 三处中断自动 free + submit 前自检）；手动查 `$PY scripts/gpu_vram.py --check`，清理 `--clean`。详见 §5.1 |
| **连续两次提交之间要留几秒**（上一段刚落盘就提下一段） | 上一轮的显存清理（清文件缓存/DLL，重试 4 次）还没跑完，新任务启动就又踩脏态。`submit` 的 `ensure_clean()` 会挡住，但**手动在窗口里点 Queue 时没人挡** → 养成"落盘后先抽帧看一遍再提下一段"的习惯，正好也符合"提交前必须看画面" |

## 13. 什么时候更新这个 skill（触发条件 + 迁移纪律）

**这个 skill 只装「换个剧本、换一组人、换一个工程名之后仍然成立」的东西。** 项目文件不进这里。

### 13.1 必须更新的六个触发条件

出现任意一条，就该改，不要等下次想起来：

| # | 触发 | 典型信号 | 落到哪 |
|---|---|---|---|
| 1 | **同类错误第二次出现** | 同一段因为同一原因重抽了第 2 次 | 原条目补数字；没有条目就新建 |
| 2 | **实测推翻了文档里写的** | 文档说 A，跑出来是 B（含"文档自己在教错"） | 先改错的地方，**不许只加不删** |
| 3 | **验证出一条服从度边界** | 某写法改 2 版无效、换 seed 也无效 | §4.1 边界表 |
| 4 | **脚本行为变了** | 新增脚本、参数默认值变了、CLI 增删子命令 | SKILL.md 对应命令块 + `references/` |
| 5 | **重抽率结构性下降** | 采了某条规则后，某类段落从 N 版降到 1 版 | §8 决策树（写清因果和数字） |
| 6 | **用户纠正过一次概念** | "不要凭空给 H3 加这种限制"这类 | 顶部铁律或 §0 契约 |

### 13.2 不该写进来的（写了就是污染）

- **项目专属内容**：片名、角色名、道具名、参考图文件名、工程名、段落编号、某段的提示词原文、`plan.json` / `progress.json` / `assets/*.json` / `成片/` 路径、当次的 trim 账、当次的黑名单 seed。
- **单次偶发失败**：一次身份漂移、一次 seed 抖动、一次手误。**偶发不是规律。**
- **未验证的猜测**：没有对照结果、没有数字的"我觉得可能"。宁可记在项目里，等第二次实测再说。
- **机器状态**：端口、盘符、显存当时的读数、ComfyUI 版本号（写进 §11 环境变量或项目记忆，不写进正文）。
- **项目侧的临时工具**：`工具/*.py` 这类一次性脚本只留在项目里；只有当它解决的问题**换项目还会遇到**，才提升为 `scripts/` 里的正式脚本并在此登记。

### 13.3 一条内容能不能迁移：三问

写之前逐条过，**三问全过才写**：

1. 换一个剧本、换一组人、换一个工程名，这条还成立吗？
2. 它描述的是 **H3 / 工具 / 管线 的行为**，还是**这一部片子的内容**？
3. 有实测数字或对照结果吗？（"改了之后从 3 版降到 1 版" / "0.07s → 0.66s"）

第 2 问答"是内容"、第 3 问答"没有"——都不写。

### 13.4 写进去的形式

固定四段，不写"建议""注意"这类没抓手的话：

```
现象：什么情况下会出问题（带触发条件）
判据：怎么判断是不是它（带数字/日志特征）
处置：改什么（具体写法或命令）
反例：错的那种长什么样（可选，写了要标"错"）
```

判据这一栏是重点：**没有判据的经验等于没写**，下一个人还是得靠猜。

### 13.5 落位规则

| 内容 | 去哪 |
|---|---|
| 铁律、契约、禁令、开工流程、命令块 | `SKILL.md` 正文 |
| 段落级技巧、写法细则、参数含义、踩坑细节 | `references/*.md` 对应那份 |
| 能被脚本判定的规则 | 直接改成 `scripts/` 里的检查（preflight / audio_gate），比写文档可靠 |
| 版本变更摘要 | `SKILL.md` 顶部 `v3.x 更新` 一行一条，不写长 |

**同一件事不要在三处各写一遍。** 正文写结论 + 指向 `references/`，`references/` 写细节 + 指向脚本。

### 13.6 改完必须做的三步自检

1. **删旧写法**：加了新写法就把被推翻的旧句子删掉，`grep` 一遍旧关键词确认清零（本次就查出「台词写在节拍末尾」「呼吸使胸腔每 2.5 秒起伏」两处一直在教错）。
2. **查结构**：`grep -n "^## "` 看章节编号没乱、没重复。
3. **脚本自检**：动了 `scripts/` 就跑 `python -c "import ast; ast.parse(open(f,encoding='utf-8').read())"` 全部过一遍，再用 `--dry-run` 跑一次真实段确认没打坏。

### 13.7 什么时候动手（时机）

**先记下来，等这一幕收工再改。** 边拍边改 skill 有两个真实风险：

- 改 `scripts/` 会让**正在跑的那一段**用上新代码：`watch` 还没结束就换了 `_kill_queue` / `finish` 的逻辑，等于半途换引擎。
- 改提示词规范会让**同一部片子里前后段落按两套规则写**，跨段一致性反而变差。

所以节奏是：拍摄中只在**项目记忆**里记一条「待沉淀：现象 + 数字」，整幕（或整个项目）交付后统一过一遍 §13.1–13.6，一次性落进 skill。**例外只有一种**：脚本 bug 正在阻塞当前渲染，那就当场修脚本，但文档留到收工再补。

## 14. 分镜定帧图前置生成工序 (I2V Keyframe Pre-Generation Gate)

> **铁律：严禁在未确立具体分镜首帧垫图的情况下盲跑纯文生视频 (T2V)。**

### 14.1 为什么必须前置生成定帧图
- **T2V 的根本缺陷**：纯文生视频在每一段（175帧）初始化潜空间随机噪声，导致镜头切换时出现“同一角色五官漂移”、“场景墙面色彩异变”、“武器道具结构软化”；
- **I2V 的几何锚定效应**：在视频生成前，利用生图模型（Flux / SDXL）结合角色设计卡（Character Reference）+ 场景提示词 + 当前机位角度，提前生成 16:9 高清定帧图（`keyframe_segXX.png`）。MiniMax H3 仅需承担“驱动定帧图动作与口型”，第 0 帧彻底锁死骨骼轮廓、衣服皱褶与道具特征。

### 14.2 三层定帧前置校验清单
每个分镜定帧图必须通过三项人工/脚本核验后方可挂载进 `first_frame`：
1. **角色面部与体态一致**：瞳色、发型发色、标志性伤疤/目镜、服装材质与角色设定卡绝对吻合；
2. **机位角度与分镜表一致**：景别（CU/MLS/LS）、倾角（俯仰平视）、人物视线朝向严格服从导演调度；
3. **关键交互道具物理就绪**：若本段涉及武器、账本、酒杯等道具，首帧图中道具必须以清晰硬表面存在，绝不能出现变形熔断。

---

## 15. 单人说话锁定与全员闭嘴抑制协议 (Speaker Lock & Mouth Suppression)

> **现象**：H3 生成多人物同框画面时，经常出现画面中所有人甚至背景群众都在张嘴说话，极度出戏。
> **根因**：H3 音频对齐器检测到画面中多张人脸，但提示词未显式指定唇形驱动权重归属，导致口型泛化扩散到所有人脸。

### 15.1 提示词四步约束法
在装配提示词时，强制执行主谓分离与闭嘴抑制指令：

1. **`[Subject 1]` 明确主从关系**：
   - 必须显式注明谁是发言者（`Primary speaker: [Name]`），谁是无声倾听者（`silent listener`）。
   - 示例：`Primary speaker: Sal (female bounty hunter), alongside Merchant (corrupt trader, silent listener).`
2. **`[Action 1]` 专属发音指令**：
   - 必须限定发言者的唇动同步：`Only Sal is actively speaking with natural, synchronized Mandarin lip movement.`
3. **`[Action 1]` 严苛闭嘴抑制死条款 (Crucial Requirement)**：
   - 必须对同框所有其他人物追加闭嘴指令：
     `Crucial requirement: Merchant remains strictly silent with lips tightly sealed and mouth completely closed, showing a tense glare without any lip movement. All other background characters have their mouths firmly shut.`
4. **段尾 1.2s 闭嘴凝视缓冲 (Ending Clamp)**：
   - `In the final 1.2 seconds, all characters firmly close their mouths, ending on a tense silent glare.`

---

## 16. 全局风格母卡 (Global Style Bible) 与前置定风闸门

> **铁律：一部短剧必须拥有全局唯一的 Style Bible，严禁各集分镜私自篡改核心风格词。**

### 16.1 风格母卡五大核心要素
生产启动前，必须在项目根目录确立 `style_bible.json`，覆盖以下 5 个维度：
1. **Visual Genre**（视觉流派）：如 `Cinematic retro-future dieselpunk graphic novel style, mature neo-noir tone`；
2. **Color Palette**（色调情绪）：如 `desaturated amber and deep teal contrast, rusty bronze highlights, rich shadow details`；
3. **Lighting Base**（布光质感）：如 `heavy chiaroscuro lighting, harsh directional rim light, high contrast dramatic shadows`；
4. **Environment Base**（场景基底材质）：如 `weathered rust and scuffed brass, damp asphalt reflections, volumetric smog`；
5. **Quality & Lens**（光学与胶片）：如 `35mm film grain, Panavision anamorphic lens flare, shallow depth of field, 8k resolution`。

### 16.2 开工前置定风闸门
开工前，利用母卡生成 4 张基准定风样张（① 大景深全景、② 主角中景、③ 配角特写、④ 标志性道具），经用户确认定调后，全剧所有分镜的 `[Quality 1]` 和 `[Environment 1]` 必须 100% 自动继承该母卡，杜绝画风漂移。

---

## 17. 短剧黄金语速与密度调控 (Pacing & Density Normalization)

> **现象**：角色说话拖沓、慢吞吞、拉长音发呆。
> **根因**：H3 为 175 帧（约 7.3 秒）视频。当台词过短（仅 8~12 个字）时，多模态模型为了平摊音频时间轴，会强行拉长每个汉字的音节发音，导致语速极其拖沓。

### 17.1 台词密度黄金准则
- **175 帧标准对白长度**：严格控制在 **20 ~ 28 个纯汉字**（折合语速 **3.2 ~ 4.2 字/秒**，契合快节奏商业短剧爽感）；
- **字数预警阈值**：
  - `< 16 字`：强制触发预警。必须扩充台词交锋密度，或将动作时序拆解；
  - `> 30 字`：强制触发超长预警。必须精简台词，防止 H3 快速吞字。

### 17.2 语速与节奏强化指令
在 `[Audio 1]` 中必须写入紧凑语速描述：
- 错误写法：`Audio: Sal says <d>你好</d>`
- 正确写法：`Strict Mandarin Chinese dialogue only. Sal speaks with a cold, aggressive and razor-sharp vocal delivery, spoken rapidly and crisply without dragging syllables or pausing between words: <d>纯中文台词</d>`。
- **时序分割**：前 4.5 秒高速吐词，后 2.8 秒切入冷眼凝视与动作反应（拔枪、冷笑、挑眉、握紧刀刃），做到有张有弛。

---

## 18. 六大电影级动态运镜与演员动线调度库 (Director Camera & Staging)

> **痛点**：对话镜头全是两个人面对面站桩正反打交谈，呆板尴尬，毫无视听张力。
> **禁令**：严禁连续两个分镜使用静态过肩（OTS）正反打！必须强制引入空间纵深与动态运镜。

### 18.1 六大电影级运镜模板库
在分镜规划时，必须根据剧情对抗从以下 6 种模式中轮换调度：

| 调度模式 | 英文提示词原语 | 视听张力与应用场景 |
| :--- | :--- | :--- |
| **1. 动线交错慢推 (Cross-Walking Tracking)** | `Slow forward tracking shot following character walking briskly through the room, camera pushing in steadily, dynamic background movement, continuous tension.` | 角色边走边说，打破静止站桩，压迫感迎面扑来。 |
| **2. 道具特写拉焦 (Prop-to-Face Rack Focus)** | `Extreme close-up starting on the prop (slammed on table/held in hands), rapid rack focus up to the speaker's intense glaring eyes, shallow depth of field, dramatic depth shift.` | 强调刀刃、手枪、假账本、怀表等关键道具，视觉焦点瞬间由物转人。 |
| **3. 荷兰角斜切 (Dutch Angle Dramatic Tilt)** | `15-degree Dutch angle tilted low shot, looking up at the dominant character stepping forward intimidatingly, creating extreme psychological pressure and cinematic unease.` | 局势逆转、暴力威胁、审讯逼迫时的心理失衡感。 |
| **4. 背身转头回眸 (Back-Turned Reveal)** | `Character begins with their back turned towards camera speaking coldly, suddenly pivots their head 90 degrees to deliver the punchline with an icy stare, dramatic rim lighting catches their jawline.` | 吐出关键底牌或冷酷裁决，强化角色霸气与戏剧性反转。 |
| **5. 贴耳逼近压迫 (Close Whisper Threat)** | `Tight medium close-up, speaker leans in uncomfortably close towards the listener's ear, whispered menacing intensity, listener flinches slightly while speaker holds cold direct gaze.` | 私密交易、耳语威胁、近身博弈，空间距离压缩到极限。 |
| **6. 侧光剪影对峙 (Profile Silhouette Standoff)** | `Cinematic two-shot in profile, characters not looking directly into each other's eyes but glaring past each other, split lighting separating them, smoke drifting between them.` | 视线错位，高手过招时的暗流涌动，拒绝直白对视。 |

---

## 19. 纯正普通话发音规约与 ASR 语种漂移闸门 (Mandarin Purity & Language Gate)

> **现象**：H3 偶尔胡言乱语、吐出含糊伪英语、或吞吐非中文杂音报错。
> **根因**：台词中含有阿拉伯数字、英文缩写或非法符号，或 `[Audio]` 中未强制锁定母语语种。

### 19.1 台词纯净化预处理规范
在进入提示词编译器前，必须调用归一化处理器：
1. **数字全量转大写汉字**：`100` -> `一百`，`5000` -> `五千`，`EP01` -> `第一集`；
2. **剔除所有英文字符与代码符号**：严禁出现英文单词（专有名词转纯汉字译名，如 `Boss` -> `老大`），去除 `/ \ @ # $ % ^ & * _`；
3. **中文标点标准化**：仅允许使用中文全角逗号 `，`、句号 `。`、问号 `？`、感叹号 `！`、冒号 `：`。

### 19.2 普通话强指令与 ASR 拦截闸门
- **提示词锁定**：`[Audio 1]` 必须冠以：`Strict Mandarin Chinese dialogue only, standard native Chinese accent with clear articulation, zero foreign tone, zero English words.`
- **ASR 语种自动化拦截闸门**：成片落盘后，调用 Whisper 快速检测音频流语种（`language == "zh"`）。若识别为其他语种或 confidence < 0.85，自动触发告警并启动重绘。

---

## 20. 工业化 Master 母调度管线全自闭环 (Pipeline v5.0 Master)

在 `scripts/director_engine_v3.py` 的统一调度下，整个生产闭环如下：

```
[剧本大纲与角色设计]
        ↓
【Step 1: 确立 Style Bible】 (全局母卡定案 + 4 张定风样张人工确认)
        ↓
【Step 2: 分镜剧本与运镜编制】 (采用 6 大动态运镜，规避面对面呆板正反打)
        ↓
【Step 3: 台词密度与纯中文清洗】 (数字转汉字，字数锁定 20~28 字，语速 3.5 字/秒)
        ↓
【Step 4: I2V 分镜定帧图前置生成】 (结合角色/场景/道具生成 16:9 首帧并核验)
        ↓
【Step 5: 提示词编译器 (Director Engine)】 (单人发音锁定 + 闭嘴抑制死条款 + 7 段式装配)
        ↓
【Step 6: ComfyUI H3 物理渲染】 (I2V 首帧锁脸 + Turbo 8-step + Windows 黄金驱动参数)
        ↓
【Step 7: 门控清洗与远景条件修脸】 (audio_gate 谱减去床音 + MLS/LS 条件局部重绘)
        ↓
【Step 8: ASR 语种双检与无损拼接】 (Whisper 语种核验 + concat -c copy 拼接全片)
        ↓
【Step 9: 影视级侧链避让配乐与 1080p 超分】 (Audio Ducking 人声避让 + RealESRGAN x2 终片)
```

---

## 文件索引

| 文件 | 什么时候读 |
|---|---|
| `references/keyframe_i2v_guide.md` | **分镜首帧出图与锁脸必读**：T2V 扩散漂移原理、I2V 几何锁脸、微观道具核验清单 |
| `references/directing_bridge.md` | 拿到剧本后：分镜怎么换算成段/拍，逻辑四问，段规划表格式 |
| `references/character_sheet_standard.md` | 角色资产卡规范：2+3 头身解耦标准设计卡 |
| `references/vividness.md` | 写每一拍之前：怎么让画面"活"，以及 12 条常见死画面 |
| `references/prompt_standard_v2.md` | 写提示词前必读（七段骨架 + 五条硬规则 + 声音口径 + preflight 清单） |
| `references/audio_pipeline.md` | 声音管线手册：床音清洗 (audio gate) 与影视配乐智能避让 (Audio Ducking) |
| `references/pipeline.md` | 节点语义、段间续接机制、踩坑记录、schema 速查 |
| `scripts/director_engine_v3.py` | **v5.0 导演视听调度引擎**：动态运镜库、单人发音锁定、闭嘴抑制、语速密度校验 |
| `scripts/keyframe_gate.py` | 首帧生图核验与 I2V 注入闸门脚本 |
| `scripts/cinematic_audio_mixer.py` | 影视级配乐智能避让混音引擎脚本 |
| `scripts/upscale_video.py` | RealESRGAN 1080p 院线级超分辨率工具 |
| `scripts/run_episodes_1_to_8_upscale.py` | 前 8 集批量超分调度管线脚本 |

## 附：从 v2.5 迁移（如果你还留着旧习惯）

| 旧做法 | v3 做法 |
|---|---|
| 手写 `ov_<项目>.json` / `build_ov_*.py`，还得改 306/308 接线 | `submit` 只注入三段数据，自动组装 |
| 背节点号 257/265/261/277/280/304/306/308 | `h3wf.py` 每次现场识别，节点号不进文档 |
| `waitfirst` 之后再手动 `sop_check` + `check_audio_seg` | `watch` 一条命令做完双检，不过自动中断 |
| 把 `scripts/` 当项目目录（残留的根源） | `h3proj.py new` 建隔离工程 |
| 手动 `audio_gate` + `ffmpeg` mux | `finish` 自动判断音轨来源并完成 |
| 手工维护 state/黑名单 | `progress.json` 台账 + `status` 仪表盘 |

v2.5 的代码备份在 `<workspace>/_h3_backup_v25/`（仅供回溯，不要再用于生产）。
