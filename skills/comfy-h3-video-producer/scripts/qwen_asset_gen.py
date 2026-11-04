# -*- coding: utf-8 -*-
"""通过 ComfyUI API 驱动「生图qwen-image_2.1全能编辑-1015」工作流生成 H3 资产参考图。

规范见 references/qwen_image_gen.md（qwen_data 槽、painter_output 键等坑都在那里）。

用法：
  # 单张
  python qwen_asset_gen.py --name 艾琳 --prompt "..." [--refs "cglide/xx/a.png"]
                           [--seed 4254] [--canvas 2048x1152] [--prefix 资产]
                           [--copy-to "D:/Comfy-Desktop/ComfyUI-Shared/input/cglide/<项目>"]
  # 批量（清单 JSON：[{"name":"艾琳","prompt":"...","refs":[],"seed":123,"canvas":"2048x1152"}, ...]）
  python qwen_asset_gen.py --list 资产清单.json --copy-to "D:/.../cglide/<项目>"

提交后轮询 /history/{prompt_id}；成功后若给 --copy-to，把成品图按 <name>.png
拷进资产目录（文件名即别名，H3 提交时按文件名映射图槽）。
"""
import argparse, json, shutil, sys, time, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
API = "http://127.0.0.1:8188"
# 默认画布：16:9 横图、长边 2048（asset_prep.md §1 的上限档，五视图/拼版模板都按横图出）
DEFAULT_CANVAS = "2048x1152"


def http_json(url, payload=None, timeout=30):
    data = None
    req = urllib.request.Request(url, method="GET" if payload is None else "POST")
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, data, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def build_graph(name, prompt, negative, refs, seed, w, h, prefix):
    # ⚠️ 班长套件 CSGlideQwenCastCS：画布/负面/别名等全部在 qwen_data 槽解析；
    # prompt_text 是外接提示词（整体替换正面提示词），用了它 canvas 就不生效（会出方图）。
    qwen_json = json.dumps({
        "prompt": prompt,
        "negative_prompt": negative or "",
        "canvas": {"w": w, "h": h},
        "canvas_from_ref": False,
        "ref_long": 1568,
        "ref_cap": 1280,
        "alias": True,
    }, ensure_ascii=False)

    images = []
    for ref in (refs or []):
        ref = ref.strip()
        if ref:
            images.append({"file": ref, "alias": [ref.rsplit("/", 1)[-1].rsplit(".", 1)[0]]})
    rack_json = json.dumps({
        "slots": {"images": images, "videos": [], "audios": []},
        "fps": 0, "audio_out": 0, "segs": {}, "cur": "",
    }, ensure_ascii=False)

    # LoRA 组与用户界面工作流默认一致（2026-11-01 校准）；
    # 若用户改过界面工作流的 LoRA 开关，以界面为准手动改这里。
    lora_cfg = json.dumps([
        {"on": True, "file": "qwen-image-2.1/V2_Qwen_image_2.1_B美丽版.safetensors", "strength": 0.15, "note": ""},
        {"on": True, "file": "qwen-image-2.1/仙侠古风美学.safetensors", "strength": 0.3, "note": ""},
        {"on": False, "file": "qwen-image-2.1/中国神话仙宫_Qwen 2.1.safetensors", "strength": 0.65, "note": ""},
        {"on": False, "file": "qwen-image-2.1/lightx2v Lightning 4-step.safetensors", "strength": 1, "note": ""},
        {"on": False, "file": "qwen-image-2.1/High quality高清修复.safetensors", "strength": 0.6, "note": ""},
        {"on": True, "file": "qwen-image-2.1/p_qwen_image_2.1_5step_v0.1.safetensors", "strength": 1, "note": ""},
    ], ensure_ascii=False)

    UNET, CLIP, VAE = "239", "240", "241"
    g = {
        UNET: {"class_type": "UNETLoader", "inputs": {
            "unet_name": "Qwen-Image-2.1\\rayQwen21编辑强化_turboV13Int8convrot.safetensors",
            "weight_dtype": "default"}},
        CLIP: {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen-image-2.1\\qwen3vl_8b_w4a8.safetensors",
            "type": "qwen_image", "device": "default"}},
        VAE: {"class_type": "VAELoader", "inputs": {
            "vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "278": {"class_type": "BanZhang_VRAM_Guard", "inputs": {
            "🔣 任意输入": [UNET, 0], "预留容量_GB": 0.2}},
        "244": {"class_type": "QwenImage21Cache", "inputs": {
            "model": ["278", 0], "device": "gpu", "dtype": "default"}},
        "249": {"class_type": "BanZhang_LoRA_VramSafe", "inputs": {
            "模型": ["244", 0], "LoRA配置": lora_cfg, "模型强度": "1.0"}},
        "246": {"class_type": "CSGlideH3MediaRackCS", "inputs": {"rack_data": rack_json}},
        "245": {"class_type": "CSGlideQwenCastCS", "inputs": {
            "clip": [CLIP, 0], "vae": [VAE, 0], "refs": ["246", 0],
            "qwen_data": qwen_json}},
        "243": {"class_type": "KSampler", "inputs": {
            "model": ["249", 0], "positive": ["245", 0], "negative": ["245", 1],
            "latent_image": ["245", 2], "seed": seed, "steps": 8, "cfg": 1.6,
            "sampler_name": "euler", "scheduler": "normal", "denoise": 1}},
        "242": {"class_type": "VAEDecode", "inputs": {"samples": ["243", 0], "vae": [VAE, 0]}},
        "248": {"class_type": "banzhangVideoCombine", "inputs": {
            "🖼️ 图像": ["242", 0], "⏱️ 帧率": 24, "📼 视频格式": "MP4 (H264/通用)",
            "🏷️ 文件前缀": prefix + "_1raw", "💾 保存元数据": True,
            "🔀 输出模式": "强制图片", "📂 自定义保存路径": ""}},
        "280": {"class_type": "BanZhang_ImageHiResUpscale", "inputs": {
            "图片": ["248", 0], "VAE": [VAE, 0],
            "放大模型": "OmniSR_X4_DIV2K.safetensors", "放大模式": "按倍数",
            "放大倍数": 1.5, "目标宽度": 2048, "目标高度": 2048, "兆像素": 2,
            "编码分块": "1024"}},
        "281": {"class_type": "KSampler", "inputs": {
            "model": ["249", 0], "positive": ["245", 0], "negative": ["245", 1],
            "latent_image": ["280", 0], "seed": seed, "steps": 3, "cfg": 1.1,
            "sampler_name": "euler", "scheduler": "normal", "denoise": 0.4}},
        "266": {"class_type": "VAEDecode", "inputs": {"samples": ["281", 0], "vae": [VAE, 0]}},
        "267": {"class_type": "banzhangVideoCombine", "inputs": {
            "🖼️ 图像": ["266", 0], "⏱️ 帧率": 24, "📼 视频格式": "MP4 (H264/通用)",
            "🏷️ 文件前缀": prefix, "💾 保存元数据": True,
            "🔀 输出模式": "强制图片", "📂 自定义保存路径": ""}},
    }
    return {"prompt": g, "client_id": "h3_asset_gen"}


def gen_one(a, name, prompt, refs, seed, canvas, prefix, timeout):
    w, h = canvas.lower().split("x")
    body = build_graph(name, prompt, "", refs, seed, int(w), int(h), prefix)
    r = http_json(API + "/prompt", body, timeout=60)
    pid = r.get("prompt_id")
    if not pid:
        print(f"[FAIL] {name} 提交失败:", json.dumps(r, ensure_ascii=False)[:500])
        return None
    print(f"[ok] {name} 已提交 prompt_id={pid} seed={seed} canvas={canvas}")

    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(10)
        try:
            hist = http_json(f"{API}/history/{pid}", timeout=20)
        except Exception as e:
            print(f"[wait] {name} {int(time.time()-t0)}s 轮询异常: {e}")
            continue
        if pid not in hist:
            q = http_json(API + "/queue", timeout=20)
            running = len(q.get("queue_running", [])) + len(q.get("queue_pending", []))
            print(f"[wait] {name} {int(time.time()-t0)}s 队列 {running}")
            if running == 0:
                print(f"[FAIL] {name} 队列已空但无结果（任务可能报错），查 ComfyUI 日志")
                return None
            continue
        item = hist[pid]
        status = item.get("status", {})
        if status.get("status_str") == "error":
            msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
            print(f"[FAIL] {name} 执行错误:", json.dumps(msgs, ensure_ascii=False)[:800])
            return None
        # ⚠️ 输出键是 painter_output（不是 images），两者都兜底
        outs = []
        for node_out in item.get("outputs", {}).values():
            for img in node_out.get("painter_output") or node_out.get("images") or []:
                sub = (img.get("subfolder") or "").strip("/\\")
                outs.append(f"{sub}/{img.get('filename')}" if sub else img.get("filename"))
        if outs:
            print(f"[DONE] {name}", json.dumps(outs, ensure_ascii=False))
            return outs
    print(f"[FAIL] {name} 超时")
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", help="资产名（=文件名=别名）")
    p.add_argument("--prompt")
    p.add_argument("--refs", default="", help="逗号分隔的参考图路径（ComfyUI input 相对路径）")
    p.add_argument("--seed", type=int, default=4254)
    p.add_argument("--canvas", default=DEFAULT_CANVAS)
    p.add_argument("--prefix", default="资产", help="输出文件前缀（建议 <项目>资产）")
    p.add_argument("--copy-to", dest="copy_to", default="",
                   help="成功后把成品拷贝为 <copy-to>/<name>.png（通常填 cglide/<项目> 绝对路径）")
    p.add_argument("--list", dest="list_file", default="",
                   help="批量清单 JSON（每项 name/prompt/refs/seed/canvas 可选）")
    p.add_argument("--timeout", type=int, default=1200)
    a = p.parse_args()

    if a.list_file:
        items = json.load(open(a.list_file, encoding="utf-8"))
    else:
        if not (a.name and a.prompt):
            p.error("单张模式需要 --name 和 --prompt（或用 --list 批量）")
        items = [{"name": a.name, "prompt": a.prompt,
                  "refs": [x for x in a.refs.split(",") if x.strip()],
                  "seed": a.seed, "canvas": a.canvas}]

    ok, fail = 0, 0
    for it in items:
        name = it["name"]
        outs = gen_one(a, name, it["prompt"], it.get("refs") or [],
                       int(it.get("seed", a.seed)), it.get("canvas", a.canvas),
                       a.prefix, a.timeout)
        if not outs:
            fail += 1
            continue
        if a.copy_to:
            src = f"{API_OUTPUT}/{outs[-1]}"
            dst = f"{a.copy_to.rstrip('/')}/{name}.png"
            try:
                shutil.copyfile(src, dst)
                print(f"[copy] {src} -> {dst}")
            except OSError as e:
                print(f"[FAIL] 拷贝失败 {src} -> {dst}: {e}")
                fail += 1
                continue
        ok += 1
    print(f"[summary] 成功 {ok} / 失败 {fail}")
    sys.exit(1 if fail else 0)


API_OUTPUT = os.environ.get("H3_OUTPUT_DIR", r"C:/AI/ComfyUI/output" if os.name == "nt" else os.path.expanduser("~/ComfyUI/output"))

if __name__ == "__main__":
    main()
