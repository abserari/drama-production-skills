# -*- coding: utf-8 -*-
"""工程与闸门：项目脚手架、进度台账、一采双检、收片、拼接、残留清理。

这个脚本的存在理由
------------------
"要求 Agent 记得做 SOP" 是不可靠的。v3 起把闸门做成**下游拒收**：
  - 没有 plan.json 里的段 → submit 拒绝
  - 提示词 preflight FAIL → submit 拒绝
  - 一采没跑 QC → review / finish 拒绝
  - 视觉复核没签字 → finish 拒绝
  - 任何一段没完成 → concat 拒绝

子命令
------
  new     建隔离工程（每个剧本一个目录，运行时不碰技能目录）
  status  台账总览（Agent 的仪表盘，含"下一步该做什么"）
  plan    段规划表校验
  gate    一采双检（视觉定量 + 音频四项），写台账
  review  视觉复核签字（8 类严重逻辑错误）
  finish  收片：取音轨 → 清床音 → mux → 复检 → 归档
  concat  全片拼接 + 接缝复盘
  residue 残留扫描 / 安全归档
  path    打印路径解析结果
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
from production_state import atomic_json, read_json, file_hash, fingerprint, require_artifact, render_context, require_configured_reviews

PY = sys.executable


# ── 台账 ────────────────────────────────────────────────
def load_progress():
    d = read_json(paths.PROGRESS, {"segs": {}})
    d.setdefault("segs", {})
    return d


def save_progress(d):
    d["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(paths.PROJECT_DIR, exist_ok=True)
    atomic_json(paths.PROGRESS, d)


def load_project():
    """project.json（工程档案）。`chain` 是**任务绑定的导演台工程名**，不是片名。

    它是"续接能不能成立"的唯一依据：同一任务的所有段必须在同一个 h3_chain/<chain>
    里排成一条 order，续拍档才找得到上一段。片名（name）只用于显示和兜底。
    """
    pj = read_json(paths.PROJECT_JSON)
    pj.setdefault("chain", "")
    return pj


def save_project(pj):
    os.makedirs(paths.PROJECT_DIR, exist_ok=True)
    atomic_json(paths.PROJECT_JSON, pj)


def chain_live(name, timeout=8):
    """读导演台工程档案的真实状态（段数/末段/续拍存档）。接口不可用时返回 None。"""
    if not name:
        return None
    try:
        import urllib.parse
        s = paths.http_json("/cglide/chain/summary?name="
                            + urllib.parse.quote(str(name), safe=""), timeout=timeout)
    except Exception:
        return None
    clips = [c for c in (s.get("clips") or []) if c.get("id")]
    last = clips[-1] if clips else {}
    has_cont = False
    if last:
        try:
            got = paths.http_json("/cglide/chain/cont?name=%s&id=%s"
                                  % (urllib.parse.quote(str(name), safe=""),
                                     urllib.parse.quote(str(last["id"]), safe="")), timeout=timeout)
            has_cont = bool(got.get("cont_path"))
        except Exception:
            pass
    return {"count": len(clips),
            "last_id": str(last.get("id") or "") if last else "",
            "last_take": int(last.get("current_take") or 1) if last else 0,
            "last_shot": str(last.get("shot") or "") if last else "",
            "has_cont": has_cont}


def _w(s):
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def _pad(s, n):
    s = str(s)
    return s + " " * max(0, n - _w(s))


def seg_of(d, seg, create=False):
    if seg not in d["segs"] and create:
        d["segs"][seg] = {"status": "pending", "reroll": 0}
    return d["segs"].get(seg)


def load_plan():
    return read_json(paths.PLAN)


def require_current_inputs(seg, record):
    """Legacy assets need explicit revalidation, not implicit trust by file size."""
    snapshot = record.get("input_snapshot")
    if not snapshot:
        raise SystemExit("[REFUSE] 缺少输入指纹，旧素材需导入并重新验证")
    if snapshot.get("segment_spec") != fingerprint(seg_spec(seg)):
        raise SystemExit("[REFUSE] 分镜计划已修改，旧生成结果失效")
    if snapshot.get("production_context") != render_context(load_project()):
        raise SystemExit("[REFUSE] 制作版本或所选技能已改变，请重新验证受影响产物")
    for path, digest in snapshot.get("files", {}).items():
        require_artifact(path, digest)


def require_review(record):
    first = record.get("first") or {}
    review = record.get("visual_review") or {}
    if first.get("verdict") != "PASS" or review.get("verdict") != "pass":
        raise SystemExit("[REFUSE] 缺少通过的检查和视觉审查")
    require_artifact(first.get("video"), first.get("artifact_sha256"))
    if review.get("artifact_sha256") != first.get("artifact_sha256"):
        raise SystemExit("[REFUSE] 视觉审查对应旧产物，请重新审查")


def seg_spec(seg):
    for s in load_plan().get("segs", []):
        if s.get("seg") == seg or s.get("id") == seg:
            return s
    return {}


def plan_order():
    return [s.get("seg") or s.get("id") for s in load_plan().get("segs", [])]


# ── 探测 ────────────────────────────────────────────────
def _ffprobe(path):
    if not os.path.isfile(path):
        return {}
    if paths.FFPROBE_OK:
        try:
            r = subprocess.run([paths.FFPROBE, "-v", "error", "-show_streams", "-show_format",
                                "-of", "json", path], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            if r.returncode == 0 and r.stdout.strip():
                return json.loads(r.stdout)
        except Exception:
            pass
    # 兜底：解析 ffmpeg -i 的 stderr
    try:
        r = subprocess.run([paths.FFMPEG, "-hide_banner", "-i", path],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        err = r.stderr
        info = {"streams": []}
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", err)
        if m:
            info["format"] = {"duration": int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))}
        if "Audio:" in err:
            info["streams"].append({"codec_type": "audio"})
        m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", err)
        if m:
            info["streams"].append({"codec_type": "video", "width": int(m.group(1)), "height": int(m.group(2))})
        return info
    except Exception:
        return {}


def stream_summary(path):
    info = _ffprobe(path)
    vs = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    aus = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    dur = 0.0
    try:
        dur = float(info.get("format", {}).get("duration", 0) or 0)
    except Exception:
        pass
    return {"has_audio": bool(aus), "has_video": bool(vs),
            "width": vs[0].get("width") if vs else None,
            "height": vs[0].get("height") if vs else None,
            "duration": round(dur, 2)}


# ── 一采双检 ────────────────────────────────────────────
def _seam_mode(seg):
    """接缝比对的启用模式——**只拦真续接，不拦设计上的切镜**：

    - "off"    plan.json 段规格写 seam_check:false / fresh_start:true（明确声明独立画面）
    - "soft"   plan.json 段规格写 seam_check:"soft"（上下文续接+设计换景硬切：续接 latent
               只为给模型世界状态，交付时裁头去掉钉帧，钉帧漂移属预期 → 只 WARN 不 FAIL）
    - "hook"   plan 的 hook 写明 硬切/切镜/新景/转场/独立（设计上的非续接）
    - "nocont" 台账 s["cont"] 为空 → 本段没做续接（第一段 / --cont off / --allow-nocont /
               纯窗口手动渲染没经过 submit）——首帧本来就不接上一段，比对必然不匹配
    - "on"     台账记录了续接（cont 含 latent_file）→ 执行比对，这才是要拦的"续接失效"
    """
    spec = seg_spec(seg)
    if spec.get("seam_check") is False or spec.get("fresh_start") is True:
        return "off"
    if spec.get("seam_check") == "soft":
        return "soft"
    hook = str(spec.get("hook") or "")
    if any(k in hook for k in ("硬切", "切镜", "新景", "转场", "不续接")):
        return "hook"
    s = (load_progress()["segs"].get(seg) or {})
    cont = s.get("cont")
    return "on" if isinstance(cont, dict) and cont else "nocont"


_SEAM_SKIP_WHY = {
    "off": "plan 指定 seam_check:false / fresh_start:true（独立画面）",
    "hook": "plan hook 写明硬切/新景（设计上的切镜，非续接）",
    "nocont": "台账记录本段未续接（第一段 / --cont off / 手动渲染）——首帧不承接上一段",
}


def _prev_deliver(seg):
    """上一段的交付片路径（接缝比对基准）。没有上一段/上一段还没收片 → None。"""
    order = plan_order()
    if seg not in order:
        return None
    i = order.index(seg)
    if i <= 0:
        return None
    prev = order[i - 1]
    rec = load_progress()["segs"].get(prev) or {}
    p = (rec.get("deliver") or {}).get("path")
    if p and os.path.isfile(p):
        return p
    p = os.path.join(paths.FINISH_DIR, f"{prev}.mp4")
    return p if os.path.isfile(p) else None


def run_qc(video, dialogue="auto", fx="auto", tag="adhoc", seg=None, seam=True,
           tail_exempt=False, full=True):
    """视觉定量 + 音频四项。返回统一 verdict。判据口径见 references/audio_pipeline.md。

    seg 给了就会带上节拍期望（evidence_pack + beat_sheet + 尾拍运动能量）；
    seam=True 时**只对台账记录了续接的段**做接缝比对（_seam_mode：--cont off /
    第一段 / hook 写明硬切切镜的段自动跳过，不拦设计上的切镜）；只对未裁刀口的
    一采有意义，finish 的交付复检传 seam=False——交付片头部已裁掉续接钉帧。

    full=False 是快速模式（v3.6）：只查流摘要 + 音频，**跳过全部视觉定量**。
    用于 finish 的交付复检——mux 走 -c:v copy，画面与已签字的一采逐字节相同，
    再跑抽帧/光流/节拍证据包是纯浪费（十几秒/段，收益 0）。

    fx 默认 "auto"=只记录不判定：H3 的动作拟音极不稳定（实测同一段三个 seed
    分别给出 1/0/0 个点状事件），把它当硬门限等于让每段必然重抽。
    要强判拟音请显式传 "yes"。
    """
    import sop_check
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(paths.CHECKS_DIR, f"{tag}_{stamp}")
    frames_dir = os.path.join(log_dir, "frames")
    beats, ending = [], ""
    visual = {"sequence": {"flags": {}}, "extracted": {}}
    # log_dir 必须在音频子进程前建好：完整模式下 sop_check.run 顺带建了它，
    # 快速模式（v3.6）没有视觉环节，不提前建的话 check_audio_seg 写 json 会炸。
    os.makedirs(log_dir, exist_ok=True)
    if full:
        if seg:
            seg_txt = os.path.join(paths.SEG_DIR, f"{seg}.txt")
            beats = sop_check.parse_beats(seg_txt)
            ending = sop_check.parse_ending(seg_txt)
        visual = sop_check.run(video, frames_dir, beats=beats, ending=ending)
    flags = visual["sequence"]["flags"]
    jumps = flags.get("teleport_jumpcut") or []
    scenes = flags.get("scene_change") or []

    aj = os.path.join(log_dir, "audio.json")
    cmd = [PY, os.path.join(HERE, "check_audio_seg.py"), "--file", video,
           "--dialogue", dialogue, "--fx", fx, "--json", aj]
    if tail_exempt:
        cmd.append("--tail-exempt")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    audio = {}
    if os.path.isfile(aj):
        try:
            audio = json.load(open(aj, encoding="utf-8"))
        except Exception:
            audio = {}
    if not audio:
        audio = {"verdict": "ERROR", "checks": [], "stderr": (r.stderr or "")[-800:]}

    reasons, warns = [], []
    if jumps:
        reasons.append(f"光流瞬移/跳切 {len(jumps)} 处: " +
                       ", ".join(f"{x['t']:.1f}s" for x in jumps[:5]))
    tm = visual.get("tail_motion")
    if tm and tm.get("verdict") == "FAIL":
        reasons.append("结尾动作疑似未执行: " + tm["note"])
    seam_info = None
    if seg and seam:
        mode = _seam_mode(seg)
        if mode in ("on", "soft"):
            prev = _prev_deliver(seg)
            if prev:
                seam_info = sop_check.seam_similarity(prev, video, log_dir)
                broken = seam_info and (seam_info["frame_corr"] < sop_check.SEAM_FRAME_MIN or
                                        seam_info["hist_corr"] < sop_check.SEAM_HIST_MIN)
                if broken and mode == "on":
                    reasons.append(
                        "段间接缝疑似断裂: 上一段尾帧 vs 本段首帧 frame_corr=%s hist_corr=%s"
                        "（对照 %s）—— 续接可能没接上（先试 --cont off 验一次，见 SKILL §4）"
                        % (seam_info["frame_corr"], seam_info["hist_corr"],
                           os.path.join(log_dir, "seam_pair.png")))
                elif broken:
                    warns.append(
                        "段间接缝钉帧漂移（soft 模式只提示不拦截）: frame_corr=%s hist_corr=%s"
                        "（对照 %s）——本段为上下文续接+设计换景，钉帧漂移帧在交付裁头时去除"
                        % (seam_info["frame_corr"], seam_info["hist_corr"],
                           os.path.join(log_dir, "seam_pair.png")))
            else:
                seam_info = {"skipped": "上一段未收片（比对基准还没生成），跳过接缝比对"}
        else:
            seam_info = {"skipped": _SEAM_SKIP_WHY[mode]}
    av = audio.get("verdict")
    if av == "NO_AUDIO":
        reasons.append("该文件没有音轨（终片可能没接音频输入；纯画面产物不能用它交付）")
    elif av != "PASS":
        bad = [c["name"] for c in audio.get("checks", []) if not c.get("pass_")]
        reasons.append("音频不达标: " + ("、".join(bad) if bad else audio.get("stderr", "检测失败")))
    if audio.get("needs_bed_clean"):
        warns.append(f"床音 {audio.get('bed_db')} dBFS 为可清乐音垫（动态范围 "
                     f"{audio.get('dyn_db')} dB）→ v3.6 默认保留原生，接缝由 mix-native 低电平床盖；确需清除用 finish --clean-bed")
    subs = visual.get("subtitles") or {}
    if subs.get("suspicious_subtitle") or subs.get("suspicious_watermark"):
        warns.append("疑似烧入字幕/水印: " + subs.get("note", "") +
                     ("（证据帧 subtitle_evidence.png，人工确认后重抽）"
                      if subs.get("evidence") else ""))
    verdict = "FAIL" if reasons else "PASS"

    result = {
        "video": video, "verdict": verdict, "reasons": reasons, "warns": warns,
        "artifact_sha256": file_hash(video),
        "full": bool(full),
        "needs_bed_clean": bool(audio.get("needs_bed_clean")),
        "visual": {"flags": flags, "first_last_sim": visual.get("first_last_sim"),
                   "fps": visual.get("fps"), "frames": visual.get("frames"),
                   "subtitles": visual.get("subtitles"),
                   # v3.9 金样本：落齐重放输入——flow/hist 序列 + 节拍期望。
                   # capture 时直接取用，老 qc.json 没有则由 golden 回退到重算。
                   "flow_series": ((visual.get("sequence") or {}).get("flow_series") or []),
                   "hist_series": ((visual.get("sequence") or {}).get("hist_series") or []),
                   "beats": beats, "ending": ending,
                   "shot_gaps_hint": [round(x["t"], 2) for x in scenes]},
        "tail_motion": tm,
        "seam": seam_info,
        "beat_sheet": (visual.get("beat_sheet") or {}).get("path"),
        "evidence_pack": visual.get("evidence_pack"),
        "audio": {k: audio.get(k) for k in
                  ("verdict", "dur", "bed_db", "bed_class", "dyn_db", "needs_bed_clean",
                   "fx_count", "speech_end", "tail_silence", "checks")},
        "log_dir": log_dir,
        "frames": {k: v["path"] for k, v in (visual.get("extracted") or {}).items()},
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    os.makedirs(log_dir, exist_ok=True)
    atomic_json(os.path.join(log_dir, "qc.json"), result)
    return result


def print_qc(qc, title="一采双检"):
    print(f"\n{title}: {qc['verdict']}  {' | '.join(qc['reasons'])}")
    for w in (qc.get("warns") or []):
        print(f"  [WARN] {w}")
    a = qc["audio"]
    print(f"  音频: 床音 {a.get('bed_db')} dBFS ({a.get('bed_class')}, 动态范围 {a.get('dyn_db')} dB)"
          f" / 拟音 {a.get('fx_count')} 个 / "
          f"台词结束 {a.get('speech_end')} / 段尾留白 {a.get('tail_silence')}")
    for c in a.get("checks", []):
        tag = "PASS" if c.get("pass_") else "FAIL"
        if not c.get("pass_") and qc.get("needs_bed_clean") and c["name"] in ("床音电平", "全段静音"):
            tag = "WARN"
        print(f"    [{tag}] {c['name']}: {c['value']} (要求 {c['threshold']})")
    v = qc.get("visual") or {}
    if v.get("flags"):
        print(f"  视觉定量: 瞬移 {len(v['flags'].get('teleport_jumpcut') or [])} 处 / "
              f"直方图突变 {len(v['flags'].get('scene_change') or [])} 处"
              f"{'（段内硬切属正常，需对照分镜核对时刻）' if v['flags'].get('scene_change') else ''}")
    elif not qc.get("full", True):
        print("  视觉定量: 跳过（快速模式：mux 为流 copy，画面与已签字一采相同）")
    tm = qc.get("tail_motion")
    if tm:
        tag = "[FAIL]" if tm.get("verdict") == "FAIL" else "[ok]"
        print(f"  尾拍运动: {tag} {tm.get('note') or '尾拍窗口运动量正常'}")
    sm = qc.get("seam")
    if sm:
        if sm.get("skipped"):
            print(f"  接缝比对: 跳过（{sm['skipped']}）")
        else:
            ok = (sm["frame_corr"] >= 0.45 and sm["hist_corr"] >= 0.45)
            print(f"  接缝比对: {'[ok]' if ok else '[FAIL]'} frame_corr={sm['frame_corr']} "
                  f"hist_corr={sm['hist_corr']}（对照图 seam_pair.png）")
    subs = ((qc.get("visual") or {}).get("subtitles")
            if isinstance(qc.get("visual"), dict) else None)
    if subs and (subs.get("suspicious_subtitle") or subs.get("suspicious_watermark")):
        print(f"  字幕/水印: [WARN] {subs.get('note')}"
              f"{'（证据帧 ' + subs['evidence'] + '）' if subs.get('evidence') else ''}")
    if qc.get("evidence_pack"):
        print(f"  逐拍复核: {qc['evidence_pack']}（同目录 beat_sheet.png，逐拍对答案）")
    print(f"  抽帧目录: {qc['frames'].get('sheet') or qc['log_dir']}")


# ── new ─────────────────────────────────────────────────
def cmd_new(a):
    root = os.path.abspath(a.dir)
    os.makedirs(root, exist_ok=True)
    pj = os.path.join(root, paths.MARK)
    if os.path.isfile(pj) and not a.force:
        raise SystemExit(f"[FATAL] {root} 已经是工程目录。要覆盖加 --force。")
    for sub in ("segments", "checks", "成片"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    name = a.name or os.path.basename(os.path.dirname(root)) or "未命名"
    json.dump({"name": name, "chain": (getattr(a, "chain", "") or "").strip(),
               "scene": a.scene or "", "created": time.strftime("%Y-%m-%d %H:%M:%S"),
               "skill": "comfy-h3-video-producer", "version": 3},
              open(pj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not os.path.isfile(os.path.join(root, "progress.json")):
        json.dump({"segs": {}}, open(os.path.join(root, "progress.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    if not os.path.isfile(os.path.join(root, "plan.json")):
        json.dump({"name": name, "segs": []},
                  open(os.path.join(root, "plan.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    tpl = os.path.join(HERE, "voice_card.json")
    vc = os.path.join(root, "voice_card.json")
    if os.path.isfile(tpl) and not os.path.isfile(vc):
        shutil.copyfile(tpl, vc)
    print(f"[OK] 工程已建: {root}")
    print("  下一步: 1) 写 plan.json（段规划表） 2) h3wf.py sync 3) submit")


# ── bind ────────────────────────────────────────────────
def cmd_bind(a):
    """把任务绑到导演台某个工程名（或只查看当前绑定）。

    绑定 = 声明"这片子的所有段都归 h3_chain/<名字>"。它决定两件事：
    续拍档从哪找上一段、成片归位落到哪个目录。中途换 = 续接断。
    """
    paths.require_project()
    pj = load_project()
    old = (pj.get("chain") or "").strip()
    new = (a.chain or "").strip()
    if not new:
        print(f"本地工程: {paths.PROJECT_DIR}")
        print(f"绑定工程: {old or '（空 —— 第一次 submit 会自动绑定）'}")
        info = chain_live(old)
        if old and info:
            print(f"导演台现状: {info['count']} 段，末段 {info['last_id'] or '—'}"
                  f"（take {info['last_take']}），续拍存档 {'有' if info['has_cont'] else '无'}")
        elif old:
            print("导演台现状: 读不到（ComfyUI 没开 / 班长套件接口不可用）")
        return
    if old and old != new and not a.force:
        raise SystemExit(
            f"[REFUSE] 本任务已绑定「{old}」。改成「{new}」会让已有段留在旧工程、新段排进新工程，"
            "续拍档找不到上一段（续接直接断），成片也会分裂到两个目录。\n"
            f"  · 接着做：用回「{old}」\n"
            f"  · 整体迁到新工程：先 h3proj.py bind --chain {new} --force，"
            "然后从第一段重新生成（旧段的 latent 在新工程里不存在）")
    pj["chain"] = new
    save_project(pj)
    print(f"[OK] 绑定: {old or '（空）'} → {new}")
    info = chain_live(new)
    if info:
        print(f"      h3_chain/{new}/ 现有 {info['count']} 段，末段 {info['last_id'] or '—'}")
    else:
        print(f"      h3_chain/{new}/ 读不到（ComfyUI 没开？），绑定已写入，不影响后续 submit")


# ── status ──────────────────────────────────────────────
STEP = {
    "pending": "① 写提示词 / 过 preflight",
    "生成中": "② 等一采落盘 → 跑 gate",
    "一采待复核": "③ 看抽帧做视觉复核 → review",
    "一采通过": "④ 等收片 → finish",
    "待收片": "④ 收片 → finish",
    "完成": "✓ 已交付",
    "失败待复核": "✗ 换 seed 重抽（提示词/构图不变）",
}


def cmd_status(a):
    paths.require_project()
    d = load_progress()
    plan = load_plan()
    order = plan_order() or list(d["segs"].keys())
    pj = {}
    try:
        pj = json.load(open(paths.PROJECT_JSON, encoding="utf-8"))
    except Exception:
        pass
    wf = {}
    try:
        wf = json.load(open(paths.WF_MAP, encoding="utf-8"))
    except Exception:
        pass

    if a.json:
        print(json.dumps({"project": pj, "workflow": {"fp": wf.get("fingerprint"),
                                                      "sync": wf.get("accepted_at")},
                          "progress": d}, ensure_ascii=False, indent=1))
        return

    print(f"工程: {pj.get('name', '?')}   目录: {paths.PROJECT_DIR}")
    print(f"工作流: {'已握手 ' + str(wf.get('accepted_at')) if wf else '未握手（先跑 h3wf.py sync）'}"
          f"  fp={wf.get('fingerprint', '-')}")

    # ── 任务-工程绑定：续接是否还成立，看这两行就够 ──
    bound = (pj.get("chain") or "").strip()
    live = (wf.get("chain_name") or "").strip()
    print(f"任务工程: {bound or '（未绑定，第一次 submit 时自动绑定握手图的 chain.name）'}")
    if bound and live and bound != live:
        print(f"[REFUSE] 工作流现在指向「{live}」，本任务绑定的是「{bound}」→ submit 会拒收。"
              f"接着做用 --chain {bound}；确实换工程用 --rebind。")
    if bound:
        info = chain_live(bound)
        if info is None:
            print(f"          h3_chain/{bound}/：读不到（ComfyUI 没开或班长套件接口不可用）")
        elif not info["count"]:
            print(f"          h3_chain/{bound}/：还没有段（第一段就是开头，正常）")
        else:
            print(f"          h3_chain/{bound}/：{info['count']} 段，末段 {info['last_id']}"
                  f"（{info['last_shot']}，take {info['last_take']}），"
                  f"续拍存档 {'有' if info['has_cont'] else '无 —— 下一段接不上，先把末段跑完'}")
    print(f"归位工程名: {wf.get('chain_name') or '—（未记录，submit 会用技能工程名兜底）'}"
          f"   一采前缀={wf.get('take1_prefix') or '-'}")
    for w in (wf.get("warnings") or []):
        print(f"[WARN] {w}")
    if not order:
        print("\n[!] plan.json 里还没有段。先按 references/directing_bridge.md 第 7 节填段规划表。")
        return
    print("\n" + _pad("段", 8) + _pad("帧长", 6) + _pad("状态", 15) + _pad("首检", 7)
          + _pad("视觉", 7) + _pad("重抽", 6) + "下一步")
    print("-" * 84)
    for seg in order:
        sp = seg_spec(seg)
        s = d["segs"].get(seg, {})
        st = s.get("status", "pending")
        fv = (s.get("first") or {}).get("verdict", "-")
        rv = (s.get("visual_review") or {}).get("verdict", "-")
        print(_pad(seg, 8) + _pad(sp.get('length', s.get('length', '-')), 6) + _pad(st, 15)
              + _pad(fv, 7) + _pad(rv, 7) + _pad(s.get('reroll', 0), 6) + STEP.get(st, '?'))
    done = sum(1 for x in order if d["segs"].get(x, {}).get("status") == "完成")
    print(f"\n完成 {done}/{len(order)}")
    # 缺口的硬提示
    for seg in order:
        s = d["segs"].get(seg, {})
        if s.get("status") == "完成" and not (s.get("first") or {}).get("verdict") == "PASS":
            print(f"[VIOLATION] {seg} 标了完成但没有一采双检记录 —— finish 本应拒绝，请复查")
    if not os.path.isfile(paths.WF_SNAPSHOT):
        print("[GATE] 没有 wf_snapshot.json：提交会被拒绝，先 h3wf.py sync")


# ── plan ────────────────────────────────────────────────
PLAN_FIELDS = ("seg", "length", "shots", "dialogue", "hook")


def cmd_plan(a):
    paths.require_project()
    plan = load_plan()
    segs = plan.get("segs", [])
    bad = []
    for i, s in enumerate(segs):
        for f in ("seg", "length"):
            if not s.get(f) and not (f == "seg" and s.get("id")):
                bad.append(f"第 {i+1} 段缺 {f}")
        if s.get("length") == 243:
            bad.append(f"{s.get('seg') or s.get('id')}: 243 帧已退役（10.13s 超过 8s 上限，"
                       f"2026-11-01 拍板）；改 175（主力）或 192（对白/4 镜段要余量时）——"
                       f"段越长一采+双检+超分周期越长，失败重抽代价越大")
        elif s.get("length") not in (124, 175, 192):
            bad.append(f"{s.get('seg') or s.get('id')}: length 必须是 124 / 175 / 192"
                       f"（当前 {s.get('length')}）——段长上限 192 帧（8s@24fps）")
        if s.get("dialogue") and s.get("length") == 124:
            bad.append(f"{s.get('seg') or s.get('id')}: 有台词不能用 124 帧（会崩成实景废片）；"
                       f"175/192 帧可用，但台词块必须放第 1 拍文本最前")
        if not s.get("hook"):
            bad.append(f"{s.get('seg') or s.get('id')}: 缺 hook（与上段怎么接）")
    ids = [s.get("seg") or s.get("id") for s in segs]
    if len(set(ids)) != len(ids):
        bad.append("段名重复")

    # 同场次风格锚点一致性（可选：plan.json 给段加 "scene" 字段即启用）。
    # 同场戏各段的风格行（detailed_description 下一行）应逐字共用——色调/光源漂移
    # 只能在拼接时看出来，那时重抽代价最大。WARN 不 FAIL（风格是创作判断）。
    scenes = {}
    for s in segs:
        sc = s.get("scene")
        if sc:
            scenes.setdefault(str(sc), []).append(s.get("seg") or s.get("id"))
    for sc, seg_ids in scenes.items():
        if len(seg_ids) < 2:
            continue
        anchors = []
        for sid in seg_ids:
            txt_p = os.path.join(paths.SEG_DIR, f"{sid}.txt")
            if not os.path.isfile(txt_p):
                anchors = []
                break
            style_ln = ""
            ls = open(txt_p, encoding="utf-8").read().splitlines()
            for j, ln in enumerate(ls):
                if ln.strip() == "detailed_description:":
                    for k in range(j + 1, len(ls)):
                        if ls[k].strip():
                            style_ln = ls[k].strip()
                            break
                    break
            anchors.append((sid, style_ln))
        vals = {a[1] for a in anchors if a[1]}
        if len(vals) > 1:
            print(f"[WARN] 场次 {sc} 各段风格锚点行不一致（同场戏拼接会跳色调/光源）：")
            for sid, v in anchors:
                print(f"    {sid}: {v[:64]}")

    print(f"段规划: {len(segs)} 段")
    for s in segs:
        print(f"  {str(s.get('seg') or s.get('id')):<8} {s.get('length'):>4} 帧  "
              f"镜 {s.get('shots')}  台词 {'有' if s.get('dialogue') else '无'}  "
              f"接: {str(s.get('hook'))[:26]}")
    if bad:
        print("\n[FAIL] 段规划表问题:")
        for b in bad:
            print("  -", b)
        sys.exit(1)
    print("\n[OK] 段规划表可用")
    if not a.check:
        print("（写提示词 → segments/<seg>.txt，然后 sop_run.py submit --seg <seg>）")


# ── gate / review ───────────────────────────────────────
def cmd_gate(a):
    paths.require_project()
    d = load_progress()
    s = seg_of(d, a.seg, create=True)
    spec = seg_spec(a.seg)
    video = a.file
    if getattr(a, "latest", False) and not video:
        video = newest_any(tag=a.seg)
        if not video:
            raise SystemExit("[FATAL] 输出目录里没找到可分析的 mp4")
        print(f"[WARN] 按修改时间取了最新的 {os.path.basename(video)}；"
              "如果同时有别的任务在跑，可能不是这一段，务必核对时长与画面。")
    if not video:
        if not s.get("baseline_ts"):
            raise SystemExit("[FATAL] 还没提交过这段，也没有 --file。窗口手动渲染的请给 --file 或 --latest。")
        video = newest_after(s.get("baseline_ts", 0), tag=a.seg)
        if not video:
            raise SystemExit("[FATAL] 提交后没有发现新的一采文件，稍后再试或显式 --file")
    dialogue = a.dialogue if a.dialogue != "auto" else ("yes" if spec.get("dialogue") else "no")
    # 拟音只记录不判定：--fx 保持 auto 原样透传。以前这里把 auto 翻成 yes，
    # 等于 spec 写了 sfx 就硬判拟音，与 finish/watch 的口径不一致（假 FAIL 的来源）。
    fx = a.fx
    qc = run_qc(video, dialogue, fx, tag=a.seg, seg=a.seg)
    print_qc(qc)
    s["first"] = qc
    is_ok = qc["verdict"] == "PASS"
    s["status"] = "一采待签" if is_ok else "失败待复核"
    if qc["verdict"] != "PASS":
        s["fail_reason"] = qc["reasons"]
    save_progress(d)
    print(f"\n[trace] 已写入 {paths.PROGRESS}")
    if qc["verdict"] == "PASS" and not a.no_abort:
        print("[NEXT] 打开 evidence_pack.md + beat_sheet.png 逐拍对答案（每拍期望动作 vs 起/中/末帧），"
              "再按 8 类严重错误复核，然后：h3proj.py review --seg "
              f"{a.seg} --pass（或 --fail --issues '...'）")
    sys.exit(0 if is_ok else 1)


def _preferred_prefixes():
    """一采优先：双检的对象是一采，不是超分/终片。

    `gate --latest` 以前按 mtime 取全部前缀里最新的 mp4 —— 完整跑完一条链之后，
    最新的必然是超分或终片，等于拿交付画质去做一采双检，判据全错。sync 现在会
    认出一采前缀（roles.take1），有它就只在这个前缀里找。
    """
    try:
        mp = json.load(open(paths.WF_MAP, encoding="utf-8"))
    except Exception:
        return []
    p = mp.get("take1_prefix")
    return [p] if p else (mp.get("output_prefixes") or [])


def newest_any(tag=""):
    """按一采前缀 + 最近 6 小时内 取最新的一个 mp4（窗口手动渲染时用）。"""
    prefixes = _preferred_prefixes()
    cands = []
    if os.path.isdir(paths.OUTPUT_DIR):
        for f in os.listdir(paths.OUTPUT_DIR):
            if not f.lower().endswith(".mp4"):
                continue
            if prefixes and not any(f.startswith(p) for p in prefixes):
                continue
            full = os.path.join(paths.OUTPUT_DIR, f)
            mt = os.path.getmtime(full)
            if time.time() - mt < 6 * 3600:
                cands.append((mt, full))
    return max(cands)[1] if cands else None


def newest_after(ts, tag=""):
    prefixes = _preferred_prefixes()
    cands = []
    for f in os.listdir(paths.OUTPUT_DIR) if os.path.isdir(paths.OUTPUT_DIR) else []:
        if not f.lower().endswith(".mp4"):
            continue
        if prefixes and not any(f.startswith(p) for p in prefixes):
            continue
        full = os.path.join(paths.OUTPUT_DIR, f)
        if os.path.getmtime(full) >= ts - 2:
            cands.append((os.path.getmtime(full), full))
    return max(cands)[1] if cands else None


def cmd_review(a):
    paths.require_project()
    d = load_progress()
    s = seg_of(d, a.seg, create=True)
    first = s.get("first") or {}
    if first.get("verdict") != "PASS":
        raise SystemExit("[REFUSE] 一采双检还没 PASS，没有可复核的画面。先跑 gate。")
    require_current_inputs(a.seg, s)
    require_artifact(first.get("video"), first.get("artifact_sha256"))
    verdict = "pass" if a.pass_ else "fail"
    review_target = getattr(a, "video", None) or first["video"]
    review_key = "final_review" if getattr(a, "video", None) else "visual_review"
    s[review_key] = {"verdict": verdict, "issues": a.issues or "",
                          "artifact_sha256": file_hash(review_target), "evidence": getattr(a, "evidence", None) or [], "reviewer_type": "agent",
                          "by": a.by, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    if verdict == "pass":
        s["status"] = "一采通过"
        print("[OK] 视觉复核通过。下一步：等终片落盘 → h3proj.py finish --seg " + a.seg)
    else:
        s["status"] = "失败待复核"
        s["fail_reason"] = [f"视觉复核: {a.issues or '未填问题'}"]
        print("[OK] 已记为视觉不通过。下一步：换 seed 重抽（提示词/构图不变），或按问题改提示词。")
    save_progress(d)
    if not getattr(a, "golden", ""):
        # v3.9 校准提醒（不强制）：人机不一致/放行 WARN 的签字是金样本最有价值的来源
        print("[calib] 本次未收割金样本。若人机判定不一致或人工放行了 WARN，"
              "建议补一条：重跑 review 加 --golden \"判例理由\"（或 calib --capture-from "
              + (first.get("log_dir") or "<checks目录>") + " --expect PASS|FAIL|WARN --why '...')")
    # v3.9 校准闭环：签字与机器不一致（或人工放行 WARN）时，一条命令固化金样本。
    # 人机一致且无判例价值的签字不必强制入库；给了 --golden 就是从现场收割。
    if getattr(a, "golden", ""):
        if not first.get("log_dir") or not os.path.isdir(first["log_dir"]):
            print("[WARN] 本次双检现场目录不存在，金样本入库失败（log_dir 缺失）")
        else:
            import golden
            golden.capture_from_qc(
                first["log_dir"], check="auto",
                expect=("PASS" if verdict == "pass" else "FAIL"),
                why=a.golden or (a.issues or ""), seg=a.seg,
                tolerant=bool(getattr(a, "golden_tolerant", False)))


def cmd_calib(a):
    """金样本校准（v3.9）：--run 回归；--capture-from 入库；--promote 候选转正；--list-pending 候选区。"""
    import golden
    if a.run:
        sys.exit(golden.run_regress())
    if getattr(a, "list_pending", False):
        golden.list_pending()
        return
    if getattr(a, "promote", None):
        golden.promote(a.promote, check=a.check, expect=a.expect, why=a.why,
                       tolerant=bool(a.tolerant))
        return
    if a.capture_from:
        golden.capture_from_qc(os.path.abspath(a.capture_from), check=a.check,
                               expect=a.expect, why=a.why, seg=a.seg,
                               tolerant=bool(a.tolerant),
                               spec_file=getattr(a, "spec_file", None))
        return
    print("用法: h3proj.py calib --run | --capture-from <checks目录> --expect PASS|FAIL|WARN "
          "[--seg X] [--check auto] [--why '...'] [--tolerant] | --promote <候选id> --expect ... "
          "| --list-pending")


# ── finish ──────────────────────────────────────────────
def cmd_finish(a):
    paths.require_project()
    d = load_progress()
    s = seg_of(d, a.seg)
    if not s:
        raise SystemExit(f"[REFUSE] 台账里没有 {a.seg}")
    require_current_inputs(a.seg, s)
    require_review(s)
    require_configured_reviews(paths.PROJECT_DIR, load_plan(), a.seg)
    if (s.get("first") or {}).get("verdict") != "PASS":
        raise SystemExit(f"[REFUSE] {a.seg} 没有一采双检 PASS 记录 —— 这就是 SOP 闸门，"
                         "先 h3proj.py gate 再谈收片。")
    if (s.get("visual_review") or {}).get("verdict") != "pass":
        raise SystemExit(f"[REFUSE] {a.seg} 还没做视觉复核签字 —— "
                         f"h3proj.py review --seg {a.seg} --pass")

    final = a.final
    if not final:
        final = (s.get("files") or {}).get("final")
    if not final or not os.path.isfile(final):
        raise SystemExit("[FATAL] 找不到终片文件。先 sop_run.py final --seg " + a.seg + " 或显式 --final")

    final_hash = file_hash(final)
    first_hash = (s.get("first") or {}).get("artifact_sha256")
    if final_hash != first_hash:
        final_review = s.get("final_review") or {}
        if final_review.get("verdict") != "pass" or final_review.get("artifact_sha256") != final_hash:
            raise SystemExit("[REFUSE] 所选终片与已审视频不同，必须对本版终片单独审查并记录 final_review")
    st = stream_summary(final)
    if not st.get("has_video") or st.get("duration", 0) <= 0:
        raise SystemExit("[REFUSE] 终片没有有效视频流")
    audio_from = a.audio_from
    if not st["has_audio"] and not a.audio_silent:
        audio_from = audio_from or (s.get("files") or {}).get("audio_src")
        if not audio_from:
            raise SystemExit("[FATAL] 终片无音轨，且没给 --audio-from。先 sop_run.py final 记录音轨来源；"
                             "本段本来就不需要声音就用 --audio-silent。")

    os.makedirs(paths.FINISH_DIR, exist_ok=True)
    out = os.path.join(paths.FINISH_DIR, f"{a.seg}.mp4")
    # 顺序锁：先写临时文件，复检通过才 os.replace 原位替换（2026-11-01）。
    # 直接写 out 的话，重跑到一半失败会把上一版好交付片覆盖成半截文件。
    tmp = out + ".tmp.mp4"
    wav = os.path.join(paths.tmp_audio(), f"{a.seg}_aud.wav")

    # 1) 取音轨（终片自带就用终片的；否则用指定源）。
    #    v3.6 默认原生直取（v3.5 拍板「H3 原生音轨全保留」），不再默认清床音：
    #    旧默认的 audio_gate 频谱减法每段白费几十秒，还把要保留的原生拟音/台词
    #    气息削掉，清完接缝照样断层、最终还是靠 mix-native 低电平床盖住 = 纯负收益。
    #    接缝断层由 concat --audio-crossfade + mix-native 处理，段级不清。
    src = final if st["has_audio"] else audio_from
    if a.audio_silent:
        # 该段本来就不需要 H3 的声音（无对白、无可用拟音），而 H3 给的是一整段铺满的乐音——
        # 频谱减除法把"内容"也一起当内容保下来，清不干净。正确做法是直接铺数字静音，
        # 环境音/配乐统一在剪辑期铺（这也是"床音必须清零"最彻底的实现）。
        print("[1/4] 音轨改为数字静音（--audio-silent）：不取 H3 的乐音")
        dur = st.get("duration") or 10.0
        r = subprocess.run([paths.FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                            "-t", f"{float(dur):.3f}", "-c:a", "pcm_s16le", wav],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not os.path.isfile(wav):
            print(r.stderr[-1200:])
            raise SystemExit("[FATAL] 生成静音轨失败")
    elif a.clean_bed:
        # 备胎路径：仅当床音真的成为交付问题（后期盖不住）时手动启用。
        print(f"[1/4] 清床音（--clean-bed 备胎）: {os.path.basename(src)}")
        gate_args = [PY, os.path.join(HERE, "audio_gate.py"), "--in", src,
                     "--out", wav, "--audio-only"]
        for opt, val in (("--frame-sel", a.frame_sel), ("--alpha-bed", a.alpha_bed),
                         ("--alpha-fx", a.alpha_fx), ("--fx-snr", a.fx_snr),
                         ("--quiet-gain", a.quiet_gain)):
            if val is not None:
                gate_args += [opt, str(val)]
        if a.frame_sel is not None or a.alpha_bed is not None:
            print(f"     gate 参数: frame-sel={a.frame_sel} alpha-bed={a.alpha_bed} "
                  f"alpha-fx={a.alpha_fx} fx-snr={a.fx_snr} quiet-gain={a.quiet_gain}")
        r = subprocess.run(gate_args, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode not in (0, None) or not os.path.isfile(wav):
            print(r.stdout[-1500:], r.stderr[-1500:])
            raise SystemExit("[FATAL] audio_gate 失败")
    else:
        print(f"[1/4] 原生音轨直取: {os.path.basename(src)}（台词/拟音/床音全保留；要清床音用 --clean-bed）")
        r = subprocess.run([paths.FFMPEG, "-y", "-v", "error", "-i", src,
                            "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", wav],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not os.path.isfile(wav):
            print(r.stderr[-1200:])
            raise SystemExit("[FATAL] 原生音轨抽取失败")
    # 1.5) 段尾淡出：拼接安全。哭腔延续豁免放行的段，最后一拍可能是被截断的
    # 哭腔/拟音，硬切到下一段会爆音；统一对最后 0.35s 做等功率淡出（对
    # 本来就该静音的段尾零副作用）。
    try:
        import wave as _wv
        with _wv.open(wav, "rb") as _f:
            _dur = _f.getnframes() / float(_f.getframerate())
        if _dur > 1.0:
            # 规则：如果画面结尾人物是动态的，不用清除尾音（保留尾音自然贯通到下一段）
            first_qc = s.get("first") or {}
            tail_eval = ((first_qc.get("visual") or {}).get("sequence") or {}).get("tail_motion_eval") or {}
            tail_ratio = tail_eval.get("ratio", 0.0)
            is_dynamic_tail = getattr(a, "keep_tail_audio", False) or (tail_ratio >= 0.35)

            if is_dynamic_tail:
                print(f"     [note] 画面结尾人物为动态（尾拍能量比 {tail_ratio:.2f}），不用清除尾音，保留自然尾音延展")
            else:
                _st = max(0.0, _dur - 0.35)
                _wav2 = wav + ".fade.wav"
                _r2 = subprocess.run([paths.FFMPEG, "-y", "-v", "error", "-i", wav,
                                      "-af", "afade=t=out:st=%.3f:d=0.35" % _st, _wav2],
                                     capture_output=True, text=True, encoding="utf-8", errors="replace")
                if _r2.returncode == 0 and os.path.isfile(_wav2):
                    os.replace(_wav2, wav)
                print("     段尾淡出 0.35s（音频 %.2fs）" % _dur)
    except Exception as _e:
        print("[WARN] 段尾淡出跳过: %s" % _e)
    # 2) mux 到终片画面
    print(f"[2/4] mux 到终片画面 {st['width']}x{st['height']}")
    cmd = [paths.FFMPEG, "-y", "-v", "error", "-i", final, "-i", wav,
           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-shortest", tmp]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-1500:])
        raise SystemExit("[FATAL] ffmpeg mux 失败")
    # 3) 复检（对 tmp 检，通过才替换）。v3.6 起走**快速模式**（full=False）：
    #    mux 是 -c:v copy，画面与已签字的一采逐字节相同，抽帧/光流/节拍证据包
    #    全是重跑（十几秒/段，收益 0），只查流完整性 + 音频。
    print(f"[3/4] 复检 {os.path.basename(tmp)}（快速模式）")
    spec = seg_spec(a.seg)
    # 音频口径：拟音 v3.5 起只记录不判定（不阻断交付），强判 = 白判，统一 auto；
    # --audio-silent 的段是数字静音，走「全段静音」分支（no），否则「拟音 0 个」假 FAIL。
    fx_mode = "no" if a.audio_silent else "auto"
    qc2 = run_qc(tmp, "auto" if spec.get("dialogue") is None else ("yes" if spec.get("dialogue") else "no"),
                 fx_mode, tag=a.seg + "_deliver", seg=a.seg, seam=False, full=False)
    print_qc(qc2, title="交付复检")
    _audio_kw = ("音频不达标", "该文件没有音轨")
    vis_fails = [x for x in qc2["reasons"] if not x.startswith(_audio_kw)]
    audio_fails = [x for x in qc2["reasons"] if x.startswith(_audio_kw)]
    if qc2["verdict"] != "PASS":
        print(f"[!] 交付片视觉复检未通过：新片保留在 {tmp}，未覆盖旧交付"
              f"（人工确认：好的话把它改名为 {os.path.basename(out)}，差则重抽）")
        sys.exit(1)
    os.replace(tmp, out)  # 顺序锁：复检通过才原位替换交付片
    # 4) 记账 —— v3.5 口径：交付复检里只有**视觉**项是硬闸门
    #    （瞬移/尾拍/接缝）。v3.5 起交付音轨 = H3 原生音轨全保留（台词/拟音不再替换），
    #    音频侧后期只做接缝淡化+低电平铺床+loudnorm，所以「音频不达标/没有音轨」
    #    降级为建议，不再把段打成"失败待复核"卡死 concat。
    s["deliver"] = {"path": out, "bed_db": (qc2["audio"] or {}).get("bed_db"),
                    "artifact_sha256": file_hash(out),
                    "input_fingerprint": s.get("input_fingerprint"),
                    "verdict": qc2["verdict"], "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "size_mb": round(os.path.getsize(out) / 1048576, 2)}
    s["status"] = "完成"
    if qc2["verdict"] != "PASS":
        s["fail_reason"] = qc2["reasons"]
    save_progress(d)
    print(f"[4/4] 交付: {out}  ({s['deliver']['size_mb']} MB, 床音 {s['deliver']['bed_db']} dBFS)")
    if audio_fails:
        print("[note] 音画分流模式：以下音频项降级为建议（不阻断交付，film 模式上音时接手）：")
        for x in audio_fails:
            print("    - " + x)


# ── concat ──────────────────────────────────────────────
def audio_pop_check(path, boundaries=(), win_ms=1.0, spike_db=20.0):
    """音频咔嗒/爆音检测（记录不判定，WARN 级）。咔嗒形态：毫秒级能量尖峰，
    比前后邻域中位数高出一大截、且邻域本身安静（对话起始/拟音是宽带渐起，
    不会在 1ms 尺度上孤立跳 20dB）。返回尖峰时刻列表（秒）。"""
    import numpy as np
    cmd = [paths.FFMPEG, "-v", "error", "-i", path, "-ac", "1", "-ar", "48000",
           "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    x = np.frombuffer(r.stdout, dtype=np.float32)
    if x.size < 96000:
        return []
    w = max(1, int(48000 * win_ms / 1000))
    m = x.size // w
    e = (x[:m * w].reshape(m, w) ** 2).mean(axis=1)
    edb = 10.0 * np.log10(e + 1e-12)
    k = int(0.02 / (win_ms / 1000.0))          # ±20ms 邻域
    pops = []
    for i in range(k, m - k):
        nb = np.median(edb[i - k:i + k + 1])
        if nb < -32.0 and edb[i] - nb > spike_db:
            t = i * win_ms / 1000.0
            if not pops or t - pops[-1] > 0.05:
                pops.append(round(t, 3))
    return pops


def cmd_concat(a):
    paths.require_project()
    d = load_progress()
    order = []
    if a.order:
        order = [x.strip() for x in open(a.order, encoding="utf-8") if x.strip()
                 and not x.strip().startswith("#")]
    else:
        # 兼容两种状态字："完成" 是 finish 写入的规范值；"已交付" 可能来自
        # 展示层/手工台账，历史上曾因两者不同步导致 concat 拒绝拼接
        _done = ("完成", "已交付")
        order = [s for s in plan_order() if (d["segs"].get(s) or {}).get("status") in _done]
        rest = [s for s in plan_order() if s not in order]
        if rest:
            print(f"[REFUSE] 还有 {len(rest)} 段没完成: {rest} —— 全片拼接拒绝半成品")
            sys.exit(1)
    if not order or len(order) != len(set(order)) or set(order) != set(plan_order()):
        raise SystemExit("[REFUSE] 拼接清单必须完整且不重复覆盖计划分镜")
    files, sizes = [], []
    chains = set()
    for seg in order:
        rec = d["segs"].get(seg) or {}
        require_current_inputs(seg, rec)
        require_review(rec)
        delivery = rec.get("deliver") or {}
        if delivery.get("verdict") != "PASS" or delivery.get("input_fingerprint") != rec.get("input_fingerprint"):
            raise SystemExit("[REFUSE] 缺少有效交付检查或输入版本已改变")
        p = (rec.get("deliver") or {}).get("path")
        if not p or not os.path.isfile(p):
            print(f"[REFUSE] {seg} 没有交付片")
            sys.exit(1)
        require_artifact(p, delivery.get("artifact_sha256"))
        cname = ((rec.get("chain") or {}).get("name") or "").strip()
        if cname:
            chains.add(cname)
        files.append(p)
        st = stream_summary(p)
        sizes.append((st["width"], st["height"]))
    if len(chains) > 1:
        print(f"[REFUSE] 这些段来自不同的导演台工程 {sorted(chains)} —— 不是同一条时间轴，"
              "拼起来接缝和续接都对不上。这正是中途换了工程名的后果。")
        sys.exit(1)
    print(f"{len(files)} 段, 分辨率 {set(sizes)}" + (f", 工程 {chains.pop()}" if chains else ""))
    out = a.out or os.path.join(paths.PROJECT_DIR, "全片.mp4")
    if any(os.path.normcase(os.path.realpath(out)) == os.path.normcase(os.path.realpath(p)) for p in files):
        raise SystemExit("[REFUSE] 拼接输出不能覆盖输入分镜")
    require_configured_reviews(paths.PROJECT_DIR, load_plan(), "concat")
    xf = getattr(a, "audio_crossfade", 0.0) or 0.0
    fps = 24.0  # H3 全链固定 24fps，裁帧↔时间换算用
    # ── 续接钉帧裁头：钉帧数是 submit 时写死的生成参数（latent 注入 cont.frames 帧），
    # 直接信台账、不做逐帧比对——静态场景会让逐帧检测误判（画面不动≠帧重复），且慢。
    # 每段（除首段/--cont off 段）开头固定复现上一段尾帧 cont.frames 帧，
    # 直接拼接会顿挫；音视频同步裁掉（只裁视频不裁音频会音画错位）。
    # 有裁帧时视频必须重编码（crf14 近无损）。
    trims = [int(((d["segs"].get(seg) or {}).get("cont") or {}).get("frames") or 0)
             for seg in order]
    if getattr(a, "trim_head", True) is False:
        trims = [0] * len(files)
    if any(trims):
        info = " ".join(f"{order[i]}:{trims[i]}" for i in range(len(files)) if trims[i])
        print(f"[trim] 裁头(台账 cont.frames): {info} —— 共 {sum(trims)} 帧"
              f"（{sum(trims) / fps:.2f}s 续接重复）")
    if len(set(sizes)) == 1 and xf <= 0 and not any(trims):
        lst = os.path.join(paths.tmp_audio(), "concat_list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for p in files:
                f.write("file '%s'\n" % p.replace("\\", "/"))
        cmd = [paths.FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
               "-i", lst, "-c", "copy", out]
    elif len(set(sizes)) == 1 and not any(trims):
        # 分辨率一致 + 需要音频淡化：**视频流 copy 零转码**，只对音频做 filter_complex。
        # （2026-10-31 实测教训：整片走 filter_complex 会被默认编码器压成
        #   mpeg4 ~700kbps，8.7Mbps 的高画质源被压掉 92%，成片肉眼可见劣化。）
        lst = os.path.join(paths.tmp_audio(), "concat_list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for p in files:
                f.write("file '%s'\n" % p.replace("\\", "/"))
        parts, labels = [], []
        for i, p in enumerate(files):
            dur_i = float((stream_summary(p) or {}).get("duration") or 0)
            if xf > 0 and dur_i > 2 * xf + 0.1:
                parts.append(
                    f"[{i + 1}:a]afade=t=in:st=0:d={xf}:curve=qsin,"
                    f"afade=t=out:st={dur_i - xf:.3f}:d={xf}:curve=qsin[a{i}]")
            else:
                parts.append(f"[{i + 1}:a]anull[a{i}]")
            labels.append(f"[a{i}]")
        fc = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(files)}:v=0:a=1[a]"
        cmd = [paths.FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst]
        for p in files:
            cmd += ["-i", p]
        cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out]
    else:
        # 需要裁头或分辨率不一致：filter_complex 全片一次重编码。
        # 视频统一 libx264 crf14（近无损，防 ffmpeg 默认 mpeg4 低码率劣化）。
        w, h = sizes[0]
        same_size = len(set(sizes)) == 1
        parts, labels = [], []
        for i, p in enumerate(files):
            vpre = f"scale={w}:{h},setsar=1," if not same_size else ""
            parts.append(f"[{i}:v]{vpre}trim=start_frame={trims[i]},setpts=PTS-STARTPTS[v{i}]")
            dur_i = float((stream_summary(p) or {}).get("duration") or 0)
            t_i = trims[i] / fps
            eff = dur_i - t_i
            atrim = f"atrim=start={t_i:.4f},asetpts=PTS-STARTPTS," if t_i > 0 else ""
            # --audio-crossfade N：段间音轨等功率交叉淡化（默认 0=关闭，逐段硬接）。
            # 实现为"段尾 N 秒淡出 + 段首 N 秒淡入"原位淡化：不重叠、不改变各段
            # 时长，音画永不失步；qsin 曲线近似等功率交叉淡化。段太短（<2N+0.1s）
            # 或探测不到时长时该段跳过淡化，宁可不淡也不切错位置。淡化时长按裁后时长算。
            if xf > 0 and eff > 2 * xf + 0.1:
                parts.append(
                    f"[{i}:a]{atrim}afade=t=in:st=0:d={xf}:curve=qsin,"
                    f"afade=t=out:st={eff - xf:.3f}:d={xf}:curve=qsin[a{i}]")
            else:
                parts.append(f"[{i}:a]{atrim}anull[a{i}]")
            labels.append(f"[v{i}][a{i}]")
        fc = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(files)}:v=1:a=1[v][a]"
        cmd = [paths.FFMPEG, "-y", "-v", "error"]
        for p in files:
            cmd += ["-i", p]
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-crf", "14", "-preset", "medium",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out]
    candidate = out + ".candidate.mp4"
    cmd[-1] = candidate
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise SystemExit("[FATAL] 拼接失败；上一版成片未覆盖")
    summary = stream_summary(candidate)
    if not summary.get("has_video") or summary.get("duration", 0) <= 0:
        raise SystemExit("[REFUSE] 拼接候选没有有效视频流；上一版成片未覆盖")
    decode = subprocess.run([paths.FFMPEG, "-v", "error", "-xerror", "-i", candidate,
                             "-f", "null", "-"], capture_output=True)
    expected = sum(float(stream_summary(p).get("duration", 0)) - trims[i] / fps for i,p in enumerate(files))
    if decode.returncode or abs(summary["duration"] - expected) > max(0.25, len(files) * 0.05):
        raise SystemExit("[REFUSE] 拼接候选解码或总时长异常；上一版成片未覆盖")
    os.replace(candidate, out)
    d["concat"] = {"path": out, "sha256": file_hash(out), "status": "needs_review",
                   "sources": {seg: d["segs"][seg]["deliver"]["artifact_sha256"] for seg in order}}
    save_progress(d)
    print(f"[OK] 拼接产物待全片审查: {out}")
    # 音频接缝咔嗒检测（记录不判定）：段边界 ±60ms 内的尖峰 = 接缝爆音，
    # 其余位置的孤立尖峰也报出来（可能是拟音贴边被切）。WARN 级，人工确认后
    # 可用 --audio-crossfade 0.15 重拼或剪辑兜底。
    try:
        bounds = []
        acc = 0.0
        for i, p in enumerate(files[:-1]):
            acc += float((stream_summary(p) or {}).get("duration") or 0) - trims[i] / fps
            bounds.append(acc)
        pops = audio_pop_check(out)
        near = [t for t in pops if any(abs(t - b) <= 0.06 for b in bounds)]
        far = [t for t in pops if t not in near]
        if pops:
            print(f"[WARN] 音频尖峰 {len(pops)} 处" +
                  (f"（接缝附近 {len(near)} 处: {', '.join(f'{t:.2f}s' for t in near[:6])}）"
                   if near else "（均不在接缝附近）"))
            if far:
                print(f"       其他位置: {', '.join(f'{t:.2f}s' for t in far[:8])}")
        else:
            print("[pop] 音频咔嗒检测: 干净")
    except Exception as _e:
        print(f"[WARN] 咔嗒检测跳过: {_e}")
    # 视觉接缝复盘（记录不判定）：交付片头部已裁掉续接钉帧，相邻段首尾是"动作进行中"
    # 的承接，不要求近似；段间设计了硬切的 corr 天然低。这里只给数值和并排图，
    # 供翻片时重点检查接缝两侧的人物/道具/光线连续性。
    try:
        import sop_check
        # 段间色彩漂移量化（v3.10.2，记录不判定，EXP-03）：每段均匀抽帧算均值色/亮度/饱和度，
        # 相邻段 Δ 为纯统计输出，不参与任何 PASS/FAIL；是否需要统一 curve 后处理等数据说话。
        col = []
        for p in files:
            try:
                col.append(sop_check.color_stats(p))
            except Exception:
                col.append(None)
        vis = []
        for i in range(len(files) - 1):
            sm = sop_check.seam_similarity(files[i], files[i + 1])
            if sm:
                sm["between"] = [order[i], order[i + 1]]
                ca, cb = col[i], col[i + 1]
                if ca and cb:
                    sm["color_delta"] = {
                        "bgr": [round(cb["bgr_mean"][k] - ca["bgr_mean"][k], 2) for k in range(3)],
                        "v": round(cb["v_mean"] - ca["v_mean"], 2),
                        "s": round(cb["s_mean"] - ca["s_mean"], 2)}
                vis.append(sm)
        if vis:
            rep_v = os.path.join(paths.PROJECT_DIR, "visual_seam_report.json")
            json.dump(vis, open(rep_v, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"[seam] 视觉接缝参考（记录不判定）: {rep_v}")
            for sm in vis:
                cd = sm.get("color_delta")
                extra = (f" | Δ色BGR={cd['bgr']} Δ亮={cd['v']:+.1f} Δ饱和={cd['s']:+.1f}"
                         if cd else "")
                print(f"    {sm['between'][0]} → {sm['between'][1]}: "
                      f"frame_corr={sm['frame_corr']} hist_corr={sm['hist_corr']}{extra}")
    except Exception as _e:
        print(f"[WARN] 视觉接缝复盘跳过: {_e}")
    # 接缝复盘
    rep = os.path.join(paths.PROJECT_DIR, "seam_report.json")
    r = subprocess.run([PY, os.path.join(HERE, "diagnose_audio.py"), "--dir", paths.FINISH_DIR,
                        "--order", a.order or _write_order(order), "--out", rep],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-1200:] or r.stderr[-1200:])


def _write_order(order):
    p = os.path.join(paths.tmp_audio(), "order.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(order))
    return p


# ── residue ─────────────────────────────────────────────
RESIDUE_GLOBS = ["ov_*.json", "ov_seg*.json", "diagnose_audio.json", "n308_to_n304.json",
                 "*.mp4", "*.wav", "prompt_*.txt"]
RESIDUE_NAMES = ["__pycache__", "_audio_tmp"]


def scan_residue():
    hits = []
    for name in RESIDUE_NAMES:
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            n = len(os.listdir(p)) if os.path.isdir(p) else 1
            hits.append((p, f"目录/文件（{n} 项）"))
    import glob
    for g in RESIDUE_GLOBS:
        for p in glob.glob(os.path.join(HERE, g)):
            hits.append((p, "项目专属产物落在 scripts/ 里"))
    for p in glob.glob(os.path.join(HERE, "checks", "2*")):
        hits.append((p, "旧的时间戳自检目录"))
    try:
        st = json.load(open(os.path.join(HERE, "state.json"), encoding="utf-8"))
        if st:
            hits.append((os.path.join(HERE, "state.json"), f"残留运行状态 {list(st)[:4]}"))
    except Exception:
        pass
    return hits


def cmd_postmortem(a):
    """项目复盘报告：从台账汇总重抽/FAIL 分布/交付清单，沉淀给 skill 改进。"""
    paths.require_project()
    import datetime
    d = paths.PROJECT_DIR
    prog = load_progress()
    segs = prog.get("segs", {})
    rows, fail_counter, total_reroll = [], {}, 0
    for sid in sorted(segs):
        s = segs[sid]
        r = int(s.get("reroll") or 0)
        total_reroll += r
        reasons = s.get("fail_reason") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        for x in reasons:
            key = re.sub(r"\d+\.\d+", "N", str(x))[:60]
            fail_counter[key] = fail_counter.get(key, 0) + 1
        dl = s.get("deliver") or {}
        fi = s.get("first") or {}
        rows.append((sid, s.get("status", "?"), r, s.get("seed", "-"),
                     dl.get("size_mb", "-"), dl.get("bed_db", "-"),
                     fi.get("ts", "-"), dl.get("ts", "-")))
    lines = [f"# 复盘报告 · {os.path.basename(d)}",
             f"生成时间：{datetime.datetime.now():%Y-%m-%d %H:%M}  |  段数 {len(segs)}  |  总重抽 {total_reroll}",
             "",
             "| 段 | 状态 | 重抽 | 最终seed | 交付MB | 床音dBFS | 一采时间 | 交付时间 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    if fail_counter:
        lines += ["", "## FAIL 原因分布（数字已脱敏，次数倒序）", ""]
        for k, v in sorted(fail_counter.items(), key=lambda x: -x[1]):
            lines.append(f"- {v} 次 · {k}")
    st_count = {}
    for sid in segs:
        st = segs[sid].get("status", "?")
        st_count[st] = st_count.get(st, 0) + 1
    lines += ["", "## 状态分布", ""] + [f"- {k}: {v}" for k, v in st_count.items()]
    report = "\n".join(lines) + "\n"
    out = os.path.join(d, f"复盘_{datetime.datetime.now():%Y%m%d_%H%M}.md")
    open(out, "w", encoding="utf-8").write(report)
    print(report)
    print(f"[OK] 报告: {out}")


def cmd_residue(a):
    hits = scan_residue()
    if not hits:
        print("[OK] 技能目录干净：没有残留状态、旧抽帧、项目专属产物。")
    else:
        print(f"发现 {len(hits)} 项残留（技能目录里的运行痕迹，会干扰下一个工程）：")
        for p, why in hits:
            print(f"  - {os.path.relpath(p, paths.SKILL)}  ← {why}")
    # 顺手报告 ComfyUI 输入目录的各项目素材（只列不改，避免误删在用的）
    cg = os.path.join(paths.INPUT_DIR, "cglide")
    if os.path.isdir(cg):
        print("\nComfyUI 输入目录里的项目素材（只报告，不动）：")
        for n in sorted(os.listdir(cg)):
            p = os.path.join(cg, n)
            if os.path.isdir(p):
                age = (time.time() - os.path.getmtime(p)) / 86400
                print(f"  {n:<22} {len(os.listdir(p)):>3} 项   {age:.0f} 天未动")
    if a.clean:
        if not hits:
            return
        dst = os.path.join(paths.SKILL, "_residue_archive", time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(dst, exist_ok=True)
        for p, _ in hits:
            shutil.move(p, os.path.join(dst, os.path.basename(p)))
        for f in ("state.json",):
            full = os.path.join(HERE, f)
            if os.path.isfile(full):
                json.dump({}, open(full, "w", encoding="utf-8"))
        bl = os.path.join(HERE, "checks", "blacklist.json")
        os.makedirs(os.path.dirname(bl), exist_ok=True)
        json.dump([], open(bl, "w", encoding="utf-8"))
        print(f"\n[OK] 已归档到 {dst}（不是删除，确认无误后可自行删掉该目录）")
    elif hits:
        print("\n执行 h3proj.py residue --clean 归档这些残留。")


def cmd_path(a):
    print(json.dumps(paths.describe(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    paths.ensure_cv2_or_reexec()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new"); n.add_argument("dir"); n.add_argument("--name"); n.add_argument("--scene"); n.add_argument("--force", action="store_true")
    n.add_argument("--chain", help="导演台工程名（建议建工程时就定下来；留空则第一次 submit 时自动绑定）")
    s = sub.add_parser("status"); s.add_argument("--json", action="store_true")
    p = sub.add_parser("plan"); p.add_argument("--check", action="store_true")
    g = sub.add_parser("gate")
    g.add_argument("--seg", required=True); g.add_argument("--file")
    g.add_argument("--latest", action="store_true", help="窗口手动渲染：取输出目录最新的 mp4")
    g.add_argument("--dialogue", default="auto", choices=["auto", "yes", "no"])
    g.add_argument("--fx", default="auto", choices=["auto", "yes", "no"])
    g.add_argument("--no-abort", action="store_true")
    rv = sub.add_parser("review")
    rv.add_argument("--seg", required=True); rv.add_argument("--pass", dest="pass_", action="store_true")
    rv.add_argument("--fail", dest="pass_", action="store_false"); rv.set_defaults(pass_=None)
    rv.add_argument("--issues"); rv.add_argument("--by", default="agent")
    rv.add_argument("--video", help="Review this exact final candidate rather than the first render")
    rv.add_argument("--evidence", action="append", help="Observed frame/contact sheet/report path")
    rv.add_argument("--golden", default="",
                    help="签字的同时把本次双检现场固化成金样本（v3.9 校准闭环）。"
                         "值为判例理由，如 --golden '黄条纹被误判为水印，人工放行'。"
                         "加 --golden-tolerant 标记已知容忍（机器仍会 WARN 但接受）。")
    rv.add_argument("--golden-tolerant", dest="golden_tolerant", action="store_true")
    cal = sub.add_parser("calib")
    cal.add_argument("--run", action="store_true", help="全量金样本回归，非 0 退出=有回归")
    cal.add_argument("--capture-from", dest="capture_from",
                     help="把 checks/<tag>_<stamp> 双检现场打包入库")
    cal.add_argument("--seg", help="段号（老 qc.json 缺 beats 时从工程 segments 补）")
    cal.add_argument("--check", default="auto",
                     help="auto/tail_motion/subtitle/seam/frames（frames=手工类留给 G4/语义判官）")
    cal.add_argument("--expect", help="人工判定的正确答案 PASS/FAIL/WARN")
    cal.add_argument("--why", default="", help="判例理由")
    cal.add_argument("--tolerant", action="store_true", help="标记已知容忍")
    cal.add_argument("--spec-file", dest="spec_file",
                     help="check=semantic 时的判卷清单 json")
    cal.add_argument("--promote", metavar="候选id", help="把 golden/pending/<id> 转正入库（需 --expect）")
    cal.add_argument("--list-pending", dest="list_pending", action="store_true",
                     help="列出 watch AUTO_ABORT 自动落存的候选现场")
    fi = sub.add_parser("finish")
    fi.add_argument("--seg", required=True); fi.add_argument("--final"); fi.add_argument("--audio-from")
    fi.add_argument("--clean-bed", dest="clean_bed", action="store_true",
                    help="备胎：清床音（audio_gate 频谱减法）后再 mux。v3.6 默认原生音轨"
                         "直取、不清床（H3 原生全保留，接缝由 concat 交叉淡化 + mix-native 铺床盖）")
    fi.add_argument("--frame-sel", type=float, help="仅 --clean-bed 生效：床音估计用的低能量帧百分比（默认 40）")
    fi.add_argument("--alpha-bed", type=float, help="仅 --clean-bed 生效：床音过减因子（默认 6.0）")
    fi.add_argument("--alpha-fx", type=float, help="仅 --clean-bed 生效：对白/拟音过减因子（默认 1.0）")
    fi.add_argument("--fx-snr", type=float, help="仅 --clean-bed 生效：帧级无内容阈值（默认 4.0）")
    fi.add_argument("--quiet-gain", type=float, help="仅 --clean-bed 生效：静音帧增益（默认 0.03）")
    fi.add_argument("--audio-silent", dest="audio_silent", action="store_true",
                    help="本段不取 H3 的声音，直接铺数字静音（无对白、且 H3 只给了乐音的段落用；"
                         "环境音/配乐在剪辑期统一铺）")
    cc = sub.add_parser("concat"); cc.add_argument("--order"); cc.add_argument("--out")
    cc.add_argument("--audio-crossfade", type=float, default=0.0,
                    help="相邻段音轨等功率交叉淡化秒数（默认 0=关闭，逐段首尾硬接。"
                         "建议 0.15；只对音轨生效，不动视频切点）")
    cc.add_argument("--no-trim-head", dest="trim_head", action="store_false",
                    help="关闭续接钉帧裁头（默认开启：按台账 cont.frames 裁掉每段开头的续接重复帧，音视频同步）")
    rs = sub.add_parser("residue"); rs.add_argument("--clean", action="store_true")
    sub.add_parser("postmortem")
    bd = sub.add_parser("bind"); bd.add_argument("--chain"); bd.add_argument("--force", action="store_true")
    sub.add_parser("path")
    a = ap.parse_args()
    if a.cmd == "review" and a.pass_ is None:
        ap.error("review 需要 --pass 或 --fail")
    {"new": cmd_new, "bind": cmd_bind, "status": cmd_status, "plan": cmd_plan, "gate": cmd_gate,
     "review": cmd_review, "finish": cmd_finish, "concat": cmd_concat,
     "residue": cmd_residue, "path": cmd_path, "postmortem": cmd_postmortem,
     "calib": cmd_calib}[a.cmd](a)
