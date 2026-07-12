# Blueprint — Limited-Access Facilities Volume Dashboard

*Design only. A QGIS-launched, map-driven dashboard reporting daily volumes on
the limited-access system — mainline, ramps, cross-streets, and turning
movements at intersections near interchanges — with Excel and HTML export.*

## 1. What it answers

For a Turnpike/limited-access analysis the recurring question is: *at this
interchange, how much is on the mainline, how much on each ramp, what does the
crossing arterial carry, and what are the turning movements at the ramp
terminals?* Today that means hand-querying several output files per location.
The dashboard makes an **interchange the unit of analysis**: pick one on the
map, see its mainline segments, every ramp, the cross-street, and the ramp-
terminal turning movements — daily and by period — in one view, exportable.

## 2. Data sources (all already produced)

| Layer | Source | Provides |
|---|---|---|
| Mainline + ramp volumes | `link_performance_{macro,meso,micro}DTA.csv` (disjoint by tier) | daily and 15-min volume, speed, `toll_rate` per directed link |
| Facility class | link table `FTYPE` / `FNAME` | mainline (11) vs ramp (71/72) vs toll (91/93/94) vs EL (96/97/98) vs cross-street (arterials/collectors) |
| Turning movements | `agentAnalysis turns` (3- or 5-node movements from `agentPaths.duckdb`) | per-movement volume at a node, by period |
| Interchange structure | node `DTA_Type` (DMN/merge/system-ramp), `System-Ramps` FNAME, ramp connectivity | which links/nodes belong to one interchange |
| Counts | `count_validation.csv` / `TSMv5.COUNT_24` | observed vs model on counted mainline/ramps |
| Geometry | `TSM_Link_ML.gpkg`, `TSM_Node_ML.gpkg` | the map |

The dashboard is an **aggregation + presentation layer** over these; no new
engine output is required (turning movements already come from agentAnalysis).

## 3. The core abstraction: the interchange group

The one piece of real logic is grouping the network into interchanges:

- **Seed** on system-ramp nodes / DMN-merge clusters, or on a supplied
  interchange point layer (FDOT interchange inventory if available).
- **Gather** within a radius (or by ramp connectivity): the mainline through-
  links, all ramp links (on/off, system-to-system), the ramp-terminal nodes,
  the crossing arterial links, and the ramp-terminal intersection nodes.
- **Classify each link**: mainline-through, on-ramp, off-ramp, system-ramp,
  cross-street, frontage. Direction (NB/SB/EB/WB) from node geometry.
- **Name** the interchange (nearest cross-street name from `ST_NAME`, or the
  FDOT id).

Output: an `interchanges.gpkg` (point per interchange + a membership table
link→interchange→role) built once per run. This is the spine the dashboard
navigates.

## 4. The four reporting scopes

For a selected interchange (or the whole system), report daily + by-period:

1. **Mainline** — through-volume by direction, speed, v/c, toll rate, count
   comparison where a count exists. The corridor profile up/downstream of the
   interchange.
2. **Ramps** — each on/off and system ramp: volume by direction, the ramp's
   share of mainline, merge/diverge context. A ramp table + a schematic.
3. **Cross-streets** — the crossing arterial's volume by direction and its
   own count comparison.
4. **Turning movements** — at each ramp-terminal intersection, the 3-/5-node
   movement volumes (from agentAnalysis) as a turning-movement diagram
   (the classic intersection "spider") and a movement table, by period.

## 5. Layout (map-driven, dashboard-style)

- **Left: map** (QGIS canvas or an embedded map) with interchanges as clickable
  points; mainline/ramps/cross-streets styled by volume. Click an interchange
  → the right panel fills.
- **Right: drill-down** for the selected interchange:
  - a header (name, route, county, mainline AADT both directions),
  - four collapsible sections (mainline / ramps / cross-streets / TMs),
  - each with a small table + a chart (bar for volumes, spider for TMs,
    line for the by-period profile),
  - a period selector (daily / AM peak / PM peak / custom) driving all charts.
- **System view**: a sortable table of all interchanges (mainline AADT, total
  ramp volume, worst movement v/c) to find the hot spots, then click through.

## 6. Two export targets

- **Excel workbook** (`interchange_volumes.xlsx`): one summary sheet (all
  interchanges) + one sheet per interchange (mainline / ramps / cross-street /
  turning-movement tables), formatted like the validation workbook. This is
  the deliverable planners hand off. Reuses the `make_validation_xlsx.py`
  styling approach.
- **HTML dashboard** (`interchange_dashboard.html`): self-contained, the map
  as an inline SVG/GeoJSON, the interchange list + drill-down interactive in
  the browser (no server) — shareable, the "living" version. Same theme-aware,
  no-external-assets pattern as the scenario report.

## 7. QGIS integration

- A **"Interchange Volumes" button** in the Analyst group opens a dialog:
  choose the run directory (link performance + agentPaths), the link/node
  gpkgs, optionally an FDOT interchange point layer, period definitions, and
  output paths.
- On run it: (a) builds/loads `interchanges.gpkg`, (b) calls `agentAnalysis
  turns` for the ramp-terminal nodes, (c) aggregates volumes, (d) writes the
  Excel + HTML, (e) loads the styled layers into the QGIS project so the
  analyst can pan the map and re-export. The dashboard HTML is the takeaway;
  the QGIS layers are the interactive workspace.

## 8. Build phases

1. **Interchange grouping** (`interchanges.gpkg` + membership table) and the
   link-role classifier. Everything else keys off this. **DONE** —
   `Apps/Dashboard/interchange_build.py`: seeds on ramp-to-mainline junction
   nodes (limited-access FTYPE {11,91,96,97,98} ∩ ramp FTYPE {71,72}), unions
   junctions within `--radius-m` (800 m) via a spatial-grid union-find, and per
   cluster gathers mainline through-links, on/off/system ramps, ramp-terminal
   nodes and the cross-street arterials/collectors touching them. Roles +
   NB/SB/EB/WB direction from node geometry; route = mainline `ST_NAME` (I-95,
   FLORIDA'S TPKE…), name = cross-street. Writes `interchanges` (points) +
   `members` (table) layers + a members CSV. Statewide: **840 interchanges,
   9,618 member links** (3,167 junctions).
2. **Mainline + ramp aggregation** → the Excel workbook (summary + per-
   interchange sheets). Delivers the core deliverable. **DONE** —
   `Apps/Dashboard/interchange_volumes.py`: daily/AM/PM volume + vol-weighted
   speed (clamped ≤85 mph) + peak toll per link from the three
   `link_performance_*` tiers, joined to members. **Summary sheet** (all 840):
   route, cross-street, county, representative two-way **mainline AADT** (median
   daily per direction × GP/EL class — not a naive sum over sequential
   segments), ramp volume, on/off/system counts, cross-street volume, model-vs-
   count with a color-graded ratio cell. **Detail sheets** (top-N by AADT or
   `--county`/`--route` filtered): mainline / ramp / cross-street tables. Also
   writes `interchange_volumes.csv` (feeds the phase-4 HTML dashboard).
3. **Cross-streets + turning movements** (wire in `agentAnalysis turns`) →
   TM tables + spider diagrams. **DONE** — `Apps/Dashboard/interchange_turns.py`:
   finds ramp-terminal nodes (shared by a ramp + a cross-street member), runs
   `agentAnalysis turns` on them (from `agentPaths.duckdb`), classifies each
   from→thru→to movement Left/Through/Right/U-turn and the approach NB/SB/EB/WB
   from node geometry, and writes `interchange_turns.csv`. `spider_svg()` renders
   the classic turning-movement diagram (curved arcs, width ∝ √volume, L blue /
   T grey / R green, volume labels, cardinal legs) — reusable by the workbook and
   the phase-4 dashboard. Verified on 20 interchanges (48 terminal nodes, 143
   movements: 83 T / 26 L / 32 R / 2 U).
4. **HTML dashboard** (map + drill-down + period selector). **DONE** —
   `Apps/Dashboard/interchange_dashboard.py` writes ONE self-contained,
   theme-aware `interchange_dashboard.html`: a Canvas **interchange map** (points
   sized by mainline AADT, red where model/obs is off >20%, pan/zoom/click), a
   **drill-down** panel (header + tiles + mainline / ramp / cross-street volume
   tables + turning-movement **spiders** from phase 3), a **Daily / AM / PM**
   period selector driving the tables, a filter box, and a **sortable system
   table** of all interchanges. Reuses `interchange_volumes.aggregate/summarize`
   (per-member volumes) and `interchange_turns.spider_svg` (pre-rendered).
   Verified: 840 interchanges on the map, 80 detailed, 48 spiders, 309 KB.
5. **Panel button** + QGIS layer loading + FDOT-interchange-layer option.

## 9. Relationship to the other blueprints

- Reads the **same standard metrics** as the scenario report (§ shared
  `scenario_metrics.csv` schema) so daily volumes reported here match the
  report card.
- The scenario report is the **whole-model narrative** (one page, all steps);
  this dashboard is the **operational drill-down** on the limited-access
  system (map, per-interchange, export). They are complementary: report to
  judge the scenario, dashboard to work an interchange.
- Turning-movement geometry can later borrow the **aerial lane view** (lane
  ribbons + gores) so a selected interchange renders realistically rather than
  as a spider schematic.
