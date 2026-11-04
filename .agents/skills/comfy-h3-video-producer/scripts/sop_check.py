# -*- coding: utf-8 -*-
"""定量自检模块：一采 MP4 -> 抽帧 + 光流/直方图分析 (SOP 模块1/2/3 的量化部分)。

输出:
  frames/  首帧、中间帧、尾帧、联络表(8格) PNG
  beat_sheet.png + evidence_pack.md  节拍锚定证据包（逐拍 起/中/末 三帧 + 期望动作）
  metrics  dict: 光流异常、直方图突变、首尾帧差异、尾拍运动能量等

v3.3 新增三道语义向检测（应对"定量全 PASS、成片全是废片"）：
  A. tail_motion_check  尾拍运动能量：尾拍窗口有动作、运动量却远低于全段 → 疑似结尾动作未执行
  B. seam_similarity    段间接缝：上一段交付片尾帧 vs 本段一采首帧（续接钉帧应≈复制尾帧）
  C. extract_beat_sheet 节拍证据包：检测和期望脱钩是根因，把 [节拍 N] 的期望动作带进复核
光流判据已做**切点感知**：硬切处的光流尖峰是正常镜头切换，不再计入瞬移。
"""
import os
import re

import cv2
import numpy as np

FLOW_JUMP_RATIO = 6.0      # 单秒位移 p99 超过 全片中位数 x 该倍数 -> 疑似瞬移/跳切
FLOW_ABS_LIMIT = 0.55      # 或 p99 超过 画面宽度 x 该比例 -> 直接异常
HIST_DROP = 0.45           # 相邻秒直方图相关性 < 该值 -> 疑似场景/环境突变
SAMPLE_SEC = 1.0           # 每秒取1帧做光流序列

# A 尾拍运动能量：尾拍窗口 mean flow 低于 全段中位数 x 该倍数（或绝对下限）→ flag
# 口径（合成+实拍噪声底校准）：真实视频的静止段 flow 噪声底约 0.4-0.8（320宽尺度），
# 比例阈值取 0.5 抓"尾拍该动没动"；绝对下限 0.45 防整段低运动的安静对话段误报。
TAIL_FLOW_RATIO = 0.5
TAIL_FLOW_ABS = 0.45      # 320 宽尺度的绝对下限
# 静态结尾标记：末拍正文或 [结尾状态] 含这些词时不做"结尾动作未执行"判定
STATIC_MARKERS = ("静止", "定格", "不动", "保持", "停在", "定住", "悬停", "沉默", "站定", "坐定",
                  # v3.7：[结尾状态] 的"回归式"语义同样是静止收尾（空镜/前兆段常用），
                  # 如"光柱恢复暖橙""红色反光渐隐/消失""尘埃浮动放缓"——尾拍低运动符合设计
                  "恢复", "渐隐", "渐暗", "消失", "熄灭", "回落", "放缓", "平息", "回归", "归寂",
                  # v3.7.1："远去型"收尾（蓝光移向深处/身影渐小）运动投影天然减小，
                  # 低尾拍运动是物理必然，与"该动没动"（如没关门）不会在结尾状态里用这些词
                  "深处", "远去", "隐没", "渐小", "远离")

# B 段间接缝：续接钉帧本质是上一段尾帧的复现，相似度应接近 1；低于任一阈值判断裂
SEAM_FRAME_MIN = 0.45
SEAM_HIST_MIN = 0.45

# C' 烧入字幕/水印检测（零下载统计法，2026-11-01）：H3 偶尔把台词字幕/水印烧进画面，
# 交付就是事故。判据（无 OCR）：
#   字幕 = 底部条带内「高亮度+低饱和+高梯度」文字像素占比超标，且逐帧出现/消失（对白开关）；
#   水印 = 画面中「恒定不变」的文字像素区（所有采样帧都有、位置固定）。
# 判疑似只 WARN 不阻断（统计法有误报，交人工看证据帧确认）。
SUB_BAND_RATIO = 0.24      # 底部条带高度占画面比例
SUB_DENSITY_WARN = 0.012   # 条带内文字像素占比超过该值 → 该帧判"有文字"
SUB_FRAME_MIN = 0.30       # ≥30% 采样帧有文字 → 疑似字幕
SUB_SAMPLE_N = 8


def _text_mask(img):
    """文字像素掩码：近白（V 高、S 低）且局部梯度大。字幕水印都是这个形态，
    画面里大面积的白色物体（墙/雪）梯度低、会被梯度条件滤掉。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2].astype(np.float32)
    s = hsv[:, :, 1].astype(np.float32)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.abs(gx) + np.abs(gy)
    return ((v > 190) & (s < 80) & (grad > 60)).astype(np.uint8)


def subtitle_check_frames(imgs, idxs=None):
    """字幕/水印检测的**纯函数版**（金样本重放入口，v3.9）：
    输入已抽好的 BGR 帧列表（原始分辨率即可，内部自行缩放），返回检测 dict。
    命中时 evidence 为内存图（evidence_img 字段），不落盘——落盘是 wrapper 的职责。
    idxs 可选，与 imgs 对齐的帧号，用于标注 evidence_frame。"""
    band_dens, wm_masks, evidence, ev_i = [], [], None, -1
    for k, img in enumerate(imgs):
        h, w = img.shape[:2]
        small = cv2.resize(img, (640, int(h * 640 / w))) if w > 640 else img
        m = _text_mask(small)
        hs, ws = m.shape
        band = m[int(hs * (1 - SUB_BAND_RATIO)):int(hs * 0.99), int(ws * 0.08):int(ws * 0.92)]
        band_dens.append(float(band.mean()))
        wm_masks.append(m)
        if evidence is None or band_dens[-1] >= max(band_dens):
            evidence = small.copy()
            ev_i = k
    res = {"sampled": len(band_dens), "suspicious_subtitle": False,
           "suspicious_watermark": False, "evidence": None, "note": ""}
    if not band_dens:
        res["note"] = "抽帧失败，未检测"
        return res
    hit = [d for d in band_dens if d > SUB_DENSITY_WARN]
    if len(hit) >= max(2, int(len(band_dens) * SUB_FRAME_MIN)):
        res["suspicious_subtitle"] = True
        res["note"] = (f"底部条带 {len(hit)}/{len(band_dens)} 帧检出文字状像素"
                       f"（峰值密度 {max(band_dens):.3f}）——疑似 H3 烧入台词字幕")
    # 恒定水印：所有帧掩码取交集，交集非零面积集中在小区域
    if len(wm_masks) >= 4:
        inter = wm_masks[0]
        for m in wm_masks[1:]:
            inter = inter & m
        area = float(inter.mean())
        if area > 2e-4:   # 交集占画面 0.02% 以上（一行水印的量级）
            res["suspicious_watermark"] = True
            res["note"] = ((res["note"] + "；") if res["note"] else "") + \
                f"检测到恒定文字区（交集面积 {area:.4f}）——疑似烧入水印"
    if res["suspicious_subtitle"] or res["suspicious_watermark"]:
        cv2.rectangle(evidence, (int(evidence.shape[1] * 0.08), int(evidence.shape[0] * (1 - SUB_BAND_RATIO))),
                      (int(evidence.shape[1] * 0.92), evidence.shape[0] - 2), (0, 0, 255), 2)
        res["evidence_img"] = evidence
        if idxs and 0 <= ev_i < len(idxs):
            res["frame_idx"] = idxs[ev_i]
    return res


def subtitle_check(mp4, out_dir):
    """检测烧入字幕（底部条带时有时无的白色文字块）与恒定水印。返回 dict。"""
    cap, fps, n = _open(mp4)
    idxs = sorted({int(i * (n - 1) / max(1, SUB_SAMPLE_N - 1)) for i in range(SUB_SAMPLE_N)})
    imgs, taken = [], []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, img = cap.read()
        if ok:
            imgs.append(img)
            taken.append(i)
    cap.release()
    res = subtitle_check_frames(imgs, idxs=taken)
    if res.get("evidence_img") is not None:
        p = os.path.join(out_dir, "subtitle_evidence.png")
        _imwrite(p, res.pop("evidence_img"))
        res["evidence"] = p
    return res


def _open(mp4):
    cap = cv2.VideoCapture(mp4)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {mp4}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if n <= 0:
        # 某些编码/容器读不到帧数（实测 mp4v 返回 0）：顺序读完计数。
        # 不兜底的话"尾帧"会取成第 0 帧，首尾相似度/接缝比对全部失真。
        n = 0
        while True:
            ok, _img = cap.read()
            if not ok:
                break
            n += 1
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return cap, fps, n


def _grab(cap, idx, target_w=720):
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, img = cap.read()
    if not ok:
        return None
    h, w = img.shape[:2]
    if w > target_w:
        img = cv2.resize(img, (target_w, int(h * target_w / w)))
    return img


def _imwrite(path, img):
    """cv2.imwrite 在 Windows 上遇到中文路径会**静默失败**（返回 False 不抛错）——
    工程目录叫「我是元婴」这种名字时，抽帧全部落不了盘，视觉复核就成了睁眼瞎。
    统一走 imencode + 二进制写，绕开 OpenCV 的文件名编码限制。"""
    ok, buf = cv2.imencode(os.path.splitext(path)[1] or ".png", img)
    if not ok:
        raise IOError(f"编码失败: {path}")
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    return True


def extract_frames(mp4, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    cap, fps, n = _open(mp4)
    picks = {"first": 0, "mid": max(0, n // 2), "last": max(0, n - 1)}
    paths = {}
    for name, idx in picks.items():
        img = _grab(cap, idx)
        if img is not None:
            p = os.path.join(out_dir, f"frame_{name}_{idx}.png")
            _imwrite(p, img)
            paths[name] = {"path": p, "frame_idx": idx}
    # 联络表: 8 帧均布
    if n > 8:
        cells = []
        for i in range(8):
            img = _grab(cap, int(i * (n - 1) / 7), target_w=360)
            if img is not None:
                cv2.putText(img, f"t={i * (n - 1) / 7 / fps:.1f}s", (8, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                cells.append(img)
        if cells:
            def pad(cs, k=4):
                return cs + [np.full_like(cells[0], 0)] * (k - len(cs))
            grid = np.hstack(pad(cells[:4]))
            grid2 = np.hstack(pad(cells[4:8]))
            sheet = np.vstack([grid, grid2])
            p = os.path.join(out_dir, "contact_sheet.png")
            _imwrite(p, sheet)
            paths["sheet"] = {"path": p, "frame_idx": -1}
    cap.release()
    return paths, fps, n


def analyze_sequence(mp4):
    """每 SAMPLE_SEC 秒取一帧（低分辨率），做稠密光流 + 直方图相关。"""
    cap, fps, n = _open(mp4)
    step = max(1, int(fps * SAMPLE_SEC))
    frames = []
    idx = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if idx % step == 0:
            small = cv2.resize(img, (320, 180))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hsv_hist = cv2.calcHist([small], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
            cv2.normalize(hsv_hist, hsv_hist)
            frames.append({"idx": idx, "t": idx / fps, "gray": gray, "hist": hsv_hist})
        idx += 1
        if idx >= n:
            break
    cap.release()

    flow_series, hist_series = [], []
    for a, b in zip(frames, frames[1:]):
        fl = cv2.calcOpticalFlowFarneback(a["gray"], b["gray"], None, 0.5, 2, 21, 2, 5, 1.2, 0)
        mag = np.linalg.norm(fl, axis=2)  # 单位: 像素(320宽尺度)
        flow_series.append({"t": b["t"], "mean": round(float(mag.mean()), 2),
                            "p99": round(float(np.percentile(mag, 99)), 2)})
        hist_series.append({"t": b["t"],
                            "corr": round(float(cv2.compareHist(a["hist"], b["hist"], cv2.HISTCMP_CORREL)), 3)})

    flags = {"teleport_jumpcut": [], "scene_change": []}
    if flow_series:
        meds = np.median([f["p99"] for f in flow_series]) or 1.0
        for f in flow_series:
            if f["p99"] > meds * FLOW_JUMP_RATIO and f["p99"] > FLOW_ABS_LIMIT * 320:
                flags["teleport_jumpcut"].append(f)
    for h in hist_series:
        if h["corr"] < HIST_DROP:
            flags["scene_change"].append(h)
    return {"flow_series": flow_series, "hist_series": hist_series,
            "flags": flags, "sample_count": len(frames)}


def first_last_similarity(mp4):
    """首尾帧像素级相似度（FLF2V 断裂辅助判据; ref2v 模式仅作参考）。"""
    cap, fps, n = _open(mp4)
    a, b = _grab(cap, 0), _grab(cap, max(0, n - 1))
    cap.release()
    if a is None or b is None or a.shape != b.shape:
        return None
    ga, gb = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    ssim_like = float(cv2.matchTemplate(ga, gb, cv2.TM_CCOEFF_NORMED)[0][0])
    return round(max(-1.0, min(1.0, ssim_like)), 3)


# ── 节拍解析（检测期望值的来源：segments/<seg>.txt 的 [节拍 N] 结构）──
def parse_beats(txt_path):
    """从提示词 txt 提取节拍列表 [{n, text}]。text = [节拍 N] 到 音效： 行之间的正文
    （去掉 <Audio N> 声线卡行和标签），作为该拍的期望动作/事件描述。"""
    if not txt_path or not os.path.isfile(txt_path):
        return []
    try:
        src = open(txt_path, encoding="utf-8").read()
    except Exception:
        return []
    beats = []
    parts = re.split(r"\[节拍 (\d+)\]", src)
    for i in range(1, len(parts) - 1, 2):
        body = parts[i + 1].split("音效：", 1)[0]
        lines = [ln for ln in body.splitlines() if not ln.strip().startswith("<Audio")]
        text = " ".join(" ".join(lines).split())
        beats.append({"n": int(parts[i]), "text": text})
    return beats


def parse_ending(txt_path):
    """提取 [结尾状态] 正文，用于静态结尾判定。"""
    if not txt_path or not os.path.isfile(txt_path):
        return ""
    try:
        src = open(txt_path, encoding="utf-8").read()
    except Exception:
        return ""
    if "[结尾状态]" not in src:
        return ""
    return " ".join(src.split("[结尾状态]", 1)[1].split())


# ── A. 尾拍运动能量：结尾该做的动作没做（最高频废片原因）──
def tail_motion_check(seq, beats, ending=""):
    """尾拍窗口的平均运动量远低于全段中位、且该拍文本不是静态结尾 → 疑似动作未执行。

    静态结尾（提示词末拍/[结尾状态] 写了 静止/定格/保持 等）是合法画面，不判。
    """
    flow = (seq or {}).get("flow_series") or []
    if not flow or not beats:
        return None
    total_t = flow[-1]["t"]
    t0 = total_t * (len(beats) - 1) / len(beats)
    tail = [f for f in flow if f["t"] > t0 + 1e-6]
    if not tail:
        return None
    med = float(np.median([f["mean"] for f in flow]))
    tail_mean = float(np.mean([f["mean"] for f in tail]))
    static = any(m in (beats[-1]["text"] + " " + ending) for m in STATIC_MARKERS)
    hit = (not static) and med > 0 and tail_mean < max(med * TAIL_FLOW_RATIO, TAIL_FLOW_ABS)
    return {"t0": round(t0, 2), "tail_mean": round(tail_mean, 3),
            "all_median": round(med, 3), "static_ending": static,
            "verdict": "FAIL" if hit else "OK",
            "note": ("尾拍窗口(%.1fs后)平均运动量 %.2f 远低于全段中位 %.2f，且该拍不是静态结尾"
                     " → 疑似「结尾该做的动作没做」（见 SKILL §8：删竞争动作/前移/状态型死条款）"
                     % (t0, tail_mean, med)) if hit else ""}


# ── B. 段间接缝：续接钉帧应≈上一段尾帧的复现 ──
def seam_from_images(a, b):
    """接缝比对的**纯函数版**（金样本重放入口，v3.9）：输入两张 BGR 帧
    （上段尾帧 a、本段首帧 b），返回 frame_corr/hist_corr。"""
    if b is None:
        return None
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    frame_corr = float(cv2.matchTemplate(ga, gb, cv2.TM_CCOEFF_NORMED)[0][0])
    ha = cv2.calcHist([a], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    hb = cv2.calcHist([b], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    cv2.normalize(ha, ha)
    cv2.normalize(hb, hb)
    hist_corr = float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))
    return {"frame_corr": round(max(-1.0, min(1.0, frame_corr)), 3),
            "hist_corr": round(max(-1.0, min(1.0, hist_corr)), 3)}


def seam_similarity(prev_mp4, cur_mp4, out_dir=None):
    """上一段交付片尾帧 vs 本段一采首帧。一采头部含续接钉帧（未裁刀口），
    钉帧接得上时相似度接近 1；续接失效（latent 没接上/钉帧不生效）会显著偏低。
    可选把并排对照图写进 out_dir/seam_pair.png 供人工确认。"""
    cap, _fps, n_prev = _open(prev_mp4)
    a = _grab(cap, max(0, n_prev - 1))
    cap.release()
    cap, _fps, _n = _open(cur_mp4)
    b = _grab(cap, 0)
    cap.release()
    r = seam_from_images(a, b)
    if r is None:
        return None
    if out_dir:
        try:
            os.makedirs(out_dir, exist_ok=True)
            _imwrite(os.path.join(out_dir, "seam_pair.png"), np.hstack([a, b]))
        except Exception:
            pass
    return {"prev": prev_mp4, "frame_corr": r["frame_corr"], "hist_corr": r["hist_corr"]}


def color_stats(mp4, samples=24):
    """整段均匀抽 samples 帧，返回均值色彩统计（v3.10.2，段间色彩漂移量化 EXP-03）。

    背景：每段独立 VAE decode，段间存在轻微曝光/色彩偏移累积（社区实测）。本函数
    只做纯统计输出（记录不判定），不参与任何 PASS/FAIL。返回 None 表示无法读取。"""
    cap, _fps, n = _open(mp4)
    if not n:
        cap.release()
        return None
    if n > 1:
        idxs = [int(round(i * (n - 1) / max(1, samples - 1))) for i in range(samples)]
    else:
        idxs = [0]
    sums = np.zeros(3, dtype=np.float64)
    v_sum = s_sum = 0.0
    cnt = 0
    for idx in idxs:
        img = _grab(cap, idx)
        if img is None:
            continue
        sums += img.reshape(-1, 3).mean(axis=0)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        v_sum += float(hsv[..., 2].mean())
        s_sum += float(hsv[..., 1].mean())
        cnt += 1
    cap.release()
    if not cnt:
        return None
    return {"bgr_mean": [round(x, 2) for x in (sums / cnt).tolist()],
            "v_mean": round(v_sum / cnt, 2),
            "s_mean": round(s_sum / cnt, 2),
            "frames_sampled": cnt}


# ── C. 节拍锚定证据包：让复核从"看 8 格猜"变成"逐拍对答案" ──
def extract_beat_sheet(mp4, out_dir, beats, target_w=480):
    """每拍一行 = 起(s)/中(m)/末(e) 三帧（480px）。行标 B<拍号>（cv2 画不了中文，
    期望动作写在 evidence_pack.md 里对照着看）。"""
    if not beats:
        return None
    cap, fps, n = _open(mp4)
    nb = len(beats)
    rows, info = [], []
    for bi, b in enumerate(beats):
        f0 = int(round(bi * (n - 1) / nb))
        f1 = int(round((bi + 1) * (n - 1) / nb))
        picks = [("s", f0), ("m", (f0 + f1) // 2), ("e", min(f1, n - 1))]
        cells = []
        for lab, idx in picks:
            img = _grab(cap, idx, target_w=target_w)
            if img is None:
                continue
            cv2.putText(img, "B%d %s %.1fs" % (b["n"], lab, idx / fps), (8, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
            cells.append(img)
        if len(cells) == 3:
            rows.append(np.hstack(cells))
            info.append({"beat": b["n"], "start": f0, "mid": (f0 + f1) // 2, "end": f1})
    cap.release()
    if not rows:
        return None
    w = min(r.shape[1] for r in rows)
    rows = [r if r.shape[1] == w else cv2.resize(r, (w, int(r.shape[0] * w / r.shape[1])))
            for r in rows]
    p = os.path.join(out_dir, "beat_sheet.png")
    _imwrite(p, np.vstack(rows))
    return {"path": p, "rows": info}


def write_evidence_pack(out_dir, beats, tail):
    """逐拍复核的"答案卷"：每拍的期望动作 + 检查口径。"""
    if not beats:
        return None
    p = os.path.join(out_dir, "evidence_pack.md")
    lines = ["# 节拍证据包（逐拍复核）", "",
             "打开同目录 `beat_sheet.png`：每拍一行 = 起(s)/中(m)/末(e) 三帧。",
             "逐行核对：该拍期望动作是否发生、结束时是否停在正确状态；",
             "再按 8 类严重错误（身份漂移/瞬移穿模/因果断裂/运镜矛盾/场景突变/"
             "首尾断裂/数量突变/背离提示词）+ 烧字幕排查过一遍。", ""]
    for b in beats:
        lines.append("## 拍 %d" % b["n"])
        lines.append("")
        lines.append("- 期望: " + (b["text"] or "（未提取到正文）"))
        lines.append("")
    if tail:
        lines.append("## 尾拍运动能量")
        lines.append("")
        lines.append("- " + (tail.get("note") or
                             "尾拍窗口运动量正常（%s，尾均 %.2f / 全段中位 %.2f）"
                             % (tail.get("verdict"), tail.get("tail_mean", 0),
                                tail.get("all_median", 0))))
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return p


def run(mp4, out_dir, beats=None, ending=""):
    os.makedirs(out_dir, exist_ok=True)
    frames, fps, n = extract_frames(mp4, out_dir)
    seq = analyze_sequence(mp4)
    # 切点感知：硬切处的光流尖峰是正常镜头切换（直方图突变点附近 ±0.6s 不计瞬移）
    cut_ts = [h["t"] for h in seq["flags"].get("scene_change") or []]
    if cut_ts:
        seq["flags"]["teleport_jumpcut"] = [
            f for f in seq["flags"].get("teleport_jumpcut") or []
            if not any(abs(f["t"] - t) <= 0.6 for t in cut_ts)]
    fl_sim = first_last_similarity(mp4)
    tail = tail_motion_check(seq, beats, ending) if beats else None
    sheet = extract_beat_sheet(mp4, out_dir, beats) if beats else None
    pack = write_evidence_pack(out_dir, beats, tail) if beats else None
    try:
        subs = subtitle_check(mp4, out_dir)
    except Exception as e:
        subs = {"note": f"检测异常跳过: {e}", "suspicious_subtitle": False,
                "suspicious_watermark": False, "evidence": None}
    return {"video": mp4, "fps": fps, "frames": n,
            "extracted": frames, "sequence": seq, "first_last_sim": fl_sim,
            "beat_sheet": sheet, "evidence_pack": pack, "tail_motion": tail,
            "subtitles": subs}
