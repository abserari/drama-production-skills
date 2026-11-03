# -*- coding: utf-8 -*-
"""
首帧核验与 I2V 注入闸门 (Keyframe Gate & I2V Injector)
遵循 §13 纪律：纯通用机制脚本，不包含任何项目专属名称。

核心功能：
1. check: 扫描指定工程目录下的 plan.json，检查各分镜段落的首帧图 (segXX_keyframe.png/jpg) 就绪状态；
2. sync:  将选定的首帧图复制并同步至 ComfyUI input 目录，生成供 LoadImage 节点安全加载的标准文件名；
3. inject: 在执行图构建时，将 LoadImage 节点安全注入 MiniMaxH3ImageToVideo 的 first_frame 端口。
4. contracts: PROJECT.md 接口契约，导出 KeyframeNotFoundError 异常类。
"""

import os
import sys
import json
import shutil
import argparse
from pathlib import Path

# Windows 控制台 UTF-8 防御
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class KeyframeNotFoundError(FileNotFoundError):
    """当首帧图片未找到且处于强制首帧锁脸模式时抛出的标准异常 (PROJECT.md 契约)"""
    pass


# 默认 ComfyUI 根目录与输入仓 (支持环境变量 COMFYUI_INPUT / COMFYUI_DIR 配置)
_default_comfy_base = os.environ.get("COMFYUI_DIR", r"C:\AI\ComfyUI")
DEFAULT_COMFYUI_INPUT = Path(os.environ.get("COMFYUI_INPUT", Path(_default_comfy_base) / "input"))


def get_keyframe_for_segment(arg1, arg2=None, force: bool = False) -> Path:
    """
    在工程中查找首帧图。
    支持调用方式：
      get_keyframe_for_segment(project_dir, seg_id, force=False)
      get_keyframe_for_segment(seg_id, project_dir, force=False)
      get_keyframe_for_segment(seg_id, force=False)

    若 force=True 且未找到首帧，抛出 KeyframeNotFoundError (满足 PROJECT.md 契约)；
    若非强制模式，返回 None。
    """
    if arg2 is None:
        # Default project_dir to cwd if only seg_id provided
        seg_id = str(arg1)
        project_dir = Path.cwd()
    else:
        # Check if arg1 is directory/Path and arg2 is seg_id string
        p1 = Path(arg1)
        p2 = Path(arg2)
        if p1.is_dir() or "/" in str(arg1) or "\\" in str(arg1):
            project_dir, seg_id = p1, str(arg2)
        elif p2.is_dir() or "/" in str(arg2) or "\\" in str(arg2):
            seg_id, project_dir = str(arg1), p2
        else:
            # Fallback heuristic: seg_id typically starts with 'seg'
            if str(arg1).lower().startswith("seg") or "seg" in str(arg1).lower():
                seg_id, project_dir = str(arg1), p2
            else:
                project_dir, seg_id = p1, str(arg2)

    search_dirs = [
        project_dir / "segments",
        project_dir / "生产" / "references",
        project_dir / "生产" / "prompts",
        project_dir / "首帧垫图与资产",
        project_dir / "examples" / "首帧核验垫图库",
        project_dir
    ]

    for d in search_dirs:
        if not d.exists():
            continue
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            # Check exact match or segXX_keyframe or prefix match
            candidates = [
                d / f"{seg_id}_keyframe{ext}",
                d / f"{seg_id}{ext}",
                d / f"{project_dir.name}_{seg_id}_keyframe{ext}"
            ]
            for candidate in candidates:
                if candidate.exists():
                    return candidate
            # Also check glob match in dir
            for match in d.glob(f"*{seg_id}*{ext}"):
                if "keyframe" in match.name.lower() or seg_id.lower() in match.name.lower():
                    return match

    if force:
        raise KeyframeNotFoundError(f"强制首帧锁脸模式下未找到分镜首帧图: seg_id={seg_id}, project_dir={project_dir}")

    return None


def sync_keyframe_to_comfyui(keyframe_path: Path, prefix: str = "kf") -> str:
    """
    同步首帧图至 ComfyUI input 仓
    返回注入 ComfyUI 图执行节点所用的内部文件名
    """
    keyframe_path = Path(keyframe_path)
    if not keyframe_path.exists():
        raise FileNotFoundError(f"首帧图文件不存在: {keyframe_path}")

    DEFAULT_COMFYUI_INPUT.mkdir(parents=True, exist_ok=True)
    comfy_filename = f"{prefix}_{keyframe_path.stem}{keyframe_path.suffix}"
    dest = DEFAULT_COMFYUI_INPUT / comfy_filename
    shutil.copy2(keyframe_path, dest)
    return comfy_filename


def apply_keyframe_to_graph(
    graph: dict,
    arg2=None,
    arg3=None,
    load_node_id: str = "20",
    h3_node_id: str = "6",
    keyframe_filename: str = None
) -> dict:
    """
    通用执行图注入：在指定图上附加 LoadImage 节点并连接至 MiniMaxH3ImageToVideo 的 first_frame 输入。
    兼容各种调用签名：
      apply_keyframe_to_graph(graph, keyframe_filename="kf.png", h3_node_id="6")
      apply_keyframe_to_graph(graph, node_id_i2v, keyframe_filename, load_node_id="20")
      apply_keyframe_to_graph(prompt_graph, keyframe_filename, h3_node_id="6")
    """
    if keyframe_filename is not None:
        actual_kf = str(keyframe_filename)
        target_h3 = str(h3_node_id) if h3_node_id else "6"
    elif arg2 is None and arg3 is None:
        return graph
    else:
        # Determine node_id_i2v and keyframe_filename
        image_exts = (".png", ".jpg", ".jpeg", ".webp")
        str_arg2 = str(arg2) if arg2 is not None else ""
        str_arg3 = str(arg3) if arg3 is not None else ""

        if any(str_arg2.lower().endswith(ext) for ext in image_exts):
            actual_kf = str_arg2
            target_h3 = str(h3_node_id) if h3_node_id else (str_arg3 or "6")
        else:
            target_h3 = str_arg2 if str_arg2 else (str(h3_node_id) if h3_node_id else "6")
            actual_kf = str_arg3

    if not actual_kf:
        return graph

    graph[str(load_node_id)] = {
        "inputs": {
            "image": str(actual_kf)
        },
        "class_type": "LoadImage"
    }

    target_id = str(target_h3)
    if target_id in graph and "inputs" in graph[target_id]:
        graph[target_id]["inputs"]["first_frame"] = [str(load_node_id), 0]

    return graph


def audit_project_keyframes(project_dir: Path):
    """巡检工程首帧就绪状态"""
    plan_path = project_dir / "plan.json"
    if not plan_path.exists():
        print(f"[提示] 未找到规划表: {plan_path}")
        return

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    segs = plan.get("segs", [])
    print("=" * 65)
    print(f" [首帧闸门巡检] 检查工程: {project_dir.name}")
    print(" 核心原则: 首帧生图核验 (10s) -> 锁脸防变形 -> 驱动 I2V 视频渲染")
    print("=" * 65)

    ready = 0
    for s in segs:
        seg_id = s.get("seg", "")
        event = s.get("event", "")[:32]
        kf = get_keyframe_for_segment(project_dir, seg_id)
        if kf:
            ready += 1
            sz_kb = kf.stat().st_size / 1024
            status = f"[OK] I2V 锁脸就绪 ({sz_kb:.1f} KB: {kf.name})"
        else:
            status = "[--] 待核验 (降级为纯文本 T2V)"
        print(f"  [{seg_id:6s}] {status:38s} | {event}...")

    print("-" * 65)
    print(f"统计: 全段 {len(segs)}，首帧核验就绪 {ready}/{len(segs)}。")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="首帧核验与 I2V 注入闸门")
    parser.add_argument("--project", type=Path, required=True, help="工程目录路径")
    parser.add_argument("--seg", type=str, default=None, help="指定段落编号 (例如 seg01)")
    parser.add_argument("--sync", action="store_true", help="将指定段落首帧同步到 ComfyUI input 仓")
    parser.add_argument("--force", action="store_true", help="强制模式：找不到首帧抛出 KeyframeNotFoundError")
    args = parser.parse_args()

    if args.sync and args.seg:
        kf = get_keyframe_for_segment(args.project, args.seg, force=args.force)
        if kf:
            fn = sync_keyframe_to_comfyui(kf, prefix=args.project.name)
            print(f"[成功] 首帧已同步至 ComfyUI: {fn}")
        else:
            print(f"[错误] 未在 {args.project / 'segments'} 中找到 {args.seg} 的首帧图！")
    else:
        audit_project_keyframes(args.project)
