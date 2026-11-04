# -*- coding: utf-8 -*-
"""提示词 v2.1 静态 preflight：把 references/prompt_standard_v2.md 第六节的检查项变成可执行判定。

提交前跑一遍，避免「情绪词没清、音效没点名、声线卡改了一个字、台词排到末拍」这类
纯文本层面就能发现的错误浪费一次 40 分钟的生成。

用法:
  python check_prompt_v2.py --seg seg13                 # 查 prompt_v2.V2_SEGS
  python check_prompt_v2.py --ov ov_deng.json --all     # 查覆盖配置里所有段
  python check_prompt_v2.py --file my_prompt.txt --length 243

退出码: 0=PASS/WARN, 1=FAIL
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import VOICE_CARD  # noqa: E402

VOICE = json.load(open(VOICE_CARD, encoding="utf-8"))

# ── 情绪词黑名单（禁止出现在 神态/画面 描述里）────────────────────────
EMO = ["茫然", "疑惑", "困惑", "平静", "悲伤", "紧张", "犹豫", "迟疑", "欣慰", "失落",
       "期待", "无奈", "惊恐", "恐惧", "愤怒", "温柔", "惊讶", "惊愕", "惶恐", "惆怅",
       "焦虑", "忧愁", "喜出望外", "如释重负", "若有所思", "依依不舍", "极轻地", "轻轻地",
       "默默地", "狠狠地", "缓缓地", "慢慢地"]
# 出现在否定/禁止语境里是合法的（防错约束、禁止清单）
NEG_CTX = ("不得", "禁止", "无", "不写", "不许", "不要", "零容忍")

REQUIRED_SECTIONS = ["subject_definitions:", "summary:", "detailed_description:",
                     "overall_soundscape:", "non_diegetic_music:", "防错约束："]

KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ffー]")
KANJI = re.compile(r"[\u4e00-\u9fff]")


def est_dialogue_seconds(line):
    """日语台词时长粗估：假名 0.20s/字、汉字 0.26s/字、标点停顿 0.12s。气声慢速口径。"""
    punct = len(re.findall(r"[、，。？！,.?!]", line))
    return round(len(KANA.findall(line)) * 0.20 + len(KANJI.findall(line)) * 0.26 + punct * 0.12 + 0.10, 2)


class Report:
    def __init__(self, name):
        self.name = name
        self.items = []

    def add(self, level, msg):
        self.items.append((level, msg))

    def ok(self, msg):
        self.add("PASS", msg)

    def warn(self, msg):
        self.add("WARN", msg)

    def fail(self, msg):
        self.add("FAIL", msg)

    @property
    def failed(self):
        return any(lv == "FAIL" for lv, _ in self.items)

    def dump(self):
        print(f"\n=== {self.name} ===")
        for lv, msg in self.items:
            print(f"[{lv}] {msg}")
        n_f = sum(1 for lv, _ in self.items if lv == "FAIL")
        n_w = sum(1 for lv, _ in self.items if lv == "WARN")
        print(f"-- {'FAIL' if self.failed else 'PASS'}  (FAIL {n_f} / WARN {n_w})")
        return not self.failed


def strip_neg_sentences(text):
    """去掉否定/禁止语境的句子，避免防错约束里的「不得表现悲伤」被误报。"""
    out = []
    for line in text.splitlines():
        if any(k in line for k in NEG_CTX):
            continue
        out.append(line)
    return "\n".join(out)


def check(name, prompt, length=243):
    r = Report(name)

    # 1. 骨架
    missing = [s for s in REQUIRED_SECTIONS if s not in prompt]
    if missing:
        r.fail(f"缺段: {missing}（段名一个字都不能改）")
    else:
        r.ok("七段骨架齐全")

    # 2. 节拍数与帧长匹配、结尾状态
    beats = re.findall(r"\[节拍 (\d+)\]", prompt)
    nb = len(beats)
    lo, hi = (2, 3) if length <= 130 else (3, 4)
    if not (lo <= nb <= hi):
        r.warn(f"节拍数 {nb}，{length}帧建议 {lo}-{hi} 拍（每拍 2-3 秒）")
    else:
        r.ok(f"节拍数 {nb} 与 {length} 帧匹配")
    if "[结尾状态]" not in prompt:
        r.fail("缺 [结尾状态]")
    if beats and beats != [str(i + 1) for i in range(nb)]:
        r.fail(f"节拍编号不连续: {beats}")

    # 3. 权限=
    subj = re.findall(r"<Subject \d+>", prompt)
    perms = prompt.count("权限=")
    if subj and perms < len(set(subj)):
        r.fail(f"{len(set(subj))} 个 Subject 只有 {perms} 个 权限=")
    elif subj:
        r.ok(f"{len(set(subj))} 个 Subject 均有 权限=")

    # 3.5 subject_definitions 质量检查（Extender 社区实测：块里显式声明每张参考图
    # 「定义角色外观还是定义场景」，跨段一致性明显更好；只声明存在的段名不够）
    m_sd = re.search(r"subject_definitions:\s*\n(.*?)(?=\n\s*\n|\nsummary:)", prompt, re.S)
    sd_items = re.findall(r"^\s*-\s+(.+)$", m_sd.group(1), re.M) if m_sd else []
    if not sd_items:
        r.fail("subject_definitions 块为空/无条目——参考图定义缺失，跨段一致性会漂")
    else:
        r.ok(f"subject_definitions {len(sd_items)} 条")
        used_tags = set(re.findall(r"<Subject (\d+)>", prompt))
        defined = set()
        for it in sd_items:
            defined.update(re.findall(r"<Subject (\d+)>", it))
        undefined = used_tags - defined
        if undefined:
            r.warn(f"<Subject {','.join(sorted(undefined))}> 在正文用到但块里没定义——"
                   "补一行「<Subject N> 是定义……的参考图像」（角色写外观/服装，场景写环境）")
        if not any(re.search(r"外观|身份|服装|发型|长相|定义.*参考图", it) for it in sd_items):
            r.warn("subject_definitions 未显式写「定义……的参考图像」句式——"
                   "建议逐条写明它定义什么（角色外观 or 场景环境）")

    # 3.7 复杂度预算（官方 complex-budget：一段承载的主体×台词过载必崩，砍的都是最不起眼的）
    n_subj = len(set(re.findall(r"<Subject (\d+)>", prompt)))
    d_cnt = len(re.findall(r"<d>.+?</d>", prompt, re.S))
    if n_subj > 3:
        r.warn(f"Subject {n_subj} 个（>3）——多主体互抢注意力，身份漂移概率陡增，"
               "考虑把次要角色降成环境描述")
    if d_cnt >= 2:
        r.warn(f"<d> 台词 {d_cnt} 句——默认一段一句（两句实测 3 次里 2 次末句贴尾），"
               "拆 a/b 两段各放一句")
    if n_subj >= 3 and d_cnt >= 2:
        r.warn("复杂度过载：≥3 Subject + ≥2 台词——10 秒预算装不下，H3 会砍掉最不起眼的内容")

    # 4. 声线卡逐字一致
    cards = re.findall(r"^- <Audio (\d+)> (.+)$", prompt, re.M)
    if not cards:
        r.warn("未使用 <Audio N> 声线卡（无对白段可忽略）")
    for sid, txt in cards:
        hit = [k for k, v in VOICE.items()
               if k != "_note" and v["prompt_text"].strip() == txt.strip()]
        if hit:
            r.ok(f"<Audio {sid}> 与 voice_card {hit[0]} 逐字一致")
        else:
            near = [k for k in VOICE if k != "_note"
                    and VOICE[k]["prompt_text"].strip()[:12] in txt]
            r.fail(f"<Audio {sid}> 与 voice_card 不一致（最接近 {near}）——改一个字就破坏跨段声线一致")

    # 5. 情绪词（排除否定语境）
    body = strip_neg_sentences(prompt)
    hits = [w for w in EMO if w in body]
    if hits:
        r.fail(f"情绪词未清零: {hits}（改成可见肌肉动作）")
    else:
        r.ok("情绪词清零")

    # 6. 每拍音效点名 + 封口
    for i in range(nb):
        m = re.search(r"\[节拍 %d\].*?音效：([^\n]*)" % (i + 1), prompt, re.S)
        if not m:
            r.fail(f"节拍 {i+1} 缺 音效： 行")
            continue
        seg_txt = m.group(1)
        if "无（后期添加）" in seg_txt or seg_txt.strip().startswith("无"):
            r.fail(f"节拍 {i+1} 用了「音效：无」写法——模型会连该有的拟音也不出")
        elif "仅此" not in seg_txt:
            r.warn(f"节拍 {i+1} 音效未用「仅此 N 类，无其他声音」封口")
        else:
            r.ok(f"节拍 {i+1} 音效逐条点名并封口")

    # 6.5 静音节拍写法：正文写静默时，音效行必须是「数字静音，无其他声音。」
    # 裸「静音/静默/无声」会被 preflight 判缺音效行、或生成出杂音（实测两类 FAIL 的来源）
    beat_bodies = []
    parts_b = re.split(r"\[节拍 (\d+)\]", prompt)
    for _i in range(1, len(parts_b) - 1, 2):
        _body = parts_b[_i + 1]
        _pre, _sfx = (_body.split("音效：", 1) + [""])[:2]
        beat_bodies.append({"n": int(parts_b[_i]), "body": _pre,
                            "sfx": _sfx.splitlines()[0] if _sfx.strip() else ""})
    for b in beat_bodies:
        if re.search(r"静(音|默)|无声|沉默", b["body"]) and "数字静音" not in b["sfx"]:
            r.fail(f"节拍 {b['n']} 正文写静默但音效行不是「音效：数字静音，无其他声音。」"
                   "——裸「静音/静默」会被判缺音效行或生成杂音")

    # 7. soundscape 四段式
    ss = prompt.split("overall_soundscape:", 1)[-1].split("non_diegetic_music:", 1)[0]
    need = [("①", "对白层"), ("②", "动作拟音层"), ("③", "数字静音"), ("禁止", "禁止清单")]
    miss = [lab for k, lab in need if k not in ss]
    if miss:
        r.fail(f"overall_soundscape 缺: {miss}（①对白 ②动作拟音 ③数字静音 + 禁止清单）")
    else:
        r.ok("overall_soundscape 四段式完整")
    if "背景音乐" not in ss and "音乐" not in ss:
        r.warn("soundscape 未点明禁止背景音乐")
    if "mono" in prompt.lower() or "单声道" in prompt:
        r.warn("不要写声道参数，H3 不吃这个")

    # 8. 台词落点预算
    lines = re.findall(r"<d>(.+?)</d>", prompt)
    speaks = prompt.count("说（")
    if len(lines) != speaks:
        r.warn(f"<d> 台词 {len(lines)} 句，但「说（」出现 {speaks} 次——检查是否漏写表演括号或漏包 <d>")
    seg_s = length / 24.0
    budget = seg_s - 1.0 - 0.3
    total = 0.0
    for ln in lines:
        # 语速折扣：读台词所在「说（…）」括号的语速描述。实测校准（2026-10-19）：
        #   默认气声慢速 0.26s/字；括号写明「字间/句间不停顿」或「语速快」实测 0.24s/字
        #   （seg07 29字6.93s）、seg06「语速偏快句间不停顿」21字5.9s≈0.28s/字 → 偏快不打折
        i = prompt.find("<d>" + ln)
        ctx = prompt[max(0, i - 400):i] if i > 0 else ""
        if ("不停顿" in ctx) or ("语速快" in ctx):
            d = round(len(KANA.findall(ln)) * 0.20 + len(KANJI.findall(ln)) * 0.24 + len(re.findall(r"[、，。？！,.?!]", ln)) * 0.08 + 0.10, 2)
        else:
            d = est_dialogue_seconds(ln)
        total += d
        if d > budget:
            r.fail(f"台词「{ln}」估 {d}s，超过单句预算 {budget:.1f}s（段长 {seg_s:.2f}s，尾部要留 1s）")
        else:
            r.ok(f"台词「{ln}」估 {d}s ≤ 预算 {budget:.1f}s")
    if total > budget * 1.6:
        r.warn(f"全段台词合计 {total:.1f}s，占段长 {total / seg_s * 100:.0f}%，挤占动作与留白")
    # 台词是否落在末拍
    last_beat = prompt.split(f"[节拍 {nb}]", 1)[-1].split("[结尾状态]", 1)[0]
    if lines and "<d>" in last_beat:
        r.warn("末句台词落在最后一拍——H3 常把它拖到段末贴尾，建议前移一拍或写明「在本节拍前半段发出」")
    if lines and "[结尾状态]" in prompt:
        tail = prompt.split("[结尾状态]", 1)[-1]
        if "<d>" in tail:
            r.fail("台词出现在 [结尾状态] 之后")

    # 9. 内容层硬规则抽查
    if "环境次级运动：" in prompt:
        motion = prompt.split("环境次级运动：", 1)[1].split("[节拍", 1)[0]
        cnt = len([s for s in re.split(r"[；;]", motion) if s.strip()])
        if cnt < 3:
            r.warn(f"环境次级运动仅 {cnt} 项，规范要求 3-4 项且带方向+频率")
        else:
            r.ok(f"环境次级运动 {cnt} 项")
    else:
        r.fail("缺 环境次级运动：")
    for kw, msg in (("瞳孔", "写了瞳孔颜色"), ("因为", "写了剧情原因"), ("像…", "用了比喻")):
        if kw in prompt:
            r.warn(f"{msg}（{kw}）——Seedance 规则禁止")
    if "像" in prompt and re.search(r"像[^，。；\n]{0,8}一样|如同", prompt):
        r.warn("疑似比喻句（「像…一样/如同」），改成直接写形态")

    # 10. 负向：水印与文字
    if "水印" not in prompt:
        r.warn("防错约束里未写「忽略参考图水印/画面无文字」")

    # 11. 服从度边界（SKILL §4.1 实测：改文案没用、换 seed 也没用，只能在写法上绕）
    body_nn = strip_neg_sentences(prompt)
    cam_bad = [w for w in ("后拉", "拉远", "拉镜头", "推近", "推镜头", "zoom") if w in body_nn]
    if cam_bad:
        r.fail(f"位移式运镜 {cam_bad}：实测 4 次全败（写『只退到…就停』照样退过头）——"
               "改纯摇（同机位只改角度）或硬切")
    for w in ("穿过窗", "穿窗", "穿过门", "穿过洞", "机位穿"):
        if w in body_nn:
            r.warn(f"「{w}」会触发模型顺手开门——改段内硬切进内景，组装时把段头裁到刀口")
            break
    neg_cam = [w for w in ("景别不变", "景不变", "不推", "不拉", "保持中景", "保持景别",
                           "近景不变", "中景不变", "远景不变") if w in body_nn]
    if neg_cam:
        r.warn(f"否定式景别指令 {neg_cam} 服从度低（后半段照样推近）——"
               "改正向写「画面里始终装得下整个 X」")

    # 12. 末拍动作预算 + 结尾状态死条款（「结尾动作被抢」是最高频废片原因）
    if beat_bodies:
        last = beat_bodies[-1]
        clauses = [c for c in re.split(r"[，。；;,]", last["body"]) if c.strip()]
        if len(clauses) >= 4:
            r.warn(f"末拍动作/事件 {len(clauses)} 个（≥4）——H3 会砍掉最不起眼的那个，"
                   "结尾主动作可能被抢：把小动作前移一拍，末拍只留两个动作")
        ending = prompt.split("[结尾状态]", 1)[-1] if "[结尾状态]" in prompt else ""
        if ending and not any(k in ending for k in ("完成态", "必须", "不允许")):
            r.warn("[结尾状态] 建议写状态型死条款（「结尾必须是…完成态，不允许停在…」）"
                   "——状态型比过程描述管用")
    return r


def _length_of(path):
    """段长从 plan.json 推断（同目录或上级的 生产/plan.json），缺省 243。"""
    import glob as _g
    try:
        import paths
        if paths.PLAN and os.path.isfile(paths.PLAN):
            seg = os.path.splitext(os.path.basename(path))[0]
            for s in json.load(open(paths.PLAN, encoding="utf-8")).get("segs", []):
                if (s.get("seg") or s.get("id")) == seg:
                    return int(s.get("length") or 243)
    except Exception:
        pass
    return 243


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", help="（历史用法）查 prompt_v2.V2_SEGS 里的段")
    ap.add_argument("--file", help="单个提示词 txt")
    ap.add_argument("--dir", help="扫一个目录下的全部 *.txt（全片盘点用）")
    ap.add_argument("--length", type=int, default=None, help="不填则从 plan.json 推断")
    a = ap.parse_args()

    if a.dir:
        import glob
        rows = []
        for f in sorted(glob.glob(os.path.join(a.dir, "*.txt"))):
            ln = a.length or _length_of(f)
            rows.append((os.path.basename(f), check(os.path.basename(f),
                                                    open(f, encoding="utf-8").read(), ln)))
        if not rows:
            sys.exit(f"{a.dir} 下没有 *.txt")
        print(f"{'提示词':<20}{'FAIL':>6}{'WARN':>6}   首个 FAIL")
        print("-" * 78)
        for name, rep in rows:
            first = next((m for lv, m in rep.items if lv == "FAIL"), "")
            nf = sum(1 for lv, _ in rep.items if lv == "FAIL")
            nw = sum(1 for lv, _ in rep.items if lv == "WARN")
            print(f"{name:<20}{nf:>6}{nw:>6}   {first[:40]}")
        bad = sum(1 for _, rep in rows if rep.failed)
        print(f"\n共 {len(rows)} 段，{bad} 段未达标")
        sys.exit(0 if bad == 0 else 1)

    reports = []
    if a.seg:
        import prompt_v2
        if a.seg not in getattr(prompt_v2, "V2_SEGS", {}):
            sys.exit(f"[FATAL] prompt_v2.V2_SEGS 里没有 {a.seg}（示例库已清空，请用 --file 或 --dir）")
        d = prompt_v2.V2_SEGS[a.seg]
        reports.append(check(a.seg, d["prompt"], d.get("length", 243)))
    elif a.file:
        ln = a.length or _length_of(a.file)
        reports.append(check(os.path.basename(a.file), open(a.file, encoding="utf-8").read(), ln))
    else:
        ap.error("需要 --file / --dir / --seg 之一")

    allok = all(r.dump() for r in reports)
    print(f"\n{'全部通过' if allok else '存在 FAIL，先改提示词再提交'}")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
