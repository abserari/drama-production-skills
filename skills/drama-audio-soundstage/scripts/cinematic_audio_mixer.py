# -*- coding: utf-8 -*-
"""
影视级短剧配乐智能避让混音引擎 (Cinematic Audio Mixer with Audio Ducking)
基于 FFmpeg 原生 sidechaincompress (侧链压制) 算法：
- 自动为短剧铺设专业商战/年代剧 BGM
- 人声智能避让 (Audio Ducking)：当主角/反派开口说台词时，BGM 瞬时下潜 -14dB (衰减至 20%)，台词字字清晰；
- 间隙自然扬起：台词结束或进入紧张动作戏时，BGM 在 0.3-0.5s 内平滑恢复满电平，情绪瞬间拉满！
- 视频流物理直通 (-c:v copy)，秒级极速成片，画质零损耗。
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

# Windows UTF-8 控制台防御
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE_ROOT = Path(os.environ.get("DRAMA_WORKSPACE", Path.cwd()))
DEFAULT_BGM = Path(os.environ.get("DEFAULT_BGM", WORKSPACE_ROOT / "assets" / "bgm" / "90s_business_suspense.wav"))

# 寻找 FFmpeg
try:
    from paths import FFMPEG as FF
except Exception:
    FF = shutil.which("ffmpeg") or "ffmpeg"
    if not os.path.exists(FF):
        FF = "ffmpeg"


def apply_cinematic_ducking(
    input_video: Path,
    bgm_path: Path,
    output_video: Path,
    bgm_volume: float = 0.35,
    ducking_threshold: float = 0.08,
    ducking_ratio: float = 8.0,
    ducking_attack_ms: int = 20,
    ducking_release_ms: int = 400
) -> bool:
    """PROJECT.md 契约接口：影视级侧链动态避让混音"""
    return mix_video_with_ducked_bgm(
        input_video=Path(input_video),
        output_video=Path(output_video),
        bgm_path=Path(bgm_path),
        bgm_volume=bgm_volume,
        ducking_threshold=ducking_threshold,
        ducking_ratio=ducking_ratio,
        ducking_attack_ms=ducking_attack_ms,
        ducking_release_ms=ducking_release_ms
    )


def mix_video_with_ducked_bgm(
    input_video: Path,
    output_video: Path,
    bgm_path: Path = DEFAULT_BGM,
    bgm_volume: float = 0.35,
    ducking_threshold: float = 0.06,
    ducking_ratio: float = 5.0,
    ducking_attack_ms: int = 80,
    ducking_release_ms: int = 400
) -> bool:
    """
    将视频原音轨（对白+拟音）与 BGM 进行侧链动态压制混音
    """
    if not input_video.exists():
        print(f"[错误] 输入视频不存在: {input_video}")
        return False
    if not bgm_path.exists():
        print(f"[错误] BGM 音频不存在: {bgm_path}")
        return False

    output_video.parent.mkdir(parents=True, exist_ok=True)

    # 复杂音频滤镜链:
    # 1. BGM 无限循环且截取与视频相同长度
    # 2. 调整 BGM 基础增益
    # 3. 采用原视频人声对 BGM 进行侧链压制 (Sidechain Compression)
    # 4. 混合人声音轨与避让后的 BGM
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

    print(f"\n[混音引擎] 正在执行影视级商战 BGM 混音与人声避让...")
    print(f"  - 原片输入: {input_video.name}")
    print(f"  - BGM 配乐: {bgm_path.name} (基准音量: {bgm_volume * 100:.0f}%)")
    print(f"  - 避让参数: 触发阈值={ducking_threshold}, 压制比={ducking_ratio}:1, 启动={ducking_attack_ms}ms, 恢复={ducking_release_ms}ms")

    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode == 0 and output_video.exists():
        print(f"[成功] 混音完成 -> {output_video.name} ({output_video.stat().st_size / (1024*1024):.2f} MB)")
        return True
    else:
        print(f"[失败] FFmpeg 混音异常退出 (code {res.returncode}):")
        print(res.stderr[-500:])
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="影视级短剧配乐智能避让混音引擎")
    parser.add_argument("--input", required=True, type=Path, help="输入源视频 mp4")
    parser.add_argument("--output", required=True, type=Path, help="输出混音视频 mp4")
    parser.add_argument("--bgm", type=Path, default=DEFAULT_BGM, help="BGM 音频文件路径")
    parser.add_argument("--volume", type=float, default=0.35, help="BGM 基础音量比例 (默认 0.35)")
    args = parser.parse_args()

    success = mix_video_with_ducked_bgm(args.input, args.output, args.bgm, args.volume)
    sys.exit(0 if success else 1)
