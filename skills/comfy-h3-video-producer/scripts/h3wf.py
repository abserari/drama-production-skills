# -*- coding: utf-8 -*-
"""工作流握手：从"正在跑的 ComfyUI"读实际执行图，自动识别节点角色，不写死任何节点号。

为什么这么做
------------
用户的工作流会更新（加三采、换超分尺寸、改输出前缀、换节点 ID）。技能里固化一份
API 图 + 固化节点号的结果是：工作流一改，技能的"接线修复"就把一条跑得通的链路改坏。
所以 v3 起：**节点号只从运行时发现，脚本不再做任何接线手术。**

子命令
------
  show    打印当前 ComfyUI 最近一次成功执行图的角色识别结果（人读）
  sync    识别 + 校验 + 落盘 <项目>/wf_snapshot.json / wf_map.json（生产的唯一依据）
  doctor  对比"当前图"与"项目已握手图"，报告漂移（节点号/前缀/角色缺失）
  probe   只探活

用法
----
  python scripts/h3wf.py show
  python scripts/h3wf.py sync [--from-ui <workflow_ui.json>] [--force]
  python scripts/h3wf.py doctor
"""
import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402

COMBINE_CLASS_HINT = "VideoCombine"
PREFIX_HINT = "文件前缀"
CLS_ROLES = [
    ("rack", ["MediaRack"], ["rack_data"]),
    ("desk", ["Desk"], ["desk_data"]),
    ("cast", ["Cast"], ["h3_data"]),
]
# 收片链路（可选角色）：成片能不能回到导演台，全看这两个节点在不在、锚点接没接
OPT_ROLES = [
    ("collector", ["LatestFilmPath"], []),
    ("adopt", ["ProducerClipAdopt"], []),
]
REQUIRED = ("rack", "desk", "cast", "seed", "final")


# ── 基础 ────────────────────────────────────────────────
def _is_link(v):
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int)


def _links_of(node):
    return {k: v for k, v in (node.get("inputs") or {}).items() if _is_link(v)}


def _prefix_of(node):
    for k, v in (node.get("inputs") or {}).items():
        if PREFIX_HINT in k or k.lower() in ("filename_prefix", "prefix"):
            return v if isinstance(v, str) else None
    return None


def _has_prefix(node):
    """有非空文件前缀 = 这个节点真的会往 output 写文件。空串不算。"""
    p = _prefix_of(node)
    return bool(p and p.strip())


def _find_by_class(graph, needles, must_input=None):
    hits = []
    for nid, e in graph.items():
        cls = e.get("class_type", "")
        if any(n.lower() in cls.lower() for n in needles):
            if must_input and not any(m in (e.get("inputs") or {}) for m in must_input):
                continue
            hits.append(nid)
    return sorted(hits, key=lambda x: (len(x), x))


def _upstream_combine(graph, nid, depth=0, seen=None):
    """从 nid 往上游走，找到最近的"会写文件的合成节点"。"""
    seen = seen or set()
    if depth > 8 or nid in seen or nid not in graph:
        return None
    seen.add(nid)
    if _has_prefix(graph[nid]):
        return nid
    # 先走视觉输入，再走其它（顺序影响"最近"的判定）
    ins = _links_of(graph[nid])
    visual = [k for k in ins if any(s in k for s in ("视频", "图像", "video", "image"))]
    order = visual + [k for k in ins if k not in visual]
    for k in order:
        got = _upstream_combine(graph, ins[k][0], depth + 1, seen)
        if got:
            return got
    return None


def _downstream_combine(graph, start, max_depth=8):
    """从 start 顺流而下，找到最近的"会写文件的合成节点"。

    用途：认出**一采**。seed 采样器下游第一个带文件前缀的合成节点就是一采
    （1018 链上是 277 → 313 → 275 → 280「一采」）。没有它，`gate --latest`
    只按 mtime 取最新 mp4，跑完整链后拿到的一定是超分/终片，双检就检错了对象。
    """
    fwd = {}
    for nid, e in graph.items():
        for v in _links_of(e).values():
            fwd.setdefault(v[0], []).append(nid)
    seen = {start}
    frontier = [start]
    for _ in range(max_depth):
        nxt = []
        for n in frontier:
            for c in sorted(fwd.get(n, [])):
                if c in seen:
                    continue
                seen.add(c)
                if _has_prefix(graph[c]):
                    return c
                nxt.append(c)
        if not nxt:
            break
        frontier = nxt
    return None


def _chain_ref(graph, roles):
    """从导演台/执行台的 JSON 里读出当前工程名。

    为什么必须记它：段尾归位靠 `cm.last_name()` 读 `h3_chain/_last.json` 定位工程，
    而那个名字就是导演台 `chain.name`。提交时若用「技能工程名」顶替，成片会落进
    另一个 h3_chain 目录，下一段续接直接断档 —— 这类错最难查（看着跑通了）。
    """
    for role in ("desk", "cast"):
        nid = roles.get(role)
        if not nid or nid not in graph:
            continue
        for key in ("desk_data", "h3_data"):
            raw = (graph[nid].get("inputs") or {}).get(key)
            if not isinstance(raw, str):
                continue
            try:
                d = json.loads(raw)
            except Exception:
                continue
            ch = d.get("chain") or {}
            if str(ch.get("name") or "").strip():
                return {"name": str(ch["name"]).strip(),
                        "clip": str(ch.get("clip") or "").strip(),
                        "shot": str(ch.get("shot") or "").strip(),
                        "from": f"{role}.{key}"}
    return {}


def discover(graph):
    """识别角色。只做识别与记录，不改图。"""
    roles, notes = {}, []
    for role, hits_cls, must in CLS_ROLES:
        hits = _find_by_class(graph, hits_cls, must)
        if hits:
            roles[role] = hits[0]
            if len(hits) > 1:
                notes.append(f"{role} 有多个候选 {hits}，取 {hits[0]}（其余未被使用）")

    samplers = [nid for nid, e in graph.items()
                if "KSampler" in e.get("class_type", "") and "seed" in (e.get("inputs") or {})]
    if samplers:
        # 优先取负条件来自 cast 的那个（真正的主采样器）
        cast = roles.get("cast")
        best = samplers[0]
        if cast:
            for nid in samplers:
                src = (_links_of(graph[nid]).get("negative") or [None])[0]
                if src == cast:
                    best = nid
                    break
        roles["seed"] = best
        if len(samplers) > 1:
            notes.append(f"KSampler 有多个 {sorted(samplers)}，取 {best} 作为重抽种子节点")

    for role, needle in (("superres", ["SuperResolution"]), ("interp", ["RIFE", "Interpolation"])):
        hits = _find_by_class(graph, needle)
        if hits:
            roles[role] = hits[0]

    # 收片链路（可选）：成片回不回导演台，看这两个节点
    for role, needle, _ in OPT_ROLES:
        hits = _find_by_class(graph, needle)
        if hits:
            roles[role] = hits[0]

    # 一采 = seed 采样器下游第一个会写文件的合成节点
    if roles.get("seed"):
        take1 = _downstream_combine(graph, roles["seed"])
        if take1:
            roles["take1"] = take1

    # 所有写文件的合成节点
    outs = []
    for nid, e in graph.items():
        pref = _prefix_of(e)
        if pref is None and COMBINE_CLASS_HINT.lower() not in e.get("class_type", "").lower():
            continue
        outs.append({"node": nid, "class": e.get("class_type"), "prefix": pref,
                     "image": (_links_of(e).get("🖼️ 图像") or _links_of(e).get("图像")),
                     "audio": (_links_of(e).get("🎵 音频") or _links_of(e).get("音频")),
                     "video": (_links_of(e).get("🎬 视频文件") or _links_of(e).get("视频文件"))})
    outs.sort(key=lambda x: (len(x["node"]), x["node"]))

    # 终片 = 输出端口无人引用的合成节点
    used = set()
    for e in graph.values():
        for v in _links_of(e).values():
            used.add((v[0], v[1]))
    terminals = []
    for o in outs:
        nid = o["node"]
        refs = [s for (n, s) in used if n == nid]
        o["referenced_slots"] = sorted(refs)
        if not refs:
            terminals.append(o)
    if len(terminals) == 1:
        final = terminals[0]
    elif terminals:
        # 多个终端：优先"吃视频文件"的那个（终片合成），否则取前缀最短的
        with_video = [t for t in terminals if t["video"]]
        final = (with_video or terminals)[0]
        notes.append(f"有 {len(terminals)} 个终端输出节点，取 {final['node']}；"
                     f"其余 {[t['node'] for t in terminals if t is not final]} 也在写文件")
    else:
        final = outs[-1] if outs else None
        if final:
            notes.append("没找到无人引用的终端节点，退化为取最后一个合成节点")
    if final:
        roles["final"] = final["node"]

    # 终片的上游"成片源"（通常是三采/二采合成），用于取音轨
    prefinal = None
    if roles.get("superres"):
        for k, v in _links_of(graph[roles["superres"]]).items():
            if any(s in k for s in ("视频", "图像", "video", "image")):
                prefinal = _upstream_combine(graph, v[0])
                if prefinal:
                    break
    if prefinal is None and final and final.get("video"):
        prefinal = _upstream_combine(graph, final["video"][0])
    if prefinal:
        roles["prefinal"] = prefinal

    prefixes = {o["node"]: o["prefix"] for o in outs if o["prefix"]}
    chain = _chain_ref(graph, roles)
    if not chain:
        notes.append("读不到 chain.name（导演台/执行台的 chain 为空）—— "
                     "submit 会退回技能工程名，成片可能落进另一个 h3_chain 目录")

    # 收片链路体检：缺了不致命（可以手动收片），但一定得让人看见
    warnings = []
    adopt = roles.get("adopt")
    if not adopt:
        warnings.append("工作流里没有「📦 段尾归位」节点：成片不会回到导演台，"
                        "下一段续接取不到承接档")
    elif not (_links_of(graph[adopt]).get("顺序锚")):
        warnings.append("「📦 段尾归位」的「顺序锚」没接线：归位会读上一个工程的 "
                        "_last.json，成片可能串到别的 h3_chain 目录")
    if not roles.get("collector"):
        warnings.append("工作流里没有「🎬 三采成片收片器」：归位拿不到三采成片路径")

    return {
        "roles": roles,
        "outputs": outs,
        "prefixes": prefixes,
        "output_prefixes": sorted({v for k, v in prefixes.items()
                                   if k != roles.get("collector")}),
        "take1_prefix": prefixes.get(roles.get("take1")),
        "chain": chain,
        "final_has_audio": bool(final and final.get("audio")),
        "warnings": warnings,
        "notes": notes,
    }


def fingerprint(info):
    g = info.get("_graph") or {}
    # 「收片归位」这类叶子节点（collector/adopt）靠扫 output 目录找三采成片，天生有竞态，
    # 提交时会被主动摘掉（见 sop_run 的 [graph] 提示）。它们不参与渲染，
    # 不该让指纹漂移 —— 否则每次提交都会自己把自己判成"工作流被改了"。
    _skip_keys = ("collector", "adopt")
    skip = {info["roles"].get(k) for k in _skip_keys} - {None}
    basis = {
        "nodes": sorted([nid, e.get("class_type")] for nid, e in g.items() if nid not in skip),
        "roles": {k: v for k, v in info["roles"].items() if k not in _skip_keys},
        "prefixes": info["prefixes"],
    }
    return hashlib.sha1(json.dumps(basis, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


# ── 取图 ────────────────────────────────────────────────
def latest_success(count=60):
    """最近一次成功执行（带 mp4 产出）的 API 图。执行图 = 真正跑通过的那张，最可信。"""
    hist = paths.http_json(f"/history?max_items={count}", timeout=30)
    best = None
    for pid, e in hist.items():
        st = (e.get("status") or {})
        if st.get("status_str") != "success" or not st.get("completed"):
            continue
        outs = [it.get("filename", "") for nd in (e.get("outputs") or {}).values()
                for v in nd.values() if isinstance(v, list)
                for it in v if isinstance(it, dict)]
        if not any(str(f).lower().endswith(".mp4") for f in outs):
            continue
        seq = (e.get("prompt") or [0])[0]
        if best is None or seq > best[0]:
            best = (seq, pid, e)
    if not best:
        raise SystemExit(
            "[FATAL] ComfyUI 里没有找到成功执行过的视频任务图。\n"
            "  请在 ComfyUI 里打开工作流，手动跑一次（或跑一次你确认正确的），再执行 sync。\n"
            "  也可以指定界面文件兜底： h3wf.py sync --from-ui \"<桌面工作流>.json\"")
    seq, pid, e = best
    graph = e["prompt"][2]
    fin = [it for nd in (e.get("outputs") or {}).values() for v in nd.values()
           if isinstance(v, list) for it in v if isinstance(it, dict)]
    return graph, {"prompt_id": pid, "seq": seq,
                   "outputs": [f.get("filename") for f in fin],
                   "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def from_ui(ui_path):
    import comfy_convert
    return comfy_convert.convert(ui_path), {"source": "ui_file", "path": os.path.abspath(ui_path),
                                            "mtime": os.path.getmtime(ui_path),
                                            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}


# 这些是 submit 运行时注入的，不算「用户在画布上改的参数」
_INJECT_ROLES = ("rack", "desk", "cast")
_INJECT_KEYS = ("h3_data", "seed", "noise_seed", "filename_prefix")


def param_diff(old, new, roles=None):
    """对比两张 API 图的可调参数，只报用户真正改得动的东西。

    rack/desk/cast 的 h3_data 是 submit 现场注入的（段数据、素材架、工程名），
    seed 与文件前缀也会被运行时替换 —— 一律跳过，否则每次提交都报一堆假变更。
    """
    roles = roles or {}
    skip = {roles.get(k) for k in _INJECT_ROLES if roles.get(k)}
    out = []
    for nid in sorted(set(old) | set(new), key=lambda x: (len(x), x)):
        a, b = old.get(nid), new.get(nid)
        if a is None:
            out.append((nid, "新增节点", (b or {}).get("class_type"), "—"))
            continue
        if b is None:
            out.append((nid, "删除节点", (a or {}).get("class_type"), "—"))
            continue
        if nid in skip:
            continue
        ia, ib = a.get("inputs") or {}, b.get("inputs") or {}
        for k in sorted(set(ia) | set(ib)):
            if k in _INJECT_KEYS:
                continue
            if ia.get(k) != ib.get(k):
                out.append((nid, k, ia.get(k), ib.get(k)))
    return out


def refresh_if_stale(apply=True, verbose=True):
    """submit 之前核对手上的图是不是画布最新版，变了就重读并列出参数差异。

    画布状态只有在「保存工作流（Ctrl+S）」之后才会落到
    ComfyUI/user/default/workflows/*.json，所以判据是文件 mtime。
    改了画布却没保存 → 这里检测不到，必须靠提示用户。
    """
    if not os.path.isfile(paths.WF_MAP):
        return {"mode": "no_map", "changed": False}
    mp = json.load(open(paths.WF_MAP, encoding="utf-8"))
    src = mp.get("source") or {}
    if src.get("source") != "ui_file":
        return {"mode": src.get("source") or "history", "changed": False}
    p = src.get("path")
    if not p or not os.path.isfile(p):
        return {"mode": "missing", "changed": False, "path": p}
    m0 = float(src.get("mtime") or 0)
    m1 = os.path.getmtime(p)
    if m0 and abs(m1 - m0) < 1.0:
        return {"mode": "ui_file", "changed": False, "path": p}

    info = inspect(p)
    try:
        old = json.load(open(paths.WF_SNAPSHOT, encoding="utf-8"))
    except Exception:
        old = {}
    diff = param_diff(old, info["_graph"], mp.get("roles"))
    if verbose and diff:
        print(f"[wf  ] 画布工作流已更新：{os.path.basename(p)}")
        print(f"[wf  ] 检测到 {len(diff)} 处参数变更，本次生成将使用新值：")
        for nid, k, a, b in diff[:30]:
            print(f"        {nid} «{k}»  {a!r} → {b!r}")
        if len(diff) > 30:
            print(f"        ……另有 {len(diff) - 30} 处")
    elif verbose:
        print(f"[wf  ] 画布工作流文件变过（{os.path.basename(p)}），但可调参数没变，沿用")
    if apply and diff:
        mp.update({"source": info["_meta"], "fingerprint": info["fingerprint"],
                   "roles": info["roles"], "prefixes": info["prefixes"],
                   "output_prefixes": info["output_prefixes"],
                   "take1_prefix": info.get("take1_prefix"),
                   "final_has_audio": info["final_has_audio"],
                   "outputs": info["outputs"], "warnings": info.get("warnings") or [],
                   "accepted_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        json.dump(info["_graph"], open(paths.WF_SNAPSHOT, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        json.dump(mp, open(paths.WF_MAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    elif apply:
        # 只更新时间戳，避免每次提交都重算一遍
        src["mtime"] = m1
        src["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        json.dump(mp, open(paths.WF_MAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return {"mode": "ui_file", "changed": bool(diff), "diff": diff, "path": p}


def history_seq():
    """当前 /history 里最大的 prompt 序号（没有就 None）。

    作用是在握手时打一个"水位线"：比它老的执行图都在握手之前，不能拿来判漂移。
    否则刚用 --from-ui 握手完，`submit` 会撞上一条更早的、别的工作流执行记录，
    被误判成"工作流漂移"而拒收。
    """
    try:
        hist = paths.http_json("/history?max_items=200", timeout=30)
    except Exception:
        return None
    seqs = []
    for e in hist.values():
        try:
            seqs.append(int((e.get("prompt") or [])[0]))
        except Exception:
            continue
    return max(seqs) if seqs else None


def inspect(from_ui_path=None):
    if from_ui_path:
        graph, meta = from_ui(from_ui_path)
    else:
        graph, meta = latest_success()
    info = discover(graph)
    info["_graph"] = graph
    info["_meta"] = meta
    info["fingerprint"] = fingerprint(info)
    return info


# ── 输出 ────────────────────────────────────────────────
def print_report(info):
    roles = info["roles"]
    print("== 工作流识别 ==")
    for k in ("rack", "desk", "cast", "seed", "take1", "superres", "interp",
              "collector", "adopt", "final", "prefinal"):
        cls = ""
        if k in roles:
            cls = info["_graph"].get(roles[k], {}).get("class_type", "")
        print(f"  {k:9} = {roles.get(k, '—'):>5}  {cls}")
    ch = info.get("chain") or {}
    print(f"  工程名     : {ch.get('name') or '—（未设置，submit 会用技能工程名兜底）'}"
          f"   clip={ch.get('clip') or '-'}  shot={ch.get('shot') or '-'}")
    print(f"  一采前缀   : {info.get('take1_prefix') or '—（认不出，watch 按全部前缀找新文件）'}")
    print(f"  终片含音轨 : {'是' if info['final_has_audio'] else '否（收片要 mux）'}")
    print("== 会写文件的节点 ==")
    for o in info["outputs"]:
        print(f"  {o['node']:>4} {str(o['prefix']):<18} img<-{o['image']} aud<-{o['audio']} vid<-{o['video']}")
    miss = [r for r in REQUIRED if r not in roles]
    if miss:
        print(f"[FAIL] 必需角色缺失: {miss} —— 请在 ComfyUI 里确认工作流是否换了节点类名")
    else:
        print("[OK] 必需角色齐全")
    for w in info.get("warnings") or []:
        print(f"[WARN] {w}")
    for n in info.get("notes") or []:
        print(f"[note] {n}")
    print(f"指纹 {info['fingerprint']} | 来源 {info['_meta']}")


def cmd_show(a):
    if not paths.comfy_alive():
        raise SystemExit(f"[FATAL] ComfyUI 未运行：{paths.COMFY}")
    print_report(inspect(a.from_ui))


def cmd_sync(a):
    paths.require_project()
    if not a.from_ui and not paths.comfy_alive():
        raise SystemExit(f"[FATAL] ComfyUI 未运行：{paths.COMFY}。先打开 ComfyUI 并加载工作流。")
    info = inspect(a.from_ui)
    print_report(info)
    miss = [r for r in REQUIRED if r not in info["roles"]]
    if miss:
        raise SystemExit(f"[FATAL] 角色缺失 {miss}，不做落盘。")

    old = {}
    if os.path.isfile(paths.WF_MAP):
        try:
            old = json.load(open(paths.WF_MAP, encoding="utf-8"))
        except Exception:
            old = {}
    if old and old.get("fingerprint") != info["fingerprint"] and not a.force:
        print(f"\n[WARN] 工作流与上次握手不同：{old.get('fingerprint')} -> {info['fingerprint']}")
        print("       如确认这是你有意更新的工作流，加 --force 接受并重新落盘。")
        sys.exit(2)

    snapshot = {k: v for k, v in info["_graph"].items()}
    mp = {
        "source": info["_meta"],
        "fingerprint": info["fingerprint"],
        "history_seq": info["_meta"].get("seq") or history_seq(),
        "roles": info["roles"],
        "prefixes": info["prefixes"],
        "output_prefixes": info["output_prefixes"],
        "take1_prefix": info.get("take1_prefix"),
        "chain_name": (info.get("chain") or {}).get("name") or "",
        "chain": info.get("chain") or {},
        "final_has_audio": info["final_has_audio"],
        "outputs": info["outputs"],
        "warnings": info.get("warnings") or [],
        "accepted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    os.makedirs(paths.PROJECT_DIR, exist_ok=True)
    json.dump(snapshot, open(paths.WF_SNAPSHOT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(mp, open(paths.WF_MAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 记到 project.json 的握手历史里，方便回溯"当时用的是哪张图"
    try:
        pj = json.load(open(paths.PROJECT_JSON, encoding="utf-8"))
    except Exception:
        pj = {"name": os.path.basename(os.path.dirname(paths.PROJECT_DIR)), "segs": []}
    pj.setdefault("workflow_history", []).append(
        {"fingerprint": info["fingerprint"], "source": info["_meta"],
         "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    json.dump(pj, open(paths.PROJECT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[OK] 已落盘: {paths.WF_SNAPSHOT}\n            {paths.WF_MAP}")


def cmd_doctor(a):
    paths.require_project()
    if not os.path.isfile(paths.WF_MAP):
        raise SystemExit("[FATAL] 项目还没有握手记录，先跑 h3wf.py sync")
    saved = json.load(open(paths.WF_MAP, encoding="utf-8"))
    if not paths.comfy_alive():
        print(f"[FATAL] ComfyUI 未运行：{paths.COMFY}")
        sys.exit(1)
    cur = inspect(a.from_ui)
    print_report(cur)
    print("\n== 与项目已握手图的差异 ==")
    diffs = []
    if saved.get("fingerprint") != cur["fingerprint"]:
        diffs.append(f"指纹变化 {saved.get('fingerprint')} -> {cur['fingerprint']}")
    for role in set(saved.get("roles", {})) | set(cur["roles"]):
        a_, b_ = saved.get("roles", {}).get(role), cur["roles"].get(role)
        if a_ != b_:
            diffs.append(f"{role}: {a_} -> {b_}")
    for p in sorted(set(saved.get("output_prefixes", [])) ^ set(cur["output_prefixes"])):
        diffs.append(f"输出前缀差异: {p}")
    old_chain = (saved.get("chain") or {}).get("name") or saved.get("chain_name") or ""
    new_chain = (cur.get("chain") or {}).get("name") or ""
    if old_chain != new_chain:
        diffs.append(f"工程名(chain.name): {old_chain or '空'} -> {new_chain or '空'}"
                     "（成片会归位到这个名字的 h3_chain 目录）")
    if not diffs:
        print("  无差异，工作流与握手时一致。")
    else:
        for d in diffs:
            print("  -", d)
        print("\n[DECIDE] 工作流确实变了 → 重新 sync --force；只是 UI 里点过别的任务 → 可以忽略，"
              "但下一次 submit 会以 wf_snapshot.json 为准。")
    sys.exit(0)


def cmd_probe(a):
    ok = paths.comfy_alive()
    print(json.dumps({"comfy": paths.COMFY, "alive": ok}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show", "sync", "doctor", "probe"):
        s = sub.add_parser(name)
        s.add_argument("--from-ui", help="用界面版工作流 json 兜底（需要 ComfyUI 在跑以提供 /object_info）")
        s.add_argument("--force", action="store_true")
    a = ap.parse_args()
    {"show": cmd_show, "sync": cmd_sync, "doctor": cmd_doctor, "probe": cmd_probe}[a.cmd](a)
