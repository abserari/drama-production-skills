---
name: drama-finishing-upscaler
description: 短剧工业化管线·第 5 工序：终期成片与 1080p 超分增强。负责全集分镜无损拼接与院线级 1080p 超分辨率放大。硬核沉淀：FFmpeg concat 零损耗直拼、RealESRGAN x2plus GPU 独占 FP16 批量超分（~4.8fps）、原生高质量避让音轨无损混流、ffprobe 工业级物理参数验收。
---

# Drama Finishing Upscaler (终期成片与 1080p 超分工序)

> **工序定位**：短剧最终交付与画质增强工序。
> **拒绝通用废话**：不解释什么是超分辨率，只沉淀**多段无损拼接语法、RealESRGAN 显存批处理加速与终片物理验收指标**。

---

## 1. 运行契约与输入输出

- **输入**：
  1. 第 4 工序输出的 8 段已清洗分镜：`cleaned_segments/seg01.mp4` ~ `seg08.mp4`；
  2. 或已完成侧链避让配乐的原画终片：`[集名]_final_ducked.mp4`。
- **输出**：
  1. `[集名]_原画商业版.mp4`（832×480 原生高清交付成片）；
  2. `[集名]_1080p.mp4`（1920×1080 院线级超分辨率终片）；
  3. `delivery_report.json`：物理参数验收台账。

---

## 2. 硬核 SOP：分镜流无损拼接 (Zero-Loss Concat)

> **铁律**：严禁在拼接分镜时进行二次有损重编码（Re-encoding）！二次编码会破坏原画锐度并带来额外的音频降质。

### 2.1 FFmpeg concat 零损耗无缝拼接
生成临时拼接索引清单并执行流拷贝：
```powershell
# 1. 自动生成有序索引清单
file 'cleaned_segments/seg01.mp4'
file 'cleaned_segments/seg02.mp4'
...
file 'cleaned_segments/seg08.mp4'

# 2. 执行零开销流拷贝拼接
ffmpeg -y -f concat -safe 0 -i concat_list.txt -c copy concat_raw.mp4
```
- **耗时**：全剧 8 段拼接仅需 **0.2 秒**，无损保留每一帧的原始像素与音画同步。

---

## 3. 硬核 SOP：RealESRGAN 1080p 独占超分辨率加速

> **显存隔离准则**：在执行 1080p 超分前，必须先释放 ComfyUI 的 GPU 显存占用，让 RealESRGAN 独占 16GB 显存，吞吐速度可达最高。

### 3.1 工业级超分推理与音轨混流
调用 `scripts/upscale_video.py`：
- **模型**：`RealESRGAN_x2plus.pth`；
- **精度与设备**：`CUDA` + `FP16` 半精度；
- **批大小 (Batch Size)**：`batch_size = 4`（在 RTX 4080 独占模式下，帧率稳定在 **~4.8 frame/s**，整集 1400 帧仅需约 4.5 分钟）；
- **音频保护机制**：
  超分前先用 ffmpeg 无损抽取原视频音轨（`audio.m4a`），帧推理完毕后使用 `libx264 -crf 18 -c:a copy` 混流合成，**100% 完整保留 90s 侧链智能避让配乐与纯净台词**。

命令：
```powershell
python scripts/upscale_video.py --input raw_video.mp4 --output final_1080p.mp4 --model RealESRGAN_x2plus.pth --width 1920 --height 1080
```

---

## 4. 硬核 SOP：终片物理参数双检验收

成片落盘后，必须使用 `ffprobe` 执行自动化验收测试：
- [ ] **分辨率严格达标**：宽 1920、高 1080（非 1080p 判为不合格）；
- [ ] **帧率严格对齐**：24.0 fps 标准电影帧率；
- [ ] **时长严格对齐**：8 段 × 175 帧 = 58.33s ~ 58.35s；
- [ ] **音轨流完整**：包含独立立体声音频流（AAC，采样率 44.1kHz/48kHz）。

---

## 5. 专属工具脚本

- **单片 1080p 超分**：`python scripts/upscale_video.py --input in.mp4 --output out.mp4`
- **全集批量超分调度**：`python scripts/run_episodes_1_to_8_upscale.py`
