# -*- coding: utf-8 -*-
"""旧批量入口：仅保留离线静态检查；生产请使用 H3 skill 的受检 SOP。"""

import os
import re
import sys
import json
import time
import uuid
import shutil
import argparse
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Windows 控制台编码防护
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 路径常量定义
WORKSPACE_ROOT = Path(os.environ.get("DRAMA_WORKSPACE", Path.cwd()))
EPISODES_ROOT = WORKSPACE_ROOT / "欺诈之地_全十集"
DELIVERY_DIR = WORKSPACE_ROOT / "欺诈之地_全十集_成片交付"
COMFYUI_OUTPUT_ROOT = Path(os.environ.get("COMFYUI_PATH", r"C:\AI\ComfyUI")) / "output"

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_SCRIPTS = SCRIPTS_DIR.parent / "skills" / "comfy-h3-video-producer" / "scripts"

# 将相关脚本路径推入 sys.path
for p in [str(SKILL_SCRIPTS), str(SCRIPTS_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# 导入核心子模块
try:
    from keyframe_gate import get_keyframe_for_segment, sync_keyframe_to_comfyui, apply_keyframe_to_graph
except ImportError as exc:
    raise ImportError("首帧工具不可用，请修复技能安装，不能静默关闭首帧检查") from exc

try:
    from face_refine_pipeline import should_refine_segment, run_face_refine_on_video
except ImportError as exc:
    raise ImportError("修脸工具不可用，请修复技能安装") from exc

try:
    from cinematic_audio_mixer import mix_video_with_ducked_bgm, DEFAULT_BGM
except ImportError as exc:
    raise ImportError("混音工具不可用，请修复技能安装") from exc

# 寻找 FFmpeg
try:
    from paths import FFMPEG as FF, FFPROBE
except Exception:
    FF = shutil.which("ffmpeg") or "ffmpeg"
    if not os.path.exists(FF):
        FF = "ffmpeg"
    FFPROBE = shutil.which("ffprobe") or "ffprobe"
    if not os.path.exists(FFPROBE):
        FFPROBE = "ffprobe"

COMFY_HOST = "127.0.0.1:8188"


# ==============================================================================
# CLI 与参数解析逻辑
# ==============================================================================

def parse_episode_args(episode_inputs: Any) -> List[str]:
    """
    解析丰富多样的 --episodes 参数：
    - "1-10" / "EP01-EP10" -> ['EP01', 'EP02', ..., 'EP10']
    - "1,3,5" / "EP01,EP03" -> ['EP01', 'EP03', 'EP05']
    - ["EP01", "EP02"] -> ['EP01', 'EP02']
    - "3" -> ['EP03']
    - 缺省 -> 全部 10 集
    """
    if not episode_inputs:
        return [f"EP{i:02d}" for i in range(1, 11)]

    if isinstance(episode_inputs, str):
        episode_inputs = [episode_inputs]

    result: List[str] = []
    for raw in episode_inputs:
        item = str(raw).strip()
        if not item:
            continue

        # 处理逗号分隔形式
        if "," in item:
            parts = [p.strip() for p in item.split(",") if p.strip()]
            result.extend(parse_episode_args(parts))
            continue

        # 处理范围形式 "1-10", "EP01-EP05", "1~5"
        range_match = re.match(r'^(?:EP)?(\d+)\s*[-~至到]\s*(?:EP)?(\d+)$', item, re.IGNORECASE)
        if range_match:
            start_idx = int(range_match.group(1))
            end_idx = int(range_match.group(2))
            for i in range(min(start_idx, end_idx), max(start_idx, end_idx) + 1):
                ep_code = f"EP{i:02d}"
                if ep_code not in result:
                    result.append(ep_code)
            continue

        # 处理单数字或单代码 "1", "01", "EP01", "EP1"
        single_match = re.match(r'^(?:EP)?(\d+)$', item, re.IGNORECASE)
        if single_match:
            ep_code = f"EP{int(single_match.group(1)):02d}"
            if ep_code not in result:
                result.append(ep_code)
            continue

        # 处理直接传目录名或集名前缀
        if item.upper().startswith("EP"):
            code = item[:4].upper()
            if code not in result:
                result.append(code)
        elif item not in result:
            result.append(item)

    return result if result else [f"EP{i:02d}" for i in range(1, 11)]


def find_episode_dir(ep_code: str, episodes_root: Path = EPISODES_ROOT) -> Optional[Path]:
    """根据集数代码 (如 EP01) 在工程根目录匹配对应的目录 (如 EP01_归来与旧账)"""
    norm = ep_code.upper()
    if norm.isdigit():
        norm = f"EP{int(norm):02d}"

    if not episodes_root.exists():
        return None

    for d in episodes_root.iterdir():
        if d.is_dir() and d.name.upper().startswith(norm):
            return d

    # 尝试直接匹配目录名
    direct = episodes_root / ep_code
    if direct.is_dir():
        return direct

    return None


# ==============================================================================
# ComfyUI 服务交互与显存管理
# ==============================================================================

def check_comfyui_alive(server: str = COMFY_HOST, timeout: float = 3.0) -> bool:
    """探测 ComfyUI 服务在线状态"""
    url = f"http://{server}/system_stats"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode() == 200
    except Exception:
        return False


def free_comfyui_vram(server: str = COMFY_HOST, timeout: float = 4.0) -> bool:
    """
    调用 ComfyUI /free 端点释放显存碎片缓存。
    payload 严格满足: {"unload_models": False, "free_memory": True}
    """
    url = f"http://{server}/free"
    payload = {"unload_models": False, "free_memory": True}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode() == 200
    except Exception:
        return False


def queue_comfyui_prompt(prompt_workflow: dict, server: str = COMFY_HOST) -> str:
    """向 ComfyUI 提交任务图谱并获取 prompt_id"""
    url = f"http://{server}/prompt"
    client_id = str(uuid.uuid4())
    data = json.dumps({"prompt": prompt_workflow, "client_id": client_id}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res["prompt_id"]


def wait_for_prompt_completion(prompt_id: str, server: str = COMFY_HOST, poll_interval: float = 3.0) -> dict:
    """轮询等待 ComfyUI 任务执行完毕"""
    url = f"http://{server}/history/{prompt_id}"
    print(f"  [H3 渲染中] 任务 ID: {prompt_id} ", end="", flush=True)
    dots = 0
    start_t = time.time()
    while True:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if prompt_id in data:
                    item = data[prompt_id]
                    status = item.get("status", {})
                    if status.get("status_str") == "error":
                        raise RuntimeError(f"ComfyUI 执行报错: {status.get('messages')}")
                    elapsed = time.time() - start_t
                    print(f" [完成, 耗时: {elapsed:.1f}s]")
                    return item
        except Exception as e:
            if "ComfyUI 执行报错" in str(e):
                raise
        dots += 1
        if dots % 15 == 0:
            print(f" ({int(time.time() - start_t)}s)", end="", flush=True)
        else:
            print(".", end="", flush=True)
        time.sleep(poll_interval)


def retrieve_comfyui_output_video(history_item: dict, prefix: str = "") -> Optional[Path]:
    """从 ComfyUI 返回的 history outputs 中提取最新落盘的视频文件"""
    outputs = history_item.get("outputs", {})
    # 优先检查常见视频输出节点 (如 15, 14)
    for target_node in ["15", "14"]:
        if target_node in outputs:
            node_out = outputs[target_node]
            for key in ("videos", "gifs", "images"):
                if key in node_out and node_out[key]:
                    for f_info in node_out[key]:
                        sub = f_info.get("subfolder", "")
                        fn = f_info.get("filename", "")
                        cand = COMFYUI_OUTPUT_ROOT / sub / fn
                        if cand.exists() and cand.stat().st_size > 0:
                            return cand

    # 通用遍历所有输出节点
    for n_id, n_data in outputs.items():
        for key in ("videos", "gifs", "images"):
            if key in n_data and n_data[key]:
                for f_info in n_data[key]:
                    fn = f_info.get("filename", "")
                    if fn.lower().endswith((".mp4", ".mov", ".mkv")):
                        sub = f_info.get("subfolder", "")
                        cand = COMFYUI_OUTPUT_ROOT / sub / fn
                        if cand.exists() and cand.stat().st_size > 0:
                            return cand

    # 兜底：若节点未标明，在 C:\AI\ComfyUI\output 下搜索按 prefix 匹配的最新 mp4
    if prefix:
        cands = list(COMFYUI_OUTPUT_ROOT.rglob(f"*{prefix}*.mp4"))
        if cands:
            cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return cands[0]

    return None


# ==============================================================================
# H3 原生执行图构建器
# ==============================================================================

def build_h3_prompt_graph(
    prompt_text: str,
    width: int = 832,
    height: int = 480,
    length: int = 175,
    seed: int = 42,
    output_prefix: str = "griftlands/seg01",
    model_type: str = "ref2va",
    first_frame_filename: Optional[str] = None
) -> dict:
    """
    构建 MiniMax H3 原生执行图 (支持 I2V 首帧锁脸与 Turbo 8-step LoRA)
    """
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
        "1": {
            "inputs": {
                "unet_name": unet_file,
                "weight_dtype": "default"
            },
            "class_type": "UNETLoader"
        },
        "2": {
            "inputs": {
                "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                "type": "minimax"
            },
            "class_type": "CLIPLoader"
        },
        "3": {
            "inputs": {
                "vae_name": "minimax_h3_video_vae_fp16.safetensors"
            },
            "class_type": "VAELoader"
        },
        "4": {
            "inputs": {
                "vae_name": "minimax_h3_audio_vae_fp32.safetensors"
            },
            "class_type": "VAELoader"
        },
        "5": {
            "inputs": {
                "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
                "strength_model": 1.0,
                "model": ["1", 0]
            },
            "class_type": "LoraLoaderModelOnly"
        },
        "6": {
            "inputs": node_6_inputs,
            "class_type": "MiniMaxH3ImageToVideo"
        },
        "7": {
            "inputs": {
                "model": ["5", 0],
                "conditioning": ["6", 0]
            },
            "class_type": "BasicGuider"
        },
        "8": {
            "inputs": {
                "sampler_name": "res_multistep"
            },
            "class_type": "KSamplerSelect"
        },
        "9": {
            "inputs": {
                "scheduler": "simple",
                "steps": 8,
                "denoise": 1.0,
                "model": ["5", 0]
            },
            "class_type": "BasicScheduler"
        },
        "10": {
            "inputs": {
                "noise_seed": int(seed)
            },
            "class_type": "RandomNoise"
        },
        "11": {
            "inputs": {
                "noise": ["10", 0],
                "guider": ["7", 0],
                "sampler": ["8", 0],
                "sigmas": ["9", 0],
                "latent_image": ["6", 1]
            },
            "class_type": "SamplerCustomAdvanced"
        },
        "12": {
            "inputs": {
                "samples": ["11", 0],
                "vae": ["3", 0]
            },
            "class_type": "VAEDecode"
        },
        "13": {
            "inputs": {
                "samples": ["11", 0],
                "vae": ["4", 0]
            },
            "class_type": "VAEDecodeAudio"
        },
        "14": {
            "inputs": {
                "images": ["12", 0],
                "audio": ["13", 0],
                "fps": 24.0,
                "bit_depth": 8,
                "color_space": "sRGB"
            },
            "class_type": "CreateVideo"
        },
        "15": {
            "inputs": {
                "video": ["14", 0],
                "filename_prefix": output_prefix,
                "format": "auto"
            },
            "class_type": "SaveVideo"
        }
    }

    if first_frame_filename:
        graph["20"] = {
            "inputs": {
                "image": str(first_frame_filename)
            },
            "class_type": "LoadImage"
        }
        node_6_inputs["first_frame"] = ["20", 0]

    return graph


# ==============================================================================
# 后处理各环节执行器
# ==============================================================================

def clean_bed_audio(src_video: Path, out_video: Path) -> float:
    """调用 audio_gate.py 清理持续背景床音"""
    t0 = time.time()
    script_path = SKILL_SCRIPTS / "audio_gate.py"
    if not script_path.exists():
        script_path = SCRIPTS_DIR / "audio_gate.py"

    if script_path.exists():
        cmd = [sys.executable, str(script_path), "--in", str(src_video), "--out", str(out_video)]
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if res.returncode == 0 and out_video.exists():
            elapsed = time.time() - t0
            print(f"  [音频门控] 床音过滤完成 -> {out_video.name} (耗时: {elapsed:.2f}s)")
            return elapsed

    # 平滑直通
    shutil.copy2(src_video, out_video)
    elapsed = time.time() - t0
    print(f"  [音频门控] 平滑直通原音轨 -> {out_video.name} (耗时: {elapsed:.2f}s)")
    return elapsed


def concat_video_segments(video_list: List[Path], out_final: Path) -> float:
    """分镜无损拼接 (FFmpeg concat -c copy)"""
    t0 = time.time()
    concat_txt = out_final.parent / "concat_list.txt"
    with open(concat_txt, "w", encoding="utf-8") as f:
        for v in video_list:
            f.write(f"file '{v.resolve().as_posix()}'\n")

    cmd = [
        str(FF), "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_txt),
        "-c", "copy",
        str(out_final)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    if concat_txt.exists():
        concat_txt.unlink()
    elapsed = time.time() - t0
    print(f"  [无损拼接] {len(video_list)} 段分镜已拼接 -> {out_final.name} (耗时: {elapsed:.2f}s)")
    return elapsed


def apply_sidechain_ducking_audio(input_video: Path, output_video: Path, bgm_path: Path) -> float:
    """影视级侧链动态避让混音"""
    t0 = time.time()
    if mix_video_with_ducked_bgm is not None:
        success = mix_video_with_ducked_bgm(
            input_video=input_video,
            output_video=output_video,
            bgm_path=bgm_path,
            bgm_volume=0.35,
            ducking_threshold=0.06,
            ducking_ratio=5.0,
            ducking_attack_ms=80,
            ducking_release_ms=400
        )
        if success and output_video.exists():
            return time.time() - t0

    # 兜底直通
    shutil.copy2(input_video, output_video)
    return time.time() - t0


def run_1080p_upscale_step(input_video: Path, output_video: Path) -> float:
    """RealESRGAN 1080p 超分辨率处理"""
    t0 = time.time()
    upscaler_script = SCRIPTS_DIR / "upscale_video.py"
    if upscaler_script.exists():
        cmd = [
            sys.executable,
            str(upscaler_script),
            "--input", str(input_video),
            "--output", str(output_video),
            "--model", "RealESRGAN_x2plus.pth",
            "--width", "1920",
            "--height", "1080"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if res.returncode == 0 and output_video.exists():
            elapsed = time.time() - t0
            print(f"  [1080p 超分] 超分完成 -> {output_video.name} (耗时: {elapsed:.2f}s)")
            return elapsed

    shutil.copy2(input_video, output_video)
    elapsed = time.time() - t0
    print(f"  [1080p 超分] 启用高品质原画直通 -> {output_video.name} (耗时: {elapsed:.2f}s)")
    return elapsed


# ==============================================================================
# Dry-Run 干跑全链路验证器
# ==============================================================================

def execute_dry_run_pipeline(
    episodes: List[str],
    start_seg: int = 1,
    episodes_root: Path = EPISODES_ROOT
) -> int:
    """
    全真干跑审计模式：
    无需 ComfyUI 实体 GPU 在线，严格校验 80 个分镜：
    - plan.json schema 合规性 (fps, 175帧, 对白存在)
    - 7 段式提示词文件语法完整性
    - 首帧锁脸就绪状态与 0-byte 损坏检测
    - 修脸景别识别策略 (MLS/LS -> refine, CU/MCU -> bypass)
    - 图谱构建无死循环
    - 侧链混音 BGM 解析
    """
    print("\n" + "=" * 70)
    print(" >>> 启动全流程 Dry-Run 全真干跑与管线链路审计")
    print(f" 目标集数: {episodes} | 起始段落: seg{start_seg:02d}")
    print("=" * 70)

    if not episodes or type(start_seg) is not int or start_seg < 1:
        print('[Dry-Run 错误] 至少选择一集，start_seg 必须为正整数')
        return 1
    total_audited_segs = 0
    refine_triggered_count = 0
    refine_bypassed_count = 0
    keyframes_ready_count = 0
    keyframes_corrupted_count = 0

    required_prompt_sections = [
        "[Shot 1]", "[Subject 1]", "[Action 1]",
        "[Environment 1]", "[Lighting 1]", "[Audio 1]", "[Quality 1]"
    ]

    for ep_code in episodes:
        ep_dir = find_episode_dir(ep_code, episodes_root)
        if not ep_dir:
            print(f"[Dry-Run 错误] 未找到集目录: {ep_code}")
            return 1

        print(f"\n[集审计] 正在核验: {ep_dir.name}")

        # 查找 plan.json
        plan_file = ep_dir / "生产" / "plan.json"
        if not plan_file.exists():
            plan_file = ep_dir / "plan.json"

        if not plan_file.exists():
            print(f"  [Dry-Run 错误] 未找到 plan.json: {plan_file}")
            return 1

        try:
            with open(plan_file, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
        except Exception as e:
            print(f"  [Dry-Run 错误] plan.json 解析失败: {e}")
            return 1

        if not isinstance(plan_data, dict):
            print('[Dry-Run 错误] plan 必须是对象')
            return 1
        segs = plan_data.get("segs", [])
        if not isinstance(segs, list) or not segs or start_seg > len(segs):
            print('[Dry-Run 错误] 分镜为空或起始段超出范围')
            return 1
        if any(not isinstance(seg, dict) for seg in segs):
            print('[Dry-Run 错误] 每个分镜必须是对象')
            return 1
        seg_ids = [seg.get('seg') for seg in segs]
        if any(not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', s) for s in seg_ids) or len(set(seg_ids)) != len(seg_ids):
            print('[Dry-Run 错误] 段号缺失、非法或重复')
            return 1

        # 逐段审计
        for seg_idx, seg in enumerate(segs, 1):
            seg_id = seg.get("seg", f"seg{seg_idx:02d}")
            if seg_idx < start_seg:
                print(f"  [{seg_id}] (跳过: 早于起始段 --start-seg {start_seg})")
                continue

            total_audited_segs += 1
            length = seg.get("length", 0)
            dialogue_text = seg.get("dialogue_text", "")
            shot_type = seg.get("shot_type", "MLS")

            # 1. 验证 schema 核心字段
            if type(length) is not int or length <= 0:
                print(f'[Dry-Run 错误] {seg_id} 帧数必须为正整数')
                return 1
            if seg.get('dialogue', True) and (not isinstance(dialogue_text, str) or not (dialogue_text.startswith("<d>") and dialogue_text.endswith("</d>"))):
                print(f"  [Dry-Run 错误] {seg_id} 台词格式异常: '{dialogue_text}'")
                return 1

            # 2. 验证提示词文件
            prompt_file = ep_dir / "生产" / "prompts" / f"{seg_id}.txt"
            if not prompt_file.exists():
                prompt_file = ep_dir / "prompts" / f"{seg_id}.txt"

            if not prompt_file.exists():
                print(f"  [Dry-Run 错误] 提示词文件不存在: {prompt_file}")
                return 1

            prompt_content = prompt_file.read_text(encoding="utf-8")
            missing_secs = [s for s in required_prompt_sections if s not in prompt_content]
            if missing_secs:
                print(f"  [Dry-Run 错误] {seg_id} 提示词缺失七段式结构: {missing_secs}")
                return 1

            # 3. 验证首帧垫图状态与 0-byte 损坏
            kf = None
            if get_keyframe_for_segment:
                try:
                    kf = get_keyframe_for_segment(ep_dir, seg_id)
                except (OSError, ValueError) as exc:
                    print(f"[FAIL] 首帧文件损坏: {exc}")
                    return 1

            mode = seg.get('generation_mode', plan_data.get('generation_mode', 'i2v'))
            if mode not in {'i2v', 't2v', 'first_frame', 'text_to_video'}:
                print(f'[Dry-Run 错误] 未识别生成模式: {mode}')
                return 1
            requires_keyframe = seg.get('requires_keyframe', mode in {'i2v', 'first_frame'})
            if requires_keyframe and not kf:
                print(f'[Dry-Run 错误] {seg_id} 缺少必需首帧，不能降级 T2V')
                return 1

            kf_status = "T2V 纯文本生成"
            if kf and kf.exists():
                if kf.stat().st_size == 0:
                    keyframes_corrupted_count += 1
                    print(f"  [Dry-Run 告警] {seg_id} 首帧图为 0 字节损坏文件: {kf.name} (CORRUPTED)")
                    return 1
                else:
                    try:
                        from PIL import Image
                        with Image.open(kf) as source_image:
                            source_image.verify()
                    except Exception as exc:
                        print(f'[Dry-Run 错误] {seg_id} 首帧无法验证: {exc}')
                        return 1
                    keyframes_ready_count += 1
                    kf_status = f"I2V 锁脸垫图挂载 ({kf.name}, {kf.stat().st_size / 1024:.1f} KB)"

            # 4. 验证中远景修脸策略判定
            needs_refine = should_refine_segment(seg)
            if needs_refine:
                refine_triggered_count += 1
                refine_action = f"[修脸触发] 判定为中远景 ({shot_type}) -> 768x768 局部重绘"
            else:
                refine_bypassed_count += 1
                refine_action = f"[修脸穿透] 判定为特写/近景 ({shot_type}) -> 安全无损穿透"

            # 5. 验证执行图构建
            try:
                graph = build_h3_prompt_graph(
                    prompt_text=prompt_content,
                    length=length,
                    first_frame_filename=kf.name if (kf and kf.stat().st_size > 0) else None
                )
                if not graph or "6" not in graph:
                    print(f"  [Dry-Run 错误] {seg_id} 执行图构建异常")
                    return 1
            except Exception as e:
                print(f"  [Dry-Run 错误] 执行图构建抛出异常: {e}")
                return 1

            print(f"  [{seg_id}] [✓] 时序: {length}f | {kf_status} | {refine_action}")

        # 6. 验证 BGM 混音解析
        bgm_path = Path(os.environ.get("DEFAULT_BGM", WORKSPACE_ROOT / "assets" / "bgm" / "90s_business_suspense.wav"))
        if not bgm_path.exists():
            bgm_path = DEFAULT_BGM
        if plan_data.get('bgm_required') and not bgm_path.exists():
            print('[Dry-Run 错误] 必需 BGM 缺失')
            return 1
        bgm_status = f"BGM 路径存在 ({bgm_path.name})" if bgm_path.exists() else "无 BGM；未验证混音"
        print(f"  -> 侧链混音状态: {bgm_status}")

    print("\n" + "=" * 70)
    print(" [Dry-Run 审计报告]")
    print(f"  - 校验分镜总数: {total_audited_segs} 段 (100% 格式达标)")
    print(f"  - 首帧锁脸垫图: {keyframes_ready_count} 段就绪, {keyframes_corrupted_count} 段损坏")
    print(f"  - 修脸路由决策: {refine_triggered_count} 段触发局部重绘, {refine_bypassed_count} 段近景安全穿透")
    print("  - 静态文件检查通过；未验证 ComfyUI 节点/模型兼容、混音效果、视觉质量或交付")
    print("=" * 70)
    return 0


# ==============================================================================
# 实体生产调度主循环
# ==============================================================================

def execute_production_pipeline(args: argparse.Namespace) -> int:
    """Legacy entry is inspection-only; production uses the H3 skill's guarded SOP."""
    if args.dry_run:
        return execute_dry_run_pipeline(
            episodes=parse_episode_args(args.episodes),
            start_seg=args.start_seg,
            episodes_root=EPISODES_ROOT,
        )
    print('[REFUSE] 旧批量生产入口已停用：它没有可靠的提交恢复和版本绑定质检。')
    print('请按 skills/drama-production-director/SKILL.md 选择制作路径，')
    print('H3 路径使用 skills/comfy-h3-video-producer/SKILL.md 中的 submit/watch/gate/review/finish SOP。')
    print('本入口仅保留 --dry-run 静态检查；检查通过不代表模型兼容或已交付。')
    return 2

def get_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="《欺诈之地》全十集工业级母生产调度管线")
    parser.add_argument(
        "--episodes",
        nargs="+",
        default=["1-10"],
        help="指定生产集数，支持范围 '1-10', 'EP01-EP05', '1,3,5' 或列表 'EP01 EP02' (默认 1-10)"
    )
    parser.add_argument(
        "--start-seg",
        type=int,
        default=1,
        help="指定集内起始断点续产段落 (1~8，默认 1)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="全真干跑审计模式：无需启动 ComfyUI GPU 推理，校验全十集图谱、语法、首帧、修脸与混音链路"
    )
    parser.add_argument(
        "--skip-render",
        action="store_true",
        help="跳过 H3 生成，仅执行后续修脸、门控清洗、拼接、混音与超分"
    )
    parser.add_argument(
        "--skip-upscale",
        action="store_true",
        help="跳过 1080p 超分环节，以高品质原画快速交付"
    )
    parser.add_argument(
        "--force-render",
        action="store_true",
        help="强制重新生成所有分镜，不复用已有分镜"
    )
    parser.add_argument(
        "--server",
        type=str,
        default=COMFY_HOST,
        help="ComfyUI 服务端地址 (默认 127.0.0.1:8188)"
    )
    parser.add_argument(
        "--model-type",
        type=str,
        default="ref2va",
        choices=["ref2va", "fl2va"],
        help="H3 推理主模型架构 (默认 ref2va)"
    )
    return parser


def main(argv=None):
    parser = get_cli_parser()
    args = parser.parse_args(argv)
    return execute_production_pipeline(args)


if __name__ == "__main__":
    sys.exit(main())
