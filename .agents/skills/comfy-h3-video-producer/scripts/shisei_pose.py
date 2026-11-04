# -*- coding: utf-8 -*-
"""
Shisei (姿勢) 本地多视角人体姿态库检索与导出工具
支持：
- 关键词搜索 (中/英/日)
- 双人对峙/交互姿态筛选 (--duo)
- 一键导出多视角线稿/原图至工程目录或 ComfyUI input 作为 ControlNet/首帧基准
"""

import os
import sys
import json
import shutil
import argparse
from pathlib import Path

# 针对 Windows 控制台编码安全配置
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
            sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass

HERE = Path(__file__).parent.resolve()
SKILL_DIR = HERE.parent
SHISEI_DIR = SKILL_DIR / "assets" / "shisei"
CATALOG_PATH = SHISEI_DIR / "data" / "catalog.json"
IMAGES_DIR = SHISEI_DIR / "images" / "line" / "w900"


def clean_text(s: str) -> str:
    if not s:
        return ""
    return str(s).replace("\u30fb", "·").strip()


def load_catalog():
    if not CATALOG_PATH.exists():
        print(f"[错误] 未找到 catalog.json: {CATALOG_PATH}")
        sys.exit(1)
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def search_poses(kw: str = None, is_duo: bool = False, limit: int = 10):
    catalog = load_catalog()
    results = []
    for item in catalog:
        pid = item.get("id", "")
        if is_duo and not pid.startswith("D"):
            continue
        
        text_corpus = (
            f"{item.get('id', '')} "
            f"{item.get('name_cn', '')} "
            f"{item.get('class_cn', '')} "
            f"{item.get('name_en', '')} "
            f"{item.get('desc_en', '')}"
        ).lower()

        if kw:
            if kw.lower() in text_corpus:
                results.append(item)
        else:
            if is_duo:
                results.append(item)

    print(f"\n[检索] 找到 {len(results)} 个匹配姿态 (展示前 {min(limit, len(results))} 条)：")
    print("-" * 75)
    for idx, r in enumerate(results[:limit], 1):
        pid = r.get("id")
        name = clean_text(r.get("name_cn") or r.get("name_en") or "未命名")
        cls = clean_text(r.get("class_cn") or r.get("class_en") or "")
        views = list(r.get("views", {}).keys())
        print(f" {idx:2d}. [{pid}] {name} | 分类: {cls} | 可用视角: {views}")
    print("-" * 75)
    return results


def export_pose(pose_id: str, view: str = "front", dest_dir: Path = None):
    catalog = load_catalog()
    matched = None
    for item in catalog:
        if item.get("id") == pose_id:
            matched = item
            break

    if not matched:
        print(f"[错误] 未找到姿态 ID: {pose_id}")
        return None

    views = matched.get("views", {})
    if view not in views:
        print(f"[警告] 姿态 {pose_id} 无视角 {view}，可用视角: {list(views.keys())}")
        view = list(views.keys())[0]

    img_filename = views[view]
    src_file = IMAGES_DIR / img_filename
    if not src_file.exists():
        # Fallback to scanning all under images
        cands = list(SHISEI_DIR.rglob(img_filename))
        if cands:
            src_file = cands[0]
        else:
            print(f"[错误] 未找到图片文件: {img_filename}")
            return None

    if not dest_dir:
        dest_dir = Path.cwd() / "references" / "poses"
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_file = dest_dir / f"{pose_id}_{view}.webp"
    shutil.copy2(src_file, dest_file)
    print(f"[导出成功] {pose_id} ({view}) -> {dest_file}")
    return dest_file


def main():
    parser = argparse.ArgumentParser(description="Shisei 本地多视角姿态库工具")
    parser.add_argument("--search", type=str, help="关键词搜索姿态")
    parser.add_argument("--duo", action="store_true", help="只筛选双人交互/对峙姿态")
    parser.add_argument("--get", type=str, help="导出指定 ID 的姿态")
    parser.add_argument("--view", type=str, default="front", choices=["front", "side", "diag", "above", "below"], help="选择视角 (默认 front)")
    parser.add_argument("--out", type=str, help="导出目标目录")
    args = parser.parse_args()

    if args.get:
        out_dir = Path(args.out) if args.out else None
        export_pose(args.get, view=args.view, dest_dir=out_dir)
    elif args.search or args.duo:
        search_poses(kw=args.search, is_duo=args.duo)
    else:
        # 默认展示双人姿态前 10 个
        search_poses(is_duo=True, limit=10)


if __name__ == "__main__":
    main()
