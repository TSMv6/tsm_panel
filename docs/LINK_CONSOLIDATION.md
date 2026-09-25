# Link Consolidation — what it is and why the model needs it

**Audience:** modelers, reviewers, and stakeholders who want to understand why the
travel-model network is built by *consolidating* the GeoMaster/Navteq network, and
what the `netPrep` step does. **Scope:** the TSMv6 statewide network (Florida),
but the rationale is general to any model built on a navigation-grade base map.

---

## 1. The short version

The GeoMaster network (derived from Navteq/HERE) is a **navigation-grade** map: it
splits every road into many short segments at every minor attribute change,
address range, and shape vertex. A statewide extract is **~1.15 million link
records** (≈1.83 million once one-way/two-way directions are expanded).

A travel-demand model does not want — and cannot efficiently use — a link for
every navigation segment. It wants one link **per homogeneous roadway section
between decision points** (intersections, merges, interchanges). **Link
consolidation** is the step that merges the many navigation segments into those
model links, **preserving the road geometry and topology** while collapsing the
record count.

On the TSMv6 2024 network this takes **1,830,790 directed navigation links → 636,149
model links** (plus centroid connectors) — roughly a **3× reduction**, with no loss
of network shape or connectivity.

```
  GeoMaster (navigation)                 Model link (after consolidation)
  o--o--o--o--o--o--o--o--o   ───────►   o═══════════════════════════════o
  ^  ^  ^     ^  ^        ^               ^                               ^
  segment breaks at every                one link: same FTYPE, lanes,
  vertex / attribute tick                speed, area type, direction
  (no intersections here)                between two real intersections
```

---

## Network resolution (the **Network Resolution** dropdown)

The network can be consolidated at three spatial resolutions:

- **TSM** — the Turnpike State Model zone system, **~8,700 zones**. This is the
  resolution used for **skimming and the demand models**.
- **RPM** — **Regional Planning Model** zones (centroids and centroid connectors)
  at **~26,000 zones** — a finer, regional-planning-grade zone system.
- **MSR** — **Multi-Spatial Resolution**: a **hybrid of TSM and RPM** where a
  user-chosen study area (subarea) carries the high-resolution RPM network while the
  rest of the state stays at TSM resolution.

**RPM and MSR are not used in skimming or the demand models** — those always run at
TSM. Instead, the demand-model outputs are **disaggregated** to the RPM/MSR
resolution afterward via a **hierarchical, sequential spatial disaggregation**
(see the **MSR widget**).

> **TSMv5** networks support **TSM resolution only** (no RPM, no MSR); the dropdown
> is locked to TSM when Network Version = TSMv5.

---

## Zone numbering (**Max Internal Zones** and **External Stn Range**)

Centroids are not ordinary network nodes: graphWalk must never consolidate
*through* one, and netPrep marks every centroid `DTA_Type = 99` in `Node.csv`.
Telling them apart from network nodes is by id, so netPrep has to be told which
ids are zones — and that is a property of the network, not of the program.

Zone ids come in **two separate blocks**, and both must be given:

| Field | What it is | TSM | RPM |
|---|---|---|---|
| **Max Internal Zones** | highest *internal* zone id; internals are `1 … max` | `8721` | `26274` |
| **External Stn Range** | first and last *external station* id, inclusive | `11501-11560` | `30001-30060` |

The external stations are the same 60 places in both systems (I-10, I-75, I-95
and the rest of the state-line crossings) — they are simply **numbered
differently**, in their own block above the internal zones. That gap is why one
"highest zone id" number cannot describe the zone system on its own: anything
between `max internal` and the external block is not a zone at all.

Neither field is defaulted, and netPrep refuses to run without them. A wrong
value does not fail loudly — it just leaves centroids unmarked in `Node.csv`,
which surfaces much later as zones that will not load.

> Real network node ids are GeoMaster/Navteq ids in the tens of millions, so
> there is no risk of a network node falling inside either block.

---

## Centroid connectors

Connectors are synthesized as `FTYPE 51` links and carry fixed attributes rather
than looked-up ones: a free-flow **speed** (so paths are not tempted to travel
along them), the synthesized link's **posted speed**, and an effectively
unlimited **capacity** (a connector must never be the binding constraint on
loading a zone). These are written into `link_consolidation_settings.txt` on
every run — `centroid_connector_speed`, `centroid_connector_postspeed` and
`centroid_connector_capacity` — and can be changed in the configuration table
without rebuilding netPrep. netPrep applies them by **facility type**, so
connectors at external stations get them exactly as internal ones do.

---

## 2. Why the navigation network can't be used as-is

| Problem with raw navigation links | Consequence for the model |
|---|---|
| **Too many links** (~1.8M directed statewide) | Assignment, skimming, and path-building scale with link/node count; 3× more links is 3× the memory and runtime for every iteration. |
| **Spurious interior nodes** — segments break mid-block where no turning movement exists | Each break is a node the path-builder must visit; it inflates the graph and creates "intersections" that aren't real, distorting turn penalties and select-link analysis. |
| **Attributes vary segment-to-segment** (tiny speed/lane ticks) | A model link needs *one* capacity, speed, and facility type. Fragmented attributes can't be assigned a single VDF or capacity cleanly. |
| **Counts & capacities are corridor-level**, not per micro-segment | Observed traffic counts and planning capacities (QLOS) are defined for a roadway section, not for each 50-ft navigation segment. They only line up after consolidation. |
| **Calibration & reporting** are done per facility | Volume/count comparisons, GEH, and facility-type summaries are meaningful per consolidated link, not per fragment. |

Consolidation fixes all of these at once: fewer links, only **real** nodes, **one**
set of attributes per link, and a geometry that still matches the road.

---

## 3. What the consolidation actually does

It walks the directed network and merges a run of successive links into one
**consolidated link** as long as they are the *same kind of road* and there is **no
reason to break** between them.

**Merge while all of these match** (a link and its successor):
`FACTYPE` (facility type) · `AREATYPE` · `NLANES` · `POSTSPEED` · `DIRECTION`.

**Stop the merge (start a new link) at a true decision point:**
- **Intersection** — the downstream node has more than one approach/departure (a
  turning movement exists).
- **Merge / diverge** — on/off ramps and lane merges where flow combines or splits.
- **Overpass / grade separation** — detected by a change in vertical level
  (`F_ZLEV`/`T_ZLEV`); two roads crossing without connecting must not be merged
  into one link.
- **Loop ramp / facility change** — a change in the roadway role.
- **Centroid connectors** are never merged through (zone-loading points stay
  distinct).

This logic is a faithful port of the deployed `walk_the_graph` procedure (the
`Get_next_Bnode` topology test), so the C++ result matches the established R/RCPP
network.

**Preserved and aggregated along each merged link:**
- **Geometry** — the segment shapes are concatenated, so the consolidated link
  follows the true road alignment (used for mapping and GMNS export).
- **Length** — recomputed from the merged geometry (miles).
- **Signals** — counted into `NSignals` wherever a merged segment ends at a
  signalized node (feeds the model's signal-delay model).
- **Tolls** — summed across the merged segments.
- **First-from / last-to** node, grade levels, and the facility attributes carry
  through; ELToD fields (free-flow speed, VDF α/β, capacity from QLOS) are derived.

---

## 4. Result on the TSMv6 2024 network

Real figures from the latest run (`netPrep`, 2024 GeoMaster with OSM signals):

| Stage | Count |
|---|---|
| GeoMaster links read | **1,147,391** (683,399 two-way) |
| → expanded to directed links | **1,830,790** |
| + TSM centroids / connectors | +8,777 zones / +52,416 connectors |
| Directed links into the walk | **1,883,206** |
| Consolidated groups | 895,462 → **638,391** |
| **Model links** (after (A,B) dedup) | **636,149** |
| Model nodes | **277,775** |
| Signalized model links (`NSignals` > 0) | **55,801** (57,037 signals) |

**~1.83M navigation links → 636k model links** — about a **3× reduction** in links
(and a much larger reduction in *interior* nodes), while keeping every real
intersection, the road geometry, signals, tolls, and counts.

---

## 5. Where it fits in the pipeline

```
  GeoMaster (Navteq/HERE) .gpkg          [navigation-grade, ~1.8M directed links]
        │   links + nodes + centroids + centroid connectors
        ▼
  netPrep  (link consolidation)          [this step]
        │   merge homogeneous runs between decision points
        │   + centroid connectors, two-way expansion, ELToD fields, NSignals
        ▼
  Link.csv / Node.csv                    [636k model links, 278k nodes]
        │
        ▼
  HyDRA (AgentFlow) DTA assignment       [routing, DNL, signal delay, counts]
```

The consolidated `Link.csv` carries the schema the assignment reads directly
(`A,B,FNAME,FTYPE,AREATYPE,NLANES,POSTSPEED,SPEED,DISTANCE,TOLL,NSignals,ANAME,
ALPHA,BETA,IMPFAC,DELAY_FLAG,CAPACITY,F_ZLEV,T_ZLEV`), plus a **Many-to-One
lookup** (`Many_to_One_lookup.csv`) that maps each original navigation `LINK_ID`
back to its consolidated link — so results can be disaggregated to the full
navigation network when needed.

---

## 6. Reproducing it

Run the self-contained app (no QGIS or separate GDAL install required):

```
C:\TSM_NextGen_v6\Apps\LinkConsolidator\netPrep_linkConsolidate.bat
```

or directly: `netPrep.exe <link_consolidation_settings.txt>`. The settings file
names the GeoMaster layers, the model resolution (`TSM` | `RPM` | `MSR`), the year,
and the output folder. Progress and the input/output paths are logged with
timestamps; a full run is ~4–5 minutes for the statewide network.

---

*See `README.md` for the field-by-field pipeline detail and build instructions.*
