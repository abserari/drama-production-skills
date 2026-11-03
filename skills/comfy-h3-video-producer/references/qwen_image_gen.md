# 资产图生成：ComfyUI「生图qwen-image_2.1全能编辑-1015」API 驱动

> 2026-11-01《最后一盏圣火》全片实测沉淀（7 张资产、0 失败、单张约 2-3 分钟）。
> 用户指定资产图一律用这套生图工作流生成；本文记录 **API 驱动的正确姿势与坑**。
> 图的内容规范（五视图/拼版/场景双图模板）见 `asset_prep.md`，两者配合使用。

## 1. 工作流与节点图（API 版）

- 界面工作流文件：`D:/Comfy-Desktop/ComfyUI-Installs/ComfyUI (1)/ComfyUI/user/default/workflows/生图qwen-image_2.1全能编辑-1015.json`
- 已固化成 API 图在 `scripts/qwen_asset_gen.py`（节点号以 2026-11-01 版为准，
  **若用户改过界面工作流，以界面为准核对节点号与取值**——同视频工作流纪律）。
- 链路：加载器(239/240/241) → VRAM_Guard(278) → Cache(244) → LoRA(249) →
  素材架(246 CSGlideH3MediaRackCS) → 生图(245 CSGlideQwenCastCS) →
  KSampler(243, 8步 cfg1.6) → 原图(248 `_1raw` 前缀) →
  超分(280 OmniSR×1.5 → 2048) → 精修(281, 3步 denoise0.4) → **成品(267, `<prefix>` 前缀)**

成品图取 `--prefix` 前缀那张（`<prefix>_N267_0001.png` 这类）；`_1raw` 是超分前原图，不用。

## 2. 三个一踩就废的坑（全部实测踩过）

| 坑 | 症状 | 正确做法 |
|---|---|---|
| **配置槽搞错** | 把 prompt/canvas 塞进 `prompt_text`、`qwen_data` 留空 → 出 1024×1024 方图（canvas 不生效） | prompt、negative、**canvas、alias 全部打包成 JSON 字符串放 `qwen_data` 槽**；`prompt_text` 是外接提示词（整体替换正面提示词），不用它 |
| **输出键名错** | 轮询 `/history` 永远等不到结果（实际已出图） | 班长套件输出键是 **`painter_output`**，不是 `images`（脚本里两者都兜底了） |
| **VAE/模型名猜错** | 提交即报 node 校验错误 | 加载器取值以界面工作流保存值为准：UNET=`Qwen-Image-2.1\rayQwen21编辑强化_turboV13Int8convrot.safetensors`、CLIP=`qwen-image-2.1\qwen3vl_8b_w4a8.safetensors`、VAE=`qwen_image_2.1_vae_bf16.safetensors`（**不是** `ae.safetensors`） |

`qwen_data` JSON 结构（脚本已封装，改提示词/画布时对照）：

```json
{
  "prompt": "正面提示词全文",
  "negative_prompt": "",
  "canvas": {"w": 2048, "h": 1152},
  "canvas_from_ref": false,
  "ref_long": 1568,
  "ref_cap": 1280,
  "alias": true
}
```

## 3. 用法

```bash
$PY scripts/qwen_asset_gen.py \
  --name 艾琳 \
  --prompt "$(cat 资产提示词/艾琳.txt)" \
  --canvas 2048x1152 --prefix 圣火资产 \
  --copy-to "D:/Comfy-Desktop/ComfyUI-Shared/input/cglide/<项目>"

# 批量：清单 JSON，每项 {"name","prompt","refs"?,"seed"?,"canvas"?}
$PY scripts/qwen_asset_gen.py --list 资产清单.json --prefix 圣火资产 \
  --copy-to "D:/Comfy-Desktop/ComfyUI-Shared/input/cglide/<项目>"
```

- `--copy-to` 成功后自动把成品拷为 `<目录>/<name>.png`——**文件名即别名**，
  直接满足 asset_prep.md 的 `cglide/<项目>/` 落位要求，无需手动搬。
- `--refs` 传参考图（ComfyUI input 相对路径，如 `cglide/xx/服装设定.png`），
  场景反向角派生（asset_prep.md §3.2 图生图）也走这个参数。
- 单张默认 seed 4254；批量时清单里逐项给 seed，同项目别撞。
- 默认画布 2048×1152（16:9 横图上限档）；图内容按 asset_prep.md 模板写提示词。
- 前置检查：`curl http://127.0.0.1:8188/queue` 确认队列空闲（视频渲染时别抢卡）。

## 4. 出图后

1. **先目检再入库**：`asset_check.py --dir <cglide>/<项目>` 统计法初筛 +
   ViewImage 逐张过内容项（五视图一致性/无人/无文字水印）——生图便宜，废图别心疼，重生成。
2. 留意 `output/` 里的废图（`_1raw` 与失败版），确认入库后可清理，别堆积。
3. 每张约 2-3 分钟（8+3 步双采样 + 超分）；7 张连跑约 15 分钟，放后台跑、
   期间并行做握手/写提示词。
