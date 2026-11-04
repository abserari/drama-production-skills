# 音画分流管线（v3.4 起的默认交付路径）

> 2026-10-31 在《如果你从未认识我》seg08 实测落地：CosyVoice2 零样本克隆 + VAD 定位 +
> 环境床铺底，首条配音成片一次通过用户听感验收（S2 对位微调一次，-0.25s 标定）。

## 0. 架构：谁管什么

| 层 | 来源 | 说明 |
|---|---|---|
| 画面 | H3 链路（一采→超分→终片→finish） | 与 v3 视觉 SOP 完全一致，不变 |
| 定位参考 | H3 原生音轨 | **不进交付**。H3 的台词驱动了口型 → 它音轨里语声出现的时间点 = 口型时间点 |
| 对白 | CosyVoice2 零样本克隆 | 声线钉死在参考音上，不再"每段祈祷"；音色跨段 100% 一致 |
| 环境床 | `assets/amb/` CC0 素材库（Blanket 14 种）+ `bed` 预设滤波 | 一床铺到底（全片 film 模式），或分时段（list 写法） |
| 点状拟音 | 音效库实录音 / `sfx_lib.py` 程序化兜底 | `--sfx "时刻:路径@增益"` 钺到全片时间轴 |
| BGM | 后期 | 依旧不归本管线 |

**收益**：H3 音频侧的"抽奖"（床音/留白/masking/台词超时导致的无穷重抽）从交付链里整体消失；
音色稳定；台词时长可以借段间空隙（不再受单段 175 帧约束）。

## 1. 对位原理与标定值

1. `h3vad.speech_events()` 在 H3 成片音轨里找语声事件（RMS 帧 + 相对门限，
   `merge_gap=0.8, min_dur=0.35` 聚类口径——细口径会把一句台词切碎）。
2. 台词按序对号入座；`--bias -0.25s`：VAD 按能量起振检测，天然比真实口型起点晚，
   2026-10-31 用户耳朵标定值（先提前 0.25s 听对了）。
3. 跨段时 `audioprod.py film` 自动累加各段时长做全片偏移。

## 2. 命令块

```bash
# ① 参考音自举（每角色要 3s+ 干净单人说白；<1s 克隆相似度明显偏弱）
$PY scripts/make_refs.py --video 成片/seg08.mp4 --seg segments/seg08.txt \
    --voice-card voice_card.json --out-dir audio_prod/refs [--apply]
#    产出 refs/<Sx>.wav + card_patch.json → 核对 ref_text 后合入 voice_card.json

# ② 环境床预处理（素材在 assets/amb/，CC0）
$PY scripts/audioprod.py bed --src assets/amb/rain.ogg --preset indoor-glass --out <项目>/audio_prod/amb/rain_glass.wav
#    preset: outdoor（原样）/ indoor-glass（隔玻璃闷响）/ room（室内空气感）

# ③ 点状音效（实录音优先；没有就用程序化兜底）
$PY scripts/sfx_lib.py whoosh --out <项目>/audio_prod/sfx/whoosh1.wav

# ④ 单段验收（调试口径用，交付不走这条）
$PY scripts/audioprod.py auto --seg segments/seg08.txt --video 成片/seg08.mp4 --out audio_prod/job.json
$PY scripts/audioprod.py gen  --job audio_prod/job.json --voice-card voice_card.json --out audio_prod/track.wav
$PY scripts/audioprod.py mux  --video 成片/seg08.mp4 --track audio_prod/track.wav --out audio_prod/seg08_配音版.mp4

# ⑤ 全片交付（默认路径）：concat 后一次上音
$PY scripts/h3proj.py concat
$PY scripts/audioprod.py film --project <生产目录> --video <生产目录>/全片.mp4 \
    --ambience <项目>/audio_prod/amb/rain_glass.wav --ambience-gain -14 \
    --sfx "12.3:audio_prod/sfx/whoosh1.wav@-4" --out audio_prod/job_film.json
$PY scripts/audioprod.py gen  --job audio_prod/job_film.json --voice-card voice_card.json --out audio_prod/track_film.wav
$PY scripts/audioprod.py mux  --video <生产目录>/全片.mp4 --track audio_prod/track_film.wav --out <生产目录>/全片_配音版.mp4
```

`gen` 缺 torch/cosyvoice 时自动重入 `H3_TTS_HOME/.venv`（默认 D:/H3AudioProd），不用换解释器。

## 3. 分时段环境床（场景切换）

job json 的 `ambience` 写成 list 即可，重叠区的 fade 就是交叉淡化：

```json
"ambience": [
  {"path": ".../wind_glass.wav", "start": 0,  "end": 14.5, "gain_db": -16, "fade_out": 1.2},
  {"path": ".../storm.wav",      "start": 13.5, "end": null, "gain_db": -14, "fade_in": 1.2}
]
```

**口径**：床只在段切换处换，且交叉淡化 ≥1s——床的突变比台词错位更刺耳。

## 4. 与 v3 闸门的关系（修剪说明）

| 旧机制 | 分流模式下的地位 |
|---|---|
| G3 床音三分类（clean/music_bed/masking） | **降级为记录**。床音不再进交付，只有"语声事件数 ≠ 台词数"才值得重抽（台词没生成 = 定位锚点没了） |
| 段尾留白 / 台词距段末 | **只影响定位**：台词贴段末时 VAD 锚点可能被截，film 时该句会报 FATAL-WARN 兜底段首，人工核对 job |
| `tail_dynamic` / `chain_continue` 豁免 | 保留：豁免的段 H3 音轨更脏，但 VAD 只认语声，无碍 |
| `finish` 清床音 / `--audio-silent` | 分流模式下成片**保留 H3 原生音轨**（那是 VAD 的原料），不清床音；交付音轨在 film 阶段整体替换 |
| G5 收片复检音频项 | 保留（保护定位参考质量），但结论不再等于交付音质 |

## 5. 环境依赖

| 项 | 值 |
|---|---|
| `H3_TTS_HOME` | D:/H3AudioProd（CosyVoice 仓库 + 模型 + py3.10 venv/torch cu128） |
| TTS 显存 | ~1.5GB；RTF≈1.7-2.4（5060），30s 全片台词约 1-2 分钟 |
| amb 素材 | skill `assets/amb/*.ogg`（Blanket，CC0 可商用，14 种） |
| 模型/venv 部署 | 见项目记忆 2026-10-31「B 方案落地」；WSL/Docker 在本机被禁，独立 venv 是唯一路线 |
