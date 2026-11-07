# -*- coding: utf-8 -*-
"""从分镜方案 markdown 里抽取 ```shots-json 机读块，落盘成
<项目>/storyboard.json。镜→段的归组仍由编排层按 directing_bridge §6 做，
本脚本只做"表格 → 机器可读"这一步，不做任何创作判断。
（机读块格式定义见 references/directing/director_advisor_skill_archive.md 的「机读块」节）

用法：
  python storyboard_json.py --md <分镜方案.md> --out <项目>/storyboard.json
  （--out 缺省写到 ./storyboard.json）
"""
import math
import argparse
import json
import os
import re
import sys

from production_state import atomic_json


def extract(md_path):
    text = open(md_path, encoding="utf-8").read()
    # 容错：```shots-json 或 ``` shots-json；取最后一个块（多次修订以最后一次为准）
    blocks = re.findall(r"```[ \t]*shots-json\s*\n(.*?)```", text, re.S)
    if not blocks:
        raise SystemExit("[FATAL] md 里没有 ```shots-json 机读块——"
                         "请按 references/directing/director_advisor_skill_archive.md"
                         "「机读块」节补一个再跑")
    raw = blocks[-1].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"[FATAL] 机读块不是合法 JSON: {e}\n前 200 字: {raw[:200]}")
    if not isinstance(data, dict):
        raise SystemExit("[FATAL] 机读块必须是 JSON 对象")
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        raise SystemExit("[FATAL] 机读块缺 shots 数组或为空")
    req = ("no", "size", "camera", "content", "sec", "transition")
    seen = set()
    for i, s in enumerate(shots):
        if not isinstance(s, dict):
            raise SystemExit(f"[FATAL] 第 {i+1} 镜不是对象")
        miss = [k for k in req if k not in s]
        if miss:
            raise SystemExit(f"[FATAL] 第 {i+1} 镜缺字段: {miss}（字段须与分镜表逐列对应）")
        if isinstance(s['sec'], bool) or not isinstance(s['sec'], (int, float)) or not math.isfinite(s['sec']) or s['sec'] <= 0:
            raise SystemExit(f"[FATAL] 第 {i+1} 镜时长必须是有限正数")
        if isinstance(s['no'], bool) or not isinstance(s['no'], (str, int)) or not str(s['no']).strip() or str(s['no']) in seen:
            raise SystemExit(f"[FATAL] 第 {i+1} 镜号缺失或重复")
        seen.add(str(s['no']))
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    data = extract(a.md)
    out = a.out or "storyboard.json"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    atomic_json(out, data)
    print(f"[OK] {len(data['shots'])} 镜 → {out}")
    print("[next] 按 directing_bridge §6 归组成段，把每段的 shot 范围填进 plan.json 的 shots 字段；"
          "storyboard.json 留作写 <seg>.txt 节拍时的镜级底稿。")


if __name__ == "__main__":
    main()
