#!/usr/bin/env python3
"""Cross-street turning movements + spider diagrams (blueprint #3, phase 3).

At each interchange the ramp terminals are signalized/priority intersections;
their turning movements are the operational detail planners want. This module:

  * finds the RAMP-TERMINAL nodes per interchange (nodes shared by a ramp member
    and a cross-street member -- where the ramp meets the arterial);
  * runs `agentAnalysis turns` on them (from agentPaths.duckdb) to get every
    from->thru->to movement with its daily veh_weight;
  * classifies each movement Left / Through / Right / U-turn and the approach
    direction (NB/SB/EB/WB) from node geometry;
  * emits interchange_turns.csv (interchange, node, approach, movement, volume)
    and provides spider_svg() -- the classic turning-movement diagram -- for the
    workbook / HTML dashboard (phase 4).

  python interchange_turns.py --run-dir <dir> --interchanges interchanges.gpkg
      --nodes TSM_Node_ML.gpkg [--agentanalysis <exe>] [--db agentPaths.duckdb]
      [--max-interchanges 40] [--county ..] [--route ..]
"""
import argparse
import csv
import html
import math
import os
import subprocess
from collections import defaultdict


# ------------------------------------------------------------- extraction ---
def terminal_nodes(members_csv):
    """{interchange_id: [ramp-terminal node ids]} -- nodes on both a ramp and a
    cross-street member (the ramp/arterial junctions)."""
    ramp, cross = defaultdict(set), defaultdict(set)
    with open(members_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ix = int(r["interchange_id"])
            for n in (int(r["a_node"]), int(r["b_node"])):
                if r["role"] in ("on_ramp", "off_ramp", "system_ramp"):
                    ramp[ix].add(n)
                elif r["role"] == "cross_street":
                    cross[ix].add(n)
    return {ix: sorted(ramp[ix] & cross[ix]) for ix in ramp if ramp[ix] & cross[ix]}


def read_node_xy(node_gpkg, needed=None):
    from osgeo import ogr
    ds = ogr.Open(node_gpkg)
    lyr = ds.GetLayer(0)
    xy = {}
    for f in lyr:
        n = f.GetField("N")
        if needed is None or n in needed:
            xy[n] = (f.GetField("X"), f.GetField("Y"))
    ds = None
    return xy


def run_turns(exe, db, nodes, out_csv):
    """Run agentAnalysis turns for the node set; return list of movement rows."""
    ncsv = out_csv + ".nodes.csv"
    with open(ncsv, "w", encoding="utf-8") as f:
        f.write("node\n" + "\n".join(str(n) for n in nodes))
    subprocess.run([exe, "turns", "--db", db, "--nodes", ncsv, "--out", out_csv],
                   check=True, capture_output=True, text=True)
    rows = []
    with open(out_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((int(r["node"]), int(r["from_node"]), int(r["to_node"]),
                         float(r.get("veh_weight") or r.get("agents") or 0)))
    return rows


# ------------------------------------------------------------ classification --
def _bearing(p, q):
    return math.atan2(q[1] - p[1], q[0] - p[0])


def _norm(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def _cardinal(brg):
    """Travel direction of the approach (0 rad = +x = East, CCW)."""
    deg = math.degrees(brg) % 360
    if 45 <= deg < 135:
        return "NB"
    if 135 <= deg < 225:
        return "WB"
    if 225 <= deg < 315:
        return "SB"
    return "EB"


def _turn(app_brg, dep_brg):
    a = math.degrees(_norm(dep_brg - app_brg))
    if abs(a) <= 30:
        return "T"
    if 30 < a <= 150:
        return "L"          # CCW = left in +x/+y (north-up) frame
    if -150 <= a < -30:
        return "R"
    return "U"


def classify(rows, xy):
    """rows -> list of dicts with approach dir + movement type + volume."""
    out = []
    for node, frm, to, vol in rows:
        pn, pf, pt = xy.get(node), xy.get(frm), xy.get(to)
        if not (pn and pf and pt):
            continue
        app = _bearing(pf, pn)       # into the intersection
        dep = _bearing(pn, pt)       # out of it
        out.append({"node": node, "from": frm, "to": to, "vol": vol,
                    "approach": _cardinal(app), "move": _turn(app, dep)})
    return out


# ---------------------------------------------------------------- spider SVG --
# where each approach's traffic ENTERS from (opposite its travel direction), in
# SVG coords (y grows downward: north=top).
_ENTRY = {"NB": "S", "SB": "N", "EB": "W", "WB": "E"}
_EDGE = {"N": (120, 26), "S": (120, 214), "E": (214, 120), "W": (26, 120)}
# exit edge for each (approach, movement)
_EXIT = {
    ("NB", "T"): "N", ("NB", "L"): "W", ("NB", "R"): "E", ("NB", "U"): "S",
    ("SB", "T"): "S", ("SB", "L"): "E", ("SB", "R"): "W", ("SB", "U"): "N",
    ("EB", "T"): "E", ("EB", "L"): "N", ("EB", "R"): "S", ("EB", "U"): "W",
    ("WB", "T"): "W", ("WB", "L"): "S", ("WB", "R"): "N", ("WB", "U"): "E",
}
_MOVE_COLOR = {"T": "--muted", "L": "--gp", "R": "--el", "U": "--bad"}


def spider_svg(node_movements, title="", w=250):
    """Turning-movement diagram for one node. node_movements = list of dicts
    (approach, move, vol). Arrow width ∝ sqrt(volume); L blue, T grey, R green."""
    mv = [m for m in node_movements if m["vol"] > 0 and (m["approach"], m["move"]) in _EXIT]
    if not mv:
        return "<p class='fignote'>no movements</p>"
    vmax = max(m["vol"] for m in mv)
    cx, cy = 120, 120
    top = 22 if title else 8
    b = ['<rect x="106" y="106" width="28" height="28" rx="4" '
         'fill="none" stroke="var(--axis)"/>']
    # present legs -- thin, recessive
    for d in {_ENTRY[m["approach"]] for m in mv} | {_EXIT[(m["approach"], m["move"])] for m in mv}:
        ex, ey = _EDGE[d]
        b.append(f'<line x1="{ex}" y1="{ey}" x2="{cx}" y2="{cy}" '
                 f'stroke="var(--grid)" stroke-width="4" stroke-linecap="round" opacity="0.5"/>')
    for m in sorted(mv, key=lambda z: -z["vol"]):
        entry = _EDGE[_ENTRY[m["approach"]]]
        exit_ = _EDGE[_EXIT[(m["approach"], m["move"])]]
        wdt = 1.5 + 7.0 * math.sqrt(m["vol"] / vmax)
        col = f'var({_MOVE_COLOR[m["move"]]})'
        # curved turns: control point pulled toward the centre; through = straight
        bow = 0.05 if m["move"] == "T" else 0.42
        ctrlx = cx + ((entry[0] + exit_[0]) / 2 - cx) * bow
        ctrly = cy + ((entry[1] + exit_[1]) / 2 - cy) * bow
        b.append(f'<path d="M{entry[0]},{entry[1]} Q{ctrlx:.0f},{ctrly:.0f} '
                 f'{exit_[0]},{exit_[1]}" fill="none" stroke="{col}" '
                 f'stroke-width="{wdt:.1f}" stroke-linecap="round" opacity="0.8"/>')
        # volume label at ~1/3 along the arc toward the exit
        lx = entry[0] + (exit_[0] - entry[0]) * 0.72
        ly = entry[1] + (exit_[1] - entry[1]) * 0.72
        lx = cx + (lx - cx) * (1 + bow)   # nudge outward off the centre
        b.append(f'<text x="{lx:.0f}" y="{ly:.0f}" font-size="9" '
                 f'text-anchor="middle" fill="var(--ink2)" '
                 f'font-variant-numeric="tabular-nums">{_kfmt(m["vol"])}</text>')
    # cardinal letters at the very corners so they never collide with arcs
    for d, (lx, ly) in (("N", (cx, top + 4)), ("S", (cx, 236)),
                        ("E", (236, cy + 3)), ("W", (6, cy + 3))):
        b.append(f'<text x="{lx}" y="{ly}" font-size="9" font-weight="600" '
                 f'text-anchor="middle" fill="var(--muted)">{d}</text>')
    t = (f'<text x="{cx}" y="14" font-size="11" text-anchor="middle" '
         f'fill="var(--ink)">{html.escape(title)}</text>') if title else ""
    return (f'<svg viewBox="0 0 242 242" width="{w}" '
            f'xmlns="http://www.w3.org/2000/svg" '
            f'font-family="system-ui,sans-serif">{t}{"".join(b)}</svg>')


def _kfmt(v):
    v = float(v)
    return f"{v/1000:.1f}k" if v >= 1000 else f"{v:.0f}"


# ---------------------------------------------------------------- driver ----
def build(run_dir, interchanges_gpkg, node_gpkg, agentanalysis=None, db=None,
          max_interchanges=40, county=None, route=None, out_csv=None):
    members_csv = os.path.splitext(interchanges_gpkg)[0] + "_members.csv"
    term = terminal_nodes(members_csv)
    # pick the interchange set (optionally filtered), cap the count
    ix_meta = _read_ix_meta(interchanges_gpkg)
    sel = sorted(term.keys(),
                 key=lambda i: -ix_meta.get(i, {}).get("n_ramps", 0))
    if county:
        sel = [i for i in sel if county.lower() in ix_meta.get(i, {}).get("county", "").lower()]
    if route:
        sel = [i for i in sel if route.lower() in ix_meta.get(i, {}).get("route", "").lower()]
    sel = sel[:max_interchanges]
    all_nodes = sorted({n for i in sel for n in term[i]})
    if not all_nodes:
        raise SystemExit("no ramp-terminal nodes for the selected interchanges")

    exe = agentanalysis or _find_exe()
    db = db or os.path.join(run_dir, "agentPaths.duckdb")
    if not exe or not os.path.exists(db):
        raise SystemExit(f"need agentAnalysis exe ({exe}) and db ({db})")
    out_csv = out_csv or os.path.join(run_dir, "interchange_turns.csv")
    raw = os.path.join(run_dir, "_turns_raw.csv")
    rows = run_turns(exe, db, all_nodes, raw)
    xy = read_node_xy(node_gpkg, set(all_nodes) |
                      {r[1] for r in rows} | {r[2] for r in rows})
    moves = classify(rows, xy)
    node_ix = {n: i for i in sel for n in term[i]}
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["interchange_id", "node", "approach", "movement",
                    "from_node", "to_node", "volume"])
        for m in moves:
            w.writerow([node_ix.get(m["node"], ""), m["node"], m["approach"],
                        m["move"], m["from"], m["to"], round(m["vol"], 1)])
    n_nodes = len({m["node"] for m in moves})
    print(f"[interchange-turns] {len(sel)} interchanges, {n_nodes} terminal nodes, "
          f"{len(moves)} movements -> {out_csv}")
    return out_csv


def _read_ix_meta(gpkg):
    from osgeo import ogr
    ds = ogr.Open(gpkg)
    pt = ds.GetLayerByName("interchanges")
    m = {f["ix_id"]: {"name": f["name"] or "", "route": f["route"] or "",
                      "county": f["county"] or "", "n_ramps": f["n_ramps"]}
         for f in pt}
    ds = None
    return m


def _find_exe():
    for p in (r"C:\Development\TSMv6_Codebase\agentAnalysis\build\release-ninja\agentAnalysis.exe",
              r"C:\Development\TSMv6_Codebase\agentAnalysis\build\agentAnalysis.exe"):
        if os.path.exists(p):
            return p
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--interchanges", required=True)
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--agentanalysis")
    ap.add_argument("--db")
    ap.add_argument("--max-interchanges", type=int, default=40)
    ap.add_argument("--county")
    ap.add_argument("--route")
    a = ap.parse_args()
    build(a.run_dir, a.interchanges, a.nodes, a.agentanalysis, a.db,
          a.max_interchanges, a.county, a.route)
