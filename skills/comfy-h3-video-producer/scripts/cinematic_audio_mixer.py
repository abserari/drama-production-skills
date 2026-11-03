# -*- coding: utf-8 -*-
"""
影视级短剧配乐智能避让混音引擎 (Cinematic Audio Mixer with Audio Ducking)
遵循 §13 纪律：纯机制代码，不含项目专属路径与名称。

核心原理：
1. 彻底解决短剧“只有干音无配乐”或“BGM盖过对白”的工业痛点；
2. 基于 FFmpeg 原生 sidechaincompress (侧链动态压缩) 滤镜；
3. 人声对白自动避让 (Audio Ducking)：
   - 当主角/人物开口说话时，BGM 瞬时下潜 -14dB (衰减至约 20%)，台词字字清晰；
   - 台词间隙或紧张动作戏份时，BGM 在 0.3-0.5s 内平滑回升至满电平，影视张力拉满！
4. 视频流物理直通 (-c:v copy)，秒级混音，画质无任何次级编码损失。
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")

# 优先从本技能环境获取经过验证的 ffmpeg 路径
try:
    from paths import FFMPEG as FF
except Exception:
    FF = "ffmpeg"


def mix_video_with_ducked_bgm(
    input_video: Path,
    output_video: Path,
    bgm_path: Path,
    bgm_volume: float = 0.35,
    ducking_threshold: float = 0.06,
    ducking_ratio: float = 5.0,
    ducking_attack_ms: int = 80,
    ducking_release_ms: int = 400
) -> bool:
    """
    将视频原音轨（对白+拟音）与指定 BGM 进行侧链动态压制混音
    """
    input_video = Path(input_video)
    output_video = Path(output_video)
    bgm_path = Path(bgm_path)

    if not input_video.exists():
        print(f"[错误] 输入视频不存在: {input_video}")
        return False
    if not bgm_path.exists():
        print(f"[错误] BGM 音频文件不存在: {bgm_path}")
        return False

    output_video.parent.mkdir(parents=True, exist_ok=True)

    # 复杂音频滤镜链:
    # 1. BGM 无限循环并自适应切齐视频时长: aloop=loop=-1:size=2e+09
    # 2. 基础音量比例调整: volume={bgm_volume}
    # 3. 采用原视频人声音轨 [0:a] 对 BGM 进行侧链压制 (Sidechain Compression)
    # 4. 混合人声音轨与避让后的 BGM: amix
    filter_complex = (
        f"[1:a]aloop=loop=-1:size=2e+09,volume={bgm_volume}[bgm_raw];"
        f"[bgm_raw][0:a]sidechaincompress=threshold={ducking_threshold}:"
        f"ratio={ducking_ratio}:attack={ducking_attack_ms}:release={ducking_release_ms}[ducked_bgm];"
        f"[0:a][ducked_bgm]amix=inputs=2:duration=first:dropout_transition=2:weights=1.0 1.0[out_a]"
    )

    cmd = [
        str(FF), "-y",
        "-i", str(input_video),
        "-i", str(bgm_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[out_a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "256k",
        str(output_video)
    ]

    print(f"\n[混音引擎] 正在执行影视级 BGM 混音与人声避让...")
    print(f"  - 原视频: {input_video.name}")
    print(f"  - 配乐轨: {bgm_path.name} (基准音量: {bgm_volume * 100:.0f}%)")
    print(f"  - 避让参数: 阈值={ducking_threshold}, 压缩比={ducking_ratio}:1, 启动={ducking_attack_ms}ms, 恢复={ducking_release_ms}ms")

    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode == 0 and output_video.exists():
        print(f"[成功] 混音交付完成 -> {output_video.name} ({output_video.stat().st_size / (1024*1024):.2f} MB)")
        return True
    else:
        print(f"[失败] FFmpeg 混音异常退出 (code {res.returncode}):")
        if res.stderr:
            print(res.stderr[-500:])
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="影视级短剧配乐智能避让混音引擎")
    parser.add_argument("--input", required=True, type=Path, help="输入源视频 mp4")
    parser.add_argument("--output", required=True, type=Path, help="输出混音视频 mp4")
    parser.add_argument("--bgm", required=True, type=Path, help="BGM 音频文件路径")
    parser.add_argument("--volume", type=float, default=0.35, help="BGM 基础音量比例 (默认 0.35)")
    parser.add_argument("--threshold", type=float, default=0.06, help="侧链避让触发阈值 (默认 0.06)")
    parser.add_argument("--ratio", type=float, default=5.0, help="侧链压缩比 (默认 5.0:1)")
    args = parser.parse_args()

    success = mix_video_with_ducked_bgm(
        args.input,
        args.output,
        args.bgm,
        bgm_volume=args.volume,
        ducking_threshold=args.threshold,
        ducking_ratio=args.ratio
    )
    sys.exit(0 if success else 1)
