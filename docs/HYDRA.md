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
- **Calibration to counts (ODME)** — reweights agents so modeled link volumes match
  observed counts. The score/adjustment is stratified by
  **O · D · person-type · VOT category**, so the reweighting preserves market mix
  rather than scaling links blindly (`CALIBRATE`, `CALIB_*`).
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
