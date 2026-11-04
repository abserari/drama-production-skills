# -*- coding: utf-8 -*-
"""
语义质检（离线）：CV 特征 + CLIP 帧级判分 → 权重打分 → verdict。
无 VLM：色温曲线 / 主光色占比曲线 / 运动节拍对齐 / 段尾状态 / 拼版粗筛 全部 OpenCV；
物体级一致性由 CLIP 零样本相似度补位（ComfyUI venv 运行，显存 ~0.5GB）。

用法（必须用 ComfyUI venv 的 python，带 torch）：
  <comfy_venv_python> semantic_qc.py --video <一采mp4> --spec <sem.json> --out <outdir> [--qc <qc.json>]

spec（JSON）字段（全部可选，缺省不判）：
{
  "n_beats": 3,                      # 节拍数（默认 3；节拍边界按等分时长近似）
  "beat_bounds": [0.4, 0.75],        # 或显式给节拍边界（时长分数，不含首尾）
  "tone":  {"expect": "cold", "weight": 2},                    # cold / warm
  "light": {"hue": "blue", "appear_by_beat": 2, "hold": true,
            "min_end_frac": 0.015, "weight": 3},               # hue: blue/orange/red/green/cyan
  "motion": {"peak_beats": [1], "quiet_beats": [], "weight": 1},
  "ending": {"light": "blue", "motion": "float", "weight": 2}, # motion: still/float/burst
  "collage": {"weight": 3},                                    # 拼版/参考图泄漏粗筛（硬项）
  "clip": {
     "must": [{"text": "a giant rusty robot", "beats": [0,1,2]}],  # 英文句子（CLIP 英文最优）
     "neg":  ["a real human person", "a collage of multiple views of one object"],
     "weight": 3
  }
}

verdict 规则：硬项（光色缺失/色调背离/neg 占优/拼版）任一触发 → FAIL；
软项加权均分 < 0.6 → WARN；否则 PASS。FAIL/WARN 均落证据（semantic_curves.png + semantic_hits/）。
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

# ── 常量 ────────────────────────────────────────────────────────
N_CURVE = 24          # 曲线采样帧数
N_CLIP = 12           # CLIP 判分帧数（按节拍均分+尾部加密）
HUE_BANDS = {         # OpenCV H ∈ [0,180)，S/V 阈值过滤灰暗像素
    "blue":   (95, 135), "cyan": (80, 95), "green": (35, 85),
    "orange": (10, 25),  "yellow": (20, 35), "red": None,  # red 跨环，特殊处理
}
S_MIN, V_MIN = 0.35, 0.30
# 段尾运动相对带：尾段中位 / 全片中位 的倍率区间（绝对 absdiff 不可跨场景比）
MOTION_RATIO = {"still": (0.0, 0.6), "float": (0.6, 2.0), "burst": (2.0, 1e9)}


def _env(name, default):
    return os.environ.get(name, default)


CLIP_MODEL_NAME = _env("SEM_CLIP_MODEL", "ViT-B-32-quickgelu")
CLIP_PRETRAINED = _env("SEM_CLIP_PRETRAINED", "openai")


def _has_cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


# ── 抽帧 ────────────────────────────────────────────────────────
def open_video(mp4):
    cap = cv2.VideoCapture(mp4)
    if not cap.isOpened():
        raise SystemExit(f"[FATAL] 打不开视频: {mp4}")
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    return cap, fps, n


def grab(cap, idx):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
    ok, img = cap.read()
    return img if ok else None


def sample_indices(n, n_beats, beat_bounds=None, count=N_CLIP):
    """按节拍均分抽帧（每拍 count//n_beats 张，拍内均匀），保证末帧入选。"""
    bounds = (beat_bounds or [i / n_beats for i in range(1, n_beats)])[: n_beats - 1]
    edges = [0.0] + list(bounds) + [1.0]
    idxs = []
    per = max(2, count // n_beats)
    for k in range(n_beats):
        a, b = edges[k], edges[k + 1]
        for j in range(per):
            frac = a + (b - a) * (j + 0.5) / per
            idxs.append(int(frac * (n - 1)))
    idxs.append(n - 1)                      # 尾帧必采
    idxs = sorted(set(i for i in idxs if 0 <= i < n))
    return idxs, edges


def beat_of(frac_t, edges):
    for k in range(len(edges) - 1):
        if edges[k] <= frac_t < edges[k + 1]:
            return k
    return len(edges) - 2


# ── CV 特征 ─────────────────────────────────────────────────────
def tone_curve(imgs):
    """每帧 R-B 均值差：>0 偏暖，<0 偏冷。"""
    out = []
    for img in imgs:
        b, g, r = cv2.split(img.astype(np.float32))
        out.append(float((r - b).mean()))
    return out


def light_curve(imgs, hue):
    """每帧指定色相高饱和亮像素占比 [0,1]。"""
    lo, hi = HUE_BANDS[hue]
    out = []
    for img in imgs:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv.astype(np.float32))
        s /= 255.0; v /= 255.0
        m = (s > S_MIN) & (v > V_MIN)
        if hue == "red":
            m &= (h < 8) | (h > 170)
        else:
            m &= (h >= lo) & (h < hi)
        out.append(float(m.mean()))
    return out


def motion_curve(mp4, n, dens=32):
    """轻量运动曲线：降采样 absdiff 均值（相对量，够做节拍对齐）。"""
    cap, _fps, _n = open_video(mp4)
    idxs = [int(i * (n - 1) / max(1, dens - 1)) for i in range(dens)]
    prev, out = None, []
    for i in idxs:
        img = grab(cap, i)
        if img is None:
            out.append(0.0); continue
        small = cv2.cvtColor(cv2.resize(img, (160, 90)), cv2.COLOR_BGR2GRAY)
        small = cv2.GaussianBlur(small, (3, 3), 0)
        if prev is not None:
            out.append(float(np.abs(small.astype(np.float32) - prev).mean()))
        else:
            out.append(0.0)
        prev = small
    cap.release()
    return idxs, out


def edge_stats(imgs):
    """拼版粗筛：Canny 边缘密度 + 长直线像素占比（多视图拼版两者皆高）。"""
    dens, line = [], []
    for img in imgs:
        g = cv2.cvtColor(cv2.resize(img, (640, 360)), cv2.COLOR_BGR2GRAY)
        e = cv2.Canny(g, 90, 220)
        dens.append(float(e.mean() / 255.0))
        hp = cv2.HoughLinesP(e, 1, np.pi / 2, 60, minLineLength=120, maxLineGap=8)
        vp = cv2.HoughLinesP(e, 1, np.pi / 2 - np.pi / 90, 60, minLineLength=120, maxLineGap=8)
        nline = (0 if hp is None else len(hp)) + (0 if vp is None else len(vp))
        line.append(float(nline))
    return dens, line


# ── CLIP ────────────────────────────────────────────────────────
_CLIP = {}


def clip_encode(imgs):
    import torch
    import open_clip
    if "m" not in _CLIP:
        m, _, pre = open_clip.create_model_and_transforms(CLIP_MODEL_NAME, pretrained=CLIP_PRETRAINED)
        m.eval().to("cuda" if _has_cuda() else "cpu")
        _CLIP["m"], _CLIP["pre"], _CLIP["tok"] = m, pre, open_clip.get_tokenizer(CLIP_MODEL_NAME)
    m, pre = _CLIP["m"], _CLIP["pre"]
    dev = next(m.parameters()).device
    from PIL import Image
    feats = []
    with torch.no_grad():
        for img in imgs:
            pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            t = pre(pil).unsqueeze(0).to(dev)
            f = m.encode_image(t)
            f = f / f.norm(dim=-1, keepdim=True)
            feats.append(f[0].cpu().numpy())
    return np.stack(feats)


def clip_text_sims(texts):
    import torch
    if not texts:
        return np.zeros((0,))
    m = _CLIP["m"]
    dev = next(m.parameters()).device
    with torch.no_grad():
        t = _CLIP["tok"](texts).to(dev)
        e = m.encode_text(t)
        e = e / e.norm(dim=-1, keepdim=True)
    return e.cpu().numpy()


# ── 证据图 ──────────────────────────────────────────────────────
def draw_curves(path, curves, edges, n):
    """把各条曲线画到一张画布上（归一化各自 0-1），节拍边界画竖线。"""
    W, H = 1200, 400
    canvas = np.full((H, W, 3), 245, np.uint8)
    names = {"light": (200, 60, 20), "tone": (30, 90, 220), "motion": (60, 160, 60)}
    for name, vals in curves.items():
        if not vals:
            continue
        a, b = min(vals), max(vals)
        rng = (b - a) or 1.0
        pts = [(int(i / max(1, len(vals) - 1) * (W - 40)) + 20,
                H - 40 - int((v - a) / rng * (H - 80))) for i, v in enumerate(vals)]
        for p, q in zip(pts, pts[1:]):
            cv2.line(canvas, p, q, names.get(name, (90, 90, 90)), 2)
    for frac in edges[1:-1]:
        x = int(frac * (W - 40)) + 20
        cv2.line(canvas, (x, 10), (x, H - 10), (150, 150, 150), 1, cv2.LINE_AA)
    y0 = 22
    for name, vals in curves.items():
        cv2.putText(canvas, name, (24, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    names.get(name, (90, 90, 90)), 1, cv2.LINE_AA)
        y0 += 22
    cv2.imwrite(path, canvas)


# ── 打分 ────────────────────────────────────────────────────────
def run(video, spec, out_dir, qc_path=None):
    os.makedirs(out_dir, exist_ok=True)
    hits = []
    cap, fps, n = open_video(video)
    dur = n / fps
    n_beats = int(spec.get("n_beats", 3))
    idxs, edges = sample_indices(n, n_beats, spec.get("beat_bounds"))
    imgs = []
    for i in idxs:
        im = grab(cap, i)
        if im is not None:
            imgs.append(im)
    cap.release()
    fracs = [i / max(1, n - 1) for i in idxs]
    beats = [beat_of(f, edges) for f in fracs]

    report = {"video": video, "dur": round(dur, 2), "n_frames": n,
              "spec": spec, "items": [], "verdict": "PASS", "fails": [], "warns": []}

    def item(name, hard, ok, detail):
        report["items"].append({"name": name, "hard": bool(hard), "ok": bool(ok), "detail": detail})
        if not ok:
            (report["fails"] if hard else report["warns"]).append(f"{name}: {detail}")

    curves = {}
    # 1) 色调（软项：地面暖尘/暖色道具会把 R-B 整体抬高，硬判误伤率高）
    if spec.get("tone"):
        tc = tone_curve(imgs)
        curves["tone"] = tc
        med = float(np.median(tc))
        want = spec["tone"].get("expect", "cold")
        margin = 8.0
        ok = (med < margin) if want == "cold" else (med > -margin)
        item("tone", False, ok, f"期望{want}，实测中位 R-B={med:+.1f}")
    # 2) 主光色
    if spec.get("light"):
        hue = spec["light"]["hue"]
        lc = light_curve(imgs, hue)
        curves["light"] = [v * 100 for v in lc]
        appear = spec["light"].get("appear_by_beat", 1)
        hold = spec["light"].get("hold", True)
        min_end = float(spec["light"].get("min_end_frac", 0.004))
        peak_after = max((v for v, b in zip(lc, beats) if b >= appear - 1), default=0.0)
        end_mean = float(np.mean(lc[-max(2, N_CLIP // 6):]))
        ok = end_mean >= min_end and (not hold or peak_after >= min_end)
        item(f"light_{hue}", True, ok,
             f"尾段均值 {end_mean:.4f} (阈值 {min_end})，出现后峰值 {peak_after:.4f}")
    # 3) 运动节拍
    if spec.get("motion"):
        midxs, mc = motion_curve(video, n)
        curves["motion"] = mc
        mfracs = [i / max(1, n - 1) for i in midxs]
        mbeats = [beat_of(f, edges) for f in mfracs]
        byb = {}
        for v, b in zip(mc, mbeats):
            byb.setdefault(b, []).append(v)
        pk = spec["motion"].get("peak_beats", [])
        qt = spec["motion"].get("quiet_beats", [])
        detail, ok = [], True
        for b in pk:
            others = [v for bb, vs in byb.items() if bb != b for v in vs]
            if byb.get(b) and others and max(byb[b]) < float(np.median(others)) * 1.3:
                ok = False; detail.append(f"节拍{b+1}应有运动峰但未见")
        for b in qt:
            others = [v for bb, vs in byb.items() if bb != b for v in vs]
            if byb.get(b) and others and float(np.median(byb[b])) > float(np.median(others)):
                ok = False; detail.append(f"节拍{b+1}应安静但运动量不低于其他拍")
        item("motion", False, ok, "; ".join(detail) or "节拍对齐符合")
    # 4) 段尾状态
    if spec.get("ending"):
        e = spec["ending"]
        ok, detail = True, []
        if e.get("light"):
            lc_e = light_curve(imgs[-max(2, N_CLIP // 6):], e["light"])
            m = float(np.mean(lc_e))
            if m < float(e.get("min_end_frac", 0.004)):
                ok = False; detail.append(f"结尾{e['light']}光不足({m:.4f})")
        mv = e.get("motion")
        if mv:
            _i, mc2 = motion_curve(video, n, dens=40)
            tail = mc2[-max(3, 40 // 10):]
            tmed = float(np.median(tail))
            gmed = float(np.median([v for v in mc2 if v > 0])) or 1e-9
            lo, hi = MOTION_RATIO[mv]
            ratio = tmed / gmed
            if not (lo <= ratio <= hi):
                ok = False; detail.append(f"结尾运动[{mv}]倍率带外({ratio:.2f}×全片中位)")
        item("ending", False, ok, "; ".join(detail) or "段尾状态符合")
    # 5) 拼版粗筛
    if spec.get("collage"):
        dens, lines = edge_stats(imgs)
        d_med, l_max = float(np.median(dens)), float(np.max(lines))
        ok = not (d_med > 0.16 and l_max > 40)
        item("collage", True, ok, f"边缘密度中位 {d_med:.3f} / 单帧最长直线 {l_max:.0f}")
    # 6) CLIP 帧级判分
    if spec.get("clip") and imgs:
        c = spec["clip"]
        must = [m["text"] for m in c.get("must", [])]
        must_beats = [m.get("beats") for m in c.get("must", [])]
        neg = c.get("neg", [])
        f_img = clip_encode(imgs)
        sims_m = clip_text_sims(must) if must else np.zeros((0, len(imgs)))
        sims_n = clip_text_sims(neg) if neg else np.zeros((0, len(imgs)))
        if len(sims_m) and len(sims_n):
            per_m = sims_m @ f_img.T          # [n_must, n_frames]
            per_n = sims_n @ f_img.T          # [n_neg, n_frames]
            # 正例：按归属节拍的帧求均值，对比 neg 均值
            margins = []
            for mi, bl in enumerate(must_beats):
                sel = [j for j, b in enumerate(beats) if bl is None or b in bl]
                if sel:
                    margins.append(float(per_m[mi, sel].mean() - per_n[:, sel].mean()))
            pos_margin = float(np.mean(margins)) if margins else 0.0
            # 负例：逐帧 neg 是否压过全部 must（隔离物体级错误）
            best_must = per_m.max(axis=0)
            worst_neg = per_n.max(axis=0)
            neg_hits = [j for j in range(len(imgs)) if worst_neg[j] - best_must[j] > 0.015]
            neg_rate = len(neg_hits) / len(imgs)
            ok = pos_margin > 0.0 and neg_rate <= 0.25
            item("clip", True, ok,
                 f"正例余量 {pos_margin:+.3f}，neg 占优帧 {len(neg_hits)}/{len(imgs)}")
            for j in neg_hits[:4]:
                p = os.path.join(out_dir, "semantic_hits")
                os.makedirs(p, exist_ok=True)
                cv2.imwrite(os.path.join(p, f"neg_f{idxs[j]}.jpg"), imgs[j],
                            [cv2.IMWRITE_JPEG_QUALITY, 88])
                hits.append(f"neg@f{idxs[j]}")
            report["clip_detail"] = {
                "must_margin": round(pos_margin, 3), "neg_rate": round(neg_rate, 3),
                "neg_hits": hits}

    # 汇总
    soft = [it for it in report["items"] if not it["hard"]]
    if soft:
        wmean = float(np.mean([1.0 if it["ok"] else 0.0 for it in soft]))
        if wmean < 0.6 and not report["fails"]:
            report["warns"].append(f"软项加权均分 {wmean:.2f} < 0.6")
    if report["fails"]:
        report["verdict"] = "FAIL"
    elif report["warns"]:
        report["verdict"] = "WARN"
    draw_curves(os.path.join(out_dir, "semantic_curves.png"), curves, edges, n)
    with open(os.path.join(out_dir, "semantic.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"[SEMANTIC] {report['verdict']} | " +
          " | ".join(f"{it['name']}={'OK' if it['ok'] else 'X'}" for it in report["items"]))
    return report


def main():
    ap = argparse.ArgumentParser(description="语义质检（CV+CLIP 离线判卷）")
    ap.add_argument("--video", required=True)
    ap.add_argument("--spec", required=True, help="sem spec json（判卷清单）")
    ap.add_argument("--out", required=True, help="证据输出目录")
    ap.add_argument("--qc", help="可选 qc.json（预留：复用其 flow_series）")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    rep = run(a.video, spec, a.out, qc_path=a.qc)
    sys.exit(0 if rep["verdict"] == "PASS" else (2 if rep["verdict"] == "WARN" else 1))


if __name__ == "__main__":
    main()
