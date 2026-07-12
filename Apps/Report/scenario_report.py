#!/usr/bin/env python3
"""Model Scenario Run Report -- assignment section (blueprint #2, phase 1).

Reads a HyDRA run directory and writes a single, self-contained report card:

  scenario_report.html   demo-page quality, inline CSS + static inline SVG
                         charts (no external assets, theme-aware light/dark),
                         so it opens anywhere and attaches to a memo.
  scenario_report.md     the diffable twin (drops into a PR or memo).
  scenario_metrics.csv   one tidy long table (stage,section,metric,segment,
                         value,unit) so the report is queryable, not just visual
                         -- the standard-metrics contract the dashboards read.

Phase 1 delivers the ASSIGNMENT half -- network totals (VMT/VHT/speed by
facility), the count-validation headline (model/obs ratio, R2, %RMSE, GEH bins
overall + by facility + by county), tolling (EL toll profile + revenue proxy +
EL share), an assignment-convergence proxy, and the multi-resolution split.
Demand sections (PopSyn / SDT / LDT / trip-list) render "not run yet" and are
filled in phase 2-3. Every section checks for its inputs and degrades to a
"not available" note rather than failing, so a partial run still reports.

Metric formulas follow the canonical Summarization (valstats + GEH) so the
numbers match the validation workbook. VMT/VHT are derived from the tier link-
performance files (length = speed x tt, verified against count_validation).

  python scenario_report.py --run-dir <dir> [--out-dir <dir>]
                            [--min-mainline 5000] [--title "..."]
"""
import argparse
import csv
import html
import math
import os
import time

import numpy as np
import pandas as pd

# ---- facility classification (canonical, extended for EL + connectors) ----
FACILITY = {11: "Limited Access", 12: "Limited Access",
            96: "Express Lanes", 97: "Express Lanes", 98: "Express Lanes",
            91: "Toll", 93: "Toll", 94: "Toll", 92: "Toll",
            71: "Ramps", 72: "Ramps",
            21: "Arterial (Div)", 31: "Arterial (Undiv)",
            41: "Collector", 45: "Collector", 48: "Collector",
            51: "Connector"}
FAC_ORDER = ["Limited Access", "Express Lanes", "Toll", "Ramps",
             "Arterial (Div)", "Arterial (Undiv)", "Collector", "Other"]
FAC_COLOR = {"Limited Access": "--gp", "Express Lanes": "--el", "Toll": "--meso",
             "Ramps": "--muted", "Arterial (Div)": "--macro",
             "Arterial (Undiv)": "--macro", "Collector": "--axis",
             "Other": "--muted"}
EL_FT = {96, 97, 98}
VOL_BINS = [0, 5000, 10000, 20000, 40000, 60000, 1e9]
VOL_LABELS = ["<5k", "5-10k", "10-20k", "20-40k", "40-60k", ">60k"]
NI = 96


def fac(ft):
    return FACILITY.get(int(ft), "Other")


# ------------------------------------------------------------------ metrics --
def valstats(g):
    """Canonical count-validation metrics for a group (obs_24h/model_24h/geh)."""
    o = g["obs_24h"].to_numpy(float)
    m = g["model_24h"].to_numpy(float)
    n = len(g)
    r2 = np.nan
    if n > 2 and o.std() > 0 and m.std() > 0:
        r2 = float(np.corrcoef(o, m)[0, 1] ** 2)
    om = o.mean() if o.mean() != 0 else np.nan
    prmse = 100.0 * math.sqrt(((m - o) ** 2).sum() / max(n - 1, 1)) / om \
        if om and not math.isnan(om) else np.nan
    geh = g["geh_hourly_avg"].to_numpy(float)
    return {"links": n, "obs": o.sum(), "model": m.sum(),
            "ratio": (m.sum() / o.sum()) if o.sum() else np.nan, "r2": r2,
            "prmse": prmse, "geh5": 100.0 * np.mean(geh < 5),
            "geh10": 100.0 * np.mean(geh < 10)}


def network_totals(run_dir):
    """VMT / VHT / mean speed by facility, summed over the disjoint tiers.
    length_mi = speed_mph * tt_min/60 (constant per link; connectors dropped)."""
    rows = []
    tiers = {}
    for tier in ("macro", "meso", "micro"):
        fp = os.path.join(run_dir, f"link_performance_{tier}DTA.csv")
        if not os.path.exists(fp):
            continue
        df = pd.read_csv(fp, usecols=["a_node", "b_node", "ftype", "interval",
                                      "volume", "travel_time_min", "speed_mph"])
        df = df[df["interval"] < NI]
        tiers[tier] = df["a_node"].astype(str).add("-").add(
            df["b_node"].astype(str)).nunique()
        df["fac"] = df["ftype"].map(fac)
        df = df[df["fac"] != "Connector"]
        good = (df["speed_mph"] > 0) & (df["travel_time_min"] > 0)
        df.loc[good, "len_mi"] = df.loc[good, "speed_mph"] * \
            df.loc[good, "travel_time_min"] / 60.0
        # per-link length = median of good intervals
        ln = df.loc[good].groupby(["a_node", "b_node"])["len_mi"].median()
        df = df.join(ln, on=["a_node", "b_node"], rsuffix="_lk")
        df["len_lk"] = df["len_mi_lk"].fillna(0.0)
        df["vmt"] = df["volume"] * df["len_lk"]
        df["vht"] = df["volume"] * df["travel_time_min"] / 60.0
        g = df.groupby("fac").agg(vmt=("vmt", "sum"), vht=("vht", "sum")).reset_index()
        g["tier"] = tier
        rows.append(g)
    if not rows:
        return None, tiers
    allg = pd.concat(rows).groupby("fac").agg(
        vmt=("vmt", "sum"), vht=("vht", "sum")).reset_index()
    allg["speed"] = allg["vmt"] / allg["vht"].replace(0, np.nan)
    return allg, tiers


def tolling(run_dir):
    """EL toll profile (mean toll by hour, volume-weighted), revenue proxy,
    EL VMT share of limited-access, from the meso tier (statewide EL)."""
    fp = os.path.join(run_dir, "link_performance_mesoDTA.csv")
    if not os.path.exists(fp):
        return None
    df = pd.read_csv(fp, usecols=["ftype", "hour", "interval", "volume",
                                  "travel_time_min", "speed_mph", "toll_rate"])
    df = df[df["interval"] < NI]
    el = df[df["ftype"].isin(EL_FT)].copy()
    if el.empty or el["toll_rate"].fillna(0).max() <= 0:
        return None
    el["rev"] = el["volume"] * el["toll_rate"]
    # volume-weighted mean toll by hour
    prof = el.groupby("hour").apply(
        lambda g: (g["volume"] * g["toll_rate"]).sum() / max(g["volume"].sum(), 1e-9),
        include_groups=False
    ).reindex(range(24)).fillna(0.0)
    return {"profile": [(h, float(prof[h])) for h in range(24)],
            "peak": float(el["toll_rate"].max()),
            "revenue": float(el["rev"].sum()),
            "el_vol": float(el["volume"].sum())}


def convergence(run_dir):
    """Assignment-quality proxy: weighted mean relative gap from agentPlans
    (gap_min / cost_min), plus the trip/weight totals."""
    fp = os.path.join(run_dir, "agentPlans_out.csv")
    if not os.path.exists(fp):
        return None
    cols = pd.read_csv(fp, nrows=0).columns
    use = [c for c in ("weight", "cost_min", "gap_min", "purpose", "scope", "vot")
           if c in cols]
    df = pd.read_csv(fp, usecols=use)
    w = df["weight"] if "weight" in df else pd.Series(1.0, index=df.index)
    out = {"trips": float(w.sum()), "rows": len(df)}
    if {"gap_min", "cost_min"}.issubset(df.columns):
        num = (w * df["gap_min"]).sum()
        den = (w * df["cost_min"]).sum()
        out["rel_gap"] = float(num / den) if den else np.nan
    if "purpose" in df:
        wcol = "weight" if "weight" in df else None
        out["by_purpose"] = (df.groupby("purpose")["weight"].sum().to_dict()
                             if wcol else df["purpose"].value_counts().to_dict())
    if "vot" in df:
        out["vot_mean"] = float((w * df["vot"]).sum() / max(w.sum(), 1e-9))
    return out


def _find(paths, *names):
    """First existing file among names, searched over paths."""
    for p in paths:
        for n in names:
            fp = os.path.join(p, n)
            if os.path.exists(fp):
                return fp
    return None


def _market_group(m):
    m = str(m)
    if m.startswith("SDT_Res"):
        return "SDT resident"
    if m.startswith("SDT_Vis"):
        return "SDT visitor"
    if m.startswith("LDT_Res") or m.startswith("LDT_Vis") or m.startswith("LDT"):
        return "LDT visitor" if "Vis" in m else "LDT resident"
    if m.startswith("OS") or "External" in m or "ext" in m.lower():
        return "External / OS"
    return m


def triplist_summary(demand_paths, cache_dir, chunk=4_000_000):
    """Chunked aggregation of the assembled tripList (the demand handed to
    assignment): vehicle- and person-trips by market / VOT segment / purpose,
    occupancy, and the departure-time profile. Cached to a small JSON keyed on
    the source mtime so re-runs are instant (the file can be tens of millions
    of rows)."""
    import json
    fp = _find(demand_paths, "tripList_30min.csv.gz", "tripList_30min.csv",
               "tripList.csv.gz", "tripList.csv")
    if not fp:
        return None
    cache = os.path.join(cache_dir, ".triplist_cache.json")
    src_mt = os.path.getmtime(fp)
    if os.path.exists(cache):
        try:
            c = json.load(open(cache))
            if abs(c.get("_mtime", 0) - src_mt) < 1 and c.get("_src") == fp:
                return c
        except Exception:
            pass
    from collections import defaultdict
    veh_mkt, per_mkt, cnt_mkt = defaultdict(float), defaultdict(float), defaultdict(int)
    veh_vot, veh_pur = defaultdict(float), defaultdict(float)
    veh_hr = defaultdict(float)
    veh_mkt_pur = defaultdict(float)   # (market_group, purpose) -> vehTrips
    tot_v = tot_p = 0.0
    use = ["purpose", "depart_time", "marketVot", "vehTrips", "occupancy", "market"]
    for ch in pd.read_csv(fp, usecols=use, chunksize=chunk,
                          dtype={"purpose": "category", "marketVot": "category",
                                 "market": "category"}):
        v = ch["vehTrips"].to_numpy(float)
        # occupancy has garbage outliers (seen up to 12,306) and sub-1 noise;
        # clamp to a physical auto range so person-trips aren't polluted.
        occ = ch["occupancy"].fillna(1.0).clip(1.0, 8.0).to_numpy(float)
        p = v * occ
        tot_v += v.sum(); tot_p += p.sum()
        gm = ch["market"].map(_market_group)
        for key, sv in ch.groupby(gm, observed=True).indices.items():
            veh_mkt[key] += v[sv].sum(); per_mkt[key] += p[sv].sum()
            cnt_mkt[key] += len(sv)
        for key, sv in ch.groupby("marketVot", observed=True).indices.items():
            veh_vot[str(key)] += v[sv].sum()
        for key, sv in ch.groupby("purpose", observed=True).indices.items():
            veh_pur[str(key)] += v[sv].sum()
        ch2 = ch.assign(_mg=gm)
        for (mgk, pk), sv in ch2.groupby(["_mg", "purpose"], observed=True).indices.items():
            veh_mkt_pur[f"{mgk}||{pk}"] += v[sv].sum()
        hr = ch["depart_time"].astype(str).str.slice(0, 2)
        hr = pd.to_numeric(hr, errors="coerce").fillna(0).astype(int).clip(0, 23)
        for h_, sv in ch.groupby(hr).indices.items():
            veh_hr[int(h_)] += v[sv].sum()
    out = {"_src": fp, "_mtime": src_mt, "total_veh": tot_v, "total_per": tot_p,
           "by_market": dict(veh_mkt), "per_market": dict(per_mkt),
           "cnt_market": dict(cnt_mkt), "by_vot": dict(veh_vot),
           "by_purpose": dict(veh_pur),
           "by_market_purpose": dict(veh_mkt_pur),
           "by_hour": {str(k): v for k, v in veh_hr.items()}}
    try:
        json.dump(out, open(cache, "w"))
    except Exception:
        pass
    return out


def load_validation(run_dir, min_mainline=5000):
    fp = os.path.join(run_dir, "count_validation.csv")
    if not os.path.exists(fp):
        return None
    cv = pd.read_csv(fp)
    cv = cv[(cv["obs_24h"] > 0)]
    # canonical mainline-trust filter: drop low-count mainline/toll links
    mask = cv["ftype"].isin([11, 12, 91, 92, 93, 94]) & (cv["obs_24h"] < min_mainline)
    cv = cv[~mask].copy()
    cv["fac"] = cv["ftype"].map(fac)
    cv["volgrp"] = pd.cut(cv["obs_24h"], VOL_BINS, labels=VOL_LABELS)
    return cv


# --------------------------------------------------------------- SVG charts --
def _svg(w, h, body):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" '
            f'style="max-width:{w}px;display:block" '
            f'xmlns="http://www.w3.org/2000/svg" '
            f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">{body}</svg>')


def hbars(pairs, unit="", w=560, rowh=26, pad_l=140):
    """pairs = [(label, value, color_var)]; horizontal bars, value labels."""
    pairs = [p for p in pairs if p[1] and not (isinstance(p[1], float) and math.isnan(p[1]))]
    if not pairs:
        return "<p class='fignote'>no data</p>"
    vmax = max(p[1] for p in pairs) or 1
    h = len(pairs) * rowh + 12
    bar_w = w - pad_l - 70
    b = []
    for i, (lab, v, col) in enumerate(pairs):
        y = 8 + i * rowh
        bw = max(1.0, bar_w * v / vmax)
        b.append(f'<text x="{pad_l-8}" y="{y+13}" text-anchor="end" '
                 f'font-size="12" fill="var(--ink2)">{html.escape(str(lab))}</text>')
        b.append(f'<rect x="{pad_l}" y="{y+3}" width="{bw:.1f}" height="14" rx="3" '
                 f'fill="var({col})" opacity="0.85"/>')
        b.append(f'<text x="{pad_l+bw+6:.1f}" y="{y+14}" font-size="11.5" '
                 f'fill="var(--ink2)" font-variant-numeric="tabular-nums">'
                 f'{_fmt(v)}{unit}</text>')
    return _svg(w, h, "".join(b))


def scatter_obs_model(cv, w=460, h=460, n=500):
    """obs vs model daily volume with the y=x reference line."""
    if cv is None or cv.empty:
        return "<p class='fignote'>no counts</p>"
    d = cv.sample(min(n, len(cv)), random_state=1) if len(cv) > n else cv
    o = d["obs_24h"].to_numpy(float); m = d["model_24h"].to_numpy(float)
    hi = max(o.max(), m.max(), 1) * 1.05
    M = {"l": 56, "b": 44, "t": 12, "r": 14}
    pw, ph = w - M["l"] - M["r"], h - M["t"] - M["b"]
    def X(v): return M["l"] + pw * v / hi
    def Y(v): return M["t"] + ph * (1 - v / hi)
    b = [f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(hi)}" y2="{Y(hi)}" '
         f'stroke="var(--axis)" stroke-dasharray="5 4"/>']
    for i in range(len(o)):
        b.append(f'<circle cx="{X(o[i]):.1f}" cy="{Y(m[i]):.1f}" r="2.6" '
                 f'fill="var(--gp)" opacity="0.5"/>')
    # axes
    b.append(f'<line x1="{M["l"]}" y1="{Y(0)}" x2="{M["l"]+pw}" y2="{Y(0)}" class="axis"/>')
    b.append(f'<line x1="{M["l"]}" y1="{M["t"]}" x2="{M["l"]}" y2="{Y(0)}" class="axis"/>')
    for f_ in (0, .5, 1):
        b.append(f'<text x="{X(hi*f_):.0f}" y="{Y(0)+16}" font-size="10.5" '
                 f'text-anchor="middle" fill="var(--muted)">{_fmt(hi*f_)}</text>')
        b.append(f'<text x="{M["l"]-8}" y="{Y(hi*f_)+3:.0f}" font-size="10.5" '
                 f'text-anchor="end" fill="var(--muted)">{_fmt(hi*f_)}</text>')
    b.append(f'<text x="{M["l"]+pw/2}" y="{h-8}" font-size="11.5" '
             f'text-anchor="middle" fill="var(--ink2)">Observed daily volume</text>')
    b.append(f'<text transform="translate(14,{M["t"]+ph/2}) rotate(-90)" '
             f'font-size="11.5" text-anchor="middle" fill="var(--ink2)">Model daily volume</text>')
    return _svg(w, h, "".join(b))


def line_profile(pairs, w=560, h=220, unit="$", ylab="EL toll ($)"):
    """pairs = [(hour, value)]; area+line over 24 h."""
    if not pairs:
        return "<p class='fignote'>no data</p>"
    vmax = max(v for _, v in pairs) or 1
    M = {"l": 48, "b": 34, "t": 14, "r": 14}
    pw, ph = w - M["l"] - M["r"], h - M["t"] - M["b"]
    def X(hh): return M["l"] + pw * hh / 23.0
    def Y(v): return M["t"] + ph * (1 - v / (vmax * 1.1))
    pts = "".join(("L" if i else "M") + f"{X(x):.1f} {Y(y):.1f}"
                  for i, (x, y) in enumerate(pairs))
    area = pts + f"L{X(23):.1f} {Y(0):.1f}L{X(0):.1f} {Y(0):.1f}Z"
    b = [f'<path d="{area}" fill="var(--meso)" opacity="0.18"/>',
         f'<path d="{pts}" fill="none" stroke="var(--meso)" stroke-width="2"/>']
    for gy in (0, vmax):
        b.append(f'<line x1="{M["l"]}" y1="{Y(gy):.1f}" x2="{M["l"]+pw}" '
                 f'y2="{Y(gy):.1f}" class="grid"/>')
        gl = f"{unit}{gy:.2f}" if unit else _fmt(gy)
        b.append(f'<text x="{M["l"]-6}" y="{Y(gy)+3:.1f}" font-size="10.5" '
                 f'text-anchor="end" fill="var(--muted)">{gl}</text>')
    for hh in (0, 6, 12, 18, 23):
        lab = "12A" if hh == 0 else (f"{hh}A" if hh < 12 else ("12P" if hh == 12 else f"{hh-12}P"))
        b.append(f'<text x="{X(hh):.0f}" y="{h-8}" font-size="10.5" '
                 f'text-anchor="middle" fill="var(--muted)">{lab}</text>')
    b.append(f'<text transform="translate(12,{M["t"]+ph/2}) rotate(-90)" '
             f'font-size="11" text-anchor="middle" fill="var(--ink2)">{ylab}</text>')
    return _svg(w, h, "".join(b))


def _fmt(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    v = float(v)
    if abs(v) >= 1e6:
        return f"{v/1e6:.2f}M"
    if abs(v) >= 1e3:
        return f"{v/1e3:.1f}k"
    if abs(v) >= 10:
        return f"{v:.0f}"
    return f"{v:.2f}"


def tiles(items):
    """items = [(value_html, key_label)] -> stat-tile grid."""
    c = "".join(f'<div class="tile"><div class="v">{v}</div>'
                f'<div class="k">{html.escape(k)}</div></div>' for v, k in items)
    return f'<div class="tiles">{c}</div>'


def table(headers, rows, num_cols=()):
    th = "".join(f'<th class="{"num" if i in num_cols else ""}">{html.escape(h)}</th>'
                 for i, h in enumerate(headers))
    tr = []
    for r in rows:
        td = "".join(f'<td class="{"num" if i in num_cols else ""}">{c}</td>'
                     for i, c in enumerate(r))
        tr.append(f"<tr>{td}</tr>")
    return f'<table><thead><tr>{th}</tr></thead><tbody>{"".join(tr)}</tbody></table>'


# ------------------------------------------------------------------ assemble --
CSS = """
:root{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;
 --muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
 --macro:#2a78d6;--meso:#c98500;--micro:#4a3aa7;--el:#1baf7a;--gp:#2a78d6;
 --good:#1baf7a;--warn:#c98500;--bad:#e34948}
@media (prefers-color-scheme:dark){:root{--surface:#1a1a19;--page:#0d0d0d;
 --ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
 --ring:rgba(255,255,255,.10);--macro:#3987e5;--meso:#eda100;--micro:#9085e9;
 --el:#199e70;--gp:#3987e5;--good:#199e70;--warn:#eda100;--bad:#e66767}}
:root[data-theme="light"]{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;
 --ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--macro:#2a78d6;
 --meso:#c98500;--micro:#4a3aa7;--el:#1baf7a;--gp:#2a78d6;--good:#1baf7a;
 --warn:#c98500;--bad:#e34948;--ring:rgba(11,11,11,.10)}
:root[data-theme="dark"]{--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;
 --ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--macro:#3987e5;
 --meso:#eda100;--micro:#9085e9;--el:#199e70;--gp:#3987e5;--good:#199e70;
 --warn:#eda100;--bad:#e66767;--ring:rgba(255,255,255,.10)}
*{box-sizing:border-box}
body{background:var(--page);color:var(--ink);margin:0;
 font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:38px 28px 80px}
.eyebrow{font-size:11.5px;text-transform:uppercase;letter-spacing:.12em;
 color:var(--muted);font-weight:600}
h1{font-size:29px;line-height:1.15;margin:6px 0 4px;letter-spacing:-.01em;text-wrap:balance}
h2{font-size:20px;margin:50px 0 4px;letter-spacing:-.005em;text-wrap:balance}
h3{font-size:14px;margin:24px 0 6px;color:var(--ink2)}
.sub{color:var(--ink2);max-width:74ch;margin:6px 0 0}
.fignote{color:var(--muted);font-size:12.5px;margin:8px 2px 0;max-width:90ch}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;
 padding:16px 20px;margin-top:14px}
.chart{overflow-x:auto;margin-top:10px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
 gap:10px;margin-top:14px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:10px;
 padding:12px 14px}
.tile .v{font-size:21px;font-weight:700;letter-spacing:-.01em;
 font-variant-numeric:tabular-nums}
.tile .v small{font-size:13px;font-weight:600;color:var(--ink2)}
.tile .k{font-size:11.5px;color:var(--muted);margin-top:2px;line-height:1.35}
.cols2{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}
@media(max-width:820px){.cols2{grid-template-columns:1fr}}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:10px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
 color:var(--muted);font-weight:600;padding:6px 12px 6px 0;border-bottom:1px solid var(--axis)}
td{padding:7px 12px 7px 0;border-bottom:1px solid var(--grid)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
svg .grid{stroke:var(--grid);stroke-width:1}
svg .axis{stroke:var(--axis);stroke-width:1}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;
 font-weight:700;letter-spacing:.03em}
.pill.good{background:color-mix(in srgb,var(--good) 18%,transparent);color:var(--good)}
.pill.warn{background:color-mix(in srgb,var(--warn) 20%,transparent);color:var(--warn)}
.pill.bad{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}
.notrun{color:var(--muted);font-style:italic;margin-top:10px}
.tog{position:fixed;top:14px;right:16px;background:var(--surface);
 border:1px solid var(--ring);border-radius:8px;color:var(--muted);
 padding:6px 10px;font-size:12px;cursor:pointer}
.prov{display:flex;flex-wrap:wrap;gap:6px 20px;margin-top:12px;font-size:12.5px;
 color:var(--ink2)}
.prov b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
a{color:var(--macro)}
"""

_THEME_JS = ("<script>document.querySelector('.tog').onclick=function(){var r="
             "document.documentElement,c=r.getAttribute('data-theme')||"
             "(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');"
             "r.setAttribute('data-theme',c==='dark'?'light':'dark')};</script>")


def _pill(label, kind):
    return f'<span class="pill {kind}">{label}</span>'


def _ratio_pill(ratio):
    if ratio is None or math.isnan(ratio):
        return ""
    d = abs(ratio - 1.0)
    k = "good" if d <= 0.10 else ("warn" if d <= 0.20 else "bad")
    return _pill(f"{ratio:.2f}", k)


def build(run_dir, out_dir=None, title=None, min_mainline=5000, demand_dir=None):
    run_dir = os.path.abspath(run_dir)
    out_dir = out_dir or run_dir
    os.makedirs(out_dir, exist_ok=True)
    title = title or f"Scenario Report — {os.path.basename(run_dir)}"
    metrics = []   # (stage,section,metric,segment,value,unit)

    def M(section, metric, segment, value, unit="", stage="Assignment"):
        metrics.append((stage, section, metric, segment,
                        "" if value is None else value, unit))

    def D(section, metric, segment, value, unit=""):
        M(section, metric, segment, value, unit, stage="Demand")

    # ---- compute ----
    net, tier_links = network_totals(run_dir)
    cv = load_validation(run_dir, min_mainline)
    toll = tolling(run_dir)
    conv = convergence(run_dir)
    # demand outputs live in the run dir, a given demand dir, or the parent scenario dir
    demand_paths = [p for p in (demand_dir, run_dir, os.path.dirname(run_dir)) if p]
    tlist = triplist_summary(demand_paths, out_dir)

    sections = []

    # ---- header / provenance ----
    n_links = sum(tier_links.values()) if tier_links else 0
    counties = int(cv["county"].nunique()) if cv is not None else 0
    veh = conv.get("trips") if conv else None
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(
        os.path.getmtime(os.path.join(run_dir, "link_performance_macroDTA.csv"))
        if os.path.exists(os.path.join(run_dir, "link_performance_macroDTA.csv"))
        else run_dir))
    prov = (f'<div class="prov"><span>Run&nbsp;<b>{html.escape(os.path.basename(run_dir))}</b></span>'
            f'<span>Network&nbsp;<b>{n_links:,}</b> directed links</span>'
            f'<span>Counties&nbsp;<b>{counties}</b></span>'
            f'<span>Vehicle-trips&nbsp;<b>{_fmt(veh)}</b></span>'
            f'<span>Generated&nbsp;<b>{when}</b></span></div>')
    M("Provenance", "directed_links", "all", n_links)
    M("Provenance", "counties", "all", counties)
    M("Provenance", "vehicle_trips", "all", veh)

    # ---- network totals ----
    if net is not None and not net.empty:
        vmt = float(net["vmt"].sum()); vht = float(net["vht"].sum())
        msp = vmt / vht if vht else float("nan")
        for _, r in net.iterrows():
            M("NetworkTotals", "VMT", r["fac"], round(r["vmt"], 1), "veh-mi")
            M("NetworkTotals", "VHT", r["fac"], round(r["vht"], 1), "veh-h")
            M("NetworkTotals", "mean_speed", r["fac"], round(r["speed"], 1), "mph")
        M("NetworkTotals", "VMT", "all", round(vmt, 1), "veh-mi")
        M("NetworkTotals", "VHT", "all", round(vht, 1), "veh-h")
        M("NetworkTotals", "mean_speed", "all", round(msp, 1), "mph")
        net["ord"] = net["fac"].map({f: i for i, f in enumerate(FAC_ORDER)}).fillna(9)
        net = net.sort_values("ord")
        bar = hbars([(r["fac"], r["vmt"], FAC_COLOR.get(r["fac"], "--muted"))
                     for _, r in net.iterrows()], unit="")
        tl = tiles([(f'{_fmt(vmt)} <small>veh-mi</small>', "Daily VMT"),
                    (f'{_fmt(vht)} <small>veh-h</small>', "Daily VHT"),
                    (f'{msp:.1f} <small>mph</small>', "Network mean speed"),
                    (f'{n_links:,}', "Directed links")])
        ft = table(["Facility", "VMT", "VHT", "Mean speed (mph)"],
                   [(r["fac"], _fmt(r["vmt"]), _fmt(r["vht"]), f'{r["speed"]:.1f}')
                    for _, r in net.iterrows()], num_cols=(1, 2, 3))
        sections.append(("Network totals",
            "VMT, VHT, and volume-weighted mean speed by facility class, summed "
            "over the disjoint macro / meso / micro tiers (centroid connectors "
            "excluded; link length recovered as speed × travel-time).",
            tl + '<div class="cols2"><div class="chart">' + bar +
            '<p class="fignote">Daily VMT by facility class.</p></div><div>' + ft + '</div></div>'))
    else:
        sections.append(("Network totals", "", '<p class="notrun">No link-performance files found.</p>'))

    # ---- count validation ----
    if cv is not None and not cv.empty:
        ov = valstats(cv)
        M("Validation", "model_obs_ratio", "all", round(ov["ratio"], 3))
        M("Validation", "r2", "all", round(ov["r2"], 3) if not math.isnan(ov["r2"]) else None)
        M("Validation", "pct_rmse", "all", round(ov["prmse"], 1), "%")
        M("Validation", "geh_lt5_pct", "all", round(ov["geh5"], 1), "%")
        M("Validation", "geh_lt10_pct", "all", round(ov["geh10"], 1), "%")
        M("Validation", "counted_links", "all", ov["links"])
        tl = tiles([
            (f'{_ratio_pill(ov["ratio"])}', "Model / observed"),
            (f'{ov["r2"]:.3f}' if not math.isnan(ov["r2"]) else "—", "R²"),
            (f'{ov["prmse"]:.1f}<small>%</small>', "%RMSE"),
            (f'{ov["geh5"]:.0f}<small>%</small>', "GEH < 5"),
            (f'{ov["geh10"]:.0f}<small>%</small>', "GEH < 10"),
            (f'{ov["links"]:,}', "Counted links")])
        # by facility
        fac_rows = []
        for f_ in FAC_ORDER:
            g = cv[cv["fac"] == f_]
            if len(g) < 3:
                continue
            s = valstats(g)
            for k in ("model_obs_ratio", "r2", "pct_rmse", "geh_lt5_pct"):
                pass
            M("Validation", "model_obs_ratio", f_, round(s["ratio"], 3))
            M("Validation", "r2", f_, None if math.isnan(s["r2"]) else round(s["r2"], 3))
            M("Validation", "pct_rmse", f_, round(s["prmse"], 1), "%")
            M("Validation", "geh_lt5_pct", f_, round(s["geh5"], 1), "%")
            fac_rows.append((f_, f'{s["links"]:,}', _ratio_pill(s["ratio"]),
                             f'{s["r2"]:.2f}' if not math.isnan(s["r2"]) else "—",
                             f'{s["prmse"]:.0f}', f'{s["geh5"]:.0f}'))
        fac_tbl = table(["Facility", "Links", "Model/Obs", "R²", "%RMSE", "GEH<5"],
                        fac_rows, num_cols=(1, 4, 5))
        # by county (top by counted links)
        cty_rows = []
        cc = cv.groupby("county").size().sort_values(ascending=False)
        for c in cc.index[:12]:
            g = cv[cv["county"] == c]
            s = valstats(g)
            M("Validation", "model_obs_ratio", f"county:{c}", round(s["ratio"], 3))
            cty_rows.append((c, f'{s["links"]:,}', _ratio_pill(s["ratio"]),
                             f'{s["r2"]:.2f}' if not math.isnan(s["r2"]) else "—",
                             f'{s["prmse"]:.0f}'))
        cty_tbl = table(["County", "Links", "Model/Obs", "R²", "%RMSE"],
                        cty_rows, num_cols=(1, 4))
        sc = scatter_obs_model(cv)
        sections.append(("Count validation",
            "The headline calibration: modelled vs observed daily volumes on "
            f"{ov['links']:,} counted links (low-count mainline/toll links below "
            f"{min_mainline:,} filtered, per the canonical summary). Ratio pills: "
            "green ≤10%, amber ≤20%, red beyond.",
            tl + '<div class="cols2"><div class="chart">' + sc +
            '<p class="fignote">Observed vs model daily volume (y=x reference).</p></div>'
            '<div><h3>By facility class</h3>' + fac_tbl +
            '<h3>By county (most-counted)</h3>' + cty_tbl + '</div></div>'))
    else:
        sections.append(("Count validation", "", '<p class="notrun">count_validation.csv not found.</p>'))

    # ---- tolling ----
    if toll:
        M("Tolling", "peak_el_toll", "all", round(toll["peak"], 2), "$")
        M("Tolling", "revenue_proxy", "all", round(toll["revenue"], 0), "$")
        M("Tolling", "el_daily_volume", "all", round(toll["el_vol"], 0), "veh")
        for h_, v in toll["profile"]:
            M("Tolling", "mean_el_toll", f"hour:{h_}", round(v, 3), "$")
        lp = line_profile(toll["profile"])
        tl = tiles([(f'${toll["peak"]:.2f}', "Peak EL toll"),
                    (f'${_fmt(toll["revenue"])}', "Toll revenue proxy (day)"),
                    (f'{_fmt(toll["el_vol"])} <small>veh</small>', "EL daily volume")])
        sections.append(("Tolling — express lanes",
            "Volume-weighted mean express-lane toll by hour (meso tier, all EL "
            "facilities statewide), the peak (LOS ceiling), and a first-order "
            "revenue proxy Σ(volume × toll).",
            tl + '<div class="chart">' + lp +
            '<p class="fignote">Mean EL toll by hour of day.</p></div>'))
    else:
        sections.append(("Tolling — express lanes", "",
                         '<p class="notrun">No EL toll_rate in the meso link performance.</p>'))

    # ---- convergence + multi-resolution ----
    conv_html = ""
    if conv:
        rg = conv.get("rel_gap")
        M("Convergence", "mean_rel_gap", "all", None if rg is None or math.isnan(rg) else round(rg, 4))
        M("Convergence", "vot_mean", "all", conv.get("vot_mean"))
        conv_html = tiles([
            (f'{rg*100:.1f}<small>%</small>' if rg is not None and not math.isnan(rg) else "—",
             "Mean relative gap (proxy)"),
            (f'{_fmt(conv.get("trips"))}', "Vehicle-trips loaded"),
            (f'${conv.get("vot_mean"):.0f}<small>/h</small>' if conv.get("vot_mean") else "—",
             "Mean value of time")])
    mr = tiles([(f'{tier_links.get("macro",0):,}', "Macro links (NodeLTM)"),
                (f'{tier_links.get("meso",0):,}', "Meso links (packets)"),
                (f'{tier_links.get("micro",0):,}', "Micro links (IDM/MOBIL)")])
    sections.append(("Convergence & multi-resolution",
        "An assignment-quality proxy (weighted mean of per-agent gap ÷ cost from "
        "the trip plans; the full relative-gap trajectory needs the run console "
        "log, wired in a later phase) and the split of the network across the "
        "three resolutions.",
        conv_html + '<h3>Resolution split</h3>' + mr))

    # ---- population synthesis (phase 3 placeholder) ----
    sections.append(("Population synthesis", "",
        '<p class="notrun">PopSyn marginals + synthesized totals land in phase 3 '
        '(reads the synthetic household / person files).</p>'))

    # ---- demand composition from the assembled trip list ----
    MKT_ORDER = ["SDT resident", "SDT visitor", "LDT resident", "LDT visitor",
                 "Truck", "External / OS"]
    MKT_COLOR = {"SDT resident": "--gp", "SDT visitor": "--el",
                 "LDT resident": "--macro", "LDT visitor": "--micro",
                 "Truck": "--meso", "External / OS": "--warn"}
    if tlist:
        tv, tp = tlist["total_veh"], tlist["total_per"]
        occ = tp / tv if tv else float("nan")
        D("TripList", "vehicle_trips", "all", round(tv, 0), "veh-trips")
        D("TripList", "person_trips", "all", round(tp, 0), "person-trips")
        D("TripList", "mean_occupancy", "all", round(occ, 2))
        bm, pm = tlist["by_market"], tlist["per_market"]
        order = [m for m in MKT_ORDER if m in bm] + [m for m in bm if m not in MKT_ORDER]
        mkt_rows = []
        for m in order:
            mv, mp = bm[m], pm.get(m, 0.0)
            D("TripList", "vehicle_trips", m, round(mv, 0), "veh-trips")
            mkt_rows.append((m, _fmt(mv), _fmt(mp),
                             f"{mp/mv:.2f}" if mv else "—",
                             f"{100*mv/tv:.1f}%" if tv else "—"))
        mkt_tbl = table(["Market", "Vehicle-trips", "Person-trips", "Occ", "Share"],
                        mkt_rows, num_cols=(1, 2, 3, 4))
        mbar = hbars([(m, bm[m], MKT_COLOR.get(m, "--muted")) for m in order])
        hours = [(h, tlist["by_hour"].get(str(h), 0.0)) for h in range(24)]
        for h_, hv in hours:
            D("TripList", "departures", f"hour:{h_}", round(hv, 0), "veh-trips")
        dep = line_profile(hours, unit="", ylab="Vehicle-trips",
                           w=560, h=200)
        # purpose bar (top 8)
        pur = sorted(tlist["by_purpose"].items(), key=lambda kv: -kv[1])[:8]
        pbar = hbars([(k, v, "--macro") for k, v in pur])
        tl_tiles = tiles([(f'{_fmt(tp)}', "Person-trips"),
                          (f'{_fmt(tv)}', "Vehicle-trips"),
                          (f'{occ:.2f}', "Mean occupancy"),
                          (f'{len(bm)}', "Demand markets")])
        sections.append(("Trip-list assembly & demand composition",
            "The assembled trip list handed to assignment: person-trips reduced "
            "to vehicle-trips by occupancy, split across the demand markets (the "
            "SDT/LDT × resident/visitor pool), with the loaded departure-time "
            "profile. This is the full demand pool; the assignment section above "
            "is what THIS run loaded onto the network.",
            tl_tiles + '<div class="cols2"><div class="chart">' + mbar +
            '<p class="fignote">Vehicle-trips by market.</p>' + dep +
            '<p class="fignote">Departure-time profile (vehicle-trips by hour).</p>'
            '</div><div>' + mkt_tbl + '<h3>Trips by purpose</h3>' + pbar + '</div></div>'))

        # SDT / LDT sub-sections from the market×purpose cross
        def _market_section(name, groups, note):
            mp_cross = tlist["by_market_purpose"]
            tot = sum(bm.get(g, 0.0) for g in groups)
            if tot <= 0:
                return (name, "", f'<p class="notrun">{note}</p>')
            # per-purpose totals across the groups
            pur_tot = {}
            for k, val in mp_cross.items():
                g, p = k.split("||", 1)
                if g in groups:
                    pur_tot[p] = pur_tot.get(p, 0.0) + val
            prows = [(p, _fmt(v), f"{100*v/tot:.1f}%")
                     for p, v in sorted(pur_tot.items(), key=lambda kv: -kv[1])[:10]]
            ptbl = table(["Purpose", "Vehicle-trips", "Share"], prows, num_cols=(1, 2))
            gtiles = tiles([(f'{_fmt(bm.get(g, 0.0))}', g) for g in groups if g in bm])
            for g in groups:
                D(name.split(" ")[0], "vehicle_trips", g, round(bm.get(g, 0.0), 0), "veh-trips")
            return (name,
                    f"Vehicle-trips in the {name.split(' (')[0].lower()} markets, "
                    "by trip purpose (from the assembled trip list). " + note,
                    gtiles + '<h3>By purpose</h3>' + ptbl)

        sections.append(_market_section(
            "Short-distance travel (SDT)", ["SDT resident", "SDT visitor"],
            "Trip-length distribution and mode split need the raw SDT trip file "
            "with its code maps — a later refinement."))
        sections.append(_market_section(
            "Long-distance travel (LDT)", ["LDT resident", "LDT visitor"],
            "Ground LDT only (air tours are not in the vehicle trip list); the "
            "DMA-to-DMA matrix is a later refinement."))
    else:
        for name in ("Trip-list assembly & demand composition",
                     "Short-distance travel (SDT)", "Long-distance travel (LDT)"):
            sections.append((name, "",
                '<p class="notrun">tripList_30min not found in the run or parent '
                'scenario directory — pass --demand-dir to point at it.</p>'))

    # ---- write metrics.csv ----
    mpath = os.path.join(out_dir, "scenario_metrics.csv")
    with open(mpath, "w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["stage", "section", "metric", "segment", "value", "unit"])
        wr.writerows(metrics)

    # ---- HTML ----
    body = []
    for i, (name, sub, content) in enumerate(sections, 1):
        body.append(f'<h2>{i} · {html.escape(name)}</h2>')
        if sub:
            body.append(f'<p class="sub">{html.escape(sub)}</p>')
        body.append(content)
    hdoc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head><body>'
            f'<button class="tog">◐ theme</button><div class="wrap">'
            f'<div class="eyebrow">HyDRA · Turnpike State Model (TSM v6) · Scenario Report</div>'
            f'<h1>{html.escape(title)}</h1>'
            f'<p class="sub">Assignment report card generated from the run\'s own '
            f'outputs. Demand-side sections are added in later phases.</p>{prov}'
            f'{"".join(body)}</div>{_THEME_JS}</body></html>')
    hpath = os.path.join(out_dir, "scenario_report.html")
    with open(hpath, "w", encoding="utf-8") as fh:
        fh.write(hdoc)

    # ---- markdown twin ----
    md = build_markdown(title, run_dir, n_links, counties, veh, when, net, cv,
                        toll, conv, tier_links, min_mainline, tlist)
    mdpath = os.path.join(out_dir, "scenario_report.md")
    with open(mdpath, "w", encoding="utf-8") as fh:
        fh.write(md)

    print(f"[report] {hpath}")
    print(f"[report] {mdpath}")
    print(f"[report] {mpath}  ({len(metrics)} metrics)")
    return hpath


def build_markdown(title, run_dir, n_links, counties, veh, when, net, cv,
                   toll, conv, tier_links, min_mainline, tl=None):
    L = [f"# {title}", "",
         f"*HyDRA · Turnpike State Model (TSM v6) · assignment report card*", "",
         f"- **Run:** `{os.path.basename(run_dir)}`",
         f"- **Network:** {n_links:,} directed links · {counties} counties",
         f"- **Vehicle-trips:** {_fmt(veh)}",
         f"- **Generated:** {when}", ""]
    if net is not None and not net.empty:
        vmt = net["vmt"].sum(); vht = net["vht"].sum()
        L += ["## Network totals", "",
              f"Daily **VMT {_fmt(vmt)}** veh-mi · **VHT {_fmt(vht)}** veh-h · "
              f"**mean speed {vmt/vht:.1f}** mph", "",
              "| Facility | VMT | VHT | Mean speed (mph) |",
              "|---|--:|--:|--:|"]
        net2 = net.assign(ord=net["fac"].map({f: i for i, f in enumerate(FAC_ORDER)}).fillna(9)).sort_values("ord")
        for _, r in net2.iterrows():
            L.append(f"| {r['fac']} | {_fmt(r['vmt'])} | {_fmt(r['vht'])} | {r['speed']:.1f} |")
        L.append("")
    if cv is not None and not cv.empty:
        ov = valstats(cv)
        L += ["## Count validation", "",
              f"Model/observed **{ov['ratio']:.2f}** · R² **{ov['r2']:.3f}** · "
              f"%RMSE **{ov['prmse']:.1f}** · GEH<5 **{ov['geh5']:.0f}%** · "
              f"GEH<10 **{ov['geh10']:.0f}%** ({ov['links']:,} counted links, "
              f"min-mainline {min_mainline:,})", "",
              "| Facility | Links | Model/Obs | R² | %RMSE | GEH<5 |",
              "|---|--:|--:|--:|--:|--:|"]
        for f_ in FAC_ORDER:
            g = cv[cv["fac"] == f_]
            if len(g) < 3:
                continue
            s = valstats(g)
            r2 = f"{s['r2']:.2f}" if not math.isnan(s["r2"]) else "—"
            L.append(f"| {f_} | {s['links']:,} | {s['ratio']:.2f} | {r2} | {s['prmse']:.0f} | {s['geh5']:.0f} |")
        L.append("")
    if toll:
        L += ["## Tolling", "",
              f"Peak EL toll **${toll['peak']:.2f}** · revenue proxy "
              f"**${_fmt(toll['revenue'])}**/day · EL volume **{_fmt(toll['el_vol'])}** veh", ""]
    if conv:
        rg = conv.get("rel_gap")
        rgs = f"{rg*100:.1f}%" if rg is not None and not math.isnan(rg) else "—"
        L += ["## Convergence & multi-resolution", "",
              f"Mean relative gap (proxy) **{rgs}** · "
              f"macro {tier_links.get('macro',0):,} / meso {tier_links.get('meso',0):,} / "
              f"micro {tier_links.get('micro',0):,} links", ""]
    if tl:
        tv, tp = tl["total_veh"], tl["total_per"]
        L += ["## Trip-list assembly & demand composition", "",
              f"Assembled demand pool: **{_fmt(tp)}** person-trips → "
              f"**{_fmt(tv)}** vehicle-trips (mean occupancy "
              f"**{tp/tv:.2f}**) across {len(tl['by_market'])} markets.", "",
              "| Market | Vehicle-trips | Person-trips | Occ | Share |",
              "|---|--:|--:|--:|--:|"]
        for m, mv in sorted(tl["by_market"].items(), key=lambda kv: -kv[1]):
            mp = tl["per_market"].get(m, 0.0)
            L.append(f"| {m} | {_fmt(mv)} | {_fmt(mp)} | "
                     f"{mp/mv:.2f} | {100*mv/tv:.1f}% |")
        L.append("")
    else:
        L += ["## Demand sections", "",
              "*tripList not found; PopSyn / Skims and detailed SDT/LDT land in "
              "later phases.*", ""]
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir")
    ap.add_argument("--title")
    ap.add_argument("--min-mainline", type=int, default=5000)
    ap.add_argument("--demand-dir", help="dir with tripList_30min / SDT / LDT "
                    "outputs (default: run dir, then its parent)")
    a = ap.parse_args()
    build(a.run_dir, a.out_dir, a.title, a.min_mainline, a.demand_dir)
