# -*- coding: utf-8 -*-
"""提交与监工：把"提交 → 等一采 → 双检 → 放行/重抽 → 等终片"压成一条命令。

v3 与旧的三个关键区别
---------------------
1. **不写死节点号**：rack/desk/cast/seed 的节点 ID 全部从 wf_map.json 读取（由
   `h3wf.py sync` 从 ComfyUI 实际执行图里识别）。工作流换了节点号，这里不需要改。
2. **不做"接线修复"**：旧版会强行把 306 的图像口改接 285、给 308 补音频，这在
   "一采→二采→三采→超分" 的链路上会把跑得通的图改坏。现在只注入三段数据，不动线。
3. **一采双检是阻塞式自动的**：`watch` 自己发现新落盘文件、自己跑视觉定量+音频四项、
   不过就直接 abort+黑名单。不依赖"记得去跑 SOP"。

子命令
------
  submit --seg seg01 [--prompt 文件] [--length 243] [--seed N] [--assets a.json] [--silent]
  watch  --seg seg01 [--timeout 3600] [--poll 5]
  final  --seg seg01 [--timeout 7200] [--file 指定终片]
  abort  --seg seg01
  seednext
"""
import argparse
import copy
import json
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
import h3proj  # noqa: E402
import gpu_vram  # noqa: E402
from production_state import atomic_json, fingerprint, file_hash, gpu_lock, render_context, connected_first_frame


# ── 台账帮手 ────────────────────────────────────────────
def seg_state(seg, create=False):
    d = h3proj.load_progress()
    s = h3proj.seg_of(d, seg, create=create)
    return d, s


def save(d):
    h3proj.save_progress(d)


def _wf():
    if not os.path.isfile(paths.WF_MAP) or not os.path.isfile(paths.WF_SNAPSHOT):
        raise SystemExit("[FATAL] 还没有工作流握手。先跑：\n"
                         "  h3wf.py sync        （ComfyUI 开着、工作流已加载）")
    wm = json.load(open(paths.WF_MAP, encoding="utf-8"))
    g = json.load(open(paths.WF_SNAPSHOT, encoding="utf-8"))
    return wm, g


def _check_fresh(accept=False):
    """提交前确认：手上的图就是画布当前最新的那张。

    两条判据，缺一不可：
    ① 画布工作流文件（Ctrl+S 保存的那份）的 mtime 变没变 —— 这是唯一能看到
       「用户在画布上改了超分参数/换了模型」的途径。变了就重读并列出差异。
    ② ComfyUI /history 里最近一次成功执行的图，和握手的图是不是同一张。
    """
    import h3wf
    try:
        st = h3wf.refresh_if_stale(apply=False, verbose=False)
        if st.get("changed") and not accept:
            raise SystemExit("[REFUSE] 工作流源文件已修改；先显式重新握手，或明确继续固定旧版本")
        if st.get("mode") == "missing":
            print(f"[warn] 握手记录的工作流文件不在了：{st.get('path')}\n"
                  f"       画布上改过参数的话，先 Ctrl+S 保存，否则这次的图仍是旧参数。")
    except Exception as e:
        raise SystemExit(f"[REFUSE] 工作流核对失败，修复后再提交: {type(e).__name__}: {e}") from e
    wm, _ = _wf()
    if "chain" not in wm or "take1_prefix" not in wm:
        raise SystemExit("[REFUSE] wf_map.json 是旧版握手的（没有工程名/一采前缀）。\n"
                         "  它会让成片归位到技能工程名、双检检错对象。\n"
                         "  重新握手一次即可： h3wf.py sync --force")
    try:
        cur = h3wf.inspect()
    except SystemExit:
        # /history 被清空（重启 ComfyUI 就会清）时没有可对照的执行图。
        # 这不是漂移，刚 sync 过的图就是唯一依据，不能因此拒收第一段。
        print("[note] ComfyUI 里没有可对照的执行图（重启后 /history 为空），"
              "以本次握手图为准。")
        return wm
    if cur["fingerprint"] == wm.get("fingerprint"):
        return wm
    cur_seq = (cur.get("_meta") or {}).get("seq")
    saved_seq = wm.get("history_seq")
    if saved_seq is not None and cur_seq is not None and cur_seq <= saved_seq:
        # 这条执行图比握手还早（握手时打过水位线）—— 它不是"你刚改了工作流"，
        # 只是一条旧记录。真正的新执行图 seq 一定大于水位线。
        return wm
    print(f"[WARN] 运行图与握手图不同：{wm.get('fingerprint')} -> {cur['fingerprint']}")
    print("       如果你确实更新了工作流，请先 h3wf.py sync --force 重新握手；")
    print("       否则提交的会是旧图，可能与你界面里看到的不是一回事。")
    if not accept:
        raise SystemExit("[REFUSE] 工作流漂移未确认（加 --accept-workflow-change 可强制用旧图提交）")
    return wm


# ── submit ──────────────────────────────────────────────
def _assets_payload(path):
    if not path:
        return []
    a = json.load(open(path, encoding="utf-8"))
    out = []
    for k, v in a.items():
        if isinstance(v, dict):
            out.append({"file": v.get("file"), "alias": v.get("alias") or [k]})
        else:
            out.append({"file": v, "alias": [k]})
    return out


def _assets_default(seg, given=None):
    """素材架来源：显式 --assets 优先；否则自动找 <工程>/assets/<seg>.json。

    以前只认 --assets，忘了传就是"提示词写着 @图片1、素材架是空的"——
    H3 会把 @图片1 当成空槽**静默丢掉**（日志里只有一行
    `@图片1 points at an empty slot — removed from the prompt`），
    然后靠文字定义硬编人物：白烧一次生成，人物还长成另一个人。
    """
    if given:
        return given
    p = os.path.join(paths.PROJECT_DIR, "assets", f"{seg}.json")
    return p if os.path.isfile(p) else None


# ── 导演台工程档案（可选依赖：班长套件的 /cglide/chain/* 接口） ──────────
def _q(s):
    import urllib.parse
    return urllib.parse.quote(str(s), safe="")


def chain_summary(name):
    return paths.http_json("/cglide/chain/summary?name=" + _q(name), timeout=20)


def ensure_clip(chain_name, seg, length, create=True, trim_frames=None):
    """提交前把这一段登记进 h3_chain 工程，返回 (cid, 说明)。

    为什么不能等执行时再登记：执行台拼续接档时用 `chain.clip` 在 `chain.order`
    里定位上一段（order[k-1]）。新段若在执行阶段才 add_clip，order 里还没有它，
    k=-1 → 退回「全局最新的续拍存档」—— 串工程的成片就是这么接错的。
    先登记拿到 cid，order 就位，续接才是确定的。

    `create=False`（dry-run）只查不建：试跑不该往用户的时间轴上塞段。

    `trim_frames` 必须显式给：add_clip 在没收到它时会退回工程级默认值
    （DEFAULT_TRIM=39），而本任务可能把续接钉帧压到 5 帧。写错的后果不是
    "显示不对"，而是组装成片时每个段头多剪 34 帧（1.4 秒）真实画面。
    """
    s = chain_summary(chain_name)
    for c in (s.get("clips") or []):
        if str(c.get("shot") or "") == str(seg):
            cid = str(c.get("id") or "")
            # 已有段（重抽 / 改段长 / 改钉帧）也要把新值压回去，否则沿用旧账。
            if trim_frames is not None and int(c.get("trim_frames") or 0) != int(trim_frames):
                try:
                    paths.http_json("/cglide/chain/update",
                                    {"name": chain_name, "id": cid,
                                     "patch": {"trim_frames": int(trim_frames)}}, timeout=20)
                except Exception:
                    pass
            return cid, f"沿用已有段 {cid}（同 shot，重抽不新增）"
    if not create:
        return "", "dry-run 不登记新段（真跑时会 add_clip 建段）"
    body = {"name": chain_name, "frames": int(length),
            "shot": str(seg), "clip_name": str(seg)}
    if trim_frames is not None:
        body["trim_frames"] = max(0, int(trim_frames))
    r = paths.http_json("/cglide/chain/add_clip", body, timeout=30)
    return str(r.get("id") or ""), f"新登记段 {r.get('id')}（第 {r.get('index')} 段）"


def resolve_cont(chain_name, cid, mode="auto", frames=39):
    """取上一段的续拍存档拼成 `h3_data.cont`，返回 (cont, 说明, kind)。

    kind 用来区分"本来就该是第一段"和"本该续接却接不上"，两者行为完全不同：
      first    — 全片第一段 / 用户 --cont off，按第一段是正确结果
      explicit — 用户指定了续拍档
      cont     — 成功接上前一段
      none     — 档案里查不到上一段的续拍档（上一段没跑完、本段没登记、被清过）
      error    — 档案接口读不到，无法判断（网络/插件问题，不据此拒收）
    """
    if mode == "off":
        return {}, "按第一段处理（--cont off）", "first"
    if mode not in ("auto", "", None):
        return ({"mode": "latent", "frames": int(frames), "latent_file": str(mode)},
                f"显式续拍档 {mode}", "explicit")
    try:
        s = chain_summary(chain_name)
    except Exception as e:
        return {}, f"读不到工程档案（{type(e).__name__}），按第一段处理", "error"
    clips = [c for c in (s.get("clips") or []) if c.get("id")]
    ids = [str(c["id"]) for c in clips]
    if cid not in ids:
        return {}, "本段不在工程档案里（add_clip 没成功），按第一段处理", "none"
    k = ids.index(cid)
    if k == 0:
        return {}, "全片第一段，不续写", "first"
    prev = clips[k - 1]
    pid = str(prev["id"])
    try:
        got = paths.http_json(f"/cglide/chain/cont?name={_q(chain_name)}&id={_q(pid)}", timeout=20)
    except Exception:
        got = {}
    if not got.get("cont_path"):
        return {}, f"上一段 {pid} 还没有续拍存档（先把它跑完），本段按第一段处理", "none"
    cont = {"mode": "latent", "frames": int(frames), "latent_file": got["cont_path"]}
    take = int(prev.get("current_take") or 1)
    rel = f"h3_chain/{chain_name}/{pid}" + (".mp4" if take <= 1 else ".t%d.mp4" % take)
    if os.path.isfile(os.path.join(paths.OUTPUT_DIR, rel)):
        cont["latent_video"] = rel
    return cont, "承接 %s（%s，take %d）" % (pid, got.get("cont_path"), take), "cont"


def _reconcile_submission(record):
    """Find the exact accepted request; absence from history is not proof of rejection."""
    pid = record.get("prompt_id")
    client_id = record.get("submission_client_id")
    queue = paths.http_json("/queue", timeout=15)
    history = paths.http_json("/history", timeout=15)
    rows = list(queue.get("queue_running") or []) + list(queue.get("queue_pending") or [])
    rows += [v.get("prompt") for v in history.values() if isinstance(v, dict) and v.get("prompt")]
    for row in rows:
        if len(row) >= 4 and ((pid and row[1] == pid) or
                              (client_id and isinstance(row[3], dict) and row[3].get("client_id") == client_id)):
            return str(row[1])
    return None


def cmd_submit(a):
    paths.require_project()
    if a.dry_run:
        return _cmd_submit(a)
    with gpu_lock(paths.COMFY):
        d, s = seg_state(a.seg)
        if s and (s.get("submission_state") in ("submitting", "unknown") or
                  s.get("status") == "生成中"):
            pid = _reconcile_submission(s)
            if pid:
                s.update(prompt_id=pid, submission_state="accepted", status="生成中")
                save(d)
                print(json.dumps({"reused_submission": True, "prompt_id": pid, "next_action": "watch"}))
                return
            raise SystemExit("[REFUSE] 上次提交结果尚未核清，禁止重投（包括 --force）；核对原 client_id/服务记录")
        queue = paths.http_json("/queue", timeout=15)
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise SystemExit("[REFUSE] ComfyUI 已有任务，请等队列空闲；不会清理其他任务")
        return _cmd_submit(a)


def _cmd_submit(a):
    paths.require_project()
    wm, g = _wf()
    wm = _check_fresh(a.accept_workflow_change)
    roles = wm["roles"]

    # ── 工程归属：成片要回到导演台那部片子，不是回到技能工程名 ──
    chain_name = (a.chain or wm.get("chain_name") or "").strip()
    if not chain_name:
        chain_name = _project_name()
        print(f"[WARN] 握手图里没有 chain.name，退回技能工程名「{chain_name}」。"
              f"成片会归位到 h3_chain/{chain_name}，与导演台里那部片子**不是同一部**。"
              "要在导演台接上：填好工程名 → 跑一次 → h3wf.py sync --force；或用 --chain 指定。")
    elif a.chain:
        print(f"[note] 用 --chain 指定工程名：{chain_name}")

    # ── 闸门 G0.5：任务-工程绑定 ──
    # 一个任务 = 一个本地工程 + 一个 h3_chain 工程名。绑错了不是"文件放错地方"这么轻：
    # 续拍档按 order[k-1] 找上一段，换了工程名就找不着，本段会被静默当成第一段重画，
    # 成片也会归位到另一部片子。所以这里直接拒收，不靠人去记。
    pj = h3proj.load_project()
    bound = (pj.get("chain") or "").strip()
    from_wf = bool((wm.get("chain_name") or "").strip())
    if bound and bound != chain_name:
        if not a.rebind:
            raise SystemExit(
                f"[REFUSE] 本任务已绑定导演台工程「{bound}」，这次解析到「{chain_name}」。\n"
                "  同一任务的所有段必须落在同一个 h3_chain 工程里，否则续接档找不到上一段、\n"
                "  成片会分裂到两个目录（这正是「串档」）。\n"
                f"  · 接着原来的任务：--chain {bound}（或把导演台工程名改回 {bound} 再 sync）\n"
                f"  · 确实要换工程：--rebind（旧段留在旧工程，本段起在新工程里从第一段算）")
        print(f"[WARN] --rebind：任务工程 {bound} → {chain_name}。旧段的续拍档不在新工程里，"
              "续接从这里断开，后面要 --allow-nocont 或手动指定续拍档。")
    if (not bound or a.rebind) and not a.dry_run and (from_wf or a.chain):
        pj["chain"] = chain_name
        h3proj.save_project(pj)
        print(f"[bind] 本任务绑定导演台工程「{chain_name}」——此后所有段都必须用它，改名会被拒收。")
    elif not bound and not (from_wf or a.chain):
        print("[WARN] 握手图里没有工程名，本次不写绑定（避免把错误名字固化下来）。")

    d, s = seg_state(a.seg, create=True)
    if (s.get("first") or {}).get("verdict") == "PASS" and not a.force:
        raise SystemExit(f"[REFUSE] {a.seg} 已经一采通过并放行，重复提交会白烧一次生成。"
                         "确实要重来加 --force。")

    prompt_file = a.prompt or os.path.join(paths.SEG_DIR, f"{a.seg}.txt")
    if not os.path.isfile(prompt_file):
        raise SystemExit(f"[FATAL] 找不到提示词：{prompt_file}")
    prompt = open(prompt_file, encoding="utf-8").read().strip()
    # 闸门 G1：段规划表里必须有这一段（plan.json 为空的首次开工除外）
    order = h3proj.plan_order()
    if not order or a.seg not in order:
        raise SystemExit(f"[REFUSE] plan.json 里没有 {a.seg}。先把段规划表补全"
                         "（references/directing_bridge.md 第 7 节），否则等于没有分镜就开始烧算力。")
    spec = h3proj.seg_spec(a.seg)
    length = int(a.length or spec.get("length") or 175)
    # 合法段长：实测链路（一采直出、无超分/无插帧）可跑 124 / 175；243 留给带插帧的链路。
    # 175 帧 = 7.29s，仍在单次渲染 8s 上限内，但净新画面比 124 多 85%（见下 cont_frames）。
    if length not in (124, 175, 243):
        raise SystemExit("[FATAL] length 只能是 124 / 175 / 243")
    if length > 175 and "interp" not in (roles or {}):
        print("[note] 本链路没有插帧节点，243 帧可能超 8s 单次上限；确认过再跑。")

    # ── 闸门：提示词 preflight 不过，不许提交 ──
    from check_prompt_v2 import check
    rep = check(a.seg, prompt, length)
    ok = rep.dump()
    if not ok:
        raise SystemExit("[REFUSE] 提示词 preflight 有 FAIL，改了再提交（一次生成几十分钟，text 层能查的错不该用生成验证）")

    # ── 组装图：只注入三段数据 + seed，绝不改接线 ──
    graph = copy.deepcopy(g)
    for need in ("rack", "desk", "cast", "seed"):
        if need not in roles or roles[need] not in graph:
            raise SystemExit(f"[FATAL] 工作流里找不到 {need} 角色节点，先 h3wf.py show 看识别结果")

    # ── 续接钉帧数：--cont-frames > project.json 的 cont_frames > 工作流里的值 ──
    # 钉 39 帧（1.625 秒）等于每段白送 1.6 秒上一段的画面，剪辑期必须整段掐掉；
    # 钉 5 帧只留 0.2 秒的上下文锚（_MC_RUN_GRID 里合法最小档之一），几乎不用剪。
    # 先算出来再登记段：add_clip 必须拿到同一个值，否则档案会按工程默认 39 记账。
    old_cont = (json.loads(graph[roles["cast"]]["inputs"]["h3_data"]).get("cont") or {})
    # 2026-10-26 用户定：导演台续接帧 = 5（原兜底 39 → 每段白送 1.6s 上一段画面）
    try:
        wf_frames = int(old_cont.get("frames") or 5)
    except Exception:
        wf_frames = 5
    _proj_frames = None
    try:
        _proj_frames = int((pj or {}).get("cont_frames") or 0) or None
    except Exception:
        _proj_frames = None
    try:
        cont_frames = int(a.cont_frames or _proj_frames or wf_frames)
    except Exception:
        cont_frames = wf_frames
    if cont_frames != wf_frames:
        print(f"[cont ] 续接钉帧 {cont_frames} 帧（工作流里是 {wf_frames} 帧）")

    # 段前显存自检：上一次若是中断/异常退出，BanZhang_VRAM_Cleaner（323/324）
    # 没跑到，模型和缓存会压在显存里，VRAM_Guard（264）随之每步卸载重载，
    # 一采能从 4 分钟拖到 30 分钟。正常跑完的段空闲够，这里不会动手。
    if not a.dry_run:
        gpu_vram.ensure_clean()

    # 首段的头部不承接任何人，trim 必须记 0；其余段记 cont_frames。
    is_first_seg = (not order) or (str(a.seg) == str(order[0]))
    trim_in = 0 if is_first_seg else cont_frames

    cid, clip_note = "", ""
    try:
        cid, clip_note = ensure_clip(chain_name, a.seg, length,
                                     create=not a.dry_run, trim_frames=trim_in)
    except Exception as e:
        raise SystemExit(f"[REFUSE] 工程档案接口不可用，先修复连接: {e}")
    print(f"[chain] {chain_name} · {clip_note}")
    print(f"[chain] {a.seg} 段长 {length} 帧，头部剪 {trim_in} 帧，净新画面 {length - trim_in} 帧")

    cont, cont_note, cont_kind = resolve_cont(chain_name, cid, a.cont, cont_frames)
    print(f"[cont ] {cont_note}")

    # ── 闸门 G0.6：该续接就必须接上 ──
    # 以前这里只打印"按第一段处理"就照跑：本段白烧一次，画面还跟上一段不接。
    # 全片第一段（plan 里排第一）和 --cont off 是合法的"不续写"，其余一律拒收。
    order_all = order or []
    is_first = (not order_all and not s.get("chain")) or (order_all and order_all[0] == a.seg)
    if cont_kind == "none" and not is_first and not a.allow_nocont:
        raise SystemExit(
            f"[REFUSE] {a.seg} 本该接着上一段，但拿不到续拍档：{cont_note}\n"
            "  照原样提交只会得到一段「独立开头」的画面（续接断掉，还得重抽）。先查：\n"
            f"  · h3proj.py status → 上一段是不是「完成」、续拍存档是否为「有」\n"
            f"  · h3_chain/{chain_name}/ 里上一段的 .cont.safetensors 是否还在\n"
            "  · 确实要一段独立画面（不是续接）→ 加 --allow-nocont 或 --cont off")
    if cont_kind == "error":
        raise SystemExit("[REFUSE] 工程档案读不到，无法确认续接")

    chain = {"name": chain_name, "clip": cid or a.seg, "shot": a.seg}
    key = chain["clip"]                      # 档案里的键是段落 id，不是段名

    # 素材架：后端 `parse_rack_data` **只读顶层 slots**（segs/cur 是前端面板的存储，
    # 后端白名单里没有）。旧版只写 segs[cur].slots、把 slots 清空 —— 等于每段都
    # 提交一个空素材架，参考图根本没进去，这也是"身份漂移"一直治不好的根因。
    assets = _assets_payload(_assets_default(a.seg, a.assets))
    # 闸门：提示词引用了 @图片N，素材架却是空的 → 直接拒收。
    # 不拒的话 H3 会静默把 @图片N 当空槽丢掉，靠文字硬编人物（实测长出另一个人）。
    import re as _re
    _refs = sorted(set(_re.findall(r"@图片(\d+)", prompt)))
    if _refs and not assets:
        raise SystemExit(
            f"[REFUSE] {a.seg} 的提示词引用了 @图片{','.join(_refs)}，但素材架是空的。\n"
            f"  H3 会把空槽引用**静默丢掉**，人物就靠文字硬编（实测会长成另一个人）。\n"
            f"  · 补素材：{os.path.join('assets', a.seg + '.json')}"
            "（键名=别名，值=素材架里的相对路径）\n"
            "  · 或显式指定：--assets <文件>\n"
            "  · 确实不要参考图：从提示词里删掉 @图片N，改用文字锚定")
    if assets:
        print(f"[rack] 素材 {len(assets)} 件：" +
              "、".join(f"{x['alias'][0]}→{os.path.basename(str(x['file']))}" for x in assets))
    rack = json.loads(graph[roles["rack"]]["inputs"]["rack_data"])
    rack["cur"] = key
    rack["slots"] = {"images": assets, "videos": [], "audios": []}
    rack["segs"] = {key: {"slots": {"images": assets, "videos": [], "audios": []}}}

    desk = json.loads(graph[roles["desk"]]["inputs"]["desk_data"])
    desk["chain"] = chain
    desk["global"] = ""
    desk["segs"] = {key: prompt}
    desk["alias"] = False
    h3 = json.loads(graph[roles["cast"]]["inputs"]["h3_data"])
    h3["chain"] = chain
    h3["length"] = length
    h3["prompt"] = ""
    # 续写开关：不给 latent_file 就等于「本段独立」，画面与上一段不接
    h3["cont"] = cont
    if a.silent:
        h3["mode"] = "anullsrc"
    graph[roles["rack"]]["inputs"]["rack_data"] = json.dumps(rack, ensure_ascii=False)
    graph[roles["desk"]]["inputs"]["desk_data"] = json.dumps(desk, ensure_ascii=False)
    graph[roles["cast"]]["inputs"]["h3_data"] = json.dumps(h3, ensure_ascii=False)

    seed = int(a.seed) if a.seed is not None else _seednext()
    graph[roles["seed"]]["inputs"]["seed"] = seed
    # Snapshot actual prompt bytes, workflow, declared materials and the segment only.
    # Mixing settings are deliberately excluded from render identity.
    material_files = [prompt_file, paths.WF_SNAPSHOT]
    asset_file = _assets_default(a.seg, a.assets)
    if asset_file:
        material_files.append(asset_file)
    for asset in assets:
        material = str(asset.get("file") or "")
        material_files.append(material if os.path.isabs(material) else os.path.join(paths.INPUT_DIR, material))
    keyframe = spec.get("keyframe") or spec.get("first_frame")
    mode = str(spec.get("generation_mode") or pj.get("production_path") or (pj.get("production") or {}).get("route") or "").lower()
    required_frame = spec.get("requires_keyframe", pj.get("requires_keyframe", False)) or mode in ("i2v", "i2va", "fl2va", "first_frame", "first_last_frame")
    if required_frame:
        if not keyframe:
            raise SystemExit("[REFUSE] 本路径要求首帧但计划未指定 keyframe")
        keyframe = keyframe if os.path.isabs(keyframe) else os.path.join(paths.PROJECT_DIR, keyframe)
        material_files.append(keyframe)
        if not connected_first_frame(graph, keyframe, paths.INPUT_DIR):
            raise SystemExit("[REFUSE] 所需首帧的实际内容未接入 first_frame；不回退 T2V")
    input_snapshot = {"segment_spec": fingerprint(spec), "production_context": render_context(pj), "files": {
        os.path.abspath(p): file_hash(p) for p in material_files}}

    # ── 摘掉「收片归位」这类叶子节点（collector/adopt）──
    # 它们不接渲染主链，靠"扫 output 目录最近 N 秒内的三采成片"来找文件——天生有竞态：
    # 实测 327 在 298 落盘之前就执行，直接 RuntimeError，ComfyUI 把整个 prompt 判失败，
    # 终片 306/307/308 一个都没跑（白等一次生成）。
    # 它们只服务于导演台 UI 的归档显示，我们的收片是 finish 自己做的，所以提交时摘掉。
    # 安全前提：这两个节点必须真的是叶子（没有其它节点消费它们的输出），否则不动。
    if not getattr(a, "keep_collector", False):
        cand = [roles[k] for k in ("collector", "adopt") if roles.get(k) in graph]
        removed = []
        # 迭代到不动点：327 被 328 消费，先删 328 后 327 才变成叶子，单趟判断会漏。
        while cand:
            consumed = set()
            for _nid, _node in graph.items():
                for _v in (_node.get("inputs") or {}).values():
                    if isinstance(_v, list) and len(_v) == 2 and isinstance(_v[0], str):
                        consumed.add(_v[0])
            leaves = [x for x in cand if x in graph and x not in consumed]
            if not leaves:
                break
            for x in leaves:
                graph.pop(x, None)
                removed.append(x)
            cand = [x for x in cand if x in graph]
        if removed:
            print(f"[graph] 摘掉收片归位叶子节点 {removed}（扫目录找成片有竞态，"
                  "会让整条 prompt 假失败；收片由 finish 负责）")
        left = [roles[k] for k in ("collector", "adopt") if roles.get(k) in graph]
        if left:
            print(f"[WARN] {left} 还有下游消费，不摘，保留原样")

    # ── 基线快照：之后只认"基线里没有的新文件" ──
    baseline = {}
    prefixes = wm.get("output_prefixes") or []
    if os.path.isdir(paths.OUTPUT_DIR):
        for f in os.listdir(paths.OUTPUT_DIR):
            if f.lower().endswith(".mp4") and (not prefixes or any(f.startswith(p) for p in prefixes)):
                baseline[f] = os.path.getmtime(os.path.join(paths.OUTPUT_DIR, f))

    t0 = time.time()
    if a.dry_run:
        # 顺手把图丢给 ComfyUI 的 /object_info 校验一遍：必填项缺一个，
        # 真跑的时候就会在排队后才报错，白等一次提交。
        probs = []
        try:
            import comfy_convert
            probs = comfy_convert.validate(graph, comfy_convert.fetch_object_info())
        except Exception as e:
            probs = [f"图校验不可用（{type(e).__name__}: {e}）"]
        print(json.dumps({"dry_run": True, "seg": a.seg, "length": length, "seed": seed,
                          "nodes": len(graph), "roles": {k: roles[k] for k in
                                                          ("rack", "desk", "cast", "seed", "final")},
                          "chain": chain, "clip_note": clip_note,
                          "cont": cont, "cont_note": cont_note,
                          "graph_problems": probs[:10],
                          "output_prefixes": wm.get("output_prefixes"),
                          "prompt_chars": len(prompt)},
                         ensure_ascii=False, indent=1))
        if [p for p in probs if not p.startswith(("跳过图校验", "[WARN]"))]:
            print("[FAIL] 图没通过 ComfyUI 的必填项校验，先修工作流再提交。")
            sys.exit(1)
        if [p for p in probs if p.startswith("[WARN]")]:
            print("[WARN] 图里有多余输入（ComfyUI 会忽略，不影响跑）：")
            for p in [x for x in probs if x.startswith("[WARN]")]:
                print("  -", p)
        print("[dry-run] 已通过 preflight 与图组装，未提交。")
        return
    client_id = "drama-" + uuid.uuid4().hex
    s.update(submission_state="submitting", submission_client_id=client_id,
             input_snapshot=input_snapshot, input_fingerprint=fingerprint({"graph": graph, "inputs": input_snapshot}),
             submitted_graph=graph, prompt_file=os.path.relpath(prompt_file, paths.PROJECT_DIR),
             baseline=baseline, baseline_ts=t0, submit_ts=t0, seed=seed, length=length,
             workflow_fp=wm.get("fingerprint"), chain=chain, cont=cont)
    s.pop("prompt_id", None)
    save(d)  # Durable intent before a network call whose response may be lost.
    try:
        res = paths.http_json("/prompt", {"prompt": graph, "client_id": client_id}, timeout=120)
    except Exception as e:
        s.update(submission_state="unknown", status="待核对", submission_error=str(e))
        save(d)
        raise SystemExit(f"[REFUSE] 提交回执不明，先核对 client_id={client_id}，禁止盲目重投: {e}")
    if res.get("error") or not res.get("prompt_id"):
        s.update(submission_state="rejected" if res.get("error") else "unknown", status="失败待复核")
        save(d)
        print(json.dumps(res, ensure_ascii=False)[:3000])
        raise SystemExit("[FATAL] ComfyUI 拒绝了这次提交")

    s.update({"status": "生成中", "submission_state": "accepted", "prompt_id": res["prompt_id"], "seed": seed, "length": length,
              "submit_ts": time.time(), "baseline": baseline, "baseline_ts": t0,
              "prompt_file": os.path.relpath(prompt_file, paths.PROJECT_DIR),
              "workflow_fp": wm.get("fingerprint"), "preflight": "PASS",
              "chain": chain, "cont": cont})
    s.pop("first", None)
    s.pop("visual_review", None)
    s.pop("deliver", None)
    save(d)
    print(json.dumps({"seg": a.seg, "prompt_id": res["prompt_id"], "seed": seed,
                      "length": length, "chain": chain,
                      "roles": {k: roles[k] for k in ("rack", "desk", "cast", "seed")}},
                     ensure_ascii=False, indent=1))
    print(f"\n[NEXT] 监工（建议后台跑）：python scripts/sop_run.py watch --seg {a.seg}")


def _project_name():
    try:
        return json.load(open(paths.PROJECT_JSON, encoding="utf-8")).get("name") or "h3proj"
    except Exception:
        return "h3proj"


# ── watch ───────────────────────────────────────────────
def _new_files(baseline, prefixes, since):
    out = []
    if not os.path.isdir(paths.OUTPUT_DIR):
        return out
    for f in os.listdir(paths.OUTPUT_DIR):
        if not f.lower().endswith(".mp4") or f in baseline:
            continue
        if prefixes and not any(f.startswith(p) for p in prefixes):
            continue
        p = os.path.join(paths.OUTPUT_DIR, f)
        try:
            mt = os.path.getmtime(p)
            sz = os.path.getsize(p)
        except OSError:
            continue
        if mt >= since - 2 and sz > 0:
            out.append((mt, sz, p))
    return sorted(out)


def _queue_pids():
    try:
        q = paths.http_json("/queue", timeout=15)
    except Exception:
        return set(), set()
    run = {it[1] for it in q.get("queue_running", []) if len(it) > 1}
    pen = {it[1] for it in q.get("queue_pending", []) if len(it) > 1}
    return run, pen


def cmd_watch(a):
    paths.require_project()
    wm, _ = _wf()
    d, s = seg_state(a.seg)
    if not s:
        raise SystemExit(f"[FATAL] 台账里没有 {a.seg}，先 submit")
    pid = s.get("prompt_id")
    since = s.get("baseline_ts") or s.get("submit_ts") or 0
    baseline = s.get("baseline") or {}
    # 一采优先：sync 认出了「一采」前缀就只在这个前缀里找。
    # 不这样会在同一轮里先抓到别的中间产物（二采/三采/超分），把三采当一采去双检。
    take1p = wm.get("take1_prefix")
    prefixes = [take1p] if take1p else (wm.get("output_prefixes") or [])

    print(f"[watch] {a.seg} prompt_id={pid} seed={s.get('seed')} "
          f"基线 {len(baseline)} 个文件 · 找「{take1p or '全部前缀'}」的新文件", flush=True)
    t0 = time.time()
    stable, last = 0, None
    cand = None
    while time.time() - t0 < a.timeout:
        news = _new_files(baseline, prefixes, since)
        if news:
            mt, sz, p = news[0]
            if last == (p, sz):
                stable += 1
            else:
                stable, last = 0, (p, sz)
            if stable >= 1:   # 连续两次同大小 → 认为写完了
                cand = p
                break
            print(f"  ... {os.path.basename(p)} 落盘中 {sz/1048576:.1f} MB", flush=True)
        else:
            run, pen = _queue_pids()
            if pid and pid not in run and pid not in pen:
                # 不在队列里也没新文件 → 要么很早前就完了，要么报错了
                try:
                    hist = paths.http_json(f"/history/{pid}", timeout=15).get(pid) or {}
                except Exception:
                    hist = {}
                stt = (hist.get("status") or {}).get("status_str")
                if stt in ("error", "failed"):
                    s["status"] = "失败待复核"
                    s["fail_reason"] = [f"ComfyUI 执行报错: {json.dumps(hist.get('status'), ensure_ascii=False)[:400]}"]
                    save(d)
                    print(json.dumps({"verdict": "ERROR", "seg": a.seg,
                                      "status": hist.get("status")}, ensure_ascii=False, indent=1))
                    sys.exit(3)
                if stt == "success":
                    # 成功但没发现新文件：可能前缀对不上，用 history 的 outputs 兜底
                    outs = [it.get("filename") for nd in (hist.get("outputs") or {}).values()
                            for v in nd.values() if isinstance(v, list)
                            for it in v if isinstance(it, dict)]
                    print(f"[WARN] 任务已完成但没发现新文件，history 产出: {outs}")
                    if outs:
                        pick = [f for f in outs if take1p and str(f).startswith(take1p)] or outs
                        cand = os.path.join(paths.OUTPUT_DIR, pick[0])
                        break
                    s["status"] = "失败待复核"
                    save(d)
                    sys.exit(3)
        time.sleep(a.poll)
    if not cand:
        print(json.dumps({"verdict": "TIMEOUT", "seg": a.seg, "waited_s": int(time.time() - t0)},
                         ensure_ascii=False))
        sys.exit(2)

    print(f"[watch] 一采落盘: {cand}", flush=True)

    # ① 落盘即刻的音频快检：不过就当场掐断，别等完整质检（那时二采已在跑）
    # 无对白段必须显式传 dialogue=no：auto 会把低频拟音（雷声、破空声、撞沙闷响）
    # 判成语声，于是按"有对白"去查台词结束点，无对白段必然顶到段末被假 FAIL。
    _dlg = "yes" if _has_dialogue(a.seg) else "no"
    # 无对白段必须显式传 fx：不传的话 check_audio_seg 走的是"全段静音 <= -45 dBFS"
    # 这条口径，而 H3 给无对白段必然铺一层拟音/乐音（实测 -39 dBFS）→ 每次必假
    # FAIL、每次白抽。plan 里写了 sfx=true 的段就是在说"这段要留拟音"。
    # 只在「无对白 + 要留拟音」时才用 fx=yes 顶掉那条"全段静音<=-45dB"的假口径；
    # 有对白的段必须走 auto —— 拿 fx=yes 去要求"必须有可点名的拟音"太严，
    # 台词段的筷子/衣料响经常被判不成事件，会白抽一批好take。
    _fx = "yes" if (not _has_dialogue(a.seg) and _has_sfx(a.seg)) else "auto"
    fast = _fast_audio_gate(cand, _dlg, _fx)
    if fast and fast.get("verdict") not in ("PASS", "NO_AUDIO"):
        bad = [c["name"] for c in (fast.get("checks") or []) if not c.get("pass_")]
        print(f"[fast] 音频快检不过（{('、'.join(bad)) or fast.get('verdict')}）→ 立即中断")
        _kill_queue((s or {}).get("prompt_id"))
        bl = _blacklist()
        if s.get("seed") is not None and s["seed"] not in bl:
            bl.append(s["seed"])
            _save_blacklist(bl)
        s["reroll"] = s.get("reroll", 0) + 1
        s["status"] = "失败待复核"
        s["fail_reason"] = [f"fast_audio:{x}" for x in bad] or ["fast_audio"]
        s["first"] = fast
        s["files"] = {"first": cand}
        save(d)
        print(f"[AUTO_ABORT] seed {s.get('seed')} 入黑名单，重抽次数 {s['reroll']}/3")
        if s["reroll"] >= 3:
            print("[STOP] 已重抽 3 次仍不过：转人工——改提示词或查素材/工作流。")
        sys.exit(1)

    qc = h3proj.run_qc(cand, "yes" if _has_dialogue(a.seg) else "no",
                       _fx, tag=a.seg)
    h3proj.print_qc(qc)
    s["first"] = qc
    s["files"] = {"first": cand}

    if qc["verdict"] != "PASS":
        # 硬错即断：中断当前执行 + 清空队列里排着的任务。
        # 只发 /interrupt 只停"正在跑的那个节点"，队列里 pending 的同类任务
        # 会接着占用 GPU，下一条要白等 —— 必须一起清掉。
        _kill_queue((s or {}).get("prompt_id"))
        bl = _blacklist()
        if s.get("seed") is not None and s["seed"] not in bl:
            bl.append(s["seed"])
            _save_blacklist(bl)
        s["reroll"] = s.get("reroll", 0) + 1
        s["status"] = "失败待复核"
        s["fail_reason"] = qc["reasons"]
        save(d)
        print(f"\n[AUTO_ABORT] 已中断队列，seed {s.get('seed')} 入黑名单，重抽次数 {s['reroll']}/3")
        if s["reroll"] >= 3:
            print("[STOP] 已重抽 3 次仍不过：按 SKILL 第 6 步转人工——要么改提示词，要么查素材/工作流。")
        else:
            print(f"[NEXT] python scripts/sop_run.py submit --seg {a.seg}   （自动换新 seed，提示词不动）")
        sys.exit(1)

    s["status"] = "一采待复核"
    save(d)
    print(json.dumps({"verdict": "PASS", "seg": a.seg, "video": cand,
                      "frames": qc["frames"], "log_dir": qc["log_dir"]}, ensure_ascii=False, indent=1))
    print(f"\n[NEXT] 必做视觉复核（8 类严重逻辑错误）→ h3proj.py review --seg {a.seg} --pass")


def _has_dialogue(seg):
    sp = h3proj.seg_spec(seg)
    if sp.get("dialogue") is not None:
        return bool(sp["dialogue"])
    f = os.path.join(paths.SEG_DIR, f"{seg}.txt")
    return os.path.isfile(f) and "<d>" in open(f, encoding="utf-8").read()


def _has_sfx(seg):
    sp = h3proj.seg_spec(seg)
    return bool(sp.get("sfx", True))


# ── final ───────────────────────────────────────────────
def cmd_final(a):
    paths.require_project()
    wm, _ = _wf()
    d, s = seg_state(a.seg)
    if not s:
        raise SystemExit(f"[FATAL] 台账里没有 {a.seg}")
    if a.file:
        final = a.file
        outs = [a.file]
    else:
        pid = s.get("prompt_id")
        if not pid:
            raise SystemExit("[FATAL] 这段没有 prompt_id（窗口手动渲染的请用 --file）")
        t0 = time.time()
        hist = {}
        while time.time() - t0 < a.timeout:
            try:
                hist = paths.http_json(f"/history/{pid}", timeout=20).get(pid) or {}
            except Exception:
                hist = {}
            stt = (hist.get("status") or {}).get("status_str")
            if stt == "success" or stt in ("error", "failed"):
                break
            time.sleep(10)
        if not hist:
            raise SystemExit("[TIMEOUT] 终片未在时限内完成")
        if (hist.get("status") or {}).get("status_str") != "success":
            raise SystemExit(f"[ERROR] 任务失败: {json.dumps(hist.get('status'), ensure_ascii=False)[:600]}")
        # 归属按 history 的"节点 id -> 文件"取，不靠前缀猜（"班长作品" 是 "班长作品_N308" 的前缀，
        # 单靠前缀会把三采那个 1248x704 的中间产物误判成终片）
        by_node = {}
        for nid, nd in (hist.get("outputs") or {}).items():
            for v in nd.values():
                if not isinstance(v, list):
                    continue
                for it in v:
                    if isinstance(it, dict) and it.get("filename", "").lower().endswith(".mp4"):
                        by_node.setdefault(nid, []).append(
                            os.path.join(paths.OUTPUT_DIR, it.get("subfolder") or "", it["filename"]))
        outs = [p for ps in by_node.values() for p in ps]
        n_final = wm["roles"].get("final")
        final_files = by_node.get(n_final) or []
        if not final_files:
            fprefix = (wm.get("prefixes") or {}).get(n_final) or ""
            final_files = [p for p in outs if os.path.basename(p).startswith(fprefix)] if fprefix else outs
        if not final_files:
            raise SystemExit(f"[FATAL] history 里没找到终片（节点 {n_final}）：{[os.path.basename(p) for p in outs]}")
        final = sorted(final_files, key=lambda p: os.path.getmtime(p))[-1]
        s.setdefault("files", {})["by_node"] = {k: [os.path.basename(x) for x in v] for k, v in by_node.items()}

    st = h3proj.stream_summary(final)
    # 音轨来源：终片自带就用终片；否则挑一个带音轨的上游产物
    audio_src = final if st["has_audio"] else None
    if not audio_src:
        n_pre = wm["roles"].get("prefinal")
        by_node = (s.get("files") or {}).get("by_node") or {}
        pre_files = [os.path.join(paths.OUTPUT_DIR, f) for f in by_node.get(n_pre, [])]
        cands = [p for p in pre_files if os.path.isfile(p) and h3proj.stream_summary(p)["has_audio"]]
        if not cands:
            allf = [os.path.join(paths.OUTPUT_DIR, f) for fs in by_node.values() for f in fs]
            cands = [p for p in allf if os.path.isfile(p) and p != final
                     and h3proj.stream_summary(p)["has_audio"]]
        cands.sort(key=lambda p: -os.path.getmtime(p))
        audio_src = cands[0] if cands else None
    s.setdefault("files", {})["final"] = final
    s["files"]["audio_src"] = audio_src
    s["files"]["all_outputs"] = [os.path.basename(p) for p in outs[:12]]
    s["status"] = "待收片"
    save(d)
    print(json.dumps({"seg": a.seg, "final": final, "video": st,
                      "audio_src": audio_src, "all_outputs": s["files"]["all_outputs"]},
                     ensure_ascii=False, indent=1))
    print(f"[NEXT] 收片（清床音+核对音轨）：python scripts/h3proj.py finish --seg {a.seg}")


# ── abort / seednext / blacklist ────────────────────────
def _kill_queue(prompt_id):
    """Cancel only this durable task id; never clear someone else's queue."""
    if not prompt_id:
        raise SystemExit("[REFUSE] 没有本任务编号，不能执行全局中断或清队列")
    queue = paths.http_json("/queue", timeout=15)
    running = {str(row[1]) for row in queue.get("queue_running", [])}
    pending = {str(row[1]) for row in queue.get("queue_pending", [])}
    if str(prompt_id) in pending:
        paths.http_json("/queue", {"delete": [prompt_id]}, timeout=15)
    if str(prompt_id) in running:
        paths.http_json("/interrupt", {"prompt_id": prompt_id}, timeout=15)
    after = paths.http_json("/queue", timeout=15)
    if not after.get("queue_running") and not after.get("queue_pending"):
        gpu_vram.free(wait=0)



def _fast_audio_gate(video, dialogue="auto", fx="auto"):
    """一采落盘后先只跑音频检查（约 2 秒），不过就立刻让出 GPU。

    完整质检要抽帧 + 视觉定量，十几秒；而 H3 的一采一落盘，二采就立刻开跑，
    等完整质检出结论时三采/超分往往已经在跑，算力白烧 —— 这就是"判失败了
    还要等它跑到超分"的根因。音频是最快也最常见的失败项，先卡这一道。
    """
    import subprocess
    import tempfile
    out = os.path.join(tempfile.gettempdir(), "h3_fast_gate.json")
    try:
        if os.path.isfile(out):
            os.remove(out)
        subprocess.run([sys.executable, os.path.join(HERE, "check_audio_seg.py"),
                        "--file", video, "--dialogue", dialogue, "--fx", fx, "--json", out],
                       capture_output=True, timeout=120)
        return json.load(open(out, encoding="utf-8"))
    except Exception as e:
        print(f"[fast] 音频快检未完成（{type(e).__name__}），转完整质检")
        return None


def _blacklist():
    try:
        return json.load(open(paths.BLACKLIST_PATH, encoding="utf-8"))
    except FileNotFoundError:
        return []


def _save_blacklist(bl):
    os.makedirs(os.path.dirname(paths.BLACKLIST_PATH), exist_ok=True)
    atomic_json(paths.BLACKLIST_PATH, bl)


def _seednext():
    import random
    bl = _blacklist()
    while True:
        v = random.randint(0, 2 ** 31 - 1)
        if v not in bl:
            return v


def cmd_abort(a):
    paths.require_project()
    d, s = seg_state(a.seg)
    _kill_queue((s or {}).get("prompt_id"))
    if s:
        bl = _blacklist()
        if s.get("seed") is not None and s["seed"] not in bl:
            bl.append(s["seed"])
            _save_blacklist(bl)
        s["status"] = "失败待复核"
        s["reroll"] = s.get("reroll", 0) + 1
        save(d)
    print(json.dumps({"aborted": True, "seg": a.seg, "blacklist": _blacklist()}, ensure_ascii=False))


def cmd_seednext(a):
    print(_seednext())


if __name__ == "__main__":
    paths.ensure_cv2_or_reexec()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("submit")
    s1.add_argument("--seg", required=True); s1.add_argument("--prompt")
    s1.add_argument("--length", type=int); s1.add_argument("--seed", type=int)
    s1.add_argument("--assets"); s1.add_argument("--silent", action="store_true")
    s1.add_argument("--force", action="store_true")
    s1.add_argument("--dry-run", dest="dry_run", action="store_true")
    s1.add_argument("--accept-workflow-change", dest="accept_workflow_change", action="store_true")
    s1.add_argument("--chain", help="导演台工程名（默认取握手图里的 chain.name；与已绑定不一致会被拒收）")
    s1.add_argument("--rebind", action="store_true",
                    help="确实要换导演台工程时用：改绑到本次解析到的工程名（续接从这里断开）")
    s1.add_argument("--allow-nocont", dest="allow_nocont", action="store_true",
                    help="本段确实要独立开头（不接上一段）时用：放行「拿不到续拍档」")
    s1.add_argument("--cont", default="auto",
                    help="auto=接着上一段；off=按第一段；<路径>=用指定续拍档")
    s1.add_argument("--cont-frames", dest="cont_frames", type=int, default=None,
                    help="续接钉帧数（默认取 project.json 的 cont_frames，再退回工作流里的值）。"
                         "钉几帧就等于每段开头多出几帧上一段的画面，剪辑期要掐掉")
    s1.add_argument("--keep-collector", dest="keep_collector", action="store_true",
                    help="保留收片归位节点（327/328）。默认摘掉：它们扫目录找成片有竞态，"
                         "会让整条 prompt 假失败，终片白跑")
    s2 = sub.add_parser("watch")
    s2.add_argument("--seg", required=True); s2.add_argument("--timeout", type=int, default=3600)
    s2.add_argument("--poll", type=int, default=5)
    s3 = sub.add_parser("final")
    s3.add_argument("--seg", required=True); s3.add_argument("--timeout", type=int, default=7200)
    s3.add_argument("--file")
    s4 = sub.add_parser("abort"); s4.add_argument("--seg", required=True)
    sub.add_parser("seednext")
    a = ap.parse_args()
    {"submit": cmd_submit, "watch": cmd_watch, "final": cmd_final,
     "abort": cmd_abort, "seednext": cmd_seednext}[a.cmd](a)
