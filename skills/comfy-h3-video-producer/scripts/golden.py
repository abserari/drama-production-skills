# -*- coding: utf-8 -*-
"""金样本库（v3.9）：检测器的「考题库 + 回归引擎」。

解决的问题是**校准没有沉淀机制**：tail_motion 误判、字幕 WARN 误报这类事故，
过去是临时处置 + 手工改标记，改完就散——下一个补丁可能把旧的误报修回来。

核心概念：
  金样本（case）= 一条「检测项 × 判例」：证据（帧/序列/媒体文件）+ 人工判定的
  标准答案（expect）+ 检测器当时的错误输出（was，可缺省）+ 判例理由（why）。
  `was` 不是垃圾数据：它让回归能区分「修好了」（was≠expect，现在=expect）、
  「已知容忍」（was=expect 之外的输出且 case 标记 tolerant，如字幕 WARN 灵敏度过头）
  和「真回归」（输出变成了既不是 expect 也不是 was 的新错法）。

目录：技能根下 golden/cases/<id>/，一条用例一个目录（证据 + case.json）。
纪律：golden/ 是技能目录里**唯一允许写入的子树**，且只经 calib 命令显式写入；
运行时状态（state/checks/帧）仍然绝不进技能目录。

用法：
  python golden.py run                                   # 全量回归，非 0 退出=有回归/未修复
  python golden.py capture --from <checks目录> [--seg X]  # 从一次 gate/review 现场打包入库
           [--check auto|tail_motion|subtitle|seam|frames]
           [--expect PASS|FAIL|WARN] [--why "..."] [--tolerant]
  python golden.py stash --from <checks目录> --reason ...  # watch AUTO_ABORT 自动落候选区（不经审核不入库）
  python golden.py pending                                # 列候选区
  python golden.py promote --id <候选id> --expect ... [--check ...] [--why ...] [--tolerant]
"""
import json
import os
import shutil
import subprocess
import sys
import time

import paths
paths.force_utf8_stdio()

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(os.path.dirname(HERE), "golden")
CASES = os.path.join(GOLDEN, "cases")
PENDING = os.path.join(GOLDEN, "pending")
MANIFEST = os.path.join(GOLDEN, "manifest.json")
PY = sys.executable

# expect 的合法取值随 check 而异：tail_motion/seam/audio_gate 用 PASS/FAIL，
# subtitle 用 PASS（应静默）/WARN（该报警）。
EXPECTS = ("PASS", "FAIL", "WARN")


# ── 基础 ────────────────────────────────────────────────
def _ensure_dirs():
    os.makedirs(CASES, exist_ok=True)


def list_cases():
    _ensure_dirs()
    out = []
    for cid in sorted(os.listdir(CASES)):
        p = os.path.join(CASES, cid, "case.json")
        if os.path.isfile(p):
            try:
                out.append(json.load(open(p, encoding="utf-8")))
            except Exception as e:
                print(f"[WARN] 用例 {cid} 的 case.json 读不了: {e}")
    return out


def _next_id(check):
    _ensure_dirs()
    n = 0
    for cid in os.listdir(CASES):
        if cid.startswith(check + "_"):
            try:
                n = max(n, int(cid.rsplit("_", 1)[1]))
            except (ValueError, IndexError):
                pass
    return f"{check}_{n + 1:03d}"


def _save_case(case):
    d = os.path.join(CASES, case["id"])
    os.makedirs(d, exist_ok=True)
    json.dump(case, open(os.path.join(d, "case.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return d


# ── 重放：check -> verdict（PASS/FAIL/WARN 或 None=手工类）──
def _replay_tail_motion(case):
    import sop_check
    flow = case["inputs"]["flow_series"]
    nb = case["inputs"]["n_beats"]
    beats = [{"n": i + 1, "text": (case["inputs"]["last_beat_text"] if i == nb - 1 else "")}
             for i in range(nb)]
    r = sop_check.tail_motion_check({"flow_series": flow}, beats, case["inputs"].get("ending", ""))
    if r is None:
        return None
    return "FAIL" if r["verdict"] == "FAIL" else "PASS"


def _replay_subtitle(case):
    import cv2
    import sop_check
    d = os.path.join(CASES, case["id"], "frames")
    imgs = []
    for f in sorted(os.listdir(d)):
        img = cv2.imread(os.path.join(d, f))
        if img is not None:
            imgs.append(img)
    if not imgs:
        return None
    r = sop_check.subtitle_check_frames(imgs)
    return "WARN" if (r["suspicious_subtitle"] or r["suspicious_watermark"]) else "PASS"


def _replay_seam(case):
    import cv2
    import sop_check
    d = os.path.join(CASES, case["id"], "frames")
    a, b = cv2.imread(os.path.join(d, "a_prev_last.png")), cv2.imread(os.path.join(d, "b_cur_first.png"))
    if a is None or b is None:
        return None
    r = sop_check.seam_from_images(a, b)
    broken = r["frame_corr"] < sop_check.SEAM_FRAME_MIN or r["hist_corr"] < sop_check.SEAM_HIST_MIN
    return "FAIL" if broken else "PASS"


def _replay_audio(case):
    """音频四项：case 里存了媒体文件（mp4/wav），重放 = 重跑 check_audio_seg.py。"""
    media = os.path.join(CASES, case["id"], case["inputs"]["media"])
    if not os.path.isfile(media):
        return None
    aj = media + ".audio.json"
    r = subprocess.run([PY, os.path.join(HERE, "check_audio_seg.py"), "--file", media,
                        "--json", aj], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if not os.path.isfile(aj):
        return None
    return json.load(open(aj, encoding="utf-8")).get("verdict")


def _sem_python():
    """semantic_qc.py 需要 torch+CLIP，跑在 ComfyUI venv 的 python 里。"""
    import glob as _g
    cands = [os.environ.get("SEM_QC_PYTHON")]
    cfg = os.path.join(GOLDEN, "sem_python.txt")
    if os.path.isfile(cfg):
        cands.append(open(cfg, encoding="utf-8").read().strip())
    cands += _g.glob(r"D:/Comfy-Desktop/ComfyUI-Installs/*/ComfyUI/.venv/Scripts/python.exe")
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def _replay_semantic(case):
    py = _sem_python()
    if not py:
        return None
    cdir = os.path.join(CASES, case["id"])
    spec_p = os.path.join(cdir, "spec.json")
    if not os.path.isfile(spec_p) and case["inputs"].get("spec"):
        json.dump(case["inputs"]["spec"], open(spec_p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    out = os.path.join(cdir, "replay")
    r = subprocess.run([py, os.path.join(HERE, "semantic_qc.py"),
                        "--video", case["inputs"]["video"], "--spec", spec_p, "--out", out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    p = os.path.join(out, "semantic.json")
    if not os.path.isfile(p):
        return None
    return json.load(open(p, encoding="utf-8")).get("verdict")


_REPLAYERS = {"tail_motion": _replay_tail_motion, "subtitle": _replay_subtitle,
              "seam": _replay_seam, "audio_gate": _replay_audio,
              "semantic": _replay_semantic}


def replay(case):
    """返回 (verdict, note)。verdict None = 手工类（manual_vlm/frames），不参与自动回归。"""
    fn = _REPLAYERS.get(case["check"])
    if fn is None:
        return None, "手工判例（留给 G4/语义判官），不参与自动回归"
    try:
        return fn(case), ""
    except Exception as e:
        return None, f"重放异常: {e}"


# ── capture：从 gate/review 现场打包一条用例 ─────────────
def _infer_check(qc):
    tm = qc.get("tail_motion") or {}
    if tm.get("verdict") == "FAIL":
        return "tail_motion"
    subs = (qc.get("visual") or {}).get("subtitles") or {}
    if subs.get("suspicious_subtitle") or subs.get("suspicious_watermark"):
        return "subtitle"
    return "frames"


def capture_from_qc(checks_dir, check="auto", expect=None, why="", seg=None,
                    tolerant=False, case_id=None, spec_file=None):
    """把一次双检现场（checks/<tag>_<stamp>/）固化为金样本。

    expect 必须给（人工判定的正确答案）；check=auto 按机器当时报了什么来推断。
    tail_motion 需要重放输入：优先用 qc.json 里 v3.9 落的 flow_series/beats，
    老格式则回退重算（要求一采 mp4 还在、工程 segments 里还有该段的提示词）。
    """
    qcp = os.path.join(checks_dir, "qc.json")
    if not os.path.isfile(qcp):
        raise SystemExit(f"[FATAL] {checks_dir} 里没有 qc.json（这不是一个双检现场目录）")
    qc = json.load(open(qcp, encoding="utf-8"))
    if check == "auto":
        check = _infer_check(qc)
    if expect is None:
        raise SystemExit("[FATAL] 必须给 --expect（人工判定的正确答案 PASS/FAIL/WARN）")
    expect = expect.upper()
    if expect not in EXPECTS:
        raise SystemExit(f"[FATAL] --expect 只能是 {'/'.join(EXPECTS)}")
    if check not in ("tail_motion", "subtitle", "seam", "frames", "semantic"):
        raise SystemExit(f"[FATAL] 未知 check: {check}")

    was = qc.get("verdict")
    video = qc.get("video")
    # was 取**检测项级别**的错误输出，不是顶层 verdict——字幕 WARN 不阻断时顶层
    # 仍是 PASS，用顶层值会把「人工放行的 WARN」记成机器全对，回归语义全歪。
    _tm = qc.get("tail_motion") or {}
    _subs = (qc.get("visual") or {}).get("subtitles") or {}
    if check == "tail_motion":
        was = "FAIL" if _tm.get("verdict") == "FAIL" else "PASS"
    elif check == "subtitle":
        was = "WARN" if (_subs.get("suspicious_subtitle") or
                         _subs.get("suspicious_watermark")) else "PASS"
    elif check == "semantic":
        # 当时有语义检测的现场（semtest_*）用其 verdict，否则记定量闸门的顶层输出
        _sp = os.path.join(checks_dir, "semantic.json")
        if os.path.isfile(_sp):
            was = json.load(open(_sp, encoding="utf-8")).get("verdict") or was
    case = {"check": check, "expect": expect, "was": was, "why": why,
            "tolerant": bool(tolerant), "source": checks_dir, "video": video,
            "created": __import__("time").strftime("%Y-%m-%d %H:%M:%S")}
    case_id = case_id or _next_id(check)
    case["id"] = case_id
    inputs = {}

    import cv2
    import sop_check
    if check == "tail_motion":
        v = qc.get("visual") or {}
        flow, beats, ending = v.get("flow_series"), v.get("beats"), v.get("ending")
        if not flow and video and os.path.isfile(video):
            print("[info] 老 qc.json 没有落 flow_series，从一采 mp4 重算…")
            flow = sop_check.analyze_sequence(video)["flow_series"]
        if not beats and seg:
            seg_txt = os.path.join(paths.SEG_DIR, f"{seg}.txt")
            beats = sop_check.parse_beats(seg_txt)
            ending = sop_check.parse_ending(seg_txt)
        if not flow or not beats:
            raise SystemExit("[FATAL] tail_motion 用例缺重放输入（flow_series/beats 都拿不到："
                             "qc.json 太老且 mp4 已删）。请给 --seg 或先确认一采还在。")
        inputs = {"flow_series": flow, "n_beats": len(beats),
                  "last_beat_text": beats[-1]["text"], "ending": ending or ""}
    elif check == "subtitle":
        fdir = os.path.join(CASES, case_id, "frames")
        os.makedirs(fdir, exist_ok=True)
        # 候选区（pending）现场已抽好 8 帧时直接复用——候选转正不依赖 mp4 还在。
        pre = [f for f in sorted(os.listdir(os.path.join(checks_dir, "frames"))
                                 if os.path.isdir(os.path.join(checks_dir, "frames")) else [])
               if f.startswith("sub_") and f.endswith(".png")]
        if len(pre) >= 4:
            for f in pre:
                shutil.copyfile(os.path.join(checks_dir, "frames", f), os.path.join(fdir, f))
        else:
            if not (video and os.path.isfile(video)):
                raise SystemExit("[FATAL] subtitle 用例需要一采 mp4 还在（按 SUB_SAMPLE_N 重抽 8 帧）")
            cap, _fps, n = sop_check._open(video)
            idxs = sorted({int(i * (n - 1) / max(1, sop_check.SUB_SAMPLE_N - 1))
                           for i in range(sop_check.SUB_SAMPLE_N)})
            for k, i in enumerate(idxs):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ok, img = cap.read()
                if ok:
                    sop_check._imwrite(os.path.join(fdir, f"sub_{k:02d}_f{i}.png"), img)
            cap.release()
    elif check == "seam":
        sm = qc.get("seam") or {}
        prev = sm.get("prev")
        if not (prev and os.path.isfile(prev) and video and os.path.isfile(video)):
            raise SystemExit("[FATAL] seam 用例需要上段交付片与本段一采都还在")
        fdir = os.path.join(CASES, case_id, "frames")
        os.makedirs(fdir, exist_ok=True)
        cap, _fps, n_prev = sop_check._open(prev)
        sop_check._imwrite(os.path.join(fdir, "a_prev_last.png"), sop_check._grab(cap, max(0, n_prev - 1)))
        cap.release()
        cap, _fps, _n = sop_check._open(video)
        sop_check._imwrite(os.path.join(fdir, "b_cur_first.png"), sop_check._grab(cap, 0))
        cap.release()
    elif check in ("frames", "manual"):  # 复制双检现场已抽好的帧，留给人工与将来的语义判官
        fdir = os.path.join(CASES, case_id, "frames")
        os.makedirs(fdir, exist_ok=True)
        n = 0
        for f in sorted(os.listdir(os.path.join(checks_dir, "frames"))
                        if os.path.isdir(os.path.join(checks_dir, "frames")) else []):
            if f.endswith(".png"):
                shutil.copyfile(os.path.join(checks_dir, "frames", f), os.path.join(fdir, f))
                n += 1
        inputs = {"frames": n}
        check = "manual_vlm" if check == "frames" else check
        case["check"] = check
    if check == "semantic":
        if not (video and os.path.isfile(video)):
            raise SystemExit("[FATAL] semantic 用例需要一采 mp4 还在")
        if not (spec_file and os.path.isfile(spec_file)):
            raise SystemExit("[FATAL] semantic 用例需要 --spec-file <sem spec json>")
        inputs = {"spec": json.load(open(spec_file, encoding="utf-8")),
                  "video": video}
    case["inputs"] = inputs

    d = _save_case(case)
    r, note = replay(case)
    print(f"[OK] 金样本入库: {case_id}  check={case['check']}  expect={expect}  was={was}"
          f"{'  tolerant' if tolerant else ''}")
    if why:
        print(f"     why: {why}")
    if r is None:
        print(f"     重放: 不可自动重放（{note}）")
    else:
        tag = "expect一致" if r == expect else ("与was同错" if r == was else "新错法")
        print(f"     重放: {r}（{tag}）")
    print(f"     目录: {d}")
    return case


# ── 候选区（pending）：watch AUTO_ABORT 自动落，人工审核后 promote 转正 ──
def stash_pending(checks_dir, reason=""):
    """把一次失败现场打包进 golden/pending/。watch 的 AUTO_ABORT 自动调用——
    误判现场永远不会因「忘了收」而丢失。**不审核不入库**：候选不参与回归，
    转正必须显式 promote（人工给 expect/why）。

    自给自足：qc.json（v3.9 起含 flow_series/beats/ending）+ frames/ 整目录 +
    字幕 8 帧（mp4 还在就当场抽好）——之后 mp4 被清理也能转正。
    """
    qcp = os.path.join(checks_dir, "qc.json")
    if not os.path.isfile(qcp):
        return None
    _ensure_dirs()
    os.makedirs(PENDING, exist_ok=True)
    tag = os.path.basename(os.path.normpath(checks_dir))
    pid = f"{time.strftime('%Y%m%d_%H%M%S')}_{tag}"
    dst = os.path.join(PENDING, pid)
    if os.path.isdir(dst):          # 同秒同名：加后缀
        pid += "_b"
        dst = os.path.join(PENDING, pid)
    shutil.copytree(checks_dir, dst, ignore=shutil.ignore_patterns("*.mp4", "audio.json"))
    video = None
    try:
        qc = json.load(open(os.path.join(dst, "qc.json"), encoding="utf-8"))
        video = qc.get("video")
    except Exception:
        qc = {}
    # 字幕 8 帧当场抽好（mp4 此刻几乎必然还在；这是唯一需要 mp4 的输入）
    if video and os.path.isfile(video):
        try:
            import cv2
            import sop_check
            cap, _fps, n = sop_check._open(video)
            idxs = sorted({int(i * (n - 1) / max(1, sop_check.SUB_SAMPLE_N - 1))
                           for i in range(sop_check.SUB_SAMPLE_N)})
            fdir = os.path.join(dst, "frames")
            os.makedirs(fdir, exist_ok=True)
            for k, i in enumerate(idxs):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ok, img = cap.read()
                if ok:
                    sop_check._imwrite(os.path.join(fdir, f"sub_{k:02d}_f{i}.png"), img)
            cap.release()
        except Exception as e:
            print(f"[calib] [WARN] 候选区抽字幕帧失败（转正时可补）: {e}")
    json.dump({"id": pid, "reason": reason, "source": checks_dir, "video": video,
               "was": qc.get("verdict"),
               "ts": time.strftime("%Y-%m-%d %H:%M:%S")},
              open(os.path.join(dst, "pending.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[calib] 失败现场已落候选区: {pid}（待人工 promote 转正，golden.py pending 查看）")
    return pid


def list_pending():
    if not os.path.isdir(PENDING):
        print("[!] 候选区为空。watch AUTO_ABORT 会自动落失败现场到这里。")
        return []
    out = []
    for pid in sorted(os.listdir(PENDING)):
        pj = os.path.join(PENDING, pid, "pending.json")
        if not os.path.isfile(pj):
            continue
        p = json.load(open(pj, encoding="utf-8"))
        out.append(p)
        print(f"{p['id']}  was={p.get('was')}  {p.get('reason', '')[:60]}")
    if not out:
        print("[!] 候选区为空。")
    return out


def promote(pending_id, check="auto", expect=None, why="", tolerant=False):
    """候选转正：pending 目录当成双检现场喂给 capture_from_qc（pending 里存有
    qc.json + 帧，字幕帧直接复用，不再依赖 mp4）。转正后删除候选目录。"""
    src = os.path.join(PENDING, pending_id)
    if not os.path.isdir(src):
        raise SystemExit(f"[FATAL] 候选区没有 {pending_id}（golden.py pending 可列出全部）")
    pj = os.path.join(src, "pending.json")
    if os.path.isfile(pj) and not why:
        why = json.load(open(pj, encoding="utf-8")).get("reason", "")
    case = capture_from_qc(src, check=check, expect=expect, why=why, tolerant=tolerant)
    shutil.rmtree(src)
    print(f"[OK] 候选 {pending_id} 已转正为 {case['id']}，候选目录已清理。")
    return case


# ── 回归 ────────────────────────────────────────────────
def run_regress():
    cases = list_cases()
    if not cases:
        print("[!] 金库为空。先 capture 一批：误判现场/已交付段的典型 PASS 都该进来。")
        return 0
    rows, n_fixed, n_stable_ok, n_still, n_regress, n_manual = [], 0, 0, 0, 0, 0
    for c in cases:
        r, note = replay(c)
        cid, chk, exp, was = c["id"], c["check"], c["expect"], c.get("was")
        if r is None:
            rows.append((cid, chk, exp, was, "—", "manual", note))
            n_manual += 1
            continue
        if r == exp:
            tag = "fixed" if (was and was != exp) else "pass"
            if tag == "fixed":
                n_fixed += 1
            rows.append((cid, chk, exp, was, r, tag, ""))
        elif r == was:
            if c.get("tolerant"):
                n_stable_ok += 1
                rows.append((cid, chk, exp, was, r, "tolerant", "已知容忍（如 WARN 灵敏度）"))
            else:
                n_still += 1
                rows.append((cid, chk, exp, was, r, "still-wrong", "仍是入库时的错法"))
        else:
            n_regress += 1
            rows.append((cid, chk, exp, was, r, "REGRESSED", "输出变成了 expect/was 之外的新错法"))
    w = max(len(r[0]) for r in rows) + 1
    print(f"{'case'.ljust(w)}{'check'.ljust(14)}{'expect'.ljust(7)}{'was'.ljust(6)}{'now'.ljust(6)}判定  备注")
    for cid, chk, exp, was, r, tag, note in rows:
        mark = {"pass": "ok", "fixed": "FIXED", "tolerant": "ok", "still-wrong": "!!",
                "REGRESSED": "XX", "manual": "--"}[tag]
        print(f"{cid.ljust(w)}{chk.ljust(14)}{str(exp).ljust(7)}{str(was).ljust(6)}{str(r).ljust(6)}[{mark}] {note}")
    auto = len(cases) - n_manual
    print(f"\n合计 {len(cases)} 条（自动 {auto} / 手工 {n_manual}）："
          f"PASS {auto - n_fixed - n_stable_ok - n_still - n_regress} · "
          f"修复确认 {n_fixed} · 已知容忍 {n_stable_ok} · 仍旧错 {n_still} · 回归 {n_regress}")
    if n_regress or n_still:
        print("[FATAL] 回归未全绿——检测器变更不得发布（改回或修到全绿，见 SKILL §10 校准纪律）。")
        return 1
    print("[OK] 回归全绿。")
    return 0


# ── CLI ─────────────────────────────────────────────────
def main():
    import argparse
    ap = argparse.ArgumentParser(description="金样本库：capture 入库 / run 回归 / stash 候选")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("pending")
    cp = sub.add_parser("capture")
    cp.add_argument("--from", dest="src", required=True, help="checks/<tag>_<stamp> 双检现场目录")
    cp.add_argument("--seg", help="段号（老 qc.json 缺 beats 时从工程 segments 补）")
    cp.add_argument("--check", default="auto",
                    help="auto(按机器当时报的推断)/tail_motion/subtitle/seam/frames")
    cp.add_argument("--expect", required=True, help="人工判定的正确答案 PASS/FAIL/WARN")
    cp.add_argument("--why", default="", help="判例理由（将来直接喂语义判官当 few-shot）")
    cp.add_argument("--tolerant", action="store_true",
                    help="标记为已知容忍（如字幕 WARN 灵敏度过头，人工放行的）")
    cp.add_argument("--spec-file", dest="spec_file",
                    help="check=semantic 时的判卷清单 json（会内嵌进用例）")
    sp = sub.add_parser("stash")
    sp.add_argument("--from", dest="src", required=True)
    sp.add_argument("--reason", default="")
    pp = sub.add_parser("promote")
    pp.add_argument("--id", required=True, help="候选区 id（golden.py pending 查看）")
    pp.add_argument("--check", default="auto")
    pp.add_argument("--expect", required=True)
    pp.add_argument("--why", default="", help="留空则沿用候选的 reason")
    pp.add_argument("--tolerant", action="store_true")
    a = ap.parse_args()
    if a.cmd == "run":
        sys.exit(run_regress())
    elif a.cmd == "pending":
        list_pending()
    elif a.cmd == "stash":
        stash_pending(a.src, a.reason)
    elif a.cmd == "promote":
        promote(a.id, check=a.check, expect=a.expect, why=a.why, tolerant=a.tolerant)
    else:
        capture_from_qc(a.src, check=a.check, expect=a.expect, why=a.why,
                        seg=getattr(a, "seg", None), tolerant=a.tolerant,
                        spec_file=getattr(a, "spec_file", None))


if __name__ == "__main__":
    main()
