# HyDRA — Hybrid Dynamic Routing Assignment (AgentFlow-DTA)

HyDRA routes **individual agents** over the network and loads them through a dynamic
network-loading (DNL) flow model with iterative equilibrium. It reads the **agent
trip list** directly (`*_tt_List_hourly.csv.gz` from agentPlans) — no trip table.

**Inputs:** Link & Node **GeoPackage** layers (converted to CSV via `gpkgcsv` at run),
the trip list, and an optional toll-policy CSV.

---

## Run Mode (flow model)

1. **PointQueue + BPR** — point queue where the running time below capacity comes from
   the **BPR/VDF** curve (V ≤ C); over-capacity still queues. General-purpose hybrid
   fallback.
2. **Node + PointQueue (nodeDNL)** — node-conserving loader (`NodeDnl`, `DTA_NodePQ`):
   flow is propagated through an explicit **node model** so `N_out = N_in` at every
   interior node, with **inflow-capacity** receiving (point-queue style).
3. **Node + Spatial/LTM (nodeDNL)** — the node-conserving loader with **spatial
   storage/spillback** receiving (`DTA_NodeLTM`). **The default** — pick it for the
   most physically consistent volumes. By default the **limited-access system**
   (freeways 11/12, ramps 71–79, toll roads 91–94, express lanes 96–98) runs
   **mesoscopic** on top of it (the Meso FTYPEs box).

### Node refresh — per iteration vs per chunk (node loaders)

The **`DTA_Node*`** loaders run a node simulation to propagate flow. The **Node
refresh** control (`NODE_SCHEDULE`) sets how often that node sim is refreshed within
an equilibrium iteration, trading speed for tightness:

- **Per iteration** (`per_iter`, default) — route every chunk against the frozen node
  travel times and run the node sim **once per iteration**. Noisier early but ~3–6×
  faster wall-time — **statewide-affordable**.
- **Per chunk** (`per_chunk`) — refresh the node sim **after every routing chunk**
  (≈ *Route Chunks* passes). Cleanest convergence, ~10× the node passes —
  **county-scale**.
- **Hybrid (per-iter → per-chunk)** (default) — cheap `per_iter` through the
  early/sampling iterations, then a short `per_chunk` polish over the last few to
  restore the directional AM/PM peaks. The dialog expands this to an iteration ramp
  from *Max Iterations* (e.g. 10 iters → `1-7:iter, 8-10:chunk`).

(*Route Chunks* is the number of incremental routing batches per pass; a "chunk" is a
batch of routing groups, not a VOT class. Node refresh applies to the node loaders;
it is harmless for the point-queue / LTM engines.)

**Node refresh is the node balancer.** *Per-link load refresh* and *Per-link load
schedule* on the Advanced tab (`LOAD_REFRESH` / `LOAD_SCHEDULE`) are a different
thing: they control the per-link **PointQueue** run mode only, which has no node
model, and are greyed out for the node run modes.

### Advanced tab: rerouting and loading

- **Reroute fraction (min)** (`REROUTE_FRACTION_MIN`, 0.05) — the floor on how much
  demand may change path in one iteration. The share allowed is
  max(2/(n+1), floor): 100% at iteration 0, 67%, 50%, 40% … down to the floor, given
  to the route keys with the largest gaps first. Higher converges faster but noisier.
- **Reroute threshold (min)** (`REROUTE_THRESHOLD_MIN`, 0.01) — a route key adopts a
  new path only if it beats its current path by more than this many minutes of
  generalized cost. Keys within it count as *stable* in the log.
- **Loading resolution (min)** (`NODE_INJECT_RES`, 1–15, default 15) — how finely a
  departure slot's trips are released by the node loaders. 1 = minute by minute,
  which smooths the loading; travel times still update every 15 minutes.
- **Departure slots** (`DEPART_SLOT_MIN`, default Auto) — the slot in the route key
  (O · D · slot · `marketVot`). Auto follows the trip list: a 15-min agentPlans
  output gets 15-min keys, a 30-min output 30-min keys.

### Meso / Micro tab: time steps, diagnostics, tiers and probes

- **Meso time step** (`MESO_DT_SEC`, 6 s) and **Micro time step** (`MICRO_DT_SEC`,
  0.1 / 0.2 / 0.5 s). **Outer loops** (`MICRO_OUTER`) is live only for `twoway_full`
  coupling: how many times the statewide assignment re-runs against the corridor
  (1 would equal `twoway_frozen`). **Micro probe every** N steps (`MICRO_PROBE_STRIDE`).
- **Meso diagnostics**: interval, movement and segment logs (`meso_interval_log.csv`,
  `meso_movement_log.csv`, `meso_segment_log.csv`), segment length or a segment file.
- **Link tiers and probes**: the run reads three fields from the HyDRA layers --
  `dta_meso` and `dta_micro` on links, `probe` on links and nodes (1 = on). Edit them
  directly (attribute table, Field Calculator), or use the buttons: *Selected links →
  meso / micro / probe*, *Selected nodes → probe*, *Set by expression…*, *Clear field*.
  The counts line shows what is tagged. `dta_micro` links simulate only with **Micro
  corridor** checked. Meso FTYPEs / Micro FTYPEs add whole facility types on top.
  Probes: a meso link → `meso_probe.csv` (every 6 s), a micro link →
  `micro_probe.csv` (per lane), a macro link or a node → `node_probe.csv` (per
  inbound link per 60-s node step: offered, sent, held, backlog).

### Engine tab: signals

**Signal delay on signalized links** (`SIGNAL_MODEL`) caps each signalized link's
discharge at saturation flow × g/C and adds control delay per signal, using the
link's `NSignals` -- the count of signalized nodes along it, from netPrep (the
GeoMaster node layer's `Signal` field). Saturation flow, cycle, g/C and per-FTYPE
g/C are set here; there are no per-intersection timing plans yet.

**Build visualizer layers after the run** (Outputs) adds Meso Segments (needs the
Segment log) and Micro Lanes (needs a micro corridor) to the map.

### Checkpoint tab (DTA and STA)

- **Write checkpoint** — `checkpoint.bin` in the output directory, every N
  iterations and at the end.
- **Resume from a checkpoint** — browse to a `checkpoint.bin`; the tab shows its
  iteration, route keys, links, slot width and engine. **Then run**: *Up to Max
  Iterations*, *N more iterations*, or *Outputs only* (no new iterations: volumes,
  agent outputs, select link and subarea from the loaded state). The network must
  have the same links and the trip list the same route keys; capacity or toll edits
  are fine (the affected trips re-route). Sampling is skipped on resume. STA resumes
  only from an STA checkpoint.

### Activating meso / micro per link

A link runs meso or micro when **either**:
- its link attribute **`dta_meso` / `dta_micro`** is set (1) in `LINK.csv`, **or**
- its **FTYPE** is listed in the control (`MESO_FTYPE` / `MICRO_FTYPE`).

So you can target a corridor by editing the link attributes, or a whole class by
facility type from this dialog (the **Meso FTYPEs** box; the **Micro corridor** box).

---

## EL vs GP and the en-route choice

Express Lanes (EL) and the parallel General-Purpose (GP) lanes are modeled as
distinct paths; an agent picks between them **en route** at the decision point:

- **Meso (en-route logit):** the EL/GP split is a logit on the current EL vs GP
  generalized cost (time + toll·VOT) for that agent's segment.
- **Micro corridor — two modes (EL/GP choice):**
  - **(a) Meso logit** — reuse the meso logit split inside the micro corridor.
  - **(b) Micro time-differential (VOT)** — take the *actual* EL−GP travel-time
    difference from the lane-level micro sim and convert it with **each agent's VOT**
    to an individual EL/GP decision (toll worth it if VOT·Δtime ≥ toll).

---

## Tolls

- **Toll policy file (CSV)** — time-of-day toll schedules and **EL toll curves**
  (toll as a function of density/LOS or time band). Set it in the dialog
  (`TOLL_POLICY_FILE`). EL links are detected/zoned and priced from this file.
- **Truck tolls by axles** — a truck pays roughly **(n − 1) × the auto rate** for an
  `n`-axle vehicle (2-axle ≈ auto, 5-axle ≈ 4× auto), applied on top of the policy.
- **VOT by vehicle class** — value of time, time/cost betas, axles and PCE are set
  per market **segment** (the segment-parameter CSV), so trucks and autos value the
  toll differently in the EL/GP choice.

---

## Agents: the 4-part ID

Every agent keeps a stable **4-part identity — `hh_id` · `person_id` · `tour_id` ·
`trip_id`** — assigned in SDT/LDT, carried by agentPlans into the trip list, and
**preserved through routing and all outputs**. That means a loaded trip on any link,
a select-link result, or a DuckDB agent record traces back to the exact household /
person / tour / trip that made it.

---

## Select link, calibration, subarea

- **Select link** — flag link(s) and extract every agent path that uses them (and
  the O-D pattern feeding them), keyed by the 4-part ID.
- **Counts / ODME** (DTA → Counts / ODME tab) — after the assignment converges,
  scales demand per route key (**O · D · 30-min departure · VOT segment**) toward
  the count file, re-assigning warm between rounds. Every output then shows the
  adjusted demand (`count_windows_pre_odme.csv` keeps the unadjusted fit).
  **Grow only** raises under-loaded routes and treats the additions as the
  **unmodeled market** (deliveries, commercial-to-commercial, escort trips):
  they are written to `odme_supplement.csv`. **Grow and reduce** also lowers
  over-loaded routes; reductions are reported in `od_adjustment.csv`, never
  added to the supplement.
- **Subarea runs** — ODME is meant for a subarea, not the statewide network.
  Use the Agent Analysis subarea trip list as the Trip list: its O/D can be
  cordon (highway) nodes and it keeps the true zones in `TSM_O` / `TSM_D`.
  HyDRA turns county routing masks off automatically for such a list, carries
  `TSM_O` / `TSM_D` into the agent and ODME outputs, splits the ODME summary by
  II / IE / EI / EE, and grows the supplement by the TSM zones.
- **Supplemental demand** — load a base-year `odme_supplement.csv` into any
  later run (base or future year) with ODME off. For a future year, grow it
  with **Scale** and/or a `zone,factor` **Zonal growth file** (each trip O→D ×
  sqrt(g_O · g_D)).
- **Subarea** — extract a subarea (`SUBAREA_BOUNDARY_FILE` + seed node): agents whose
  paths touch the subarea are cut at the boundary into a subarea trip list (with
  external stations at the cut points). Because the 4-part ID is preserved, the
  subarea results **tie back** to the full-region agentPlans run.

---

## Outputs

- **Link performance** — always written, one file per resolution actually used:
  `link_performance_macroDTA.csv`, `…_mesoDTA.csv` (and micro). Time-sliced volume,
  speed, delay by link, plus per-**purpose** volume columns
  (`LINK_VOLUME_BREAKDOWN Purpose`, written by the dialog's control file).
  **All volumes are actual vehicles** — PCE is applied only inside the flow model
  for congestion, never in the outputs.
- **Agent plans** — per-agent chosen plan/route summary.
- **Agent paths** — full per-agent link paths (**large**; enable only when needed).
- **DuckDB** — tick *Write to DuckDB* to emit `agent_results.duckdb` (agent results +
  key paths) instead of CSV — fast to query, Parquet-native.

---

## Configuration file

On **Run**, the dialog writes `<output>/hydra_run.ctl` and runs
`Apps\Hydra\afdta.exe --control hydra_run.ctl`, with `NODE_FILE`, `LINK_FILE`,
`TRIP_FILE`, `OUTPUT_DIRECTORY`, `MACRO_MODEL`, equilibrium knobs, `MESO_FTYPE`,
`MICRO_*`, `SIGNAL_MODEL`, `TOLL_POLICY_FILE`, and `WRITE_AGENT_RESULTS`.
