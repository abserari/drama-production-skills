# -*- coding: utf-8 -*-
"""make_refs —— 从 H3 成片自举角色参考音（零样本克隆的原料）。

原理：分镜 txt 的台词顺序已知（谁说的、说的什么），VAD 在成片音轨里
找到语声事件，两者按序对号 → 每个角色取"最长台词"对应的事件切参考音；
F0 复核（男声 80-160Hz / 女声 170-300Hz，与 voice_card 的 qa.target_f0 比对），
防止对号错位。产出：<项目>/audio_prod/refs/<Sx>.wav + card_patch.json。

用法：
  python make_refs.py --video 成片/seg07.mp4 --seg segments/seg07.txt \
      --voice-card voice_card.json --out-dir audio_prod/refs [--apply]
不传 --apply 只打印分配表，不写文件。参考音 ≤1s 时克隆相似度会明显偏弱，
尽量挑 3s 以上的台词事件；不够就把多段同一角色的事件手工拼接后再切。
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audioprod  # noqa: E402
import h3vad  # noqa: E402

SR = h3vad.SR


def estimate_f0(x, sr, fmin=70, fmax=350):
    """自相关基频（粗）。返回 Hz 或 None。"""
    seg = x[int(0.05 * sr): int(min(len(x) / sr, 1.2) * sr)]
    if len(seg) < sr // 4:
        return None
    seg = seg - seg.mean()
    ac = np.correlate(seg, seg, mode="full")[len(seg) - 1:]
    if ac[0] <= 0:
        return None
    ac /= ac[0]
    lo, hi = int(sr / fmax), int(sr / fmin)
    if hi >= len(ac):
        return None
    k = int(np.argmax(ac[lo:hi])) + lo
    return round(sr / k, 1) if ac[k] > 0.3 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--seg", required=True)
    ap.add_argument("--voice-card", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    card = json.load(open(a.voice_card, encoding="utf-8"))
    lines = audioprod.parse_dialogue(a.seg)
    if not lines:
        raise SystemExit("[REFUSE] 该段没有台词")
    ev = h3vad.speech_events(a.video, merge_gap=0.8, min_dur=0.35)
    print(f"[vad] {len(ev)} 事件 / {len(lines)} 句台词")
    if len(ev) != len(lines):
        print("[WARN] 事件数与台词数不一致，对号可能错位，逐行核对 F0 再用")
    x = h3vad.load_mono(a.video)

    rows = []
    for i, ln in enumerate(lines):
        e = ev[i] if i < len(ev) else None
        f0 = estimate_f0(x[int(e["start"] * SR): int(e["end"] * SR)], SR) if e else None
        rows.append({"i": i, "speaker": ln["speaker"], "text": ln["text"],
                     "start": e["start"] if e else None,
                     "end": e["end"] if e else None, "dur": e["dur"] if e else 0,
                     "f0": f0})
        print(f"  #{i} {ln['speaker']} f0={f0} {e['start'] if e else '-'}-"
              f"{e['end'] if e else '-'}s ({e['dur'] if e else 0:.2f}s)「{ln['text'][:20]}」")

    # 每个角色取最长台词的事件
    picks = {}
    for r in rows:
        if r["start"] is None:
            continue
        spk, tol = card.get(r["speaker"], {}).get("qa", {}).get("target_f0"), 70
        if spk and r["f0"] and abs(r["f0"] - spk) > tol:
            print(f"[WARN] #{r['i']} f0={r['f0']} 偏离 {r['speaker']} 目标 {spk}±{tol}，疑似对号错位")
        if r["speaker"] not in picks or r["dur"] > picks[r["speaker"]]["dur"]:
            picks[r["speaker"]] = r
    if not a.apply:
        print("[dry] 加 --apply 实切")
        return

    patch = {}
    for spk, r in picks.items():
        out = os.path.join(a.out_dir, f"{spk}.wav")
        audioprod.cut_ref(a.video, r["start"], r["end"], out)
        patch[spk] = {"ref_wav": os.path.abspath(out), "ref_text": r["text"]}
    patch_path = os.path.join(a.out_dir, "card_patch.json")
    json.dump(patch, open(patch_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[patch] {patch_path} —— 人工核对 ref_text 与实际说的是否一致后，合入 voice_card.json")


if __name__ == "__main__":
    main()
