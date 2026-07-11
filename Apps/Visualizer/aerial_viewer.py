#!/usr/bin/env python3
"""Self-contained animated aerial lane viewer (blueprint phase 5).

Reads micro_lanes_aerial.gpkg (the phase 1-4 output: lane_ribbons + gores +
lane_markings) and writes ONE self-contained HTML file: a dependency-free
Canvas renderer that draws the true-width lane pavement, colored by per-lane
speed (level-of-service), with a time scrubber that animates across the built
periods, pan/zoom, hover tooltips, and a LOS legend.

Why not deck.gl / MapLibre: the artifact/self-contained constraint blocks
external CDNs and basemap tile servers, so the viewer inlines everything and
draws its own Canvas -- no library, no network, works as a local file and as a
shareable artifact. Vehicle-dot playback (deck.gl TripsLayer equivalent) can be
layered on later from the micro trajectories; this delivers the animated
lane-congestion view.

  python aerial_viewer.py --gpkg micro_lanes_aerial.gpkg [--out viewer.html]
                          [--title "I-95 Express — Broward"]
Coordinates stay in the gpkg CRS (FL Albers meters); the viewer fits the bbox
to the canvas and does its own pan/zoom, so no reprojection is needed.
"""
import argparse
import json
import os

from osgeo import ogr

ogr.UseExceptions()


def _poly_pts(feat):
    g = feat.GetGeometryRef()
    if g is None:
        return None
    if g.GetGeometryType() in (ogr.wkbMultiPolygon, ogr.wkbMultiPolygon25D):
        g = g.GetGeometryRef(0)
    ring = g.GetGeometryRef(0)
    if ring is None:
        return None
    return [[round(ring.GetX(i), 2), round(ring.GetY(i), 2)]
            for i in range(ring.GetPointCount())]


def _line_pts(feat):
    g = feat.GetGeometryRef()
    if g is None:
        return None
    return [[round(g.GetX(i), 2), round(g.GetY(i), 2)]
            for i in range(g.GetPointCount())]


def collect(gpkg):
    ds = ogr.Open(gpkg)
    if ds is None:
        raise SystemExit(f"cannot open {gpkg}")
    rib = ds.GetLayerByName("lane_ribbons")
    defn = rib.GetLayerDefn()
    sufs = sorted({defn.GetFieldDefn(i).GetName()[6:]
                   for i in range(defn.GetFieldCount())
                   if defn.GetFieldDefn(i).GetName().startswith("speed_")})
    ribbons, minx = [], [1e18, 1e18, -1e18, -1e18]  # xmin,ymin,xmax,ymax

    def grow(pts):
        for x, y in pts:
            minx[0] = min(minx[0], x); minx[1] = min(minx[1], y)
            minx[2] = max(minx[2], x); minx[3] = max(minx[3], y)

    for f in rib:
        pts = _poly_pts(f)
        if not pts:
            continue
        grow(pts)
        sp = [f.GetField(f"speed_{s}") for s in sufs]
        fl = [f.GetField(f"flow_{s}") for s in sufs]
        ribbons.append({"t": f.GetField("lane_type"), "l": f.GetField("lane"),
                        "p": pts,
                        "s": [round(v, 1) if v is not None else None for v in sp],
                        "f": [round(v) if v is not None else None for v in fl]})
    gores = []
    gl = ds.GetLayerByName("gores")
    if gl:
        for f in gl:
            pts = _poly_pts(f)
            if pts:
                grow(pts); gores.append({"k": f.GetField("kind"), "p": pts})
    marks = []
    ml = ds.GetLayerByName("lane_markings")
    if ml:
        for f in ml:
            pts = _line_pts(f)
            if pts and len(pts) >= 2:
                marks.append({"k": f.GetField("kind"), "p": pts})
    ds = None
    return {"periods": sufs, "bbox": minx, "ribbons": ribbons,
            "gores": gores, "marks": marks}


def build(gpkg, out=None, title=None):
    data = collect(gpkg)
    if out is None:
        out = os.path.splitext(gpkg)[0] + "_viewer.html"
    title = title or "Micro Lane Aerial — HyDRA"
    payload = json.dumps(data, separators=(",", ":"))
    html = _TEMPLATE.replace("__TITLE__", _esc(title)).replace(
        "__DATA__", payload).replace(
        "__NRIB__", str(len(data["ribbons"]))).replace(
        "__NPER__", str(len(data["periods"])))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[viewer] {len(data['ribbons'])} ribbons, {len(data['gores'])} gores, "
          f"{len(data['periods'])} periods -> {out}")
    return out


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{
    --ground:#0e1217; --ground2:#131922; --ink:#e9eef4; --muted:#8b98a8;
    --line:#26303c; --card:#161d27cc; --accent:#3ec9c0; --accent-ink:#08110f;
    --edge:#c8a000; --buffer:#e34948; --dash:#f2f5f9;
  }
  :root[data-theme="light"]{
    --ground:#dfe5ec; --ground2:#eef2f6; --ink:#182029; --muted:#5a6675;
    --line:#c3ccd6; --card:#ffffffdd; --accent:#0f8a83; --accent-ink:#ffffff;
    --dash:#2a3340;
  }
  @media (prefers-color-scheme: light){
    :root{
      --ground:#dfe5ec; --ground2:#eef2f6; --ink:#182029; --muted:#5a6675;
      --line:#c3ccd6; --card:#ffffffdd; --accent:#0f8a83; --accent-ink:#ffffff;
      --dash:#2a3340;
    }
    :root[data-theme="dark"]{
      --ground:#0e1217; --ground2:#131922; --ink:#e9eef4; --muted:#8b98a8;
      --line:#26303c; --card:#161d27cc; --accent:#3ec9c0; --accent-ink:#08110f;
      --dash:#f2f5f9;
    }
  }
  *{box-sizing:border-box}
  html,body{height:100%;margin:0}
  body{
    background:var(--ground);color:var(--ink);overflow:hidden;
    font:14px/1.45 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  canvas{position:fixed;inset:0;display:block;cursor:grab;touch-action:none}
  canvas.drag{cursor:grabbing}
  .panel{
    position:fixed;background:var(--card);border:1px solid var(--line);
    border-radius:12px;backdrop-filter:blur(8px);
    box-shadow:0 8px 30px #0006;
  }
  #head{top:16px;left:16px;padding:14px 16px;max-width:min(70vw,420px)}
  #head h1{margin:0 0 3px;font-size:16px;font-weight:650;letter-spacing:.2px;
    text-wrap:balance}
  #head .sub{color:var(--muted);font-size:12px;
    font-variant-numeric:tabular-nums}
  #legend{top:16px;right:16px;padding:12px 14px;min-width:170px}
  #legend .lt{font-size:11px;text-transform:uppercase;letter-spacing:.7px;
    color:var(--muted);margin-bottom:8px}
  .row{display:flex;align-items:center;gap:8px;margin:3px 0;font-size:12px;
    font-variant-numeric:tabular-nums}
  .sw{width:22px;height:11px;border-radius:3px;flex:none;border:1px solid #0003}
  .swl{width:22px;height:0;border-top-width:2px;border-top-style:solid;flex:none}
  #scrub{left:50%;bottom:20px;transform:translateX(-50%);
    display:flex;align-items:center;gap:14px;padding:12px 16px;
    width:min(78vw,760px)}
  #play{width:38px;height:38px;border-radius:50%;flex:none;border:none;
    background:var(--accent);color:var(--accent-ink);font-size:15px;cursor:pointer;
    display:grid;place-items:center;transition:transform .08s}
  #play:active{transform:scale(.93)}
  #clock{font-size:20px;font-weight:650;font-variant-numeric:tabular-nums;
    min-width:74px;text-align:center}
  #clock small{display:block;font-size:10px;font-weight:500;color:var(--muted);
    text-transform:uppercase;letter-spacing:1px}
  #slider{flex:1;appearance:none;height:6px;border-radius:3px;background:var(--line);
    outline:none;cursor:pointer}
  #slider::-webkit-slider-thumb{appearance:none;width:16px;height:16px;
    border-radius:50%;background:var(--accent);border:2px solid var(--ground);
    box-shadow:0 1px 4px #0007}
  #slider::-moz-range-thumb{width:16px;height:16px;border-radius:50%;
    background:var(--accent);border:2px solid var(--ground)}
  #tt{position:fixed;pointer-events:none;opacity:0;transition:opacity .1s;
    background:var(--card);border:1px solid var(--line);border-radius:9px;
    padding:8px 11px;font-size:12px;font-variant-numeric:tabular-nums;
    box-shadow:0 6px 20px #0007;z-index:9;max-width:220px}
  #tt b{color:var(--accent)}
  #tt .big{font-size:16px;font-weight:650}
  .tog{position:fixed;top:16px;right:200px;background:var(--card);
    border:1px solid var(--line);border-radius:8px;color:var(--muted);
    padding:6px 10px;font-size:12px;cursor:pointer}
  #hint{position:fixed;left:16px;bottom:20px;color:var(--muted);font-size:11px;
    background:var(--card);border:1px solid var(--line);border-radius:8px;
    padding:7px 10px}
  @media (max-width:640px){#legend,#hint,.tog{display:none}
    #head{max-width:80vw}#scrub{width:92vw}}
</style>
</head>
<body>
<canvas id="c"></canvas>
<div class="panel" id="head">
  <h1>__TITLE__</h1>
  <div class="sub">__NRIB__ lane ribbons · __NPER__ periods · per-lane speed (level of service)</div>
</div>
<button class="tog" id="tog">◐ theme</button>
<div class="panel" id="legend">
  <div class="lt">Level of service (mph)</div>
  <div id="losrows"></div>
  <div class="lt" style="margin-top:10px">Features</div>
  <div class="row"><span class="sw" style="background:#9aa0a6"></span>Ramp</div>
  <div class="row"><span class="sw" style="background:#f2e6c2"></span>Gore nose</div>
  <div class="row"><span class="swl" style="border-top-color:var(--buffer)"></span>EL buffer</div>
</div>
<div class="panel" id="scrub">
  <button id="play" aria-label="Play">▶</button>
  <div id="clock">--:--<small>time of day</small></div>
  <input type="range" id="slider" min="0" value="0" step="1">
</div>
<div id="tt"></div>
<div id="hint">drag to pan · scroll to zoom · hover a lane</div>
<script>
const DATA=__DATA__;
const cv=document.getElementById("c"), ctx=cv.getContext("2d");
const LOS=[[0,10,"#a50026"],[10,20,"#d73027"],[20,30,"#f46d43"],[30,40,"#fdae61"],
           [40,50,"#a6d96a"],[50,60,"#66bd63"],[60,999,"#1a9850"]];
function losColor(v){ if(v==null) return null;
  for(const[a,b,c] of LOS) if(v>=a&&v<b) return c; return "#1a9850"; }
// legend rows
document.getElementById("losrows").innerHTML=LOS.map(([a,b,c])=>
  `<div class="row"><span class="sw" style="background:${c}"></span>${b>=999?a+"+":a+"–"+b}</div>`).join("");

const bb=DATA.bbox, cx=(bb[0]+bb[2])/2, cy=(bb[1]+bb[3])/2;
let zoom=1, panx=0, pany=0, base=1, dpr=Math.min(devicePixelRatio||1,2);
function resize(){ cv.width=innerWidth*dpr; cv.height=innerHeight*dpr;
  cv.style.width=innerWidth+"px"; cv.style.height=innerHeight+"px";
  base=0.92*Math.min(cv.width/((bb[2]-bb[0])||1), cv.height/((bb[3]-bb[1])||1));
  draw(); }
function S(x,y){ const s=base*zoom;
  return [ (x-cx)*s + cv.width/2 + panx, -(y-cy)*s + cv.height/2 + pany ]; }
function Sinv(px,py){ const s=base*zoom;
  return [ (px-cv.width/2-panx)/s + cx, -(py-cv.height/2-pany)/s + cy ]; }

let ti=0;  // period index
function path(p){ ctx.beginPath();
  for(let i=0;i<p.length;i++){ const[x,y]=S(p[i][0],p[i][1]);
    i?ctx.lineTo(x,y):ctx.moveTo(x,y);} ctx.closePath(); }
function pathL(p){ ctx.beginPath();
  for(let i=0;i<p.length;i++){ const[x,y]=S(p[i][0],p[i][1]);
    i?ctx.lineTo(x,y):ctx.moveTo(x,y);} }
const css=k=>getComputedStyle(document.documentElement).getPropertyValue(k).trim();
function draw(){
  ctx.clearRect(0,0,cv.width,cv.height);
  ctx.fillStyle=css("--ground2");
  // gores
  for(const g of DATA.gores){ path(g.p); ctx.fillStyle="#f2e6c2"; ctx.globalAlpha=.85;
    ctx.fill(); } ctx.globalAlpha=1;
  // ribbons
  for(const r of DATA.ribbons){
    let col;
    if(r.t==="RAMP") col="#9aa0a6";
    else { col=losColor(r.s[ti]); if(!col) col=r.t==="EL"?"#3a4658":"#333d49"; }
    path(r.p); ctx.fillStyle=col; ctx.fill();
    ctx.lineWidth=Math.max(.4,base*zoom*0.15); ctx.strokeStyle=css("--ground");
    ctx.globalAlpha=.55; ctx.stroke(); ctx.globalAlpha=1;
  }
  // markings
  for(const m of DATA.marks){
    pathL(m.p);
    if(m.k==="buffer"){ ctx.strokeStyle=css("--buffer"); ctx.lineWidth=Math.max(1,base*zoom*.4);
      ctx.setLineDash([]); }
    else if(m.k==="edge"){ ctx.strokeStyle=css("--edge"); ctx.lineWidth=Math.max(.6,base*zoom*.2);
      ctx.setLineDash([]); }
    else { ctx.strokeStyle=css("--dash"); ctx.lineWidth=Math.max(.5,base*zoom*.18);
      ctx.setLineDash([base*zoom*2, base*zoom*2]); }
    ctx.globalAlpha=.9; ctx.stroke(); ctx.globalAlpha=1;
  }
  ctx.setLineDash([]);
}

// ---- time ----
const per=DATA.periods, slider=document.getElementById("slider"),
      clock=document.getElementById("clock");
slider.max=Math.max(0,per.length-1);
function hhmm(s){ return s.length>=4? s.slice(0,2)+":"+s.slice(2,4) : s; }
function setT(i){ ti=Math.max(0,Math.min(per.length-1,i|0)); slider.value=ti;
  clock.innerHTML=hhmm(per[ti])+"<small>time of day</small>"; draw(); }
slider.oninput=e=>setT(+e.target.value);
let playing=false, acc=0, last=0;
const playBtn=document.getElementById("play");
function loop(ts){ if(!playing) return;
  if(!last) last=ts; acc+=ts-last; last=ts;
  if(acc>700){ acc=0; setT(ti+1>=per.length?0:ti+1); }
  requestAnimationFrame(loop); }
playBtn.onclick=()=>{ playing=!playing; playBtn.textContent=playing?"❚❚":"▶";
  last=0; if(playing) requestAnimationFrame(loop); };

// ---- pan / zoom ----
let dragging=false, lx=0, ly=0;
cv.addEventListener("pointerdown",e=>{ dragging=true; lx=e.clientX*dpr; ly=e.clientY*dpr;
  cv.classList.add("drag"); cv.setPointerCapture(e.pointerId); });
cv.addEventListener("pointerup",e=>{ dragging=false; cv.classList.remove("drag"); });
cv.addEventListener("pointermove",e=>{
  const px=e.clientX*dpr, py=e.clientY*dpr;
  if(dragging){ panx+=px-lx; pany+=py-ly; lx=px; ly=py; draw(); return; }
  hover(px,py,e.clientX,e.clientY);
});
cv.addEventListener("wheel",e=>{ e.preventDefault();
  const px=e.clientX*dpr, py=e.clientY*dpr, before=Sinv(px,py);
  zoom*=Math.exp(-e.deltaY*0.0013); zoom=Math.max(.2,Math.min(60,zoom));
  const after=Sinv(px,py), s=base*zoom;
  panx+=(after[0]-before[0])*s; pany-=(after[1]-before[1])*s; draw();
},{passive:false});

// ---- hover hit-test ----
const tt=document.getElementById("tt");
function inPoly(p, x, y){ let c=false;
  for(let i=0,j=p.length-1;i<p.length;j=i++){
    const xi=p[i][0],yi=p[i][1],xj=p[j][0],yj=p[j][1];
    if(((yi>y)!==(yj>y)) && (x < (xj-xi)*(y-yi)/(yj-yi)+xi)) c=!c; }
  return c; }
function hover(px,py,cxs,cys){
  const w=Sinv(px,py);
  let hit=null;
  for(let i=DATA.ribbons.length-1;i>=0;i--){ if(inPoly(DATA.ribbons[i].p,w[0],w[1])){ hit=DATA.ribbons[i]; break; } }
  if(!hit){ tt.style.opacity=0; return; }
  const sp=hit.s[ti], fl=hit.f[ti];
  const lab = hit.t==="RAMP"?"Ramp":(hit.t==="EL"?"Express lane "+(hit.l): "GP lane "+(hit.l+1));
  tt.innerHTML=`<div class="big">${sp==null?"—":sp+" <span style='font-size:11px'>mph</span>"}</div>`+
    `<div><b>${lab}</b></div>`+
    `<div style="color:var(--muted)">${hhmm(per[ti])}${fl!=null?" · "+fl+" veh/h":""}</div>`;
  tt.style.opacity=1;
  const ox=cxs+14, oy=cys+14;
  tt.style.left=Math.min(ox, innerWidth-tt.offsetWidth-8)+"px";
  tt.style.top=Math.min(oy, innerHeight-tt.offsetHeight-8)+"px";
}
cv.addEventListener("pointerleave",()=>tt.style.opacity=0);

// ---- theme toggle ----
document.getElementById("tog").onclick=()=>{
  const r=document.documentElement;
  const cur=r.getAttribute("data-theme")||
    (matchMedia("(prefers-color-scheme: light)").matches?"light":"dark");
  r.setAttribute("data-theme", cur==="dark"?"light":"dark"); draw();
};
addEventListener("resize",resize);
setT(0); resize();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpkg", required=True)
    ap.add_argument("--out")
    ap.add_argument("--title")
    a = ap.parse_args()
    build(a.gpkg, a.out, a.title)
