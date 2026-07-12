#!/usr/bin/env python3
"""Interchange volumes HTML dashboard (blueprint #3, phase 4).

Ties phases 1-3 into the "living" deliverable: ONE self-contained HTML page --
a clickable interchange map on the left, a drill-down on the right (mainline /
ramp / cross-street volume tables + turning-movement spider diagrams), a
Daily / AM / PM period selector, and a sortable system table of every
interchange. No server, no external assets, theme-aware.

Reuses interchange_volumes.aggregate/summarize (per-member daily/AM/PM volumes)
and interchange_turns.spider_svg (pre-rendered per terminal node).

  python interchange_dashboard.py --run-dir <dir> --interchanges interchanges.gpkg
      --nodes TSM_Node_ML.gpkg [--turns interchange_turns.csv]
      [--out interchange_dashboard.html] [--detail 80]
"""
import argparse
import csv
import html
import importlib.util
import json
import os


def _load(name, fname):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _ix_points(gpkg):
    from osgeo import ogr
    ds = ogr.Open(gpkg)
    pt = ds.GetLayerByName("interchanges")
    out = {}
    for f in pt:
        g = f.GetGeometryRef()
        out[f["ix_id"]] = (g.GetX(), g.GetY())
    ds = None
    return out


def build(run_dir, interchanges_gpkg, node_gpkg, turns_csv=None, out=None,
          detail=80, am_hour=8, pm_hour=17):
    iv = _load("iv_dash", "interchange_volumes.py")
    it = _load("it_dash", "interchange_turns.py")
    out = out or os.path.join(run_dir, "interchange_dashboard.html")

    mem, ixmeta = iv.aggregate(run_dir, interchanges_gpkg, am_hour, pm_hour)
    summary = iv.summarize(mem, ixmeta)
    pts = _ix_points(interchanges_gpkg)

    # turning movements (run if not supplied)
    turns_csv = turns_csv or os.path.join(run_dir, "interchange_turns.csv")
    tmoves = {}   # node -> list[{approach,move,vol}]
    node_ix = {}  # node -> interchange id
    if os.path.exists(turns_csv):
        for r in csv.DictReader(open(turns_csv, encoding="utf-8")):
            n = int(r["node"])
            tmoves.setdefault(n, []).append(
                {"approach": r["approach"], "move": r["movement"],
                 "vol": float(r["volume"])})
            if r["interchange_id"]:
                node_ix[n] = int(r["interchange_id"])
    ix_nodes = {}
    for n, i in node_ix.items():
        ix_nodes.setdefault(i, []).append(n)

    # detail set = interchanges with turns, unioned with the top-N by AADT
    have_turns = set(ix_nodes.keys())
    top = list(summary.sort_values("mainline_AADT", ascending=False)["ix_id"])
    detail_ids = list(dict.fromkeys(list(have_turns) + top))[:detail]
    detail_ids = set(detail_ids)

    # ---- assemble payload ----
    bbox = [min(p[0] for p in pts.values()), min(p[1] for p in pts.values()),
            max(p[0] for p in pts.values()), max(p[1] for p in pts.values())]
    IX = []
    for _, r in summary.iterrows():
        i = int(r["ix_id"])
        if i not in pts:
            continue
        IX.append({"id": i, "x": round(pts[i][0], 1), "y": round(pts[i][1], 1),
                   "rt": r["route"], "cs": r["cross_street"], "co": r["county"],
                   "aadt": int(r["mainline_AADT"]), "sp": float(r["mainline_speed"]),
                   "rmp": int(r["ramp_vol"]), "on": int(r["n_on"]),
                   "off": int(r["n_off"]), "sys": int(r["n_sys"]),
                   "xv": int(r["cross_vol"]),
                   "mo": (float(r["model_obs"]) if r["model_obs"] != "" else None),
                   "d": 1 if i in detail_ids else 0})
    DETAIL = {}
    ROLE_ORDER = {"mainline": 0, "on_ramp": 1, "off_ramp": 2, "system_ramp": 3,
                  "cross_street": 4}
    for i in detail_ids:
        g = mem[mem["ix"] == i]
        rows = []
        for _, m in g.sort_values("role", key=lambda s: s.map(ROLE_ORDER)).iterrows():
            rows.append([m["role"], m["direction"], round(m["daily"]),
                         round(m["am"]), round(m["pm"]), round(m["speed"], 1),
                         round(m["toll"], 2), round(m["count"]),
                         (m["label"] or "")[:26]])
        spiders = []
        for n in sorted(ix_nodes.get(i, [])):
            svg = it.spider_svg(tmoves.get(n, []), title=f"Node {n}", w=250)
            spiders.append(svg)
        DETAIL[str(i)] = {"m": rows, "sp": spiders}

    payload = {"bbox": bbox, "ix": IX, "detail": DETAIL}
    hdoc = _TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":"))
                             ).replace("__N__", str(len(IX))
                             ).replace("__ND__", str(len(DETAIL)))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(hdoc)
    print(f"[dashboard] {len(IX)} interchanges, {len(DETAIL)} detailed "
          f"({sum(len(d['sp']) for d in DETAIL.values())} spiders) -> {out}")
    return out


_TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Interchange Volumes — HyDRA</title>
<style>
:root{--surface:#fcfcfb;--page:#f4f4f1;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8880;
 --grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.12);--accent:#2a78d6;
 --gp:#2a78d6;--el:#1baf7a;--meso:#c98500;--bad:#e34948;--good:#1baf7a;--warn:#c98500;
 --sel:#2a78d6}
@media(prefers-color-scheme:dark){:root{--surface:#191918;--page:#0e0e0d;--ink:#fff;
 --ink2:#c3c2b7;--muted:#8a8880;--grid:#2c2c2a;--axis:#3a3a37;--ring:rgba(255,255,255,.12);
 --accent:#3987e5;--gp:#3987e5;--el:#199e70;--meso:#eda100;--bad:#e66767;--good:#199e70;
 --warn:#eda100;--sel:#5aa0ff}}
:root[data-theme="light"]{--surface:#fcfcfb;--page:#f4f4f1;--ink:#0b0b0b;--ink2:#52514e;
 --muted:#8a8880;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.12);--accent:#2a78d6;
 --gp:#2a78d6;--el:#1baf7a;--meso:#c98500;--bad:#e34948;--good:#1baf7a;--warn:#c98500;--sel:#2a78d6}
:root[data-theme="dark"]{--surface:#191918;--page:#0e0e0d;--ink:#fff;--ink2:#c3c2b7;
 --muted:#8a8880;--grid:#2c2c2a;--axis:#3a3a37;--ring:rgba(255,255,255,.12);--accent:#3987e5;
 --gp:#3987e5;--el:#199e70;--meso:#eda100;--bad:#e66767;--good:#199e70;--warn:#eda100;--sel:#5aa0ff}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:var(--page);color:var(--ink);
 font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:16px;padding:10px 18px;border-bottom:1px solid var(--ring);
 background:var(--surface);flex:none}
header h1{font-size:16px;margin:0;font-weight:650}
header .sp{flex:1}
.seg{display:inline-flex;border:1px solid var(--ring);border-radius:8px;overflow:hidden}
.seg button{border:none;background:var(--surface);color:var(--ink2);padding:5px 12px;font:inherit;
 font-size:12px;cursor:pointer}
.seg button.on{background:var(--accent);color:#fff}
input#q{border:1px solid var(--ring);border-radius:8px;padding:5px 10px;background:var(--page);
 color:var(--ink);font:inherit;font-size:12px;width:180px}
.tog{border:1px solid var(--ring);border-radius:8px;background:var(--surface);color:var(--muted);
 padding:5px 10px;font-size:12px;cursor:pointer}
main{flex:1;display:grid;grid-template-columns:1.15fr .85fr;min-height:0}
#mapwrap{position:relative;border-right:1px solid var(--ring);min-height:0}
canvas{position:absolute;inset:0;width:100%;height:100%;cursor:grab}
canvas.drag{cursor:grabbing}
#legend{position:absolute;left:12px;bottom:12px;background:var(--surface);border:1px solid var(--ring);
 border-radius:8px;padding:8px 10px;font-size:11px;color:var(--ink2)}
#legend .row{display:flex;align-items:center;gap:6px;margin:2px 0}
.dot{width:10px;height:10px;border-radius:50%}
#side{overflow:auto;padding:14px 16px;min-height:0}
.hint{color:var(--muted);font-style:italic;margin-top:30px;text-align:center}
h2{font-size:16px;margin:0 0 2px;text-wrap:balance}
.meta{color:var(--ink2);font-size:12.5px;margin-bottom:10px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:8px;margin:10px 0}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:8px 10px}
.tile .v{font-size:17px;font-weight:700;font-variant-numeric:tabular-nums}
.tile .k{font-size:10.5px;color:var(--muted);margin-top:1px}
h3{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:16px 0 4px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);
 font-weight:600;padding:5px 8px 5px 0;border-bottom:1px solid var(--axis);cursor:pointer;white-space:nowrap}
td{padding:5px 8px 5px 0;border-bottom:1px solid var(--grid)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.pill{padding:1px 7px;border-radius:999px;font-size:11px;font-weight:700}
.spiders{display:flex;flex-wrap:wrap;gap:10px;margin-top:6px}
.spiders .sp{background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:4px}
#systable{flex:none;max-height:34vh;overflow:auto;border-top:1px solid var(--ring);background:var(--surface)}
#systable table{font-size:12px}
#systable th{position:sticky;top:0;background:var(--surface);z-index:1;padding:7px 10px}
#systable td{padding:5px 10px}
#systable tr{cursor:pointer}
#systable tr:hover td{background:color-mix(in srgb,var(--accent) 9%,transparent)}
#systable tr.sel td{background:color-mix(in srgb,var(--accent) 18%,transparent)}
.rolechip{font-size:10px;padding:1px 6px;border-radius:4px;font-weight:600}
</style></head><body>
<header>
  <h1>Interchange Volumes <span style="font-weight:400;color:var(--muted)">· TSM v6 / HyDRA</span></h1>
  <span style="font-size:12px;color:var(--muted)">__N__ interchanges · __ND__ detailed</span>
  <span class="sp"></span>
  <input id="q" placeholder="filter route / cross-street / county">
  <div class="seg" id="period">
    <button data-p="daily" class="on">Daily</button>
    <button data-p="am">AM</button><button data-p="pm">PM</button></div>
  <button class="tog" id="tog">◐</button>
</header>
<main>
  <div id="mapwrap">
    <canvas id="c"></canvas>
    <div id="legend">
      <div style="font-weight:600;color:var(--ink);margin-bottom:3px">Mainline AADT</div>
      <div class="row"><span class="dot" style="background:var(--gp);width:6px;height:6px"></span>lower</div>
      <div class="row"><span class="dot" style="background:var(--gp);width:14px;height:14px"></span>higher</div>
      <div class="row" style="margin-top:5px"><span class="dot" style="background:var(--bad)"></span>model/obs off &gt;20%</div>
    </div>
  </div>
  <div id="side"><div class="hint">Click an interchange on the map or in the table below.</div></div>
</main>
<div id="systable"></div>
<script>
const D=__DATA__;
let period="daily", sel=null, filt="";
const $=s=>document.querySelector(s);
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const kf=v=>v==null?"—":(Math.abs(v)>=1e6?(v/1e6).toFixed(2)+"M":Math.abs(v)>=1e3?(v/1e3).toFixed(1)+"k":(""+Math.round(v)));

// ---------- map ----------
const cv=$("#c"),ctx=cv.getContext("2d");
const bb=D.bbox,cx=(bb[0]+bb[2])/2,cy=(bb[1]+bb[3])/2;
let zoom=1,panx=0,pany=0,base=1,dpr=Math.min(devicePixelRatio||1,2);
function resize(){const w=cv.parentNode.clientWidth,h=cv.parentNode.clientHeight;
 cv.width=w*dpr;cv.height=h*dpr;base=0.92*Math.min(cv.width/((bb[2]-bb[0])||1),cv.height/((bb[3]-bb[1])||1));draw();}
function S(x,y){const s=base*zoom;return[(x-cx)*s+cv.width/2+panx,-(y-cy)*s+cv.height/2+pany];}
function Sinv(px,py){const s=base*zoom;return[(px-cv.width/2-panx)/s+cx,-(py-cv.height/2-pany)/s+cy];}
const amax=Math.max(...D.ix.map(d=>d.aadt))||1;
function rad(d){return 2.5+9*Math.sqrt(d.aadt/amax);}
function vis(d){return !filt||((d.rt+" "+d.cs+" "+d.co).toLowerCase().includes(filt));}
function draw(){ctx.clearRect(0,0,cv.width,cv.height);
 for(const d of D.ix){if(!vis(d))continue;const[x,y]=S(d.x,d.y);
  if(x<-20||x>cv.width+20||y<-20||y>cv.height+20)continue;
  const off=d.mo!=null&&Math.abs(d.mo-1)>0.2;
  ctx.beginPath();ctx.arc(x,y,rad(d)*dpr,0,7);
  ctx.fillStyle=off?css("--bad"):css("--gp");ctx.globalAlpha=d===selObj()?1:.72;ctx.fill();
  if(d===selObj()){ctx.globalAlpha=1;ctx.lineWidth=2.5*dpr;ctx.strokeStyle=css("--sel");ctx.stroke();}
 }ctx.globalAlpha=1;}
function selObj(){return D.ix.find(d=>d.id===sel);}
let drag=false,lx,ly,moved=false;
cv.addEventListener("pointerdown",e=>{drag=true;moved=false;lx=e.offsetX*dpr;ly=e.offsetY*dpr;cv.setPointerCapture(e.pointerId);cv.classList.add("drag");});
cv.addEventListener("pointerup",e=>{drag=false;cv.classList.remove("drag");
 if(!moved){const px=e.offsetX*dpr,py=e.offsetY*dpr;let best=null,bd=1e9;
  for(const d of D.ix){if(!vis(d))continue;const[x,y]=S(d.x,d.y);const dd=(x-px)**2+(y-py)**2;
   if(dd<bd&&dd<(rad(d)*dpr+6*dpr)**2){bd=dd;best=d;}}
  if(best)select(best.id);}});
cv.addEventListener("pointermove",e=>{const px=e.offsetX*dpr,py=e.offsetY*dpr;
 if(drag){panx+=px-lx;pany+=py-ly;lx=px;ly=py;moved=true;draw();}});
cv.addEventListener("wheel",e=>{e.preventDefault();const px=e.offsetX*dpr,py=e.offsetY*dpr,b4=Sinv(px,py);
 zoom*=Math.exp(-e.deltaY*0.0013);zoom=Math.max(.3,Math.min(80,zoom));
 const af=Sinv(px,py),s=base*zoom;panx+=(af[0]-b4[0])*s;pany-=(af[1]-b4[1])*s;draw();},{passive:false});

// ---------- drill-down ----------
const ROLE={mainline:["Mainline","--gp"],on_ramp:["On-ramp","--el"],off_ramp:["Off-ramp","--meso"],
 system_ramp:["System ramp","--accent"],cross_street:["Cross-street","--muted"]};
const PIDX={daily:2,am:3,pm:4};
function volOf(row){return row[PIDX[period]];}
function moPill(mo){if(mo==null)return"—";const d=Math.abs(mo-1);
 const c=d<=.1?"--good":d<=.2?"--warn":"--bad";
 return `<span class="pill" style="background:color-mix(in srgb,var(${c}) 20%,transparent);color:var(${c})">${mo.toFixed(2)}</span>`;}
function select(id){sel=id;
 document.querySelectorAll("#systable tr").forEach(t=>t.classList.toggle("sel",+t.dataset.id===id));
 const d=D.ix.find(x=>x.id===id);const det=D.detail[id];
 let h=`<h2>${esc(d.rt)} @ ${esc(d.cs)}</h2><div class="meta">${esc(d.co)} County · interchange #${id}</div>`;
 h+=`<div class="tiles">
  <div class="tile"><div class="v">${kf(d.aadt)}</div><div class="k">Mainline AADT (2-way)</div></div>
  <div class="tile"><div class="v">${d.sp.toFixed(0)}<small> mph</small></div><div class="k">Mainline speed</div></div>
  <div class="tile"><div class="v">${kf(d.rmp)}</div><div class="k">Ramp volume</div></div>
  <div class="tile"><div class="v">${d.on}/${d.off}/${d.sys}</div><div class="k">On/Off/System ramps</div></div>
  <div class="tile"><div class="v">${moPill(d.mo)}</div><div class="k">Model / count</div></div></div>`;
 if(!det){h+=`<p class="hint" style="margin-top:14px">Detailed breakdown not computed for this interchange (outside the detail set).</p>`;$("#side").innerHTML=h;return;}
 // grouped member tables
 const groups=[["mainline"],["on_ramp","off_ramp","system_ramp"],["cross_street"]];
 const gt=["Mainline","Ramps","Cross-streets"];
 groups.forEach((roles,gi)=>{const rows=det.m.filter(r=>roles.includes(r[0]));
  if(!rows.length)return;
  h+=`<h3>${gt[gi]}</h3><table><thead><tr><th>Role</th><th>Dir</th><th class="num">${period.toUpperCase()} vol</th><th class="num">Speed</th><th class="num">Toll</th><th class="num">Count</th><th>Label</th></tr></thead><tbody>`;
  rows.sort((a,b)=>volOf(b)-volOf(a));
  for(const r of rows){const[role,dir,,,,speed,toll,count,label]=r;const rc=ROLE[role]||["",""];
   h+=`<tr><td><span class="rolechip" style="background:color-mix(in srgb,var(${rc[1]}) 16%,transparent);color:var(${rc[1]})">${rc[0]}</span></td>
   <td>${dir||""}</td><td class="num">${kf(volOf(r))}</td><td class="num">${speed?speed.toFixed(0):"—"}</td>
   <td class="num">${toll?("$"+toll.toFixed(2)):"—"}</td><td class="num">${count?kf(count):"—"}</td><td>${esc(label||"")}</td></tr>`;}
  h+=`</tbody></table>`;});
 if(det.sp&&det.sp.length){h+=`<h3>Turning movements <span style="font-weight:400;text-transform:none;letter-spacing:0">(daily · <span style="color:var(--gp)">left</span> / <span style="color:var(--muted)">thru</span> / <span style="color:var(--el)">right</span>)</span></h3><div class="spiders">`;
  for(const s of det.sp)h+=`<div class="sp">${s}</div>`;h+=`</div>`;}
 $("#side").innerHTML=h;draw();}

// ---------- system table ----------
let sortKey="aadt",sortDir=-1;
const COLS=[["rt","Route",0],["cs","Cross-street",0],["co","County",0],["aadt","AADT",1],
 ["rmp","Ramp vol",1],["on","On",1],["off","Off",1],["xv","Cross vol",1],["mo","Mdl/Obs",1]];
function systable(){const rows=D.ix.filter(vis).slice().sort((a,b)=>{
  let x=a[sortKey],y=b[sortKey];if(x==null)x=-1;if(y==null)y=-1;return (x>y?1:x<y?-1:0)*sortDir;});
 let h=`<table><thead><tr>`;
 for(const[k,lab,num]of COLS)h+=`<th class="${num?'num':''}" data-k="${k}">${lab}${sortKey===k?(sortDir<0?" ▾":" ▴"):""}</th>`;
 h+=`</tr></thead><tbody>`;
 for(const d of rows.slice(0,400))h+=`<tr data-id="${d.id}" class="${d.id===sel?'sel':''}">
  <td>${esc(d.rt)}</td><td>${esc(d.cs)}</td><td>${esc(d.co)}</td><td class="num">${kf(d.aadt)}</td>
  <td class="num">${kf(d.rmp)}</td><td class="num">${d.on}</td><td class="num">${d.off}</td>
  <td class="num">${kf(d.xv)}</td><td class="num">${d.mo==null?"—":d.mo.toFixed(2)}</td></tr>`;
 h+=`</tbody></table>`;$("#systable").innerHTML=h;
 $("#systable").querySelectorAll("th").forEach(th=>th.onclick=()=>{
  const k=th.dataset.k;if(k===sortKey)sortDir*=-1;else{sortKey=k;sortDir=(k==="rt"||k==="cs"||k==="co")?1:-1;}systable();});
 $("#systable").querySelectorAll("tr[data-id]").forEach(tr=>tr.onclick=()=>select(+tr.dataset.id));}
function esc(s){return(""+(s==null?"":s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}

// ---------- controls ----------
$("#period").querySelectorAll("button").forEach(b=>b.onclick=()=>{
 $("#period").querySelectorAll("button").forEach(x=>x.classList.remove("on"));
 b.classList.add("on");period=b.dataset.p;if(sel)select(sel);});
$("#q").oninput=e=>{filt=e.target.value.toLowerCase().trim();draw();systable();};
$("#tog").onclick=()=>{const r=document.documentElement;
 const c=r.getAttribute("data-theme")||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");
 r.setAttribute("data-theme",c==="dark"?"light":"dark");draw();};
addEventListener("resize",resize);
systable();resize();
</script></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--interchanges", required=True)
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--turns")
    ap.add_argument("--out")
    ap.add_argument("--detail", type=int, default=80)
    a = ap.parse_args()
    build(a.run_dir, a.interchanges, a.nodes, a.turns, a.out, a.detail)
