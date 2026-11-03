# 🎬 短剧工业化 AI 管线模型资产与环境配置清单 (Model Asset Guide)

为保证第三方开发者或协作智能体在克隆本仓库后，能够 **100% 完整复现与我们完全一致的视听成片质量**，请严格对照本清单完成模型部署与 ComfyUI 环境配置。

---

## 1. 硬件与系统基线标准 (Hardware Requirements)

| 组件 | 推荐配置 (生产环境) | 最低配置 (极客模式) | 避坑重点与说明 |
| :--- | :--- | :--- | :--- |
| **GPU 显卡** | NVIDIA RTX 4090 / 3090 / 4080 (16GB ~ 24GB VRAM) | NVIDIA RTX 4070 Ti Super (16GB VRAM) | **严禁低于 16GB VRAM**。int8 UNet(19.5GB) + CLIP(15GB) 总重 34.5GB，需在 16G 显存上配合内存动态搬运。 |
| **系统内存 (RAM)** | 32 GB ~ 64 GB DDR5/DDR4 | 32 GB DDR4 | 动态换入换出时，内存需暂存模型张量与 3D 潜空间激活值。 |
| **操作系统** | Windows 11 / Windows 10 (WSL2 / 原生 PowerShell) | Ubuntu 22.04 LTS | Windows 环境必须遵循 **WDDM 互斥锁防御启动参数**。 |
| **FFmpeg** | FFmpeg 6.0+ (需支持 `sidechaincompress` 滤镜) | FFmpeg 4.4+ | 必须将 `ffmpeg` 与 `ffprobe` 加入系统环境变量 `PATH`。 |

---

## 2. 模型下载与存放目录结构 (Models Directory Tree)

请将相关模型文件下载并放置在您的 ComfyUI 根目录下的对应子目录中（若使用环境变量 `COMFYUI_PATH` 指定路径，脚本将自动识别）：

```
<COMFYUI_PATH>/
└── models/
    ├── diffusion_models/   # 存放 MiniMax H3 扩散生成骨干模型 (UNet)
    │   └── minimax_h3_ref2va_pruned_int8_convrot.safetensors  (~19.53 GB)
    │
    ├── clip/               # 存放 Qwen 3VL 文本与视觉多模态编码器 (或放入 text_encoders/)
    │   └── qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors       (~15.10 GB)
    ├── text_encoders/      # 兼容目录 (ComfyUI text_encoders)
    │   └── qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
    │
    ├── vae/                # 存放 MiniMax H3 3D 视频变分自编码器
    │   └── minimax_h3_vae.safetensors (或官方标准 H3 VAE)
    │
    ├── loras/              # 存放 MiniMax H3 极速 8 步 Turbo LoRA
    │   └── minimax_h3_turbo_lora.safetensors                  (可选/极速生成)
    │
    └── upscale_models/     # 存放 1080p 超分辨率神经增强模型
        └── RealESRGAN_x2plus.pth                              (~64 MB)
```

---

## 3. 模型下载来源与校验规范 (Download Sources & Checksums)

### 3.1 核心视频生成模型 (MiniMax H3 Turbo 套件)
- **UNet 扩散模型**：
  - 文件名：`minimax_h3_ref2va_pruned_int8_convrot.safetensors`
  - 架构：MiniMax H3 Reference-to-Video-Audio (带音画联合潜空间)
  - 精度：int8 工业级量化（显存占用从 42GB 压缩至 19.53GB，画质无肉眼可辨损耗）
  - 存放路径：`<COMFYUI_PATH>/models/diffusion_models/`
- **CLIP 文本/视觉编码器**：
  - 文件名：`qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`
  - 架构：Qwen 2.5/3 VL 32B（NVFP4 / AWQ 量化）
  - 存放路径：`<COMFYUI_PATH>/models/clip/`
- **VAE 模型**：
  - 文件名：`minimax_h3_vae.safetensors`
  - 存放路径：`<COMFYUI_PATH>/models/vae/`

### 3.2 终期 1080p 超分增强模型 (RealESRGAN)
- **模型文件**：`RealESRGAN_x2plus.pth`
- **官方下载地址**：
  - [GitHub Releases - Real-ESRGAN v0.2.1](https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth)
  - 或通过 HuggingFace: `ai-forever/Real-ESRGAN`
- **存放路径**：`<COMFYUI_PATH>/models/upscale_models/RealESRGAN_x2plus.pth`
- **用途**：管线第 5 工序专用。采用 FP16 半精度独占 GPU 批处理，将 832×480 原生视频极速重绘至 1920×1080 院线级清晰度，单集 50 秒耗时仅约 2.8 分钟。

---

## 4. ComfyUI 必备自定义节点插件 (Custom Nodes)

在 ComfyUI 的 `custom_nodes/` 目录下，克隆以下开源/工业插件仓库：

1. **MiniMax H3 官方驱动节点** (`ComfyUI-H3`):
   ```bash
   cd <COMFYUI_PATH>/custom_nodes
   git clone https://github.com/MiniMax/ComfyUI-H3.git
   ```
2. **视频合成套件** (`ComfyUI-VideoHelperSuite`):
   ```bash
   git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git
   ```
3. **远景修脸工作流节点** (`ComfyUI-H3-FaceRefine` - 可选):
   - 若不安装，管线会自动触发平滑降级（Soft Fallback），直通原始视频，绝不中断调度。

---

## 5. 关键运行参数 (黄金防翻车启动命令行)

> [!CAUTION]
> **Windows 用户核心避坑法则**：
> Windows WDDM 显卡驱动模型在多流异步搬运大权重时，会产生严重的内核互斥锁争抢（Mutex Lock Contention），导致生成速度暴跌 15 倍（从 350 秒暴增到近 600 秒/步）。
> **必须** 严格使用以下命令行参数启动 ComfyUI：

```powershell
# 切换到 ComfyUI 根目录
cd <COMFYUI_PATH>

# 启动 ComfyUI 服务 (防显存碎片、防锁争抢黄金组合)
python main.py --disable-auto-launch --disable-mmap --disable-cuda-malloc --disable-async-offload --listen 127.0.0.1 --port 8188
```

---

## 6. 一键自检与环境体检 (Environment Health Check)

配置完毕后，在本项目根目录执行环境医生脚本，即可获得全链路就绪诊断：

```bash
python scripts/check_environment.py
```

若所有项均为 `[PASS]`，则说明您的本地环境已完全具备与商业化短剧同等的生产能力！
