# 短剧后期字幕与片尾字卡压制规范 (Subtitles & Ending Cards Standard)

## 1. 核心架构：生片与字层解耦 (Decoupled Pipeline)

- **严禁在 H3 生视频阶段画字幕**：
  在生视频模型 Prompt 中要求生成中文字幕，会导致扩散模型在像素空间强行生造文字，不仅必定出现错字、乱码、笔画闪烁漂移（Ghosting），还会严重消耗模型注意力与高频特征表现力，导致角色面部口型扭曲、画质劣化。
- **纯净底片（Clean Feed）原则**：
  H3 生片工序只输出无字纯净视频与高质量对齐音频。字幕与包装字卡统一交由后期 Finishing 工序压制。

---

## 2. Whisper 逐字对齐原理（每句字幕跟嘴型走的机理）

- **声学对齐（Word-level Timestamps）**：
  H3 生成的视频具有高精度原生声画同步（Audio-to-Video）。Whisper 开启 `word_timestamps=True` 对音轨进行识别时，可毫秒级捕获每个字/词从声带震动到闭合的发音起止点（`start` -> `end`）。
- **剧本真值校正（Script-Guided Forced Alignment）**：
  - 单纯 Whisper ASR 会产生同音错别字或专有名词误识别；
  - 本规范将 ASR 输出的字级时间戳与剧本原台词进行 SequenceMatcher 文本强制对齐：
    * **时间轴**：100% 继承 Whisper 提取的物理发音与张嘴瞬态；
    * **文本内容**：100% 采用剧本原字，错字率归零。
- **卡拉OK卡点动效（Karaoke Lip-Sync）**：
  字幕随字词发音瞬态逐字/逐词高亮（`\k` 特效），视觉呈现与角色唇齿张合分秒不差。

---

## 3. 视觉与排版工业标准 (Visual & Layout Bible)

### 3.1 短剧专属 ASS 字幕规范
- **字体族**：无衬线粗黑体/综艺体（`SimHei`、`Source Han Sans CN Bold`、`Microsoft YaHei Bold`），严禁使用细线体或发虚宋体。
- **色彩与层级**：
  - 主色：短剧经典醒目明黄（`#FFDE00` / `&H0000FFFF`）或纯白（`#FFFFFF`）；
  - 描边：2.5~3.5px 纯黑描边（`#000000`）；
  - 阴影：1.5px 半透明黑色背衬阴影（`&H80000000`）；
  - 确保无论画面处于强光雪地、霓虹夜市还是昏暗室内，字幕均具备刺目穿透力。
- **安全边距（Safe Margins）**：
  - 底部垂直边距 `MarginV` 占画面高度 10%~12%（竖屏约 140~180px，横屏约 48~60px）；
  - 严格避开抖音/快手/微短剧播放器的播放进度条、标题文案与右侧交互按钮。
- **单行字数门控**：
  - 单行不超过 12~14 个汉字；超长台词依据标点或语义拆分为两个时序卡点展示，确保观众在 0.5 秒内完成信息抓取。

### 3.2 片尾完结字卡规范 (Ending Hook Card)
- **展示区间**：全片结束前 2.0 ~ 2.5 秒（最后镜头淡出或定格处）。
- **构件组成**：
  1. **半透明磨砂背板**：黑色 80%~85% 透明度，辅以高档香槟金边框；
  2. **集数定格**：《短剧名称》 · 第 X 集 完（金色高亮）；
  3. **下集悬念钩子（Next Episode Hook）**：提炼最核心冲突或反转（白色 28~32px）；
  4. **完播与转化导流标语**：“点击右下角合集 · 连看全集不迷路”。

---

## 4. 工具调用与自动化

- 执行脚本：`scripts/drama_subtitles_and_cards.py`
```bash
python scripts/drama_subtitles_and_cards.py \
  --video "path/to/clean_video.mp4" \
  --script "path/to/screenplay.md" \
  --title "重回90：倒腾电子表，我成了百货大亨" \
  --episode "第一集 夜市翻盘 完" \
  --hook "周天宇带打手砸场，陈海当场亮出百万外汇支票！" \
  --out "path/to/delivered_video.mp4"
```
- 产物检查：
  - `*_drama.ass`：包含卡拉OK时间轴的标准短剧字幕文件；
  - `*_subtitled_card.mp4`：集成精准嘴型同步字幕与片尾钩子字卡的最终交付成片。
