# -*- coding: utf-8 -*-
"""
短剧工业化 AI 管线 · 运行环境与模型就绪体检医生 (Environment & Asset Doctor)
Automated Readiness Verification Tool for Drama Production Pipeline
"""

import os
import sys
import shutil
import urllib.request
import urllib.error
import subprocess
from pathlib import Path

# 控制台 UTF-8 防御
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
COMFYUI_PATH = Path(os.environ.get("COMFYUI_PATH", r"C:\AI\ComfyUI" if os.name == "nt" else Path.home() / "ComfyUI"))
COMFY_HOST = os.environ.get("COMFYUI_HOST", "127.0.0.1:8188")


def print_banner():
    print("=" * 75)
    print("      🎬 短剧工业化 AI 管线 · 运行环境与资产就绪体检医生 (Environment Doctor)")
    print("=" * 75)


def check_python():
    v = sys.version_info
    v_str = f"{v.major}.{v.minor}.{v.micro}"
    if v.major == 3 and v.minor >= 10:
        return True, f"Python 版本: {v_str} (>= 3.10)"
    return False, f"Python 版本过低: {v_str} (需 >= 3.10)"


def check_cuda_and_torch():
    try:
        import torch
        if not torch.cuda.is_available():
            return False, "PyTorch 已安装，但未能检测到可用的 NVIDIA CUDA 环境！"
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        msg = f"PyTorch {torch.__version__} | GPU: {gpu_name} ({vram_gb:.1f} GB VRAM)"
        if vram_gb < 15.0:
            return "WARN", f"{msg} (显存低于 16GB，运行 int8 H3 容易发生 OOM 降速)"
        return True, msg
    except ImportError:
        return False, "未安装 PyTorch！请执行: pip install torch torchvision torchaudio"


def check_python_packages():
    missing = []
    for pkg in ["cv2", "spandrel", "numpy", "scipy", "requests", "tqdm", "PIL"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        return False, f"缺失必要 Python 包: {', '.join(missing)}。请执行: pip install -r requirements.txt"
    return True, "核心计算机视觉与推理依赖库已全部就绪 (OpenCV, Spandrel, Pillow, NumPy, SciPy)"


def check_ffmpeg():
    ffmpeg_bin = shutil.which("ffmpeg") or ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    try:
        res = subprocess.run([ffmpeg_bin, "-version"], capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return False, f"FFmpeg 存在但执行失败: {ffmpeg_bin}"
        version_line = res.stdout.splitlines()[0] if res.stdout else "FFmpeg 已识别"
        
        # 检查 sidechaincompress 滤镜
        res_filter = subprocess.run([ffmpeg_bin, "-filters"], capture_output=True, text=True, timeout=5)
        has_ducking = "sidechaincompress" in (res_filter.stdout or "")
        ducking_note = "支持侧链避让混音" if has_ducking else "警告: 滤镜库未找到 sidechaincompress"
        return True, f"{version_line} ({ducking_note})"
    except Exception as e:
        return False, f"未检测到 FFmpeg！请安装 FFmpeg 并将其加入系统环境变量 PATH ({e})"


def check_comfyui_service():
    url = f"http://{COMFY_HOST}/system_stats"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DramaEnvDoctor/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                return True, f"ComfyUI 服务联通正常 (http://{COMFY_HOST})"
    except Exception:
        pass
    return "WARN", f"ComfyUI 离线或端口未响应 (http://{COMFY_HOST})。请参考 MODELS.md 启动服务"


def check_model_assets():
    if not COMFYUI_PATH.exists():
        return "WARN", f"未找到 ComfyUI 根目录: {COMFYUI_PATH} (可通过环境变量 COMFYUI_PATH 指定)"

    clip_path = COMFYUI_PATH / "models" / "clip" / "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
    if not clip_path.exists():
        alt_clip = COMFYUI_PATH / "models" / "text_encoders" / "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
        if alt_clip.exists():
            clip_path = alt_clip

    checks = {
        "H3 UNet 模型": COMFYUI_PATH / "models" / "diffusion_models" / "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
        "Qwen3VL 编码器": clip_path,
        "RealESRGAN 超分模型": COMFYUI_PATH / "models" / "upscale_models" / "RealESRGAN_x2plus.pth"
    }

    missing = []
    ready = []
    for name, p in checks.items():
        if p.exists() and p.stat().st_size > 1024 * 1024:
            size_mb = p.stat().st_size / (1024 * 1024)
            ready.append(f"{name} ({size_mb:.1f}MB)")
        else:
            missing.append(f"{name} (缺失路径: {p.relative_to(COMFYUI_PATH)})")

    if not missing:
        return True, f"ComfyUI 核心模型全部就绪: {', '.join(ready)}"
    elif len(ready) > 0:
        return "WARN", f"部分模型已就绪，但仍有缺失: {'; '.join(missing)}。请对照 MODELS.md 补充下载"
    else:
        return "WARN", f"ComfyUI 模型仓为空，请对照 MODELS.md 下载所需模型文件"


def check_repo_assets():
    bgm = REPO_ROOT / "assets" / "bgm" / "90s_business_suspense.wav"
    wf1 = REPO_ROOT / "workflows" / "MiniMax_H3_Ref2VA_Standard.json"
    wf2 = REPO_ROOT / "workflows" / "H3-FaceRefine-远景修脸-固定工作流.json"
    
    missing = []
    if not bgm.exists():
        missing.append("默认 BGM 资产 (assets/bgm/90s_business_suspense.wav)")
    if not wf1.exists():
        missing.append("H3 标准工作流模板 (workflows/MiniMax_H3_Ref2VA_Standard.json)")
    if not wf2.exists():
        missing.append("远景修脸工作流模板 (workflows/H3-FaceRefine-远景修脸-固定工作流.json)")
        
    if not missing:
        return True, "项目内置 BGM 音轨与 ComfyUI 工作流模板完整校验通过"
    return False, f"仓库内置资产缺失: {', '.join(missing)}"


def main():
    print_banner()
    checks = [
        ("1. Python 解释器环境", check_python),
        ("2. NVIDIA CUDA & 显卡显存", check_cuda_and_torch),
        ("3. 核心计算机视觉与推理依赖", check_python_packages),
        ("4. FFmpeg 多媒体与侧链音频引擎", check_ffmpeg),
        ("5. ComfyUI 运行端口联通状态", check_comfyui_service),
        ("6. MiniMax H3 与超分物理模型资产", check_model_assets),
        ("7. 仓库核心工作流与原生音轨资产", check_repo_assets)
    ]

    all_pass = True
    has_warn = False

    for title, func in checks:
        status, desc = func()
        if status is True:
            badge = "[PASS]"
        elif status == "WARN":
            badge = "[WARN]"
            has_warn = True
        else:
            badge = "[FAIL]"
            all_pass = False
        print(f"{badge:<8} {title:<28} : {desc}")

    print("=" * 75)
    if all_pass and not has_warn:
        print("🎯 诊断结论: 您的本地环境与模型资产已 100% 完整就绪！")
        print("   随时可以执行 scripts/run_episodes_1_to_10_master.py 或使用技能开启工业化出片。")
    elif all_pass and has_warn:
        print("⚠️ 诊断结论: 核心基础工具链已就绪，但存在警告项（如模型未完全放齐或 ComfyUI 服务暂未启动）。")
        print("   这不会影响分镜编剧、台词归一化等前序工序；请启动 ComfyUI 并查阅 MODELS.md 补全模型后出片。")
    else:
        print("❌ 诊断结论: 检测到缺失核心硬依赖（如 Python 依赖或 FFmpeg 未安装）。")
        print("   请按照上述 [FAIL] 提示进行排查安装后重新体检。")
    print("=" * 75)


if __name__ == "__main__":
    main()
