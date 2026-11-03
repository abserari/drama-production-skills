# -*- coding: utf-8 -*-
"""ComfyUI workflow converter: UI format (nodes/links) -> API format (prompt graph).

Usage:
  python comfy_convert.py <workflow_ui.json> [--out api.json] [--validate]

--validate checks the converted graph against the running ComfyUI's /object_info
(class types exist, required inputs present) without submitting anything.
"""
import json
import sys
import urllib.request

COMFY = "http://127.0.0.1:8188"


def fetch_object_info():
    with urllib.request.urlopen(COMFY + "/object_info", timeout=60) as r:
        return json.load(r)


def convert(ui_path):
    d = json.load(open(ui_path, encoding="utf-8"))
    nodes = {n["id"]: n for n in d["nodes"]}
    links = {l[0]: l for l in d["links"]}  # id -> [id, from_node, from_slot, to_node, to_slot, type]

    # class definition lookup: class_type -> {input_name -> [type, props]}
    obj = None

    def class_def(cls):
        nonlocal obj
        if obj is None:
            obj = fetch_object_info()
        return obj.get(cls)

    # Rewire links that pass THROUGH bypassed/muted nodes (mode 2/4).
    # Frontend rule: a bypassed node's output consumers are fed from the
    # bypassed node's corresponding input link (matched by output index),
    # recursively.
    def resolve_source(node_id, slot):
        n = nodes.get(node_id)
        if n is None or n.get("mode", 0) == 0:
            return (node_id, slot)
        # find input feeding this output index
        inp = None
        for i in n.get("inputs", []):
            if i.get("link") is not None and i.get("widget") is None:
                pass
        # match by output index -> input index (same position)
        ins = [i for i in n.get("inputs", []) if i.get("link") is not None]
        outs = n.get("outputs", [])
        if slot < len(outs):
            out_name = outs[slot].get("name")
            # try match by type/name among inputs
            cand = None
            for i in n.get("inputs", []):
                if i.get("link") is None:
                    continue
                if i.get("type") == outs[slot].get("type"):
                    cand = i
                    if i.get("name") == out_name:
                        break
            if cand is None and ins:
                cand = ins[min(slot, len(ins) - 1)]
            if cand is not None:
                l = links[cand["link"]]
                return resolve_source(l[1], l[2])
        return None

    prompt = {}
    for n in d["nodes"]:
        mode = n.get("mode", 0)
        if mode != 0 or n["type"] in ("Note", "MarkdownNote"):
            continue
        cls = n["type"]
        entry = {"class_type": cls, "inputs": {}, "_meta": {"title": n.get("title") or cls}}
        # widget values (named preferred)
        named = n.get("widgets_values_named") or {}
        inputs = entry["inputs"]
        # determine which named keys are actual widget params: use class def if available
        cd = class_def(cls)
        valid_params = set()
        if cd:
            for grp in ("required", "optional", "hidden"):
                if grp in cd.get("input", {}):
                    valid_params |= set(cd["input"][grp].keys())
        # named widgets
        for k, v in named.items():
            if k in ("gmr_ui", "h3_ui", "desk_ui", "preview_grid", "lora面板", "rack_ui"):
                continue  # UI-only helper widgets
            if valid_params and k in valid_params:
                inputs[k] = v
        # positional fallback for nodes lacking named map
        if not named and n.get("widgets_values") and cd:
            wv = n["widgets_values"]
            # collect widget-connected input names in order
            wnames = []
            for g in ("required", "optional"):
                if g in cd.get("input", {}):
                    for k, spec in cd["input"][g].items():
                        if isinstance(spec, list) and spec and isinstance(spec[0], (str, list)) and not spec[0] in (
                            "INT", "FLOAT", "STRING", "COMBO") or (isinstance(spec, list) and spec and spec[0] in ("INT", "FLOAT", "STRING", "COMBO")):
                            pass
                    wnames += [k for k, spec in cd["input"][g].items()
                               if not (isinstance(spec, list) and spec and isinstance(spec[0], str)
                                       and spec[0] in ("IMAGE", "LATENT", "MODEL", "VAE", "CLIP", "CONDITIONING",
                                                       "AUDIO", "MASK", "VIDEO", "SIGMAS", "H3_REFS", "STRING_LINK"))]
            for k, v in zip(wnames, wv):
                if k not in inputs and not (isinstance(v, str) and v.startswith("data:")):
                    inputs.setdefault(k, v)
        # link inputs
        for inp in n.get("inputs", []):
            lid = inp.get("link")
            if lid is None or inp.get("widget") is not None:
                continue
            if lid not in links:
                continue
            l = links[lid]
            src = resolve_source(l[1], l[2])
            if src is None:
                continue
            name = inp["name"]
            if valid_params and name not in valid_params:
                continue
            inputs[name] = [str(src[0]), src[1]]
        prompt[str(n["id"])] = entry
    return prompt


def validate(prompt, obj):
    problems = []
    for nid, e in prompt.items():
        cls = e["class_type"]
        if cls not in obj:
            problems.append(f"node {nid}: class {cls} NOT FOUND")
            continue
        cd = obj[cls]["input"]
        valid = set()
        for g in ("required", "optional", "hidden"):
            valid |= set(cd.get(g, {}).keys())
        for k in e["inputs"]:
            if k == "_meta":
                continue
            if k not in valid:
                # 多余输入 ComfyUI 只告警、不会拒跑（这套工作流里 banzhangVideoCombine
                # 的 painter_preview、SaveVideo 的 format.codec 就是这样跑通的）。
                # 所以只标 WARN：真跑会自己忽略，别让 --dry-run 误判成图坏了。
                problems.append(f"[WARN] node {nid} ({cls}): unknown input '{k}'（会被忽略）")
        for g in ("required",):
            for k, spec in cd.get(g, {}).items():
                if k in e["inputs"]:
                    continue
                # link-only inputs appear in node['inputs']; we already mapped them.
                # treat missing as problem only if not a connection type
                if isinstance(spec, list) and spec and isinstance(spec[0], str) and spec[0] in (
                        "IMAGE", "LATENT", "MODEL", "VAE", "CLIP", "CONDITIONING", "AUDIO", "MASK",
                        "VIDEO", "SIGMAS", "H3_REFS", "UPSCALE_MODEL", "STRING", "INT", "FLOAT"):
                    problems.append(f"node {nid} ({cls}): missing required link input '{k}'")
    return problems


def output_nodes(prompt, obj):
    outs = []
    for nid, e in prompt.items():
        cd = obj.get(e["class_type"])
        if cd and cd.get("output_node"):
            outs.append((nid, e["class_type"]))
    return outs


if __name__ == "__main__":
    wf = sys.argv[1]
    out = None
    do_validate = "--validate" in sys.argv
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    p = convert(wf)
    print(f"converted nodes: {len(p)}")
    if out:
        json.dump(p, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("written:", out)
    if do_validate:
        obj = fetch_object_info()
        probs = validate(p, obj)
        print("output nodes:", output_nodes(p, obj))
        if probs:
            print(f"PROBLEMS ({len(probs)}):")
            for x in probs:
                print(" -", x)
        else:
            print("validation OK")
