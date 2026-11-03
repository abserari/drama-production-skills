# -*- coding: utf-8 -*-
"""台词覆盖率检查：原剧本的每一句台词，到底有没有排进提示词。

为什么要有这个：G1–G6 六道闸门全是「单段内」检查（骨架/节拍/时长/声线/画面/接缝），
没有一道看「跨段叙事链」。结果是《我是元婴》第 1 集把「江家」整条线删掉了 94%，
六道门依然全绿。这个脚本补的就是那一刀：拿剧本原文逐句对提示词，缺一句就列出来。

用法：
  python line_coverage.py --docx 剧本.docx --from 68 --to 115
  python line_coverage.py --docx 剧本.docx --from 68 --to 115 --segs seg04,seg05,seg06
  python line_coverage.py --docx 剧本.docx --from 68 --to 115 --json out.json
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import zipfile

CJK = re.compile(r"[^\u4e00-\u9fa5A-Za-z0-9]")


def norm(s):
    """只留汉字数字字母，用来做跨标点比对（剧本和提示词的分句不一样）。"""
    return CJK.sub("", s or "")


def read_docx_lines(path):
    z = zipfile.ZipFile(path)
    x = z.read("word/document.xml").decode("utf-8")
    paras = re.findall(r"<w:p[ >].*?</w:p>", x, re.S)
    out = []
    for p in paras:
        t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
        t = re.sub(r"<[^>]+>", "", t)
        if t.strip():
            out.append(t.strip())
    return out


def script_lines(lines, lo, hi):
    """取 [lo, hi] 段（含端点，0 基）里的引号台词，保持原顺序。"""
    got = []
    for i in range(lo, min(hi + 1, len(lines))):
        for q in re.findall(r"“([^”]+)”", lines[i]):
            if len(norm(q)) >= 2:
                got.append({"para": i, "text": q})
    return got


def load_segs(build_py, only=None):
    # 提示词生成器可能 import 同目录的兄弟模块（如 scene_home），
    # 不把所在目录放进 sys.path 会 ModuleNotFoundError。
    d = os.path.dirname(os.path.abspath(build_py))
    if d not in sys.path:
        sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location("bp", build_py)
    m = importlib.util.module_from_spec(spec)
    sys.modules["bp"] = m
    spec.loader.exec_module(m)
    out = []
    for d in getattr(m, "SEGS", []):
        seg = d.get("seg")
        if only and seg not in only:
            continue
        said = []
        for b in d.get("beats") or []:
            for t in re.findall(r"<d>(.*?)</d>", b):
                said.append(t)
        # 台词也可能只写在 soundscape 里（不该发生，兜一层）
        for t in re.findall(r"<d>(.*?)</d>", (d.get("soundscape") or "")):
            if t not in said:
                said.append(t)
        out.append({"seg": seg, "ep": d.get("ep"), "lines": said,
                    "dialogue_flag": d.get("dialogue")})
    return out


def cover(script, segs):
    """把每句剧本台词对到提示词里。

    做法：把提示词里所有 <d> 台词收集成归一化块，对每句原台词，找出所有
    「是本句子串」的块，按在原句里的位置排序后首尾拼接；覆盖率达到 90% 就算排入。
    一处命中 = adopted，跨多块/多段 = split。只有覆盖率不足的才是真事故。

    分类：
      adopted   一句话在某一段的台词里完整说完
      split     一句话被拆到多个节拍或多个段（原文标点处断开）——合法
      truncated 只覆盖了一截，剩下的哪儿都找不到——这才是事故
      sfx       极短拟声（咔哒/砰/啪），由音效承载，不算台词
      missing   完全没有
    """
    pool = []
    for s in segs:
        for t in s["lines"]:
            n = norm(t)
            if n:
                pool.append((s["seg"], n))

    rows = []
    # 把所有 <d> 台词拼成一条长串，用「贪心最长匹配」量覆盖率：
    # 能覆盖 = 台词确实排进去了（无论是一段说完、拆两个节拍、还是拆到几段）。
    # 覆盖不到 = 那截话真的没写。
    big = "|".join(txt for _, txt in pool)
    for it in script:
        q = norm(it["text"])
        if len(q) <= 3 and it["text"].strip("。！？…") in ("咔哒", "砰", "啪", "咚", "哗", "咔"):
            rows.append({"para": it["para"], "text": it["text"], "chars": len(q),
                         "seg": None, "how": "sfx"})
            continue
        if not q:
            continue
        i, covered, used_segs = 0, 0, []
        while i < len(q):
            best = 0
            for L in range(len(q) - i, 0, -1):   # 从最长开始试
                chunk = q[i:i + L]
                if chunk in big:
                    best = L
                    break
            if best < 4:                          # 少于 4 字不算命中，避免巧合
                break
            chunk = q[i:i + best]
            for seg, txt in pool:
                if chunk in txt and seg not in used_segs:
                    used_segs.append(seg)
            covered += best
            i += best
        ratio = covered / len(q)
        if ratio >= 0.9:
            uniq = list(dict.fromkeys(used_segs))
            how = "adopted" if len(uniq) == 1 else "split"
        elif len(q) <= 3:
            how = "term"          # 「清月」这类被引号括起来的词，由画面/对白承载，不算台词
        else:
            how = "truncated"
        rows.append({"para": it["para"], "text": it["text"], "chars": len(q),
                     "seg": "+".join(dict.fromkeys(used_segs)) or None,
                     "how": how, "ratio": round(ratio, 2)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docx", required=True)
    ap.add_argument("--from", dest="lo", type=int, required=True, help="起始段落号（0 基）")
    ap.add_argument("--to", dest="hi", type=int, required=True, help="结束段落号（含）")
    ap.add_argument("--build", default="build_prompts.py", help="提示词生成器路径")
    ap.add_argument("--segs", default="", help="只看这些段（逗号分隔）")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    only = {x.strip() for x in a.segs.split(",") if x.strip()} or None
    lines = read_docx_lines(a.docx)
    script = script_lines(lines, a.lo, a.hi)
    segs = load_segs(os.path.abspath(a.build), only)
    rows = cover(script, segs)

    tot = sum(r["chars"] for r in rows)
    ok = [r for r in rows if r["how"] in ("adopted", "split")]
    part = [r for r in rows if r["how"] == "truncated"]
    miss = [r for r in rows if r["how"] == "missing"]

    sfx = [r for r in rows if r["how"] in ("sfx", "term")]
    okc = sum(r["chars"] for r in ok)
    partc = sum(r["chars"] for r in part)

    print(f"剧本段落 {a.lo}–{a.hi}：{len(rows)} 句台词 / {tot} 字")
    print(f"  已排入 {len(ok)} 句 {okc} 字（{okc / tot * 100:.1f}%，含拆到两段的句子）")
    print(f"  只留半句（事故）{len(part)} 句 {partc} 字（{partc / tot * 100:.1f}%）")
    if sfx:
        print(f"  拟声词/被引用的词 {len(sfx)} 处（由音效与画面承载，不计入台词）")
    print(f"  完全缺失 {len(miss)} 句 {sum(r['chars'] for r in miss)} 字"
          f"（{sum(r['chars'] for r in miss) / tot * 100:.1f}%）")
    print(f"  按 4.5 字/秒，本段剧本台词约需 {tot / 4.5:.0f} 秒；"
          f"单段台词上限约 8.8 秒 → 至少 {int(tot / 4.5 / 8.8) + 1} 段\n")

    print("【完全缺失】")
    for r in miss:
        print(f"  段{r['para']:>4}  {r['chars']:>3}字  {r['text'][:70]}")
    if part:
        print("\n【只留半句，剩下的哪儿都找不到 —— 这是事故】")
        for r in part:
            print(f"  段{r['para']:>4}  {r['chars']:>3}字  -> {r['seg']}  {r['text'][:70]}")
    print("\n【已排入】")
    for r in ok:
        print(f"  段{r['para']:>4}  {r['chars']:>3}字  -> {r['seg']}  {r['text'][:60]}")

    if a.json:
        json.dump({"lo": a.lo, "hi": a.hi, "total_chars": tot,
                   "adopted_chars": okc, "partial_chars": partc,
                   "missing_chars": sum(r["chars"] for r in miss),
                   "rows": rows}, open(a.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n[json] {a.json}")

    return 0 if not miss else 1


if __name__ == "__main__":
    sys.exit(main())
