---
name: drama-audio-soundstage
description: 短剧工业化管线·第 4 工序：声音工程与智能避让配乐。负责 H3 视频生成后的声音精修。硬核沉淀：谱减法音频门控（消灭风噪/电流床音）、Whisper ASR 纯普通话语种漂移拦截、FFmpeg 原生侧链动态避让混音（Sidechain Ducking，台词开口 BGM 瞬降 -14dB，闭嘴扬起）。
---

# Drama Audio Soundstage (声音工程与智能配乐工序)

> **工序定位**：短剧声音设计与商业配乐工序。
> **拒绝通用废话**：不解释什么是音轨，只沉淀**音频门控清洗参数、语种漂移拦截阈值与侧链避让混音曲线**。

---

## 1. 运行契约与输入输出

- **输入**：
  1. 第 3 工序输出的带原生音频的视频分镜：`segments/{seg_id}.mp4`；
  2. 独立高质量电影配乐 BGM：`assets/bgm/*.wav`。
- **输出**：
  1. 滤除床音后的纯净分镜：`cleaned_segments/{seg_id}.mp4`；
  2. 挂载 90s 悬疑商战配乐与人声侧链智能避让的成片：`[集名]_final_ducked.mp4`；
  3. ASR 语种与台词准确性质检单。

---

## 2. 硬核 SOP：谱减法音频门控清洗 (Audio Gate)

> **现象**：H3 生成的音频往往自带持续的“嗡嗡”低频电流声、假风噪或刺耳环境床音，破坏视听沉浸感。
> **目标**：彻底滤除持续床音，100% 保全人物对白与短促动作拟音（拔刀声、拍桌声、脚步声）。

### 2.1 门控核心参数与物理意义
调用 `scripts/audio_gate.py` 时执行黄金参数组：
- `--bed-q 15`：时域滑动窗分位数（设为第 15 百分位），精确识别持续底噪；
- `--alpha-bed 6.0`：持续床音扣除强度；
- `--alpha-fx 1.0`：瞬态拟音/对白保护因子，越小对白越完整；
- `--fx-snr 4.0`：信噪比判定阈值；
- `--quiet-gain 0.03`：纯静音帧衰减系数。

命令：
```powershell
python scripts/audio_gate.py --in segments/seg01.mp4 --out cleaned_segments/seg01.mp4
```

---

## 3. 硬核 SOP：ASR 普通话语种漂移自动化拦截

> **现象**：角色发音漂移为伪英语、含糊乱码或非中文杂音，严重影响交付。

### 3.1 拦截与判据
落盘后通过轻量 Whisper 执行极速语种校验：
1. 提取音轨前 5 秒进行 Language ID 判定；
2. **通过判据**：`language == "zh"` 且置信度 `prob >= 0.85`；
3. **拦截处置**：若判定为 `en` 或其他语种，自动抛出 `LanguageDriftError` 并将分镜标记为失败，触发换 seed 重跑。

---

## 4. 硬核 SOP：影视级侧链动态避让混音 (Sidechain Ducking)

> **禁令（反例）**：严禁无脑将 BGM 铺在视频底下固定音量！对白会被背景音乐淹没，毫无商业片层次感。

### 4.1 FFmpeg 原生 sidechaincompress 黄金曲线
使用人物对白作为侧链控制信号，实时动态压制 BGM：
- **BGM 基础底音**：`bgm_volume = 0.35`；
- **阈值 (Threshold)**：`ducking_threshold = 0.06`（只要人声开口，立即触发下潜）；
- **下潜深度 (Ratio)**：`ducking_ratio = 5.0`（台词说话时，BGM 瞬时下潜约 **-14dB**，给人声留出完全清晰的频段）；
- **起音时间 (Attack)**：`ducking_attack_ms = 80ms`（人声首字开口瞬间平滑下潜，无生硬爆音）；
- **释放时间 (Release)**：`ducking_release_ms = 400ms`（台词闭嘴后，BGM 在 0.4 秒内丝滑回升，烘托紧张情绪）。

命令：
```powershell
python scripts/cinematic_audio_mixer.py --input concat_raw.mp4 --output final_ducked.mp4 --bgm assets/bgm/suspense.wav
```
