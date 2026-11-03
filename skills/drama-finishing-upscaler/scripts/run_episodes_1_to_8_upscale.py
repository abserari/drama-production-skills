# -*- coding: utf-8 -*-
"""
《欺诈之地》前 8 集（EP01~EP08）RealESRGAN 1080p 工业级超分辨率批量增强调度器
Batch 1080p Upscaler for Episodes 1 to 8
"""

import os
import sys
import time
import json
import shutil
import subprocess
from pathlib import Path

# Windows 控制台编码保护
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE_ROOT = Path(r"c:\Users\34903\Documents\短剧试做")
DELIVERY_DIR = WORKSPACE_ROOT / "欺诈之地_全十集_成片交付"
SCRIPTS_DIR = WORKSPACE_ROOT / "scripts"
FFPROBE_EXE = r"C:\Users\34903\scoop\shims\ffprobe.exe"
FFMPEG_EXE = r"C:\Users\34903\scoop\shims\ffmpeg.exe"

# 推入 scripts 目录
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from upscale_video import upscale_video
except ImportError:
    upscale_video = None


def verify_1080p_video(video_path: Path) -> dict:
    """使用 ffprobe 严谨校验输出成片的分辨率、时长与音画流"""
    if not video_path.exists() or video_path.stat().st_size < 1024 * 1024:
        return {"valid": False, "reason": "文件不存在或小于 1MB"}

    cmd = [
        FFPROBE_EXE, "-v", "error",
        "-show_entries", "format=duration,size:stream=width,height,codec_name,r_frame_rate",
        "-of", "json", str(video_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if res.returncode != 0:
        return {"valid": False, "reason": f"ffprobe 校验失败: {res.stderr}"}

    try:
        data = json.loads(res.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        streams = data.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_name") in ["h264", "hevc", "mp4v"]), {})
        a_stream = next((s for s in streams if s.get("codec_name") in ["aac", "mp3", "pcm_s16le"]), {})

        width = v_stream.get("width")
        height = v_stream.get("height")
        fps = v_stream.get("r_frame_rate")
        has_audio = bool(a_stream)

        is_1080p = (width == 1920 and height == 1080)
        is_valid = is_1080p and duration > 50.0 and has_audio

        return {
            "valid": is_valid,
            "width": width,
            "height": height,
            "fps": fps,
            "duration": duration,
            "size_mb": video_path.stat().st_size / 1024 / 1024,
            "has_audio": has_audio,
            "audio_codec": a_stream.get("codec_name", "none")
        }
    except Exception as e:
        return {"valid": False, "reason": f"解析元数据异常: {e}"}


def run_batch_upscale(episodes: list = None, force: bool = False, batch_size: int = 4):
    """批量执行前 8 集 1080p 超分主循环"""
    if not upscale_video:
        raise ImportError("未能导入 upscale_video 模块！")

    if not episodes:
        episodes = [f"EP{i:02d}" for i in range(1, 9)]

    DELIVERY_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print(" 《欺诈之地》前 8 集 (EP01~EP08) RealESRGAN 1080p 院线级超分流水线")
    print(f" 目标集数: {episodes} | GPU 批大小: {batch_size} (RTX 4080 FP16 全速独占)")
    print(f" 交付目录: {DELIVERY_DIR}")
    print("=" * 70)

    # 扫描交付目录中所有的原画商业版文件
    raw_files = list(DELIVERY_DIR.glob("*原画商业版*.mp4"))

    overall_start = time.time()
    results = []

    for ep_code in episodes:
        # 寻找匹配的原画视频
        matching_raw = [f for f in raw_files if ep_code.lower() in f.name.lower()]
        if not matching_raw:
            print(f"\n[跳过] 未在交付目录找到 {ep_code} 的原画商业版成片！")
            continue

        raw_video = matching_raw[0]
        # 构造目标 1080p 成片路径
        target_name = raw_video.name.replace("原画商业版", "1080p")
        if target_name == raw_video.name:
            target_name = f"{raw_video.stem}_1080p.mp4"
        out_1080p = DELIVERY_DIR / target_name

        print(f"\n{'-' * 70}")
        print(f" >>> [处理中] {ep_code}: {raw_video.name}")
        print(f"     目标产物: {out_1080p.name}")
        print(f"{'-' * 70}")

        # 检查是否已完成
        if not force:
            v_check = verify_1080p_video(out_1080p)
            if v_check.get("valid"):
                print(f"  [复用] {out_1080p.name} 已存在且符合 1920x1080 规范，跳过！")
                results.append((ep_code, True, 0.0, v_check))
                continue

        t0 = time.time()
        try:
            upscale_video(
                input_path=str(raw_video),
                output_path=str(out_1080p),
                model_name="RealESRGAN_x2plus.pth",
                batch_size=batch_size,
                device="cuda",
                target_width=1920,
                target_height=1080
            )
            elapsed = time.time() - t0
            v_info = verify_1080p_video(out_1080p)
            if v_info.get("valid"):
                print(f"  [成功] {ep_code} 超分完成！耗时: {elapsed:.1f}s | 大小: {v_info['size_mb']:.2f} MB")
                results.append((ep_code, True, elapsed, v_info))
            else:
                print(f"  [警告] {ep_code} 产物校验未达标: {v_info.get('reason')}")
                results.append((ep_code, False, elapsed, v_info))
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  [失败] {ep_code} 超分报错: {e}")
            results.append((ep_code, False, elapsed, {"error": str(e)}))

    # 输出汇总报告
    total_elapsed = time.time() - overall_start
    print("\n" + "=" * 70)
    print(f" 前 8 集 1080p 超分增强全流程结束！累计耗时: {total_elapsed:.1f}s")
    print("=" * 70)
    for ep, ok, dur, meta in results:
        status_str = "SUCCESS [✓]" if ok else "FAILED [X]"
        meta_str = f"{meta.get('width')}x{meta.get('height')} @ {meta.get('fps')} ({meta.get('size_mb', 0):.2f}MB)" if ok else str(meta)
        print(f"  - {ep}: {status_str} | 耗时: {dur:.1f}s | {meta_str}")
    print("=" * 70)


if __name__ == "__main__":
    force_run = "--force" in sys.argv
    run_batch_upscale(force=force_run)
