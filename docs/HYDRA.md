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

**Node refresh is the node balancer.** The per-link **PointQueue** run mode has no
node model; it reloads every agent after each chunk (the engine default).

Also on the Macro DTA tab:

- **Max trips** (0 = all) and **Sample every** — cut the trip list for a quick test.
- **Sampling schedule** (`SAMPLE_SCHEDULE`) — the share of trips each iteration runs
  on, coarse to fine (*Progressive* 25 → 50 → 100%); *Custom schedule* sets the
  iteration ranges.
- **Loading resolution (min)** (`NODE_INJECT_RES`, 1–15, default 15) — how finely a
  departure slot's trips are released by the node loaders. 1 = minute by minute,
  which smooths the loading; travel times still update every 15 minutes.
- **Departure slots** (`DEPART_SLOT_MIN`, default Auto) — the slot in the route key
  (O · D · slot · `marketVot`). Auto follows the trip list: a 15-min agentPlans
  output gets 15-min keys, a 30-min output 30-min keys.

### Advanced tab: rerouting, LTM and signals

- **Min. reroute share** (`REROUTE_FRACTION_MIN`, 0.05) — the smallest share of
  route keys allowed to switch path in one iteration (0.05 = 5%). Candidates are
  the keys whose new shortest path beats their current one by more than the
  reroute threshold; the share allowed is max(2/(n+1), floor): 100% at iteration
  0, 67%, 50%, 40% … down to the floor, picked at random (largest-gap-first sends
  the worst corridors all to the same alternative and oscillates). A key switches
  as a whole, all its agents together. Higher converges faster but noisier.
- **Reroute threshold (min)** (`REROUTE_THRESHOLD_MIN`, 0.01) — a route key adopts a
  new path only if it beats its current path by more than this many minutes of
  generalized cost. Keys within it count as *stable* in the log.
- **LTM max spillback** and **Jam density** — the spatial-queue (LTM) settings.
- **Signals (macro and meso)** — see *Advanced tab: signals* below.

### Meso / Micro tab

Four sub-tabs: **Meso**, **Micro**, **GMNS**, **Tiers & probes**.

- **Meso**: Meso FTYPEs, **Meso time step** (`MESO_DT_SEC`, 6 s) and the
  diagnostics -- interval, movement and segment logs (`meso_interval_log.csv`,
  `meso_movement_log.csv`, `meso_segment_log.csv`), segment length or a
  segment file.
- **Micro**: **Micro corridor** (+ Micro FTYPEs), **Micro model**, EL/GP
  choice, **Micro time step** (`MICRO_DT_SEC`, 0.1 / 0.2 / 0.5 s), **Micro
  probe every** N steps (`MICRO_PROBE_STRIDE`), the **Micro package** group,
  and **Coupling** (`MICRO_COUPLING`):
  *Macro > meso > micro* (`oneway`) runs micro once on the converged traffic, no
  feedback; *Micro feedback, demand fixed* (`twoway_frozen`) feeds micro travel
  times (freeway corridor: also the EL/GP split and tolls) back with the traffic
  entering the area unchanged -- no re-routing; *Full loop: macro re-routes*
  (`twoway_full`) re-assigns statewide against the micro travel times, then runs
  micro again, **Outer loops** (`MICRO_OUTER`) times.
- **Tiers & probes**: the run reads three fields from the HyDRA layers --
  `dta_meso` and `dta_micro` on links, `probe` on links and nodes (1 = on). Edit them
  directly (attribute table, Field Calculator), or use the buttons: *Selected links →
  meso / micro / probe*, *Selected nodes → probe*, *Set by expression…*, *Clear field*.
  The buttons write the fields of the HyDRA link and node layers (added if missing);
  the run reads them as they are. The counts line shows what is tagged.
  - *Meso*: these links run as meso (packets, queues per movement); Meso FTYPEs
    add whole facility types on top.
  - *Micro*: `dta_micro` links simulate only with **Micro corridor** checked;
    Micro FTYPEs add whole facility types. Freeway corridor: one contiguous
    corridor. Network: these links, the links inside the **Micro area
    (polygon)** and, ticked, the approaches of every intersection they touch.
  Probes: a meso link → `meso_probe.csv` (every 6 s), a micro link →
  `micro_probe.csv` (per lane), a macro link or a node → `node_probe.csv` (per
  inbound link per 60-s node step: offered, sent, held, backlog).

### Micro model: freeway corridor or network

**Micro model** (Micro sub-tab): *Freeway corridor* is one contiguous
freeway / express-lane corridor with EL choice and tolls. *Network (GMNS)*
simulates the micro area with its intersections, from the GMNS package (it is
exported for the run automatically):

- **The area** (Tiers & probes > Micro): the `dta_micro` links, the links
  inside the **Micro area (polygon)** layer (selected polygons, else all), and,
  ticked, **the cross-street approaches of every intersection** they touch. Only
  this area is simulated.
- Lanes and turn pockets, movement lanes, signal timing plans (time-of-day plans
  by clock), stop and yield control come from the GMNS package -- edit them on
  the GMNS tab.
- Outputs: `micro_movement_performance.csv` and
  `micro_intersection_performance.csv` (volume, control delay, HCM LOS, max
  queue per 15 min and for the day), `agents_in_microDTA.csv`, and micro travel
  times on the area links in `link_performance_microDTA.csv`. With **Build
  visualizer layers** the dialog adds *Micro movement LOS* and *Micro
  intersection LOS* (whole day) from `visualizer/micro_los.gpkg`; its
  `movement_los` / `intersection_los` tables hold every 15-min interval with a
  `time` field for the Temporal Controller.

### Advanced tab: signals

Unchecked, nothing about signals reaches the macro / meso loading: no
discharge cap, no control delay, and saturation flow, cycle and g/C (greyed
out) are not read. Links run at their discharge rate (capacity x any
discharge factor). Micro still simulates its intersections from the GMNS
package.

**Signal delay on signalized links** (`SIGNAL_MODEL`) caps each signalized link's
discharge at saturation flow × g/C and adds control delay per signal, using the
link's `NSignals` -- the count of signalized nodes along it, from netPrep (the
GeoMaster node layer's `Signal` field). Saturation flow, cycle, g/C and per-FTYPE
g/C are set here; per-intersection timing plans come from the GMNS package
(below) when *Use GMNS in the run* is ticked. It applies to every signalized
macro and meso link, statewide; never to a static (STA) run, whose BPR curve
runs on the planning capacity (afdta ignores `SIGNAL_MODEL` there). The micro
tier simulates its own signals from the GMNS plans instead.

### Macro DTA tab: lane schedule

*Schedule file* (`CAPACITY_FILE`, optional) changes a link's lanes by time of
day: reversible facilities (I-595) and peak-hour shoulder lanes. One row per link
and window:

    A,B,start_time,end_time,added_lanes
    1039418447,1039417885,00:00,04:00,-1
    1039418447,1039417885,13:00,24:00,-1

- **Reversible lanes:** code both directions as links, then close each one outside
  its window with a negative `added_lanes` (−1 for a one-lane facility). Only the
  schedule keeps the two directions from being open at once. In the example the
  eastbound direction is closed 00:00–04:00 and 13:00–24:00, so it is open
  04:00–13:00.
- **Shoulder lanes:** a positive `added_lanes` adds that many lanes of capacity in
  its window only. An optional `added_vph` column gives the capacity directly.
- A link with no capacity left in an interval is **closed**: routing does not
  enter it then, and the macro, node and meso loaders discharge nothing from it.
- Times are clock times; past midnight is allowed (`26:00` = 2 AM next day).
- A static (STA) run does not read the schedule.

### Meso / Micro tab: GMNS sub-tab

netPrep writes `gmns_network.gpkg` (`gmns_network_msr.gpkg` for MSR) beside
`Link.csv`: node, link, lane, segment (turn pockets), segment_lane and movement
layers and the GMNS signal tables, seeded from the network -- lanes, a left
pocket on multi-lane arterial approaches to a signal, movements with lanes and
types, stop / yield control from the facility hierarchy, and a fixed-time
dual-ring plan at every GeoMaster signal (netprep/docs/GMNS.md).

- **Load layers** -- a *GMNS* group, styled; lanes, pockets and movements draw
  from 1:10,000 in. The attribute forms link link -> lanes / pockets, node ->
  movements, plan -> phases -> movements.
- **Signal timing...** -- the plans of the controller driving a node: a
  time-of-day plan list (*New time-of-day plan*; blank time of day = all day,
  else `HH:MM-HH:MM`; the first plan is the one macro / meso use), cycle,
  offset, phases (ring, barrier, position, min green, green, clearance, walk),
  which movements each phase serves (protected / permitted) and the
  ring-barrier diagram. A divided road's intersection is two to four nodes;
  one controller drives them all and the dialog lists every node's movements.
  *Fit greens to cycle*, *Seed plan* (also signalizes an unsignalized node),
  *Remove signal*, *Export plans...* (a timing pack). Select a node on the map
  first and it opens on that node.
- **Import timing pack...** -- loads a timing pack (three CSVs keyed by node,
  from node and to node, so they survive a netPrep rebuild) and replaces the
  timing of every node its controllers drive. `config/gmns/samples/colonial_dr`
  is a demonstration pack for W Colonial Dr, Orange Co.: time-of-day plans,
  lead-lag lefts, split phasing, a pedestrian phase, two-phase and
  protected-permitted lefts, coordinated at 120 s (its README).
- **Validate...** -- timing plans fit the cycle, every signal movement is in a
  phase, movement lanes and pockets are in range, lane rows match link lanes;
  *Fill in pocket geometry* draws pockets added in the attribute table.
- **Use GMNS in the run** -- exports the layers to
  `<output>/gmns` and writes `GMNS_DIR`: the timing plans set the g/C and
  cycle of every timed approach in the macro / meso signal model, statewide
  (needs Signal delay on), and lane truck restrictions in the micro corridor.
  It does not run micro anywhere: micro runs only on the micro area, and the
  network micro always exports the package itself.

### Micro sub-tab: Micro package

A network micro run writes `<output>/micro_package` (about 1 MB): the area's
link and node rows, its GMNS subset, and the traffic through the area with
each trip's route and entry time from the converged run. Rerunning it needs
no statewide model -- seconds, and the same vehicles every time, so a timing
or lane change is the only difference between two runs. Routes are frozen:
when a change should move traffic onto other roads, rerun the full model or
a subarea DTA.

- **Package folder** -- filled in after a network micro run, which also puts
  `micro_gmns.gpkg` (the area's GMNS with geometry, cut from the statewide GMNS
  package) in it: the package is self-contained.
- **Open for editing** -- loads `micro_gmns.gpkg` (cutting it first if it is
  missing) and sets **GMNS tools edit** (GMNS tab) to it: Signal timing, Validate and
  Import timing pack, and the attribute tables, then change the package, not
  the statewide file.
- **Back to the statewide package** -- timing: *Export plans...* in Signal
  timing (a timing pack), then *Import timing pack* with **GMNS tools edit**
  on the statewide package. Lane / pocket / movement edits stay in the package.
- **Run** -- exports `micro_gmns.gpkg` back to the package, reruns micro into
  `<package>/<run name>` and adds that run's LOS layers (named by the run).
  Same outputs as a full run's micro.
- An unedited package reproduces the full run's micro results exactly.

**Extra volume breakdowns** (Outputs): Purpose is always in the link performance
files; Market, Market x VOT and VOT bins (edges in $/hr) each write a
`link_volume_by_<kind>.csv` for Summarization > Link Performance. Each is about the
size of a link performance file.

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

Express Lanes (EL) and the parallel General-Purpose (GP) lanes are separate links.
Without the Enroute Choice tab, the router picks between them by generalized cost
(time + distance + toll ÷ VOT) like any other route. With it, the choice at each
coded decision node is the ELToD logit (next section).

Inside a **micro corridor** the *EL/GP choice* setting on the Micro sub-tab decides:

- **Enroute Choice** — each agent keeps the EL or GP route the
  assignment gave it (generalized cost, or the en-route logit where it ran).
- **Micro time-differential (VOT)** — the actual EL−GP travel-time difference from
  the lane-level micro sim, converted with **each agent's VOT** into an individual
  decision (the toll is worth it if VOT·Δtime ≥ toll).

### Enroute Choice tab

The ELToD 5 express-lane logit, run **inside** the HyDRA iterations with the
current congested times and dynamic tolls (`ENROUTE_CHOICE`). The checkbox turns
it on; four sub-tabs hold the settings: **Node & link types**, **Utility**,
**Constants & logs** and **Vehicle use** (the last applies even with the choice off).

**Where it runs.** Only where the node layer codes the decision and join nodes
(`DTA_Type`); with no 90 or no 94 node in the network it stays off.

| DTA_Type | Role |
|---|---|
| 90 (*Entry nodes*) | On the GP lanes: enter the express lanes or not. |
| 91 (*Exit nodes*) | On the express lanes: stay, or exit back to GP. |
| 94 (*Join nodes*) | Where the two alternatives meet again. |

- Each decision node is paired with the **nearest 94 node that both alternatives
  reach**, within *Join search (mi)*. `el_segments.csv` lists every pair and both
  paths; a decision node without a join is listed and makes no choice.
- The two alternatives from a decision node:
  - at a **90**: the express one starts on any *Express link type*; the GP one uses
    no express link.
  - at a **91**: the stay one starts on the express mainline (an express type that
    is not an *Access link type*); the exit one starts off it and never returns.
- A trip makes the logit choice only if its route passes **both** the decision node
  and its join. A trip that leaves or ends before the join has no common path to
  compare, so it keeps its generalized-cost route.
- Choices chain: a trip that enters at a 90 meets the 91 nodes further on and makes
  a stay-or-exit choice at each.

**The utility (ELToD 5).** Between the decision node and its join:

    U    = C(node, time) + scale × ( TF×(perceived_EL − perceived_GP)
                                     + KF×(toll_EL − toll_GP)
                                     + TF×RR×(reliability_EL − reliability_GP) )
    P_EL = 1 / (1 + e^−U)

- **TF and KF** come from each market segment's `beta_time` and `beta_cost` in the
  segment file, so every segment keeps its own VOT. Tolls are those the toll policy
  sets for that link and 15 minutes, times the axle factor.
- The **Utility** fields are the global ELToD parameters, with their ELToD names in
  the tooltips. *Perceived* time grows with v/c; *reliability* = time × (congested −
  free-flow time) × distance^−distance-exponent; *Max circuity* forces the shorter
  side when one alternative is that many times longer. The *Path* values build the
  two alternatives. *Express weight* is read but, as in ELToD 5, not used.
- **Constants file** (optional): `NODE_ID, HH:MM, CONSTANT`, rows at 15, 30 or
  60 minutes. A node's constant holds from its row's time until its next row; a node
  not in the file uses node 0's rows, and without node 0 the constant is 0.

**Who chooses what.** Each agent draws one random number per decision node, seeded
by its **household**, so the persons of a shared ride always choose together. A
choice changes between iterations only when P(EL) crosses the draw. The agents'
paths in `agentPaths.duckdb` are the version they chose.

**Vehicle use on no_trucks links.** *Barred classes* (`TRUCK_BAN`) applies to every
link with `no_trucks` = 1, whether or not the choice runs: medium and heavy trucks
(3+ axles, the default), heavy only (5+ axles), or none. A barred class makes no
express-lane choice.

**Outputs.**

| File | Rows |
|---|---|
| `el_segments.csv` | One per decision node: its join, status, both paths. |
| `el_choice_summary.csv` | Decision node × 15 min: trips, EL share, mean P(EL), EL/GP toll, congested time, free-flow time, length and speed. |
| `el_choice_log.csv` | *Log nodes* only: one row per route key and choice, with every utility term (ELToD's model-data file). |
| `el_choice_agents.csv` | *Log nodes* only: one row per agent and choice (hh, person, tour, trip, EL/GP, P, draw). |

*Log nodes* takes decision node ids or `ALL`; *Write* keeps the final pass or
appends every iteration.

ODME keeps the last split while it re-assigns. A static (STA) run has no per-agent
paths to split, so the choice does not run there.

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
