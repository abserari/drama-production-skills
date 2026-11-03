# 🎬 drama-production-skills (短剧工业化多工序生产 Skill 管线)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-green.svg)]()
[![Model](https://img.shields.io/badge/Model-MiniMax%20H3%20%7C%20ComfyUI-orange.svg)]()
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)]()

> **为 AI 视频短剧工业化落地而生**：将混乱臃肿的单体生成流程，彻底解耦为 **5 大专业分工、自包含的工程化 Skill 矩阵**。
> 拒绝大模型本就知晓的基础废话，专注沉淀实机踩坑得出的**复杂多步 SOP、硬核参数判据、防翻车闸门与自动化调度脚本**。

---

## 🏛️ 五大独立工序 Skill 矩阵架构

```
┌────────────────────────────────────────────────────────────────────────┐
│               短剧工程化 Skill 流水线矩阵 (Modular Skill Pipeline)             │
└────────────────────────────────────────────────────────────────────────┘

 原始剧本/小说大纲
     │
     ▼
 1. drama-director-staging (编剧与导演分镜调度工序)
    ├─ 职责：短剧快节奏分镜、视听动线、台词密度与纯中文规范
    ├─ 硬核SOP：
    │  ① 6 大电影级动态运镜轮换决策树（严禁面对面对话站桩）；
    │  ② 台词纯正汉字归一化（数字 100% 强制转大写汉字，剔除英文缩写与符号）；
    │  ③ 7.3s 时序 20~28 字黄金密度管控（前 4.5s 吐词完，后 2.8s 冷凝视/动作）；
    │  ④ 显式标注发言主体（speaker）与无声旁观者（silent_listeners）。
    └─ 工具：scripts/director_engine_v3.py
     │
     ▼
 2. drama-keyframe-forge (分镜定帧与资产一致性工序)
    ├─ 职责：全局风格母卡锁定、分镜级“场景+人物+道具”三合一定帧垫图前置生成
    ├─ 硬核SOP：
    │  ① 严禁 T2V 盲跑，实行前置低成本控图（单张生图 5 秒，不满意秒级重抽）；
    │  ② 全局 Style Bible 5 大要素固化 + 开工前 4 张定风样张人工确认；
    │  ③ 分镜级 16:9 联合首帧生图与三层质检（面部一致性、机位服从度、道具硬表面）。
    └─ 工具：scripts/keyframe_gate.py
     │
     ▼
 3. comfy-h3-render-core (H3 物理视频渲染与防翻车调度工序)
    ├─ 职责：本地 ComfyUI 握手、I2V 注入、显存生命周期与驱动避坑
    ├─ 硬核SOP：
    │  ① 潜空间尺寸 32 整除铁律（标准 832×480，严禁 848×480 导致 VAE 潜空间崩溃）；
    │  ② Windows WDDM 驱动互斥锁防御（采用规避驱动死锁的黄金参数，单段保持 350s 高速）；
    │  ③ 单人发音锁定与闭嘴抑制死条款装配（彻底消除全员动嘴惨状）；
    │  ④ 分镜间 PyTorch 激活值缓存清空与断点续产防重跑。
    └─ 工具：scripts/h3_render_orchestrator.py, scripts/run_episodes_1_to_10_master.py
     │
     ▼
 4. drama-audio-soundstage (声音工程与智能避让配乐工序)
    ├─ 职责：H3 原生音频清洗、语言漂移质检、影视级侧链动态避让配乐
    ├─ 硬核SOP：
    │  ① 谱减法音频门控清洗（`--bed-q 15 --alpha-bed 6.0` 滤除持续床音，保全对白与拟音）；
    │  ② Whisper ASR 语言质检闸门（检测 `zh` 语种，置信度 < 0.85 自动拦截重跑）；
    │  ③ FFmpeg 原生 sidechaincompress 侧链避让混音（台词开口 BGM 瞬降 -14dB，闭嘴扬起）。
    └─ 工具：scripts/audio_gate.py, scripts/cinematic_audio_mixer.py
     │
     ▼
 5. drama-finishing-upscaler (终期成片与 1080p 超分增强工序)
    ├─ 职责：多段分镜零损耗拼接与 RealESRGAN 院线级超分
    ├─ 硬核SOP：
    │  ① FFmpeg concat 无损直拼（`-c copy` 零编码损耗，8 段分镜 0.2s 拼接）；
    │  ② RealESRGAN x2plus GPU 独占 FP16 批处理加速（吞吐达 ~4.8fps，单集仅需 4.5 分钟）；
    │  ③ 原生立体声避让音轨无损混流；
    │  ④ ffprobe 终片物理验收（1920×1080、24fps、58.35s、AAC 双声道严格达标）。
    └─ 工具：scripts/upscale_video.py, scripts/run_episodes_1_to_8_upscale.py
```

---

## ⚡ 核心痛点与硬核避坑字典

### 1. 为什么禁止两人面对面站桩正反打？
- **传统弊端**：角色不动、机位不动，AI 面孔极易显得呆滞木偶化。
- **6 大动态运镜解决方案**：
  1. `M1_TRACKING`（动线交错慢推）：角色边走边说，推镜跟随；
  2. `M2_RACK_FOCUS`（道具特写拉焦）：刀刃/表盘/账本拉焦点到双眸；
  3. `M3_DUTCH_TILT`（荷兰角斜切逼迫）：倾斜 15 度仰俯拍，心理失衡感；
  4. `M4_BACK_REVEAL`（背身转头冷酷回眸）：背对镜头冷声说话，转头交锋；
  5. `M5_CLOSE_WHISPER`（贴耳逼近压迫）：距离压缩到极致；
  6. `M6_PROFILE_STAND`（侧光剪影对峙）：视线错位，高手暗流。

### 2. 为什么画面中所有人都在动嘴？
- **根因**：H3 音频对齐器自动向检测到的所有人脸分配口型权重。
- **指令语法规约**：
  ```markdown
  [Action 1] Only Sal is actively speaking with natural, synchronized Mandarin lip movement. 
  Crucial requirement: Merchant remains strictly silent with lips tightly sealed and mouth completely closed, showing a tense glare without any lip movement. 
  In the final 1.2 seconds, all characters firmly close their mouths, ending on a tense silent glare.
  ```

### 3. 为什么 Windows 下单步采样需要 10 分钟（暴慢 15 倍）？
- **根因**：Windows 的 WDDM 显卡驱动模型在跨 CUDA Stream 异步搬运大权重时，会产生严重的内核互斥锁争抢（Mutex Lock Contention）。
- **ComfyUI 黄金启动参数**：
  ```powershell
  python C:\AI\ComfyUI\main.py --disable-auto-launch --disable-mmap --disable-cuda-malloc --disable-async-offload --listen 127.0.0.1 --port 8188
  ```
  单段 175 帧生成耗时稳定保持在 **350 秒（5.8 分钟）**。

### 4. 为什么 VAE 潜空间会报错崩溃？
- **报错特征**：`RuntimeError: shape '[1, 24, 1, 1, 15, 2, 26, 2]' is invalid for input of size 38160`
- **规约**：MiniMax H3 的 3D Patch 尺寸强制要求 `width % 32 == 0`。严禁使用 848×480（848/16=53 为奇数），必须严格锁定 **832×480**。

---

## 🚀 快速上手与使用

### 安装为 Agent / Antigravity 技能
将本项目直接克隆或复制到您的智能体技能目录：
```bash
git clone https://github.com/abserari/drama-production-skills.git .agents/skills/
```

### 独立命令行执行

#### 1. 运行分镜提示词编译器
```bash
python scripts/director_engine_v3.py
```

#### 2. 全十集自动化流水线母调度（支持断点续产与跳过超分）
```bash
# 阶段一：全量原画商业版生成（跳过超分）
python scripts/run_episodes_1_to_10_master.py --episodes 1-10 --skip-upscale

# 阶段二：逐集 1080p 超分增强
python scripts/run_episodes_1_to_8_upscale.py
```

#### 3. 独立音频侧链智能避让配乐
```bash
python scripts/cinematic_audio_mixer.py --input raw.mp4 --output ducked.mp4 --bgm assets/bgm.wav
```

---

## 📄 License
[MIT License](LICENSE) © 2026 abserari
