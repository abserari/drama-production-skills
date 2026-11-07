# -*- coding: utf-8 -*-
"""参考图（资产）统计法校验：比例 / 分辨率 / 背景均匀度初筛，不合格打回重生成。
用法：
  $PY asset_check.py --files "cglide/项目/游侠.png" --type character
  $PY asset_check.py --dir "<ComfyUI输入目录>/cglide/<项目>"
判定（WARN 不阻断，交给视觉签字确认；几何类 FAIL 建议重生成）：
  FAIL：偏离所选目标比例（默认16:9或1216:704，±2%）/ 长边低于 --min-edge（默认1024）
  WARN：四角背景均匀度差（影棚背景要求）——可能带环境杂物
说明：只做统计法初筛；「无人/特征可描述/方向盘可见」等内容项靠视觉签字终审。
"""
import os
import sys
import argparse

import cv2
import numpy as np


def _imread(path):
    """cv2.imread 在 Windows 上不支持中文路径，用 fromfile+imdecode 绕开。"""
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


# 合法比例：16:9 与 H3 生产分辨率 1216×704（≈1.727，精简版出片分辨率，非 16:9）
ASPECTS = (16 / 9, 1216 / 704)


def check_one(path, aspect_tol=0.02, bg_tol=12.0, min_edge=1024, aspects=ASPECTS, check_background=True):
    try:
        img = _imread(path)
    except (OSError, ValueError, cv2.error):
        img = None
    if img is None:
        return {"file": path, "fails": ["文件无法读取"], "warns": []}
    h, w = img.shape[:2]
    fails, warns = [], []
    # 1) 比例：命中 16:9 或生产分辨率比例任一
    ratio = w / h
    if all(abs(ratio - r) / r > aspect_tol for r in aspects):
        fails.append(f"比例 {ratio:.3f} 不符合所选目标比例（±{aspect_tol * 100:.0f}%）")
    # 2) 分辨率
    long_edge = max(w, h)
    if long_edge < min_edge:
        fails.append(f"长边 {long_edge}px < {min_edge}")
    # 3) 四角背景均匀度（影棚背景要求：四角区域灰度 std 小且互相接近）
    k = max(1, min(h, w) // 10)
    corners = [img[:k, :k], img[:k, -k:], img[-k:, :k], img[-k:, -k:]]
    means = [float(c.mean()) for c in corners]
    spread = max(means) - min(means)
    if check_background and spread > bg_tol:
        warns.append(f"四角亮度差 {spread:.1f} > {bg_tol}——背景可能带环境杂物或渐变")
    # 4) 整体过暗/过曝
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if gray.mean() < 30:
        warns.append("整图过暗——疑似深底图，影棚模板要求浅色背景")
    if gray.mean() > 250:
        warns.append("整图近全白——可能内容缺失")
    return {"file": path, "size": f"{w}x{h}", "fails": fails, "warns": warns}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="+", help="图片路径（可多个）")
    ap.add_argument("--dir", help="目录：校验全部 png/jpg")
    ap.add_argument('--min-edge', type=int, default=1024, help='资产长边下限，按所选路径配置')
    ap.add_argument('--aspect', type=float, action='append', help='目标宽高比，可重复；默认16:9与1216:704')
    ap.add_argument('--type', choices=('character','scene','prop'), default='character')
    a = ap.parse_args()
    if a.min_edge <= 0 or (a.aspect and any(not np.isfinite(r) or r <= 0 for r in a.aspect)):
        ap.error('min-edge 与 aspect 必须为有限正数')
    files = list(a.files or [])
    if a.dir:
        for fn in sorted(os.listdir(a.dir)):
            if fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                files.append(os.path.join(a.dir, fn))
    if not files:
        raise SystemExit("需要 --files 或 --dir")
    n_fail = 0
    for f in files:
        r = check_one(f, min_edge=a.min_edge, aspects=a.aspect or ASPECTS, check_background=a.type != "scene")
        tag = "FAIL" if r["fails"] else ("WARN" if r["warns"] else "PASS")
        if r["fails"]:
            n_fail += 1
        print(f"[{tag}] {os.path.basename(f)}  {r.get('size', '')}")
        for x in r["fails"]:
            print(f"    ✗ {x}")
        for x in r["warns"]:
            print(f"    ! {x}")
    print(f"\n[asset] {len(files)} 张，{n_fail} FAIL（FAIL 建议重生成；WARN 交视觉签字确认）")

    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
