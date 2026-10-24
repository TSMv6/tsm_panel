# Signal timing packs

A timing pack carries signal timing between GMNS packages. It is three CSVs.
Movements are keyed by node, from node and to node. Those ids come from the
GeoMaster, so a pack still loads after netPrep rebuilds the package (the
package's own `mvmt_id` changes on every rebuild).

| File | Columns |
|---|---|
| `signal_timing_plan.csv` | `timing_plan_id`, `controller_id`, `timeday_id` (blank = all day, or `HH:MM-HH:MM`, which may wrap midnight), `cycle_length`, `offset`, `name` (optional) |
| `signal_timing_phase.csv` | `timing_plan_id`, `signal_phase_num`, `ring`, `barrier`, `position`, `min_green`, `max_green` (the fixed-time green), `clearance` (yellow + all-red), `walk_time`, `ped_clearance` |
| `signal_phase_mvmt.csv` | `timing_plan_id`, `signal_phase_num`, `node_id`, `ib_from_node_id`, `ob_to_node_id`, `protection` (`protected` / `permitted`), `mvmt_code` (informational) |

**Load:** HyDRA dialog > Meso / Micro > GMNS > **Import timing pack...**, then
pick the pack folder. The import replaces the timing of every node a pack
controller drives. Loading the same pack again gives the same result.
**Export plans...** in the Signal timing dialog writes a controller's plans as
a pack.

## One controller, several nodes

On a divided road, one intersection is two to four GMNS nodes: one per
carriageway, joined by short median links. netPrep seeds each node with its
own plan. In a pack, one controller drives all of those nodes: its phases list
movements at every node.

How the median movements are timed:
- A movement that starts on a median link gets the phases of the movements
  feeding it. For example, at Mercy Dr the EB left enters the median at the EB
  node, then crosses the WB lanes as the WB node's `NBT`. That `NBT` runs in
  Ø5 (EB left arrow) and Ø4 (Mercy NB).
- A left turn that is only permitted crosses into the median and waits there
  for the next phase that clears the far carriageway.

The engine handles controllers like this:
- **Micro:** the controller's plan drives each node it lists, and replaces any
  seeded plan left on those nodes.
- **Macro / meso:** each approach link gets the green of its phases.

## `colonial_dr`: W Colonial Dr (SR 50), Orange County

Five controllers. Main street phases: Ø2 EB through, Ø6 WB through, Ø5 EB
left, Ø1 WB left. Cross street: Ø4 NB, Ø8 SB. Clearance is 6 s (4 s yellow +
2 s all-red).

The all-day plans run a 120 s cycle and are coordinated for EB progression at
45 mph. Offsets are measured from Hiawassee to where each EB through green
starts.

| Controller (nodes) | Location | Demonstrates | Cycle | Offset |
|---|---|---|---|---|
| 43118626 (+929334196, 929328224) | N Hiawassee Rd | **Time-of-day plans.** EB leading advance: Ø5 runs beside Ø2, then Ø6. WB and Hiawassee lefts are permitted. Plans: midday 09:00-15:30 (120 s, the base plan), AM 06:30-09:00 (150 s), PM 15:30-19:00 (150 s, longer EB left), night 19:00-06:30 (90 s). | 120/150/150/90 | 0 |
| 43129002 (+43129003) | N Pine Hills Rd | **Lead-lag lefts:** the EB left arrow leads, the WB left arrow lags, both protected only. **Split phasing** on Pine Hills (NB, then SB). | 120 | 18 |
| 43129307 | Mid-block crossing | **Pedestrian phase**: 7 s walk + 17 s flashing don't walk every cycle. | 120 | 61 |
| 43129371 (+43129372) | Fairvilla Rd | **Two-phase**, every left permitted (gap acceptance). | 120 | 91 |
| 43129377 (+43129378) | Mercy Dr | **Protected-permitted lefts**, lead-lead (Ø1 + Ø5 first); Mercy permitted. | 120 | 86 |

Built against the TSMv6 2024 network (navteq_2024 GeoMaster).

### Running it

1. Draw a polygon over the corridor between Hiawassee and Mercy. Include both
   carriageways and the cross streets.
2. Pick the polygon as **Micro area**, tick **Micro corridor**, and set
   **Micro model** to *Network (GMNS)*.
3. Run, with **Build visualizer layers** on.
4. Compare the movement and intersection LOS against a run on the seeded plans.

On the test run (Orange Co., a 2-iteration DTA, the EB carriageway area):
- Mid-block crossing: delay fell from 7.2 s to 0.1 s, because EB platoons
  arrive on green.
- Fairvilla: 13.4 s to 5.7 s.
- Mercy: 21.7 s to 17.7 s.
- Pine Hills EB left: LOS F. A 03:30 burst of 33 left-turners hits the 12 s
  protected-only arrow; the rest of the day averages ~52 s, close to the 49 s
  uniform-delay theory. Making it protected-permitted, or lengthening Ø5, is
  the obvious next edit to try in the Signal timing dialog.
