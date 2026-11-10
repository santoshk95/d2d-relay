"""BPMN 2.0 for Business process documents (and the other W4 packs that draw a process): the map a person confirmed ->
BPMN 2.0 XML with its diagram (BPMNDI shapes and edges laid out in lanes, so bpmn.io-style tools open it as drawn), the
checks that XML must pass, the graph rules a map must keep before anything proceeds, and the readers that bring a
process in from an export: BPMN 2.0 files (Signavio, ARIS, Bizagi, Camunda, Lucidchart all export it) and Visio .vsdx
(shapes and connectors by their masters — rules first, no AI).

A map: {"name", "lanes": [{"id", "name", "kind"}], "steps": [{"id", "name", "type", "lane", "next": [{"to", "when"}], …}]}
with type one of start | end | task | user | service | manual | gateway.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL", "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
      "dc": "http://www.omg.org/spec/DD/20100524/DC", "di": "http://www.omg.org/spec/DD/20100524/DI", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
TYPES = {"start": "startEvent", "end": "endEvent", "task": "task", "user": "userTask", "service": "serviceTask", "manual": "manualTask", "gateway": "exclusiveGateway"}
TYPE_OF = {v: k for k, v in TYPES.items()} | {"intermediateThrowEvent": "task", "intermediateCatchEvent": "task", "parallelGateway": "gateway", "inclusiveGateway": "gateway",
                                             "eventBasedGateway": "gateway", "sendTask": "service", "receiveTask": "service", "scriptTask": "service", "businessRuleTask": "service",
                                             "subProcess": "task", "callActivity": "task"}
SIZE = {"start": (36, 36), "end": (36, 36), "gateway": (50, 50)}
TASK = (110, 70)
ID_RE = re.compile(r"^[A-Za-z_][\w.-]*$")


def _xid(s: str) -> str:
    s = re.sub(r"[^\w.-]", "_", str(s))
    return s if ID_RE.match(s) else f"N_{s}"


def graph_problems(proc: dict) -> list[str]:
    """The rules a map keeps before anything proceeds: one start, an end, every link to a step that exists, every step
    reachable, a decision with two or more labelled ways out, every step in a lane that exists."""
    steps = proc.get("steps") or []
    ids = [s.get("id") for s in steps]
    out = []
    if len(ids) != len(set(ids)):
        out.append("two steps share an id: " + ", ".join(sorted({i for i in ids if ids.count(i) > 1})))
    known = set(ids)
    lanes = {l["id"] for l in proc.get("lanes") or []}
    starts = [s for s in steps if s.get("type") == "start"]
    if len(starts) != 1:
        out.append(f"a map has exactly one start (it has {len(starts)})")
    if not any(s.get("type") == "end" for s in steps):
        out.append("a map needs at least one end")
    for s in steps:
        where = f"{s.get('id')} “{str(s.get('name') or '')[:40]}”"
        if s.get("type") not in TYPES:
            out.append(f"{where}: the type is one of {', '.join(TYPES)}")
        if not str(s.get("name") or "").strip():
            out.append(f"{where}: give the step a name")
        if lanes and s.get("lane") not in lanes:
            out.append(f"{where}: its lane {s.get('lane')!r} is not one of the lanes")
        nxt = s.get("next") or []
        for n in nxt:
            if n.get("to") not in known:
                out.append(f"{where}: goes on to {n.get('to')!r}, which is not a step")
        if s.get("type") == "end" and nxt:
            out.append(f"{where}: an end has no next step")
        if s.get("type") != "end" and not nxt:
            out.append(f"{where}: say what comes next (or make it an end)")
        if s.get("type") == "gateway":
            if len(nxt) < 2:
                out.append(f"{where}: a decision has two or more ways out")
            elif any(not str(n.get("when") or "").strip() for n in nxt):
                out.append(f"{where}: label each way out of the decision (when …)")
    if starts and not out:
        seen, todo = {starts[0]["id"]}, [starts[0]["id"]]
        by = {s["id"]: s for s in steps}
        while todo:
            for n in by[todo.pop()].get("next") or []:
                if n["to"] not in seen:
                    seen.add(n["to"])
                    todo.append(n["to"])
        lost = [i for i in ids if i not in seen]
        if lost:
            out.append("not reachable from the start: " + ", ".join(lost))
    if any(s.get("type") == "start" and any(s["id"] == n.get("to") for x in steps for n in x.get("next") or []) for s in steps):
        out.append("nothing leads into the start")
    return out


def _layout(proc: dict) -> dict:
    steps = proc["steps"]
    by = {s["id"]: s for s in steps}
    start = next((s["id"] for s in steps if s["type"] == "start"), steps[0]["id"] if steps else None)
    depth = {start: 0} if start else {}
    todo = [start] if start else []
    while todo:                                       # breadth first: a loop back keeps the earlier column
        a = todo.pop(0)
        for n in by[a].get("next") or []:
            if n["to"] in by and n["to"] not in depth:
                depth[n["to"]] = depth[a] + 1
                todo.append(n["to"])
    for s in steps:
        depth.setdefault(s["id"], max(depth.values(), default=0) + 1)
    lanes = proc.get("lanes") or [{"id": "_all", "name": proc.get("name") or "Process"}]
    lane_ix = {l["id"]: i for i, l in enumerate(lanes)}
    slots: dict = {}
    pos = {}
    LANE_H = 150
    for s in sorted(steps, key=lambda x: (depth[x["id"]], x["id"])):
        li = lane_ix.get(s.get("lane"), 0)
        k = slots.get((li, depth[s["id"]]), 0)
        slots[(li, depth[s["id"]])] = k + 1
        w, h = SIZE.get(s["type"], TASK)
        cx, cy = 230 + depth[s["id"]] * 170, 80 + li * LANE_H + LANE_H / 2 + k * 18
        pos[s["id"]] = (cx - w / 2, cy - h / 2, w, h)
    width = 230 + (max(depth.values(), default=0) + 1) * 170 + 40
    return {"pos": pos, "lanes": lanes, "lane_h": LANE_H, "width": width, "height": len(lanes) * LANE_H}


def to_bpmn(proc: dict, pid: str = "Process_1") -> str:
    """BPMN 2.0 XML with a diagram: a participant (pool) with a lane per role, the steps as events, tasks and exclusive
    gateways, the links as sequence flows (a decision's ways out carry their names)."""
    for p, u in NS.items():
        ET.register_namespace(p, u)
    B = lambda t: f"{{{NS['bpmn']}}}{t}"  # noqa: E731
    D = lambda t: f"{{{NS['bpmndi']}}}{t}"  # noqa: E731
    steps = proc["steps"]
    lay = _layout(proc)
    defs = ET.Element(B("definitions"), {"id": "Definitions_1", "targetNamespace": "http://bpmn.io/schema/bpmn", "exporter": "Relay", "exporterVersion": "1.0"})
    collab = ET.SubElement(defs, B("collaboration"), {"id": "Collaboration_1"})
    ET.SubElement(collab, B("participant"), {"id": "Participant_1", "name": proc.get("name") or "Process", "processRef": pid})
    process = ET.SubElement(defs, B("process"), {"id": pid, "name": proc.get("name") or "Process", "isExecutable": "false"})
    flows = []
    for s in steps:
        for i, n in enumerate(s.get("next") or []):
            fid = _xid(f"Flow_{s['id']}_{n['to']}" + (f"_{i}" if sum(1 for m in s.get("next") or [] if m["to"] == n["to"]) > 1 else ""))
            flows.append({"id": fid, "from": s["id"], "to": n["to"], "name": str(n.get("when") or "")})
    if proc.get("lanes"):
        ls = ET.SubElement(process, B("laneSet"), {"id": "LaneSet_1"})
        for l in proc["lanes"]:
            le = ET.SubElement(ls, B("lane"), {"id": _xid(f"Lane_{l['id']}"), "name": l["name"]})
            for s in steps:
                if s.get("lane") == l["id"]:
                    ET.SubElement(le, B("flowNodeRef")).text = _xid(s["id"])
    for s in steps:
        el = ET.SubElement(process, B(TYPES.get(s["type"], "task")), {"id": _xid(s["id"]), "name": s.get("name") or ""})
        if s.get("instructions"):
            ET.SubElement(el, B("documentation")).text = s["instructions"]
        for f in flows:
            if f["to"] == s["id"]:
                ET.SubElement(el, B("incoming")).text = f["id"]
        for f in flows:
            if f["from"] == s["id"]:
                ET.SubElement(el, B("outgoing")).text = f["id"]
    for f in flows:
        ET.SubElement(process, B("sequenceFlow"), {"id": f["id"], "sourceRef": _xid(f["from"]), "targetRef": _xid(f["to"]), **({"name": f["name"]} if f["name"] else {})})
    dia = ET.SubElement(defs, D("BPMNDiagram"), {"id": "BPMNDiagram_1"})
    plane = ET.SubElement(dia, D("BPMNPlane"), {"id": "BPMNPlane_1", "bpmnElement": "Collaboration_1"})

    def bounds(parent, x, y, w, h):
        ET.SubElement(parent, f"{{{NS['dc']}}}Bounds", {"x": f"{x:g}", "y": f"{y:g}", "width": f"{w:g}", "height": f"{h:g}"})
    sh = ET.SubElement(plane, D("BPMNShape"), {"id": "Participant_1_di", "bpmnElement": "Participant_1", "isHorizontal": "true"})
    bounds(sh, 40, 80, lay["width"], lay["height"])
    for i, l in enumerate(proc.get("lanes") or []):
        sh = ET.SubElement(plane, D("BPMNShape"), {"id": _xid(f"Lane_{l['id']}") + "_di", "bpmnElement": _xid(f"Lane_{l['id']}"), "isHorizontal": "true"})
        bounds(sh, 70, 80 + i * lay["lane_h"], lay["width"] - 30, lay["lane_h"])
    for s in steps:
        x, y, w, h = lay["pos"][s["id"]]
        attrs = {"id": _xid(s["id"]) + "_di", "bpmnElement": _xid(s["id"])}
        if s["type"] == "gateway":
            attrs["isMarkerVisible"] = "true"
        sh = ET.SubElement(plane, D("BPMNShape"), attrs)
        bounds(sh, x, y, w, h)
    for f in flows:
        ax, ay, aw, ah = lay["pos"][f["from"]]
        bx, by_, bw, bh = lay["pos"][f["to"]]
        ed = ET.SubElement(plane, D("BPMNEdge"), {"id": f["id"] + "_di", "bpmnElement": f["id"]})
        p1, p2 = (ax + aw, ay + ah / 2), (bx, by_ + bh / 2)
        if bx <= ax:                                  # a loop back: under the boxes
            low = max(ay + ah, by_ + bh) + 20
            pts = [(ax + aw / 2, ay + ah), (ax + aw / 2, low), (bx + bw / 2, low), (bx + bw / 2, by_ + bh)]
        elif abs(p1[1] - p2[1]) < 1:
            pts = [p1, p2]
        else:
            mx = (p1[0] + p2[0]) / 2
            pts = [p1, (mx, p1[1]), (mx, p2[1]), p2]
        for px, py in pts:
            ET.SubElement(ed, f"{{{NS['di']}}}waypoint", {"x": f"{px:g}", "y": f"{py:g}"})
    ET.indent(defs, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(defs, encoding="unicode")


def validate(xml: str) -> list[str]:
    """What a BPMN 2.0 file must pass before it is published: well-formed, the BPMN 2.0 namespaces, one process, ids
    unique, every flow between flow nodes that exist and their incoming / outgoing in step, a start and an end, and a
    diagram shape for every node and an edge for every flow (so it opens as drawn)."""
    try:
        root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except ET.ParseError as e:
        return [f"the BPMN is not well-formed XML: {e}"]
    q = lambda t: f"{{{NS['bpmn']}}}{t}"  # noqa: E731
    if root.tag != q("definitions"):
        return [f"the root element is {root.tag}, not BPMN 2.0 definitions"]
    out = []
    procs = root.findall(q("process"))
    if not procs:
        return ["there is no process"]
    ids = [e.get("id") for e in root.iter() if e.get("id")]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        out.append("ids used twice: " + ", ".join(dup[:8]))
    bad_ids = [i for i in ids if not ID_RE.match(i)]
    if bad_ids:
        out.append("ids that are not valid XML names: " + ", ".join(bad_ids[:6]))
    for p in procs:
        nodes = {e.get("id"): e for e in p if e.tag.split("}")[1] in TYPE_OF}
        flows = {e.get("id"): e for e in p if e.tag == q("sequenceFlow")}
        for fid, f in flows.items():
            for side in ("sourceRef", "targetRef"):
                if f.get(side) not in nodes:
                    out.append(f"flow {fid}: {side} {f.get(side)!r} is not a flow node")
        for nid, n in nodes.items():
            inc = {x.text for x in n.findall(q("incoming"))}
            outg = {x.text for x in n.findall(q("outgoing"))}
            want_in = {fid for fid, f in flows.items() if f.get("targetRef") == nid}
            want_out = {fid for fid, f in flows.items() if f.get("sourceRef") == nid}
            if inc != want_in or outg != want_out:
                out.append(f"{nid}: its incoming / outgoing do not match the sequence flows")
            kind = n.tag.split("}")[1]
            if kind == "startEvent" and want_in:
                out.append(f"{nid}: a start event has no incoming flow")
            if kind == "endEvent" and want_out:
                out.append(f"{nid}: an end event has no outgoing flow")
        if not any(n.tag == q("startEvent") for n in nodes.values()):
            out.append(f"process {p.get('id')}: no start event")
        if not any(n.tag == q("endEvent") for n in nodes.values()):
            out.append(f"process {p.get('id')}: no end event")
        for lane in p.iter(q("lane")):
            for ref in lane.findall(q("flowNodeRef")):
                if ref.text not in nodes:
                    out.append(f"lane {lane.get('id')}: refers to {ref.text!r}, which is not a flow node")
        shapes = {s.get("bpmnElement") for s in root.iter(f"{{{NS['bpmndi']}}}BPMNShape")}
        edges = {e.get("bpmnElement"): e for e in root.iter(f"{{{NS['bpmndi']}}}BPMNEdge")}
        miss = [n for n in nodes if n not in shapes]
        if miss:
            out.append("no diagram shape for: " + ", ".join(miss[:8]))
        for fid in flows:
            e = edges.get(fid)
            if e is None or len(e.findall(f"{{{NS['di']}}}waypoint")) < 2:
                out.append(f"flow {fid}: no diagram edge with its waypoints")
    return out


def from_bpmn(xml: str) -> dict:
    """A BPMN 2.0 export -> a map (lanes, steps, links). Unknown node kinds become tasks; the first process is read."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    q = lambda t: f"{{{NS['bpmn']}}}{t}"  # noqa: E731
    p = root.find(q("process"))
    if p is None:
        raise ValueError("no process in the BPMN file")
    lanes, lane_of = [], {}
    for i, lane in enumerate(p.iter(q("lane")), 1):
        lid = f"L{i}"
        lanes.append({"id": lid, "name": lane.get("name") or f"Lane {i}", "kind": "person"})
        for ref in lane.findall(q("flowNodeRef")):
            lane_of[ref.text] = lid
    steps, idmap = [], {}
    for e in p:
        kind = e.tag.split("}")[1]
        if kind in TYPE_OF:
            idmap[e.get("id")] = e.get("id")
            doc = e.find(q("documentation"))
            steps.append({"id": e.get("id"), "name": e.get("name") or kind, "type": TYPE_OF[kind], "lane": lane_of.get(e.get("id"), lanes[0]["id"] if lanes else ""),
                          "instructions": (doc.text or "").strip() if doc is not None else "", "next": []})
    by = {s["id"]: s for s in steps}
    for f in p.findall(q("sequenceFlow")):
        if f.get("sourceRef") in by:
            by[f.get("sourceRef")]["next"].append({"to": f.get("targetRef"), "when": f.get("name") or ""})
    return {"name": p.get("name") or "Process", "lanes": lanes, "steps": steps}


VNS = "http://schemas.microsoft.com/office/visio/2012/main"


def from_vsdx(path: Path) -> dict:
    """A Visio flowchart -> a map, by the shapes' masters: Start/End (terminator) events, Decision gateways, Process (and
    anything else with text) tasks, Dynamic connectors as the links with their text as the condition. Swimlanes of a
    cross-functional flowchart become lanes when the shapes sit in them; otherwise one lane a person corrects."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        masters = {}
        if "visio/masters/masters.xml" in names:
            for m in ET.fromstring(z.read("visio/masters/masters.xml")).iter(f"{{{VNS}}}Master"):
                masters[m.get("ID")] = (m.get("NameU") or m.get("Name") or "").lower()
        page = next((n for n in sorted(names) if re.match(r"visio/pages/page\d+\.xml$", n)), None)
        if not page:
            raise ValueError("the Visio file has no page")
        root = ET.fromstring(z.read(page))
    shapes, conns = {}, []
    for s in root.iter(f"{{{VNS}}}Shape"):
        kind = masters.get(s.get("Master") or "", (s.get("NameU") or "").lower())
        text = " ".join("".join(t.itertext()) for t in s.findall(f"{{{VNS}}}Text")).strip()
        cells = {c.get("N"): c.get("V") for c in s.findall(f"{{{VNS}}}Cell")}
        shapes[s.get("ID")] = {"kind": kind, "text": " ".join(text.split()), "x": float(cells.get("PinX") or 0), "y": float(cells.get("PinY") or 0)}
    links: dict = {}
    for c in root.iter(f"{{{VNS}}}Connect"):
        links.setdefault(c.get("FromSheet"), {})["from" if c.get("FromCell") == "BeginX" else "to"] = c.get("ToSheet")
    lanes = [{"id": f"L{i}", "name": v["text"], "kind": "person", "y": v["y"]} for i, (k, v) in enumerate(sorted(((k, v) for k, v in shapes.items() if "swimlane" in v["kind"]), key=lambda kv: -kv[1]["y"]), 1)]
    steps = {}
    for sid, s in shapes.items():
        if "connector" in s["kind"] or "swimlane" in s["kind"] or not s["text"]:
            continue
        typ = "gateway" if "decision" in s["kind"] else "start" if ("start" in s["kind"] or "terminator" in s["kind"]) else "task"
        lane = min(lanes, key=lambda l: abs(l["y"] - s["y"]))["id"] if lanes else "L1"
        steps[sid] = {"id": f"V{sid}", "name": s["text"], "type": typ, "lane": lane, "next": [], "instructions": "", "visio": sid}
    for cid, ends in links.items():
        a, b = ends.get("from"), ends.get("to")
        if a in steps and b in steps:
            steps[a]["next"].append({"to": steps[b]["id"], "when": shapes.get(cid, {}).get("text") or ""})
    has_in = {n["to"] for s in steps.values() for n in s["next"]}
    for s in steps.values():
        if s["type"] == "start" and s["id"] in has_in:
            s["type"] = "end" if not s["next"] else "task"
    order = sorted(steps.values(), key=lambda s: (s["type"] != "start", int(s["visio"]) if str(s["visio"]).isdigit() else 0))
    return {"name": Path(path).stem, "lanes": [{k: v for k, v in l.items() if k != "y"} for l in lanes] or [{"id": "L1", "name": "Unassigned (correct the lane)", "kind": "person"}],
            "steps": [{k: v for k, v in s.items() if k != "visio"} for s in order]}


def inventory(xml: str) -> dict:
    """What a BPMN file holds, for an assessment: processes, lanes, nodes by kind, flows."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    q = lambda t: f"{{{NS['bpmn']}}}{t}"  # noqa: E731
    procs = root.findall(q("process"))
    kinds: dict = {}
    for p in procs:
        for e in p:
            k = e.tag.split("}")[1]
            if k in TYPE_OF:
                kinds[TYPE_OF[k]] = kinds.get(TYPE_OF[k], 0) + 1
    return {"processes": [p.get("name") or p.get("id") for p in procs], "lanes": sum(1 for p in procs for _ in p.iter(q("lane"))), "nodes": kinds,
            "flows": sum(1 for p in procs for e in p if e.tag == q("sequenceFlow"))}
