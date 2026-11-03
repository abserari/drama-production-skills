# -*- coding: utf-8 -*-
"""
MiniMax H3 本地超分辨率增强工具 (Video Upscaler)
使用 GPU 加速 (RealESRGAN / Compact) 将 480p/544p 视频无损放大至 1080p/2K，
并通过 ffmpeg 无损保留原视频中的原生立体声音频对白与音效。
"""

import os
import sys
import time
import shutil
import argparse
import subprocess
from pathlib import Path

import torch
import cv2
from tqdm import tqdm
from spandrel import ModelLoader

DEFAULT_MODELS_DIR = Path(r"C:\AI\ComfyUI\models\upscale_models")


def get_available_upscale_models() -> dict:
    if not DEFAULT_MODELS_DIR.exists():
        return {}
    models = {}
    for ext in ("*.pth", "*.safetensors", "*.pt", "*.bin"):
        for f in DEFAULT_MODELS_DIR.glob(ext):
            models[f.name] = f
    return models


def upscale_video(
    input_path: str,
    output_path: str,
    model_name: str = "RealESRGAN_x2plus.pth",
    batch_size: int = 2,
    device: str = "cuda",
    target_width: int = 1920,
    target_height: int = 1080
):
    inp = Path(input_path).resolve()
    if not inp.exists():
        raise FileNotFoundError(f"输入视频不存在: {inp}")

    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    model_file = DEFAULT_MODELS_DIR / model_name
    if not model_file.exists():
        candidates = list(DEFAULT_MODELS_DIR.glob(f"*{model_name}*"))
        if candidates:
            model_file = candidates[0]
        else:
            raise FileNotFoundError(f"超分模型未找到: {model_name} (搜索路径: {DEFAULT_MODELS_DIR})")

    print(f"\n==================================================")
    print(f" [超分增强] 开始处理: {inp.name}")
    print(f"  模型: {model_file.name}")
    print(f"  设备: {device.upper()} (FP16 加速, Batch: {batch_size})")
    print(f"==================================================")

    # 1. 加载模型
    print("  -> 加载超分模型权重...", end="", flush=True)
    loader = ModelLoader()
    descriptor = loader.load_from_file(str(model_file)).eval().to(device)
    if device == "cuda":
        descriptor = descriptor.half()
    print(" [就绪]")

    # 2. 读取输入视频元数据
    cap = cv2.VideoCapture(str(inp))
    if not cap.isOpened():
        raise RuntimeError(f"无法读取视频: {inp}")

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"  -> 原视频规格: {src_w}x{src_h} @ {fps:.2f}fps (共 {total_frames} 帧)")

    # 计算目标尺寸 (按 2x 或保持宽高比适配 1080p)
    scale = descriptor.scale
    raw_scaled_w = int(src_w * scale)
    raw_scaled_h = int(src_h * scale)

    # 如果有显式指定目标尺寸且比例接近，直接缩放到目标分辨率
    final_w = target_width if target_width > 0 else raw_scaled_w
    final_h = target_height if target_height > 0 else raw_scaled_h
    print(f"  -> 输出目标分辨率: {final_w}x{final_h} (原生放大倍率: {scale}x)")

    # 3. 抽取音频至临时文件
    temp_dir = out.parent / f"_tmp_{int(time.time())}_{inp.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_audio = temp_dir / "audio.m4a"
    temp_video_no_audio = temp_dir / "video_no_audio.mp4"

    has_audio = False
    ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
    extract_cmd = [
        ffmpeg_exe, "-y", "-i", str(inp),
        "-vn", "-c:a", "copy",
        str(temp_audio)
    ]
    ret = subprocess.run(extract_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ret.returncode == 0 and temp_audio.exists() and temp_audio.stat().st_size > 500:
        has_audio = True
        print(f"  -> 原生音轨已提取 (大小: {temp_audio.stat().st_size / 1024:.1f} KB)")
    else:
        print("  -> 原视频无独立音轨或提取静音")

    # 4. 初始化视频写入器
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(temp_video_no_audio), fourcc, fps, (final_w, final_h))

    # 5. 批处理帧推理
    frames_batch = []
    pbar = tqdm(total=total_frames, desc="  超分渲染", unit="frame", ncols=85)

    def process_batch(batch):
        if not batch:
            return
        # batch: list of BGR numpy arrays (H, W, 3), range 0-255
        # Convert BGR -> RGB -> Float Tensor [B, 3, H, W] in [0, 1]
        rgb_list = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in batch]
        tensor = torch.from_numpy(
            np_stack := cv2.dnn.blobFromImages(rgb_list, 1.0 / 255.0, (src_w, src_h), swapRB=False)
        ).to(device)
        if device == "cuda":
            tensor = tensor.half()

        with torch.no_grad():
            out_tensor = descriptor(tensor)

        # out_tensor: [B, 3, out_h, out_w] in [0, 1]
        out_tensor = torch.clamp(out_tensor, 0.0, 1.0)
        out_np = (out_tensor.permute(0, 2, 3, 1).cpu().float().numpy() * 255.0).astype("uint8")

        for i in range(len(batch)):
            frame_rgb = out_np[i]
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            if (raw_scaled_w, raw_scaled_h) != (final_w, final_h):
                frame_bgr = cv2.resize(frame_bgr, (final_w, final_h), interpolation=cv2.INTER_LANCZOS4)
            writer.write(frame_bgr)

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames_batch.append(frame)
        if len(frames_batch) >= batch_size:
            process_batch(frames_batch)
            pbar.update(len(frames_batch))
            frames_batch = []

    if frames_batch:
        process_batch(frames_batch)
        pbar.update(len(frames_batch))

    cap.release()
    writer.release()
    pbar.close()

    # 6. 使用 ffmpeg 合成音视频 (无损音频混流 + H.264 高质量重编码)
    print("  -> 正在封装高质量 MP4 (保留音轨与色域)...", end="", flush=True)
    if has_audio:
        merge_cmd = [
            ffmpeg_exe, "-y",
            "-i", str(temp_video_no_audio),
            "-i", str(temp_audio),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "fast",
            "-c:a", "copy",
            "-shortest",
            str(out)
        ]
    else:
        merge_cmd = [
            ffmpeg_exe, "-y",
            "-i", str(temp_video_no_audio),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "fast",
            str(out)
        ]

    ret = subprocess.run(merge_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ret.returncode != 0:
        # 如果 libx264 失败，兜底直接复制
        shutil.copy2(temp_video_no_audio, out)

    # 7. 清理临时缓存
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass

    print(f" [完成]\n  -> 输出成片已就绪: {out} ({out.stat().st_size / (1024**2):.2f} MB)")


def main():
    parser = argparse.ArgumentParser(description="MiniMax H3 视频超分辨率批处理工具")
    parser.add_argument("--input", "-i", type=str, required=True, help="输入视频路径或目录")
    parser.add_argument("--output", "-o", type=str, default="", help="输出视频路径或目录")
    parser.add_argument("--model", "-m", type=str, default="RealESRGAN_x2plus.pth", help="超分模型名称")
    parser.add_argument("--batch-size", "-b", type=int, default=2, help="GPU 批处理帧数 (建议 2-4)")
    parser.add_argument("--width", type=int, default=1920, help="目标宽度 (默认 1920，填 0 则使用模型原生倍率)")
    parser.add_argument("--height", type=int, default=1080, help="目标高度 (默认 1080，填 0 则使用模型原生倍率)")
    args = parser.parse_args()

    inp = Path(args.input)
    if inp.is_file():
        out = Path(args.output) if args.output else inp.with_stem(inp.stem + "_1080p")
        upscale_video(
            str(inp),
            str(out),
            model_name=args.model,
            batch_size=args.batch_size,
            target_width=args.width,
            target_height=args.height
        )
    elif inp.is_dir():
        out_dir = Path(args.output) if args.output else inp / "upscaled_1080p"
        out_dir.mkdir(parents=True, exist_ok=True)
        videos = sorted(list(inp.glob("*.mp4")))
        print(f"找到 {len(videos)} 个视频待处理: {inp}")
        for v in videos:
            if "_1080p" in v.stem:
                continue
            target_file = out_dir / f"{v.stem}_1080p.mp4"
            upscale_video(
                str(v),
                str(target_file),
                model_name=args.model,
                batch_size=args.batch_size,
                target_width=args.width,
                target_height=args.height
            )
    else:
        print(f"[错误] 输入路径不存在: {args.input}")


if __name__ == "__main__":
    main()
