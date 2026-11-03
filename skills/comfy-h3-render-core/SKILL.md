---
name: comfy-h3-render-core
description: 短剧工业化管线·第 3 工序：H3 物理视频渲染与防翻车调度。负责与本地 ComfyUI 服务交互，调度 MiniMax H3 进行 Turbo 8-step 视频生成。硬核沉淀：Windows WDDM 驱动锁防御、潜空间 32 整除铁律、单人发音锁定与全员闭嘴抑制指令装配、首帧 I2V 安全注入、分镜间显存防泄漏。
---

# ComfyUI H3 Render Core (H3 物理渲染与调度工序)

> **工序定位**：短剧物理生成核心工序。
> **核心原则**：不写死 ComfyUI 节点号，严防 Windows WDDM 驱动锁死，强制执行单人发音锁定与潜空间尺寸安全检查。

---

## 1. 运行契约与输入输出

- **输入**：
  1. `plan.json`（含运镜、对白、时序 175 帧）；
  2. 第 2 工序的定帧垫图：`segments/{seg_id}_keyframe.png`；
  3. `style_bible.json`。
- **输出**：
  1. H3 原生生成视频：`segments/{seg_id}.mp4`（带原生音画）；
  2. 显存状态监控日志与渲染耗时台账。

---

## 2. 硬核 SOP：三大防翻车物理铁律（带数字特征与报错反例）

### 2.1 铁律一：潜空间尺寸 32 整除定律（防 VAE 潜空间崩溃）
- **现象/报错**：
  `RuntimeError: shape '[1, 24, 1, 1, 15, 2, 26, 2]' is invalid for input of size 38160`
- **根因**：MiniMax H3 的 3D Patch 尺寸要求宽度必须被 16 整除，且商必须为偶数（即 `width % 32 == 0`）。
- **判据与处置**：
  - **严禁使用**：848×480（848/16=53 为奇数，无法被 patch=2 整除，必崩！）；
  - **强制锁定**：标准宽屏一律锁定 **832×480**（832/16=52 为偶数，52/2=26 完美整除！）。

### 2.2 铁律二：Windows WDDM 驱动互斥锁防御（防暴慢 15 倍）
- **现象**：
  在 Windows 下启用 `cudaMallocAsync` 或多流异步搬运（`async-offload`）后，单步采样从 40 秒暴跌至 600 秒（单段耗时高达 70 分钟）。
- **根因**：Windows 的 WDDM 驱动模型在跨 CUDA Stream 搬运大权重时，会产生严重的内核互斥锁争抢（Mutex Lock Contention）。
- **处置（ComfyUI 黄金启动参数）**：
  ```powershell
  python C:\AI\ComfyUI\main.py --disable-auto-launch --disable-mmap --disable-cuda-malloc --disable-async-offload --listen 127.0.0.1 --port 8188
  ```
  利用原生缓存与单流调度避开驱动锁，单段生成耗时稳定保持在 **350 秒（5.8 分钟）**。

### 2.3 铁律三：单人发音与闭嘴抑制指令装配（消灭全员动嘴）
在构建 `[Subject 1]` 与 `[Action 1]` 时，必须强制执行分离装配：
- **`[Subject 1]`**：`Primary speaker: [SpeakerName], alongside [ListenerName] (silent listener).`
- **`[Action 1]` 核心原语**：
  ```
  Only [SpeakerName] is actively speaking with natural, synchronized Mandarin lip movement, [Action]. 
  Crucial requirement: [ListenerName] remains strictly silent with lips tightly sealed and mouth completely closed, neither speaking nor making any mouth motions, showing a tense glare. 
  In the final 1.2 seconds, all characters firmly close their mouths, ending on a tense silent glare.
  ```

---

## 3. 硬核 SOP：显存防碎片与断点续产保护

1. **分镜间显存回收**：
   每个分镜渲染完毕后，必须调用 ComfyUI `/free` 端点：
   ```python
   payload = {"unload_models": False, "free_memory": True}
   ```
   清空 PyTorch 中间 3D 潜空间张量缓存，防止长周期连续生产累积 OOM。
2. **断点续产防重复渲染**：
   检测 `segments/{seg_id}.mp4`，若文件已存在且大小大于 100KB，直接打印 `[复用]` 跳过，支持秒级断点续跑。

---

## 4. 专属工具脚本

- **H3 执行图组装与调度引擎**：`python scripts/h3_render_orchestrator.py --plan plan.json --server 127.0.0.1:8188`
