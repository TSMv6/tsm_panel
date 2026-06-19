# Long-Distance Travel — Florida Residents

This step runs the **long-distance** model for **Florida resident households**
(long trips, roughly 50+ miles one way). Like the Out-of-State model it is an
activity-based model with a **joint destination- and mode-choice** core, run over
the FL synthetic households.

---

## In-state vs. out-of-state travel

For each long-distance tour, a FL resident chooses a **destination zone** that may
be **inside Florida** or **anywhere in the U.S.** — the joint destination/mode model
weighs every candidate zone by its attractiveness and how reachable it is by each
mode. So the in-state vs. out-of-state split is an **outcome** of destination
choice, not a fixed input: short in-state trips tend to be auto, while distant
out-of-state destinations draw more air/rail.

### AL / GA cross-border commuters

Florida's land borders are **Alabama (state 1)** and **Georgia (state 13)** — set in
the control as `FLBorderState_1` and `FLBorderState_2`. Commute-purpose trips that
cross these borders (FL ↔ AL, FL ↔ GA) are shorter than typical long-distance trips
but still cross the state line, so they are handled as a **special cross-border
commuter market**: the GA/AL destination table supplies the cross-border
destinations, and these commuter trips are added during the trip-table step rather
than left to the generic long-distance destination choice.

---

## Model segmentation

| Dimension | Categories |
|---|---|
| **Purpose** | personal business · visit friends/relatives · leisure · commute · employer business |
| **Mode** (line-haul) | car · bus · rail · air |
| **Destination** | zone-level choice, nested by DMA / distance band; in-state (FL zones) and out-of-state (US zones) |
| **Party size** | 1 · 2 · 3 · 4+ travelers |
| **Tour mode** | the line-haul mode **plus** its auto **access/egress** legs (below) |

The tour cascade is the same as the OS model: **Auto Ownership → Tour Frequency &
Purpose → Nights Away → Party Size → Destination + Main Mode (joint) → Vehicle**.

---

## Access / egress and how auto trips are built

A long-distance tour by a **non-auto line-haul mode** (air, rail, bus) is not a
single trip — the traveler must reach the boarding point and leave the alighting
point. The tour therefore has **intermediate stops** at the stations/airports, and
the legs to/from them are made **by auto**:

```
origin ──auto access──▶ first station/airport ──line-haul (air/rail/bus)──▶
        last station/airport ──auto egress──▶ final destination
```

The trip-table step **converts each non-auto tour into auto trips on both ends**:

- **Auto access trip** — origin → **first station/airport** (board the line-haul).
- **Auto egress trip** — **last station/airport** → final destination.

The **access and egress ends are auto** (drive, or drop-off/pick-up); the line-haul
middle leg stays air/rail/bus. **Car tours** are auto end-to-end (no station legs).

### Share of auto travel computed

The auto trips that load the roadway network are the **sum of**:

1. **Direct car tours** — auto from origin to destination and back, and
2. **The auto access + egress legs** of every air/rail/bus tour (origin↔airport,
   airport↔destination).

So the computed **auto share** is not just the car-mode tours — it includes the
auto first/last-mile legs of the air/rail/bus tours, which is what actually shows up
on the highway and toll network.

---

## Configuration file

On **Run**, the dialog writes the LDT control file `<scenario>/LDT_resident.txt`
(same `KEY value` format as `LDT_FL_config.txt`). The fields you set are written in:

| GUI field | Control key |
|---|---|
| Input Directory | `InputDirectoryName` |
| Road / Rail / Air LOS (OMX) | `RoadLOSFileName` / `RailLOSFileName` / `AirLOSFileName` |
| Land-use (FL) | `ZoneLandUseFileName` |
| Syn HH (FL) | `HouseholdFileName` |
| Num of HHs | `numberOfHouseholds` |
| Output Dir | `OutputDirectoryName` |

Coefficients/constants come from `config/ldt_coefficients`
(`CoefficientDirectoryName`); the AL/GA border states are set by `FLBorderState_1`
(Alabama) and `FLBorderState_2` (Georgia).
