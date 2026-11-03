# -*- coding: utf-8 -*-
"""单段音频自检 v3：区分「持续床音 / 对白 / 动作拟音」三类声音。

v2 的判据（最长静音 ≥1s、有声占比 ≤0.55）在「保留动作拟音」的新要求下会误判：
一段有脚步与珠子落槽声的戏，静音段本来就短，拟音也会抬高有声占比。

v3 改成三层判定：
  1. 床音电平 bed  —— 每频点时间低分位反推的「一直在响」的成分。环境风声、
                      空间长混响、低频音乐垫都会显著抬高它。要求足够低（默认 <= -50 dBFS）。
  2. 点状事件       —— 高出床音 10dB、时长 <0.55s 的短事件＝动作拟音（脚步/碰撞/摩擦），
                      统计数量与总时长，用于确认拟音**还在**（--fx yes 时强弱判定）。
  3. 台词语义       —— 长事件（>=0.55s）视为语声，检查结束点距段末 >=1.0s（防一采截断）。

另加「段首/段尾留白」检查：拟音不得贴着段边界，否则拼接时会被硬切或跨接缝。

用法:
  python check_audio_seg.py --file <mp4> [--card S1] [--fx yes] [--json out.json]
  python check_audio_seg.py --latest
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import FFMPEG as FF, OUTPUT_DIR as OUTDIR, VOICE_CARD, tmp_audio  # noqa: E402
SR = 16000
WIN, HOP = 1024, 256            # 64ms / 16ms
SPEECH_MIN_S = 0.55             # 事件长于此视为语声（台词），否则视为拟音


def _output_prefixes():
    """输出前缀从项目握手结果取，不写死文件名（工作流会改）。"""
    try:
        import json as _j
        from paths import WF_MAP
        if WF_MAP and os.path.isfile(WF_MAP):
            return _j.load(open(WF_MAP, encoding="utf-8")).get("output_prefixes") or []
    except Exception:
        pass
    return []


def load(path):
    TMP = tmp_audio()
    wav = os.path.join(TMP, os.path.splitext(os.path.basename(path))[0] + ".wav")
    subprocess.run([FF, "-y", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "wav", wav], check=True)
    with wave.open(wav, "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def frame_rms(x, win=WIN, hop=HOP):
    if len(x) < win:
        return np.array([0.0]), np.array([0.0])
    idx = np.arange(0, len(x) - win + 1, hop)
    r = np.array([np.sqrt(np.mean(x[i:i + win] ** 2)) for i in idx])
    return r, idx / SR


def db(v):
    return -120.0 if v <= 1e-9 else 20 * np.log10(v)


def detect_events(x, bed_rms, thr_db=10.0, gap_s=0.2, rel_peak_db=-16.0):
    """可闻事件检测。

    阈值取两者较大值：高出床音 10dB，且不低于全段峰值 -16dB。
    第二条很关键 —— 床音被清理到 -60dBFS 后，-37dB 的谱减残差若只按「相对床音」
    判会全部被当成事件；但相对 -18dB 的峰值它低 19dB，人耳不构成独立声音。
    """
    r, t = frame_rms(x)
    peak_rms = float(np.percentile(r, 95))
    thr = max(bed_rms * 10 ** (thr_db / 20.0), peak_rms * 10 ** (rel_peak_db / 20.0), 1e-4)
    on = r > thr
    ev, i, n = [], 0, len(on)
    while i < n:
        if not on[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and on[j + 1]:
            j += 1
        ev.append([float(t[i]), float(t[j] + WIN / SR), float(db(r[i:j + 1].max()))])
        i = j + 1
    merged = []
    for e in ev:
        if merged and e[0] - merged[-1][1] <= gap_s:
            merged[-1][1] = e[1]
            merged[-1][2] = max(merged[-1][2], e[2])
        else:
            merged.append(e)
    return [dict(start=round(a, 2), end=round(b, 2), peak_db=round(c, 1), dur=round(b - a, 2))
            for a, b, c in merged]


def _looks_like_speech(x, t0, t1):
    """频谱判据：人声是强谐波，拟音是宽带或低频，两者谱平坦度差一个量级。

    纯按能量+时长判语声会把门缝合拢、鞋底、布料这类低频闷响算成台词，
    于是 speech_end 顶到段末、段尾留白判 0。这里用谱平坦度为主、F0 自相关
    置信度为辅，两条都不放行才判拟音。
    """
    s, e = int(t0 * SR), int(t1 * SR)
    seg = x[s:e]
    if len(seg) < 512:
        return False
    seg = (seg - seg.mean())
    if np.sqrt(np.mean(seg ** 2)) <= 1e-6:
        return False
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2 + 1e-12
    flat = float(np.exp(np.mean(np.log(spec))) / np.mean(spec))
    ac = np.correlate(seg, seg, "full")[len(seg) - 1:]
    lo, hi = int(SR / 420), int(SR / 100)
    conf = 0.0
    if hi < len(ac):
        k = int(np.argmax(ac[lo:hi])) + lo
        conf = float(ac[k] / ac[0]) if ac[0] > 0 else 0.0
    if flat < 0.02:
        return True
    # 气声/低语台词平坦度可到 0.02–0.06，但基频仍稳定；闷响两条都不过
    if flat < 0.06 and conf >= 0.25:
        return True
    return False


def estimate_f0(x, floor_rms, frame=640, hop=320, fmin=120, fmax=420):
    """只在明显高于底噪的帧上估基频，避开床音污染。"""
    lo, hi = int(SR / fmax), int(SR / fmin)
    f0s = []
    th = max(floor_rms * 3.0, 0.01)
    for i in range(0, len(x) - frame, hop):
        fr = x[i:i + frame]
        if np.sqrt(np.mean(fr ** 2)) < th:
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, "full")[frame - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        if len(seg) == 0:
            continue
        k = int(np.argmax(seg)) + lo
        if ac[k] / ac[0] > 0.3:
            for mult in (2, 3):
                k2 = k * mult
                if lo <= k2 < hi and k2 < len(ac) and ac[k2] / ac[0] > 0.85 * (ac[k] / ac[0]):
                    k = k2
                    break
            f0 = SR / k
            if fmin <= f0 <= fmax:
                f0s.append(f0)
    if len(f0s) < 6:
        return None, 0
    return float(np.median(f0s)), len(f0s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--card", default="auto",
                    help="声线卡 key（S1/S2/S3）；不给则只测门限、不比对 F0")
    ap.add_argument("--dialogue", choices=["auto", "yes", "no"], default="auto")
    ap.add_argument("--fx", choices=["auto", "yes", "no"], default="auto",
                    help="yes=要求存在动作拟音（短事件）")
    ap.add_argument("--tail-exempt", action="store_true",
                    help="续接/动态尾段豁免（chain_continue / tail_dynamic）：结尾动作、"
                         "拟音或台词收束顶到段末属正常，段尾留白阈值按哭腔豁免口径降到 0.15s，"
                         "不再触发重抽。拼接安全由段尾裁剪 + 拼接兜底。")
    ap.add_argument("--json")
    a = ap.parse_args()

    path = a.file
    if a.latest or not path:
        prefixes = _output_prefixes()
        pats = [os.path.join(OUTDIR, p + "*.mp4") for p in prefixes] or [os.path.join(OUTDIR, "*.mp4")]
        cands = sorted({f for pat in pats for f in glob.glob(pat)}, key=os.path.getmtime)
        if not cands:
            print("未找到可分析的 mp4（输出前缀取自 wf_map.json）")
            return 2
        path = cands[-1]
        print(f"[WARN] --latest 按 mtime 取全目录最新：{os.path.basename(path)}\n"
              f"       若有其它任务同时在跑，可能取到别人批次的文件。判定归属请用 "
              f"`sop_run.py watch`（按基线增量 + prompt_id 归属）或显式 --file。", flush=True)

    try:
        x = load(path)
    except Exception as e:
        msg = {"file": path, "verdict": "NO_AUDIO", "checks": [],
               "stderr": f"无法解码音轨（该文件可能没有音频流）: {e}"}
        print(f"\n[NO_AUDIO] {os.path.basename(path)} 没有可解码的音轨。")
        if a.json:
            json.dump(msg, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return 3
    dur = len(x) / SR
    r, t = frame_rms(x)
    # 15 分位 = 无内容时段的电平（床音）；台词密集段也不会占满 85%
    bed = float(np.percentile(r, 15))
    bed_db = db(bed)
    peak = float(np.percentile(r, 95))

    events = detect_events(x, bed)
    # 只有「像人声」的长事件才算台词。纯按时长判会把段尾的闷响（门缝合拢、
    # 脚步、布料低频传导）也算成台词，于是 speech_end 顶到段末、留白判 0，
    # 触发 AUTO_ABORT 白换 seed。实测区分度很高：
    #   人声      谱平坦度 0.002 左右，F0 自相关置信度 >= 0.28
    #   低频闷响  谱平坦度 0.044，F0 置信度 0.16（无稳定基频）
    for e in events:
        if e["dur"] >= SPEECH_MIN_S:
            e["speech"] = _looks_like_speech(x, e["start"], e["end"])
        else:
            e["speech"] = False
    speech = [e for e in events if e["dur"] >= SPEECH_MIN_S and e["speech"]]
    # 逐语声事件估 F0：哭腔延续豁免要用（延续声是同角色哭腔 → F0 落在声域内）
    for e in speech:
        seg = x[int(e["start"] * SR):int(e["end"] * SR)]
        if len(seg) < SR // 4:
            e["f0"] = None
            continue
        seg_bed = float(np.percentile(frame_rms(seg)[0], 15))
        f0e, _ = estimate_f0(seg, seg_bed)
        e["f0"] = None if not f0e else round(f0e, 1)
    fx = [e for e in events if not (e["dur"] >= SPEECH_MIN_S and e["speech"])]
    speech_end = max((e["end"] for e in speech), default=None)
    last_event_end = max((e["end"] for e in events), default=0.0)
    tail_silence = dur - last_event_end
    head_silence = min((e["start"] for e in events), default=dur)

    # 门限（max_bed / min_tail）全项目统一，取任一张卡即可；
    # F0 比对只在显式给了 --card 时做 —— 多角色项目用默认 S1 比祖母段会一直误报。
    _vc = json.load(open(VOICE_CARD, encoding="utf-8"))
    _key = a.card if (a.card and a.card != "auto" and a.card in _vc) else None
    if _key:
        card = _vc[_key]["qa"]
    else:
        card = next((v["qa"] for k, v in _vc.items() if k != "_note" and "qa" in v), {})
    max_bed = card.get("max_bed_db", -50)
    min_tail = card.get("min_tail_silence", 0.35)

    has_dialogue = a.dialogue
    if has_dialogue == "auto":
        has_dialogue = "yes" if speech else "no"

    checks = []
    # 哭腔延续豁免（先算，段尾留白也要用到）：主台词（第一束语声）按时结束、
    # 其后只剩同角色哭腔（F0 落在 140–320Hz 人声域）延续到段末。表演上
    # 「喊完还在哭」是对的，真正要保的是拼接安全 → 放行台词超时、把段尾
    # 留白阈值降到 0.15s，finish 阶段对交付音频统一做 0.35s 段尾淡出兜底。
    exempt_weep = False
    if speech and speech_end is not None and (dur - speech_end) < 1.0:
        main_end = speech[0]["end"]
        follow = [e for e in speech[1:] if e.get("f0")]
        if (main_end <= dur - 1.0 and follow
                and all(140.0 <= e["f0"] <= 320.0 for e in follow)):
            exempt_weep = True
    # --tail-exempt：续接/动态尾段，结尾顶到段末是设计使然，口径同哭腔豁免
    min_tail_eff = 0.15 if (exempt_weep or a.tail_exempt) else min_tail
    tail_note = "（续接/动态尾段豁免）" if a.tail_exempt else ""
    checks.append(("床音电平", f"{bed_db:.1f} dBFS", f"<= {max_bed} dBFS（无环境音/音乐垫）",
                   bed_db <= max_bed))
    checks.append(("段尾留白", f"{tail_silence:.2f}s",
                   f">= {min_tail_eff:.2f}s（拟音不贴边界）{tail_note}",
                   tail_silence >= min_tail_eff))
    if has_dialogue == "yes":
        # v3.4 分流口径下唯一音频硬闸门：模型必须真的说了话。
        # 台词结束点/床音/留白都可降级为建议（TTS 超一点、床音反正弃用），
        # 但没说话 = 口型没有开口动作、film 模式也找不到 VAD 定位锚，必须重抽。
        checks.append(("台词存在", f"{len(speech)} 句",
                       ">= 1 句（VAD 定位锚，film 模式靠它找开口点）",
                       len(speech) >= 1))
        ok_end = speech_end is not None and (dur - speech_end) >= 1.0
        checks.append(("台词结束点",
                       f"{speech_end if speech_end is not None else '-'}s / 全段 {dur:.2f}s",
                       "距段末 >= 1.0s" + ("（哭腔延续豁免：主台词 %.2fs 已收）" % speech[0]["end"] if exempt_weep else ""),
                       bool(ok_end or exempt_weep or a.tail_exempt)))
        if a.fx == "yes":
            checks.append(("动作拟音", f"{len(fx)} 个 / {sum(e['dur'] for e in fx):.2f}s",
                           ">= 1 个（保留动作拟音）", len(fx) >= 1))
    else:
        if a.fx == "yes":
            checks.append(("动作拟音", f"{len(fx)} 个 / {sum(e['dur'] for e in fx):.2f}s",
                           ">= 1 个（保留动作拟音）", len(fx) >= 1))
        else:
            checks.append(("全段静音", f"{db(float(np.sqrt(np.mean(x ** 2)))):.1f} dBFS",
                           "<= -45 dBFS（本段无台词）", db(float(np.sqrt(np.mean(x ** 2)))) <= -45))

    f0, nfr = estimate_f0(x, bed)
    if f0 and has_dialogue == "yes":
        if _key:
            dev = abs(f0 - card["target_f0"])
            checks.append((f"语声 F0({_key})", f"{f0:.0f} Hz",
                           f"{card['target_f0']}±{card['f0_tol']} Hz"
                           + ("" if dev <= card["f0_tol"] else "｜仅警告:气声/垫音会干扰估计"), True))
        else:
            checks.append(("语声 F0(实测)", f"{f0:.0f} Hz",
                           "未指定 --card，仅记录不作判定", True))

    # 床音分类：H3 对「安静段落」会稳定垫一层乐音（实测三个不同 seed 都是 -27.0 dBFS、
    # 400Hz 及整数倍谐波），它属于**后期可清**的东西，不是 seed 问题。
    # 能清的前提是「声音与床音拉开距离」：动态范围够大 → 频谱减除法能把床音抠掉；
    # 动态范围太小说明人声/拟音被床音糊住，减完也就没声了，那种才必须重抽。
    dyn = db(peak) - bed_db
    if bed_db > max_bed:
        bed_class = "music_bed" if dyn >= 12.0 else "masking"
    else:
        bed_class = "clean"

    # v3.5 口径（2026-10-31 拍板）：台词+拟音全走 H3 原生，后期只做接缝淡化+
    # 低电平铺床+loudnorm，所以下列项目全部"后期可补/可盖"，不再触发重抽：
    #   床音电平（外部床盖）、段尾留白（crossfade 盖）、台词结束点、动作拟音
    #   （点状补）、全段静音（铺床+补音效）。
    # 唯一音频硬闸门仍是「台词存在」：没说话=口型没有开口动作，重抽/备胎 TTS 二选一。
    SOFT_CHECKS = ("床音电平", "段尾留白", "台词结束点", "动作拟音", "全段静音")

    ok = all(c[3] for c in checks if c[0] not in SOFT_CHECKS)
    print(f"\n=== {os.path.basename(path)} ===")
    print(f"时长 {dur:.2f}s | 床音 {bed_db:.1f} dBFS | 峰值(95%) {db(peak):.1f} dBFS "
          f"| 动态范围 {dyn:.1f} dB")
    print({"clean": "床音分类: clean（无需处理）",
           "music_bed": "床音分类: music_bed（乐音垫 → v3.5 低电平床覆盖即可，不阻断）",
           "masking": "床音分类: masking（v3.5 口径：低电平外部床覆盖，不重抽）"}[bed_class])
    fx_detail = " | 拟音明细 " + ", ".join(
        "%ss(%ss,%sdB)" % (e["start"], e["dur"], e["peak_db"]) for e in fx[:6]) if fx else ""
    print(f"事件 {len(events)} 个：语声 {len(speech)} / 拟音 {len(fx)}{fx_detail}")
    print(f"{'项目':<12}{'实测':<26}{'阈值':<30}结果")
    for name, val, thr_s, good in checks:
        if good:
            tag = "PASS"
        elif name in SOFT_CHECKS:
            tag = "WARN（后期可补）"
        else:
            tag = "FAIL"
        print(f"{name:<12}{val:<28}{thr_s:<32}{tag}")
    print(f"\n总判定: {'PASS 可放行' if ok else 'FAIL 需重抽（音频侧只剩台词缺失）'}")

    if a.json:
        json.dump(dict(file=path, dur=round(dur, 2), bed_db=round(bed_db, 1),
                       peak_db=round(db(peak), 1), dyn_db=round(dyn, 1),
                       bed_class=bed_class,
                       needs_bed_clean=bool(bed_class == "music_bed"),
                       speech_count=len(speech), fx_count=len(fx),
                       fx_total_s=round(sum(e["dur"] for e in fx), 2),
                       speech_end=speech_end, tail_silence=round(tail_silence, 2),
                       head_silence=round(head_silence, 2),
                       f0=None if not f0 else round(f0, 1), f0_frames=nfr,
                       events=events,
                       checks=[dict(name=c[0], value=c[1], threshold=c[2], pass_=bool(c[3])) for c in checks],
                       verdict="PASS" if ok else "FAIL"),
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
