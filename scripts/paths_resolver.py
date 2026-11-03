# -*- coding: utf-8 -*-
"""
短剧工业化管线跨平台路径与环境自适应解析器
Universal Cross-Platform Path & Environment Resolver for Drama Production Pipeline
"""

import os
import shutil
from pathlib import Path

# 1. 动态自适应探测工作区根目录
# 优先从环境变量 DRAMA_WORKSPACE 取；若未设置，则根据当前脚本所在目录向上自适应推断
SCRIPT_DIR = Path(__file__).resolve().parent
if SCRIPT_DIR.name == "scripts":
    REPO_ROOT = SCRIPT_DIR.parent
else:
    REPO_ROOT = SCRIPT_DIR

WORKSPACE_ROOT = Path(os.environ.get("DRAMA_WORKSPACE", REPO_ROOT)).resolve()
DELIVERY_DIR = WORKSPACE_ROOT / "成片交付"
EPISODES_ROOT = WORKSPACE_ROOT / "分集工程"
ASSETS_DIR = WORKSPACE_ROOT / "assets"
DEFAULT_BGM = ASSETS_DIR / "bgm" / "90s_business_suspense.wav"

# 2. 动态自适应探测 ComfyUI 根目录
# 优先从环境变量 COMFYUI_PATH 取；若未设置，则检测常见系统默认路径
DEFAULT_COMFY_PATHS = [
    Path(r"C:\AI\ComfyUI"),
    Path(r"D:\AI\ComfyUI"),
    Path(os.path.expanduser("~/ComfyUI")),
    Path("/opt/ComfyUI")
]
COMFYUI_ROOT = None
if "COMFYUI_PATH" in os.environ:
    COMFYUI_ROOT = Path(os.environ["COMFYUI_PATH"]).resolve()
else:
    for candidate in DEFAULT_COMFY_PATHS:
        if candidate.exists():
            COMFYUI_ROOT = candidate
            break

if not COMFYUI_ROOT:
    COMFYUI_ROOT = Path(r"C:\AI\ComfyUI") if os.name == "nt" else Path(os.path.expanduser("~/ComfyUI"))

COMFYUI_INPUT_DIR = COMFYUI_ROOT / "input"
COMFYUI_OUTPUT_DIR = COMFYUI_ROOT / "output"
COMFYUI_MODELS_DIR = COMFYUI_ROOT / "models"
UPSCALE_MODELS_DIR = COMFYUI_MODELS_DIR / "upscale_models"

# 3. 动态探测系统 FFmpeg 与 FFprobe
FFMPEG = shutil.which("ffmpeg") or ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
FFPROBE = shutil.which("ffprobe") or ("ffprobe.exe" if os.name == "nt" else "ffprobe")

# 4. 默认服务端口
COMFY_HOST = os.environ.get("COMFYUI_HOST", "127.0.0.1:8188")
