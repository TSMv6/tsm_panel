# Blueprint — Micro Lane Aerial Visualizer

*Design only. How to turn the micro lane outputs into a real, aerial-quality
lane view instead of parallel offset lines.*

## 1. Where we are, and why it looks flat

`build_resolution_gpkg.py` today draws `micro_lanes.gpkg` as **one offset
polyline per lane** — the mainline centerline shifted perpendicular by
`(lane − center) × 12 ft`. It renders as a bundle of parallel lines. That is
correct as a schematic (lanes on the right side, EL on the median) but it is
not an aerial view: the lanes have no width, no pavement, the count never
changes along the corridor, the EL buffer is invisible, and merges/diverges
are just crossing lines. To sit convincingly on aerial imagery we need lanes
that look like **pavement ribbons of real width, with the cross-section
changing where lanes are added or dropped, a painted buffer beside the express
lanes, and gore areas at every ramp.**

## 2. The data we already have

The network-prep step emits GMNS sidecars that carry exactly the geometry this
needs — we are not inventing data, we are using what netPrep already writes:

| File | Columns that matter | Role in the aerial view |
|---|---|---|
| `gmns_lane.csv` | `link_id, lane_num, lane_type, width_ft, allowed_uses` | true per-lane width and type (GP / EL / aux / ramp); lane_num orders them across the section |
| `gmns_segment.csv` | `link_id, start_lr, end_lr, l_lanes_added, r_lanes_added, free_speed_mph` | **where the cross-section changes** — a lane add/drop between two linear-referenced positions is a taper |
| `gmns_movement.csv` | `node_id, ib/ob_link, start/end lane, type, ctrl_type` | turn pockets and gore connectivity at junctions |
| `link_performance_microDTA.csv`, `micro_lane_performance.csv` | per-lane `speed/density/flow` × 15-min | the value each lane ribbon is colored by, per period |
| link geometry GPKG (`TSM_Link_ML.gpkg`) | link centerline, CRS (FL Albers, meters) | the spine every lane is built from |

The current builder ignores `width_ft`, both `_lanes_added` columns, and the
movement file. The aerial view is mostly a matter of consuming them.

## 3. The geometry pipeline (centerline → ribbons)

Build each corridor once, in five passes:

**3.1 Corridor spine.** Chain the micro links head-to-tail into one continuous
directed polyline (already done — the chain-offset fix). Linear-reference it
(station 0 → L) so every lane/segment/movement position maps to a station.

**3.2 Per-station cross-section.** Walk the GMNS segments along the spine.
Between `start_lr` and `end_lr` a link has a fixed lane count; `l_lanes_added`
/ `r_lanes_added` change it at a boundary. Produce a **cross-section profile**:
for each station, the ordered list of lanes with `(offset_from_centerline,
width, type)`. Lane offsets accumulate half-widths from the centerline
outward, so a 4-lane 12-ft section spans −24…+24 ft.

**3.3 Lane ribbons as polygons, not lines.** For each lane, sample its
centerline offset at closely spaced stations (respecting curvature — denser
samples in curves), then **buffer to the lane's width with flat caps and miter
joins** to get a filled ribbon. Where a lane is added or dropped, the ribbon
**tapers**: interpolate its width 0 → full (or full → 0) over a standard taper
length (e.g. 12:1 per AASHTO, or a fixed 300 ft), so a lane drop looks like a
real closing wedge rather than a hard stop. This is the single biggest visual
win over the current straight offset.

**3.4 Separators and buffers as their own features.** Between adjacent lanes,
emit a thin line feature carrying a `marking` attribute (`solid`, `dashed`,
`double`, `buffer`, `barrier`). The **GP↔EL boundary** becomes a wide `buffer`
(the painted chevron median) or `barrier` (pylons) styled distinctly — this is
what reads as "express lanes" from the air. Access windows (from the corridor
builder's ingress/egress spans) break the buffer into openings.

**3.5 Gores at ramps.** At each ramp merge/diverge (from `gmns_movement` /
the DMN/merge nodes), build a small triangular **gore polygon** between the
mainline edge and the ramp edge. Ramps themselves are ribbons built the same
way off their own link chain. This turns interchanges from crossing lines into
recognizable merge/diverge geometry.

Output: `micro_lanes_aerial.gpkg` with three layers — `lane_ribbons`
(polygons, per lane × link, carrying the period columns), `lane_markings`
(lines, with marking type), `gores` (polygons). All keep the wide-format time
columns (`speed_<HHMM>`, `density_<HHMM>`, `flow_<HHMM>`) so one feature spans
all periods.

## 4. Rendering (QGIS)

- **Ribbons** filled by a graduated ramp on the chosen period column
  (speed = green→red reversed; density = white→red; flow = sequential blue).
  Because they are true-width polygons, zooming in over aerial imagery shows
  lane-level congestion as colored pavement.
- **Markings** styled by `marking`: dashed white for GP↔GP, solid white edge
  lines, a hatched/again-colored band for the EL buffer, a heavier line for
  barriers.
- **Gores** a neutral fill (or striped) so merges read correctly.
- **Time**: the wide columns drive either the QGIS Temporal Controller (weak)
  or the JS viewer below (preferred).
- A companion QML style file ships with the builder so the layer loads
  pre-symbolized.

## 5. The JS aerial viewer (the "complex way," recommended for animation)

QGIS temporal playback is clunky. A self-contained HTML viewer gives a real
aerial, animated lane view:

- **Base**: MapLibre GL (open, no token) or deck.gl over an aerial raster /
  vector basemap. Lane ribbons as a `deck.gl PolygonLayer` (or a MapLibre
  fill layer from the GPKG converted to GeoJSON/PMTiles).
- **Animation**: a time slider scrubs `<HHMM>`; the fill color of every ribbon
  updates from that period's column — smooth, 60 fps, unlike the temporal
  controller. deck.gl's `TripsLayer` can additionally animate individual
  vehicle dots along the ribbons from the micro trajectories for a true
  micro-simulation playback.
- **Interaction**: hover a lane → tooltip with its speed/density/flow at the
  current time; click an interchange → zoom + isolate its ramps.
- Packaged like the existing demo page: one self-contained `.html`, data
  inlined or as a sibling `.pmtiles`, theme-aware, shareable.

## 6. Build phases

1. **Cross-section profile** from GMNS lanes + segments (consume `width_ft`,
   `_lanes_added`). Output straight-width ribbons (no tapers) — already an
   aerial improvement.
2. **Tapers** at lane adds/drops; **buffer/barrier** separators; access-window
   openings.
3. **Gores + ramp ribbons** at interchanges from movements.
4. **QML styles** + Visualizer-dialog option ("Aerial lane polygons").
5. **JS viewer** (MapLibre/deck.gl) with time slider; optional vehicle-dot
   playback from trajectories.

Phases 1–2 deliver the "real lane view" the request is about; 3 makes
interchanges read; 4–5 make it animate and ship. Each phase is a self-contained
addition to `build_resolution_gpkg.py` and does not disturb the existing
offset-line output (keep it as the lightweight schematic mode).

## 7. Open questions to settle before building

- **Aerial imagery source** under a strict-CSP artifact: an embedded raster
  tile set (PMTiles) vs a plain neutral base. (External tile servers are
  blocked in artifacts.)
- **Taper standard**: fixed length vs speed-based (AASHTO) — affects realism
  vs simplicity.
- **CRS**: everything stays in FL Albers meters; the JS viewer needs WGS84 —
  reproject at export.
- Whether to drive lane geometry purely from GMNS (needs netPrep to populate
  real per-lane widths, currently a flat 12 ft) or allow a manual lane-config
  override file for a study corridor.
