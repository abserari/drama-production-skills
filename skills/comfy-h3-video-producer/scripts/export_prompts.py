# -*- coding: utf-8 -*-
"""导出《灯》全片最终提示词为 HTML 手册。
输入：build_ov_deng.py 的 SEGS + progress.json 的 seed/重抽记录
输出：C:/Users/windows/Desktop/视频制作/灯/生产/提示词手册.html
"""
import json, os, sys, html

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_ov_deng as B

PROG = json.load(open("C:/Users/windows/Desktop/视频制作/灯/生产/progress.json", encoding="utf-8"))
meta = {s["id"]: s for s in PROG["segments"]}

# 保持剧本顺序
order = [s["id"] for s in PROG["segments"]]

rows = []
for i, sid in enumerate(order, 1):
    m = meta.get(sid, {})
    if sid not in B.SEGS:
        rows.append({
            "no": i, "id": sid, "title": m.get("title", ""), "frames": m.get("frames", 0),
            "images": m.get("images", []), "seconds": 5.15,
            "subj": "（冒烟测试阶段复用的测试段：该段未走完整提示词流程，成片由早期测试任务产出，剧本对应镜头为「嵌灯点火」。）",
            "summ": "", "det": "",
            "seed": m.get("seed", ""), "reroll": 0,
            "check": m.get("check", "冒烟复用，未单列分镜提示词"),
        })
        continue
    seg = B.SEGS[sid]
    prompt = seg["prompt"]
    # 拆解 P() 拼装出的结构
    def section(name, nxt=None):
        s = prompt.find(name + ":\n")
        if s < 0:
            return ""
        start = s + len(name) + 2
        if nxt:
            e = prompt.find(nxt, start)
            e = len(prompt) if e < 0 else e
        else:
            e = len(prompt)
        return prompt[start:e].strip()
    subj = section("subject_definitions", "summary")
    summ = section("summary", "detailed_description")
    det = section("detailed_description")

    rows.append({
        "no": i, "id": sid, "title": seg["title"], "length": seg["length"],
        "frames": seg["length"], "images": seg["images"],
        "seconds": round((seg["length"] - 3) / 24, 2) if seg["length"] else 0,
        "subj": subj, "summ": summ, "det": det,
        "seed": m.get("seed", ""), "reroll": m.get("reroll", 0),
        "check": m.get("check", ""),
    })

def esc(t):
    return html.escape(t).replace("\n", "<br>")

cards = []
for r in rows:
    reroll = f'<span class="tag warn">重抽 {r["reroll"]} 次</span>' if r["reroll"] else '<span class="tag ok">一次通过</span>'
    check = f'<div class="check"><b>自检结论：</b>{esc(r["check"])}</div>' if r["check"] else ""
    cards.append(f"""
  <section class="card" id="{r['id']}">
    <header>
      <div class="idx">{r['no']:02d}</div>
      <div class="hd">
        <h2>{r['id']} · {esc(r['title'])}</h2>
        <div class="meta">
          <span>时长 {r['seconds']}s（{r['frames']} 帧 @48fps 输出）</span>
          <span>资产：{'、'.join(r['images'])}</span>
          <span>seed {r['seed']}</span>
          {reroll}
        </div>
      </div>
    </header>
    <div class="block"><h3>subject_definitions</h3><p>{esc(r['subj'])}</p></div>
    <div class="block"><h3>summary</h3><p>{esc(r['summ'])}</p></div>
    <div class="block"><h3>detailed_description</h3><p>{esc(r['det'])}</p></div>
    {check}
  </section>""")

doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>《砂上の灯·火種の名》最终提示词手册</title>
<style>
  :root {{ --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --ink:#1c1f23; --sub:#5b626b; --accent:#8a6a2f; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.75 "Microsoft YaHei","PingFang SC",system-ui,sans-serif; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:40px 22px 80px; }}
  h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:.5px; }}
  .lead {{ color:var(--sub); font-size:13.5px; margin-bottom:8px; }}
  .legend {{ background:#fff; border:1px solid var(--line); border-radius:10px;
    padding:14px 18px; margin:22px 0 30px; font-size:13px; color:var(--sub); }}
  .legend b {{ color:var(--ink); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:20px 22px; margin-bottom:18px; }}
  .card header {{ display:flex; gap:14px; align-items:flex-start; }}
  .idx {{ flex:0 0 40px; height:40px; border-radius:9px; background:#efe7d8; color:var(--accent);
    display:flex; align-items:center; justify-content:center; font-weight:700; font-size:15px; }}
  .hd h2 {{ font-size:17px; margin:2px 0 6px; }}
  .meta {{ display:flex; flex-wrap:wrap; gap:8px; font-size:12.5px; color:var(--sub); }}
  .meta span {{ background:#f2f4f6; border-radius:6px; padding:2px 8px; }}
  .tag {{ font-size:12.5px; border-radius:6px; padding:2px 8px; }}
  .tag.ok {{ background:#e7f4ea; color:#2f7a45; }}
  .tag.warn {{ background:#fdeee2; color:#a8631f; }}
  .block {{ margin-top:14px; border-left:3px solid #e8e2d6; padding:2px 0 2px 14px; }}
  .block h3 {{ font-size:12.5px; letter-spacing:.6px; text-transform:uppercase;
    color:var(--accent); margin:0 0 4px; font-weight:700; }}
  .block p {{ margin:0; font-size:14px; }}
  .check {{ margin-top:14px; background:#faf8f4; border:1px dashed #e0d8c8;
    border-radius:8px; padding:9px 12px; font-size:13px; color:#6a6255; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>《砂上の灯 · 火種の名》最终提示词手册</h1>
  <div class="lead">MiniMax H3 · ref2va · 房规三段式（subject_definitions / summary / detailed_description）· 共 {len(rows)} 段</div>
  <div class="legend">
    <b>生成参数：</b>576×320 一采 → 二采解码帧 → 超分 1728×960@48fps 输出；每段长度在正文中标注为帧数（124 帧≈5s，243 帧≈10s）。<br>
    <b>资产调用：</b>@图片N 对应各段「资产」字段列出的本地资产图（命名即调用）；未备资产以文字定义描述。<br>
    <b>自检：</b>每段在一采结束后做定量自检（光流突变 / 直方图场景突变 / 首尾帧相似度）+ 8 格联络表视觉复核；不通过则换随机种子重抽。
  </div>
  {''.join(cards)}
</div>
</body>
</html>"""

out = "C:/Users/windows/Desktop/视频制作/灯/生产/提示词手册.html"
open(out, "w", encoding="utf-8").write(doc)
print("written:", out, len(doc), "chars,", len(rows), "segments")
