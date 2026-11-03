# -*- coding: utf-8 -*-
"""
外部 20 节点远景修脸工作流管线化驱动器 (H3 Face Refinement Pipeline)
基于 ComfyUI-H3-FaceRefine 套件：
1. 20 节点拓扑图构建：解析并封装外部远景修脸固定工作流；
2. 中远景自适应判定：LS / MLS / WS / FS 触发局部 768x768 放大重绘，CU / ECU 近景自动穿透跳过；
3. 降级熔断与平滑直通：若 ComfyUI 离线或缺失修脸自定义节点，无缝降级原视频直通，绝不阻断母调度；
4. 原生音频无损直通：保持对白与拟音完整性，无缝衔接后续影视级侧链动态避让混音。
"""

import os
import sys
import json
import time
import shutil
import urllib.request
import urllib.error
import argparse
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Union

# Windows UTF-8 控制台防御
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 默认权威外部工作流 JSON 路径
DEFAULT_EXTERNAL_WORKFLOW = Path(
    r"c:\Users\34903\xwechat_files\wxid_hc2xpfk13zri11_7825\msg\file\2026-11\H3-FaceRefine-远景修脸-固定工作流(1).json"
)

# 必需的自定义修脸节点集合
REQUIRED_FACE_REFINE_NODES = {
    "H3FaceTrackCrop",
    "H3InjectVideoLatent",
    "H3PerFrameDenoise",
    "H3FaceStitch"
}

# 默认 ComfyUI 仓路径
DEFAULT_COMFYUI_INPUT = Path(r"C:\AI\ComfyUI\input")
DEFAULT_COMFYUI_OUTPUT = Path(r"C:\AI\ComfyUI\output")


def should_refine_segment(meta: Union[Dict[str, Any], str, None]) -> bool:
    """
    智能判定分镜是否需要执行远景修脸。
    
    规则：
    1. 若 meta 中显式设置了 'face_refine': True/False 或 'skip_face_refine': True，以显式声明为最高优先级；
    2. 近景 / 特写镜头 (CU, ECU, MCU, 近景, 特写) 面部像素充足 (>120px)，返回 False 跳过以节约推理耗时；
    3. 中远景 / 全景镜头 (LS, MLS, WS, FS, 远景, 中远景, 全景, 大远景, 中景) 面部像素稀疏 (<120px)，返回 True 触发修脸；
    4. 缺省或无法判定时，默认返回 False（保守策略，优先保证生产效率）。
    """
    if meta is None:
        return False

    # 处理字典输入 (如 plan.json 中的 segment_spec)
    if isinstance(meta, dict):
        if "face_refine" in meta:
            return bool(meta["face_refine"])
        if meta.get("skip_face_refine") is True:
            return False

        shot_candidates = [
            meta.get("shot_type"),
            meta.get("shot"),
            meta.get("camera"),
            meta.get("type"),
            meta.get("scale"),
            meta.get("event"),
            meta.get("description")
        ]
        text_to_check = " ".join([str(c) for c in shot_candidates if c])
    else:
        text_to_check = str(meta)

    text_upper = text_to_check.upper()

    # 近景 / 特写标识 (优先级高，明确排除)
    close_up_tokens = [
        "ECU", "EXTREME CLOSE-UP", "EXTREME CLOSE UP", "大特写",
        "CU", "CLOSE-UP", "CLOSE UP", "特写",
        "MCU", "MEDIUM CLOSE-UP", "MEDIUM CLOSE UP", "中近景", "近景",
        "FACE-ONLY", "HEADSHOT", "面部特写"
    ]
    for token in close_up_tokens:
        if token in text_upper or token in text_to_check:
            return False

    # 中远景 / 全景标识
    mid_far_tokens = [
        "MLS", "MEDIUM LONG SHOT", "MEDIUM-LONG SHOT", "中远景",
        "LS", "LONG SHOT", "远景", "大远景",
        "WS", "WIDE SHOT", "全景", "大全景",
        "FS", "FULL SHOT", "全景人身",
        "VWS", "VERY WIDE SHOT",
        "MS", "MEDIUM SHOT", "中景"
    ]
    for token in mid_far_tokens:
        if token in text_upper or token in text_to_check:
            return True

    return False


def build_face_refine_graph(
    input_video_path: Union[str, Path],
    char_ref_path: Union[str, Path],
    prompt_text: str = "男性惊讶看向前方",
    seed: int = 42,
    base_denoise: float = 0.4,
    output_prefix: str = "修脸",
    unet_name: str = r"MiniMax-H3\fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors",
    clip_name: str = r"qwen3vl_32b_minimax_h3-w4a8_convrot.safetensors",
    video_vae_name: str = "minimax_h3_video_vae_int8_convrot.safetensors",
    audio_vae_name: str = "minimax_h3_audio_vae_fp32.safetensors"
) -> Dict[str, Any]:
    """
    构建符合 ComfyUI API 规范的 20 节点外部修脸执行图谱。
    
    数据拓扑流：
    1:LoadVideo -> 2:GetVideoComponents -> 3:H3FaceTrackCrop
    6:LoadImage -> 9:MiniMaxH3ReferenceToVideo (结合 8:CLIP, 4:VideoVAE, 5:AudioVAE)
    10:H3InjectVideoLatent (注入 768x768 面部图块潜空间)
    15:H3PerFrameDenoise (按原始面部像素绝对尺寸动态缩放模型降噪)
    14:BasicScheduler (8-step, denoise 0.4) + 12:BasicGuider + 13:KSamplerSelect(er_sde) + 16:RandomNoise
    17:SamplerCustomAdvanced (Turbo采样) -> 18:VAEDecode
    19:H3FaceStitch (16px软边缘羽化贴回底图 2:images)
    20:CreateVideo (贴合帧 19 + 原始无损音频 2:audio + 物理帧率 2:fps)
    21:SaveVideo (最终输出)
    """
    video_file_name = Path(input_video_path).name
    char_ref_file_name = Path(char_ref_path).name

    prompt_graph = {
        "1": {
            "class_type": "LoadVideo",
            "inputs": {
                "file": video_file_name,
                "upload": "image"
            }
        },
        "2": {
            "class_type": "GetVideoComponents",
            "inputs": {
                "video": ["1", 0]
            }
        },
        "3": {
            "class_type": "H3FaceTrackCrop",
            "inputs": {
                "images": ["2", 0],
                "model_name": r"bbox\face_yolov8m.pt",
                "confidence": 0.35,
                "pad_ratio": 3,
                "target_w": 768,
                "target_h": 768,
                "rescale_mode": "auto_capped_768",
                "smooth_window": 21,
                "max_lost_frames": 51,
                "smooth_kernel": "gaussian",
                "denoise_strategy": "per_frame",
                "tight_crop": True,
                "tight_ratio": 0.28,
                "track_selection": "largest_face",
                "landmark_model": "none",
                "face_align_strength": 0.5,
                "face_align_roll_max": 0,
                "retina_mode": "insightface",
                "tracking_algorithm": "none",
                "max_age": 3,
                "face_restore": "off",
                "fade_in_frames": 0,
                "fade_out_frames": 0,
                "crop_edge_expand": 0
            }
        },
        "4": {
            "class_type": "VAELoader",
            "inputs": {
                "vae_name": video_vae_name
            }
        },
        "5": {
            "class_type": "VAELoader",
            "inputs": {
                "vae_name": audio_vae_name
            }
        },
        "6": {
            "class_type": "LoadImage",
            "inputs": {
                "image": char_ref_file_name,
                "upload": "image"
            }
        },
        "7": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": unet_name,
                "weight_dtype": "default"
            }
        },
        "8": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": clip_name,
                "type": "minimax",
                "device": "default"
            }
        },
        "9": {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": {
                "prompt": prompt_text,
                "width": ["3", 4],
                "height": ["3", 5],
                "length": ["3", 6],
                "match_mode": "match",
                "clip": ["8", 0],
                "vae": ["4", 0],
                "audio_vae": ["5", 0],
                "ref_images": ["6", 0]
            }
        },
        "10": {
            "class_type": "H3InjectVideoLatent",
            "inputs": {
                "av_latent": ["9", 1],
                "images": ["3", 0],
                "vae": ["4", 0]
            }
        },
        "12": {
            "class_type": "BasicGuider",
            "inputs": {
                "model": ["15", 2],
                "conditioning": ["9", 0]
            }
        },
        "13": {
            "class_type": "KSamplerSelect",
            "inputs": {
                "sampler_name": "er_sde"
            }
        },
        "14": {
            "class_type": "BasicScheduler",
            "inputs": {
                "scheduler_name": "simple",
                "steps": 8,
                "denoise": base_denoise,
                "model": ["15", 2]
            }
        },
        "15": {
            "class_type": "H3PerFrameDenoise",
            "inputs": {
                "model": ["7", 0],
                "av_latent": ["10", 0],
                "transform": ["3", 1],
                "max_denoise": 1.0,
                "min_denoise": 0.35,
                "mode": "absolute_px",
                "min_px": 30,
                "max_px": 120,
                "curve_power": 1.0,
                "smooth_frames": 9
            }
        },
        "16": {
            "class_type": "RandomNoise",
            "inputs": {
                "noise_seed": seed,
                "control_after_generate": "fixed"
            }
        },
        "17": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["16", 0],
                "guider": ["12", 0],
                "sampler": ["13", 0],
                "sigmas": ["14", 0],
                "latent_image": ["15", 0]
            }
        },
        "18": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["17", 0],
                "vae": ["4", 0]
            }
        },
        "19": {
            "class_type": "H3FaceStitch",
            "inputs": {
                "base_images": ["2", 0],
                "refined_crops": ["18", 0],
                "transform": ["3", 1],
                "blend_mode": "face_only",
                "feather_x": 16,
                "feather_y": 16,
                "colour_match": 1.0,
                "colour_match_strength": 1.0,
                "lost_strategy": "fade_out",
                "show_debug_box": False
            }
        },
        "20": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["19", 0],
                "audio": ["2", 1],
                "fps": ["2", 2],
                "fps_val": 24,
                "bitrate": "auto",
                "color_space": "sRGB",
                "pixel_format": "none"
            }
        },
        "21": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["20", 0],
                "filename_prefix": output_prefix,
                "format": "auto",
                "codec": "auto",
                "compression": "auto"
            }
        }
    }
    return prompt_graph


def load_raw_workflow_template(workflow_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """
    加载并解析原始外部 20 节点 GUI 格式工作流文件。
    """
    wf_path = Path(workflow_path) if workflow_path else DEFAULT_EXTERNAL_WORKFLOW
    if not wf_path.exists():
        raise FileNotFoundError(f"未找到外部修脸工作流文件: {wf_path}")

    with open(wf_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def check_comfyui_face_refine_support(
    server_url: str = "http://127.0.0.1:8188",
    timeout: float = 3.0
) -> Tuple[bool, str]:
    """
    探测 ComfyUI 服务状态与 `ComfyUI-H3-FaceRefine` 自定义节点安装状态。
    返回: (支持状态 bool, 详细原因描述 str)
    """
    clean_url = server_url.rstrip("/")
    object_info_url = f"{clean_url}/object_info"

    try:
        req = urllib.request.Request(
            object_info_url,
            headers={"User-Agent": "H3-FaceRefine-Pipeline/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False, f"ComfyUI HTTP 返回非正常状态码: {resp.status}"
            data = json.loads(resp.read().decode("utf-8"))

        installed_nodes = set(data.keys())
        missing_nodes = REQUIRED_FACE_REFINE_NODES - installed_nodes

        if missing_nodes:
            return False, f"ComfyUI 服务已在线，但缺少修脸核心节点: {sorted(list(missing_nodes))}"

        return True, "ComfyUI 在线且所有修脸自定义节点均就绪"

    except urllib.error.URLError as e:
        return False, f"无法连接到 ComfyUI 服务 ({clean_url}): {e.reason}"
    except Exception as e:
        return False, f"探测 ComfyUI 时捕获异常: {type(e).__name__} - {e}"


def run_face_refine_on_video(
    input_video_path: Union[str, Path],
    char_ref_path: Optional[Union[str, Path]],
    output_video_path: Union[str, Path],
    server_url: str = "http://127.0.0.1:8188",
    shot_type: Optional[str] = None,
    prompt_text: str = "男性惊讶看向前方",
    seed: int = 42,
    base_denoise: float = 0.4,
    dry_run: bool = False,
    timeout: int = 600,
    verbose: bool = True
) -> bool:
    """
    调度执行单段视频远景修脸全流程。
    
    关键保障：
    1. 景别过滤：若 shot_type 为特写/近景，直接原样直通并跳过；
    2. 离线/缺节点平滑降级：若 ComfyUI 无法连接或缺失自定义节点，无损直通输出原视频，绝不崩溃；
    3. 原生音轨 100% 物理直通：无论直通还是 ComfyUI 重构，均完整保全原始音轨，确保后续侧链混音无缝工作。
    """
    input_p = Path(input_video_path)
    output_p = Path(output_video_path)

    if not input_p.exists():
        if verbose:
            print(f"[FaceRefine 错误] 输入视频不存在: {input_p}")
        return False

    output_p.parent.mkdir(parents=True, exist_ok=True)

    # 1. 景别识别过滤 (特写 / 近景穿透)
    if shot_type and not should_refine_segment(shot_type):
        if verbose:
            print(f"[FaceRefine 穿透] 景别 '{shot_type}' 判定为近景/特写，面部细节充足，执行无损直通。")
        shutil.copy2(input_p, output_p)
        return True

    # 2. 检查角色定妆/首帧参考图
    if char_ref_path:
        char_p = Path(char_ref_path)
        if not char_p.exists():
            if verbose:
                print(f"[FaceRefine 警告] 角色参考图不存在: {char_p}，降级直通原视频。")
            shutil.copy2(input_p, output_p)
            return True
    else:
        char_p = None

    # 3. Dry-Run 模式直通
    if dry_run:
        if verbose:
            print(f"[FaceRefine Dry-Run] 干跑模式：跳过远程 GPU 推理，执行无损直通 -> {output_p.name}")
        shutil.copy2(input_p, output_p)
        return True

    # 4. 服务端探活与自定义节点支持检测 (降级熔断防线)
    supported, reason = check_comfyui_face_refine_support(server_url=server_url, timeout=3.0)
    if not supported:
        if verbose:
            print(f"[FaceRefine 降级熔断] {reason}")
            print(f"  -> 启用平滑直通保护：输出原视频至 {output_p.name}，母调度流程不受阻断。")
        shutil.copy2(input_p, output_p)
        return True

    # 5. 线上真实提交与执行
    try:
        if verbose:
            print(f"[FaceRefine] ComfyUI 环境就绪，正在准备修脸工作流...")

        # 同步资产至 ComfyUI input 仓
        DEFAULT_COMFYUI_INPUT.mkdir(parents=True, exist_ok=True)
        dest_video = DEFAULT_COMFYUI_INPUT / input_p.name
        if not dest_video.exists() or dest_video.stat().st_mtime < input_p.stat().st_mtime:
            shutil.copy2(input_p, dest_video)

        if char_p:
            dest_char = DEFAULT_COMFYUI_INPUT / char_p.name
            if not dest_char.exists() or dest_char.stat().st_mtime < char_p.stat().st_mtime:
                shutil.copy2(char_p, dest_char)
        else:
            dest_char = dest_video

        # 组装 20 节点 API Prompt
        graph = build_face_refine_graph(
            input_video_path=dest_video.name,
            char_ref_path=dest_char.name,
            prompt_text=prompt_text,
            seed=seed,
            base_denoise=base_denoise,
            output_prefix=f"refined_{input_p.stem}"
        )

        payload = json.dumps({"prompt": graph}).encode("utf-8")
        req = urllib.request.Request(
            f"{server_url.rstrip('/')}/prompt",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "H3-FaceRefine-Pipeline/1.0"}
        )

        with urllib.request.urlopen(req, timeout=10.0) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            prompt_id = res_data.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"未能获取 prompt_id: {res_data}")

        if verbose:
            print(f"[FaceRefine 提交成功] 任务 ID: {prompt_id}，正在等待修脸渲染...")

        # 轮询等待任务完成
        t0 = time.time()
        completed = False
        target_output_filename = None

        while time.time() - t0 < timeout:
            history_url = f"{server_url.rstrip('/')}/history/{prompt_id}"
            try:
                with urllib.request.urlopen(history_url, timeout=5.0) as h_resp:
                    hist_data = json.loads(h_resp.read().decode("utf-8"))
                    if prompt_id in hist_data:
                        task_history = hist_data[prompt_id]
                        status = task_history.get("status", {})
                        if status.get("completed", False):
                            # 从 outputs 提取保存的视频
                            outputs = task_history.get("outputs", {})
                            for nid, out_dict in outputs.items():
                                if "videos" in out_dict:
                                    for v in out_dict["videos"]:
                                        target_output_filename = v.get("filename")
                                        break
                                elif "gifs" in out_dict:
                                    for g in out_dict["gifs"]:
                                        target_output_filename = g.get("filename")
                                        break
                            completed = True
                            break
                        if status.get("status_str") == "error":
                            raise RuntimeError(f"ComfyUI 执行抛错: {status.get('messages')}")
            except Exception as poll_e:
                if verbose:
                    print(f"  [轮询重试] {poll_e}")
            time.sleep(2.5)

        if completed and target_output_filename:
            # 查找落盘成片
            src_out = DEFAULT_COMFYUI_OUTPUT / target_output_filename
            if src_out.exists():
                shutil.copy2(src_out, output_p)
                if verbose:
                    print(f"[FaceRefine 成功] 远景修脸完成 -> {output_p.name}")
                return True

        if verbose:
            print(f"[FaceRefine 超时或未获取视频] 降级使用原视频直通保证生产连续性。")
        shutil.copy2(input_p, output_p)
        return True

    except Exception as e:
        if verbose:
            print(f"[FaceRefine 异常保护] 运行时捕获异常: {e}")
            print(f"  -> 触发降级保护，无损直通输出原片。")
        shutil.copy2(input_p, output_p)
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="外部远景修脸管线驱动器")
    parser.add_argument("--input", "-i", type=Path, required=True, help="待修脸的输入视频")
    parser.add_argument("--output", "-o", type=Path, required=True, help="修脸后成片输出路径")
    parser.add_argument("--char-ref", "-c", type=Path, default=None, help="角色首帧/定妆参考图")
    parser.add_argument("--shot-type", "-s", type=str, default=None, help="景别标注 (例如 LS, MLS, CU, ECU)")
    parser.add_argument("--server", type=str, default="http://127.0.0.1:8188", help="ComfyUI 服务端地址")
    parser.add_argument("--dry-run", action="store_true", help="干跑测试模式，不调用远端 GPU")
    parser.add_argument("--prompt", type=str, default="男性惊讶看向前方", help="面部表情修饰提示词")
    args = parser.parse_args()

    ok = run_face_refine_on_video(
        input_video_path=args.input,
        char_ref_path=args.char_ref,
        output_video_path=args.output,
        server_url=args.server,
        shot_type=args.shot_type,
        prompt_text=args.prompt,
        dry_run=args.dry_run
    )
    sys.exit(0 if ok else 1)
