# -*- coding: utf-8 -*-
"""
MiniMax H3 执行图构建与物理调度器 (H3 Render Orchestrator)
"""

import os
import sys
import json
import uuid
import time
import urllib.request
from pathlib import Path
from typing import Optional

COMFY_HOST = "127.0.0.1:8188"
COMFYUI_OUTPUT_ROOT = Path(os.environ.get("COMFYUI_PATH", r"C:\AI\ComfyUI")) / "output"


def build_h3_prompt_graph(
    prompt_text: str,
    width: int = 832,
    height: int = 480,
    length: int = 175,
    seed: int = 42,
    output_prefix: str = "griftlands/seg01",
    model_type: str = "fl2va",
    first_frame_filename: Optional[str] = None
) -> dict:
    """构建 MiniMax H3 原生执行图 (32整除防御与 I2V 首帧挂载)"""
    # Explicit exceptions remain active under python -O. These are this template's
    # constraints, not universal requirements for every video model.
    for label, value, divisor in (("width", width, 32), ("height", height, 32)):
        if type(value) is not int or value <= 0 or value % divisor:
            raise ValueError(f"{label} must be a positive integer divisible by {divisor}")
    if type(length) is not int or length <= 0:
        raise ValueError("length must be a positive integer")
    if model_type not in {"ref2va", "fl2va"}:
        raise ValueError("model_type must be ref2va or fl2va")
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ValueError("prompt_text must be non-empty text")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    if model_type == "ref2va":
        raise ValueError("This I2V builder uses FL2VA; full-reference mode requires a verified Ref2VA workflow")

    unet_file = (
        "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
        if model_type == "ref2va"
        else "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    )

    node_6_inputs = {
        "clip": ["2", 0],
        "vae": ["3", 0],
        "prompt": prompt_text,
        "width": int(width),
        "height": int(height),
        "length": int(length)
    }

    graph = {
        "1": {"inputs": {"unet_name": unet_file, "weight_dtype": "default"}, "class_type": "UNETLoader"},
        "2": {"inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax"}, "class_type": "CLIPLoader"},
        "3": {"inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}, "class_type": "VAELoader"},
        "4": {"inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}, "class_type": "VAELoader"},
        "5": {"inputs": {"lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", "strength_model": 1.0, "model": ["1", 0]}, "class_type": "LoraLoaderModelOnly"},
        "6": {"inputs": node_6_inputs, "class_type": "MiniMaxH3ImageToVideo"},
        "7": {"inputs": {"model": ["5", 0], "conditioning": ["6", 0]}, "class_type": "BasicGuider"},
        "8": {"inputs": {"sampler_name": "res_multistep"}, "class_type": "KSamplerSelect"},
        "9": {"inputs": {"scheduler": "simple", "steps": 8, "denoise": 1.0, "model": ["5", 0]}, "class_type": "BasicScheduler"},
        "10": {"inputs": {"noise_seed": int(seed)}, "class_type": "RandomNoise"},
        "11": {"inputs": {"noise": ["10", 0], "guider": ["7", 0], "sampler": ["8", 0], "sigmas": ["9", 0], "latent_image": ["6", 1]}, "class_type": "SamplerCustomAdvanced"},
        "12": {"inputs": {"samples": ["11", 0], "vae": ["3", 0]}, "class_type": "VAEDecode"},
        "13": {"inputs": {"samples": ["11", 0], "vae": ["4", 0]}, "class_type": "VAEDecodeAudio"},
        "14": {"inputs": {"images": ["12", 0], "audio": ["13", 0], "fps": 24.0, "bit_depth": 8, "color_space": "sRGB"}, "class_type": "CreateVideo"},
        "15": {"inputs": {"video": ["14", 0], "filename_prefix": output_prefix, "format": "mp4", "format.codec": "h264", "format.codec.encoding": "auto"}, "class_type": "SaveVideo"}
    }

    if first_frame_filename:
        graph["20"] = {"inputs": {"image": str(first_frame_filename)}, "class_type": "LoadImage"}
        node_6_inputs["first_frame"] = ["20", 0]

    return graph


def free_vram(server: str = COMFY_HOST):
    """显存快速清空防碎片"""
    url = f"http://{server}/free"
    payload = {"unload_models": False, "free_memory": True}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception:
        pass
