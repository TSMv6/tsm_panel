# Visitor Simulated Daily Travel (SDT)

The visitor SDT simulates travel by **out-of-region visitors** staying in Florida on
the simulation day. Like the resident model it is **tour-based** — each visiting
party's day is built as tours and trips — but the population is generated from
tourism data rather than synthetic resident households.

**Inputs:** zonal land use (`tsm_landuse.csv`) and the distance/level-of-service
skim. **Outputs:** visitor tour and trip records that feed the trip-table and
assignment steps.

---

## How visitors are generated

Visitor travel is driven by **VisitFL** tourism data, reported per **DMA**
(Designated Market Area — 8 in Florida). Annual VisitFL reporting supplies the
distributions used directly in the model: travel-party composition (size, age,
income), length of stay, mode of arrival (air vs. auto), top origin states, and
destinations by DMA.

**Lodging types** anchor where visitor parties stay, each with its own occupancy
rate (from DBPR and VisitFL):

- **Hotel rooms** (by DMA)
- **Staying with Florida residents** — resident households (by DMA)
- **Short-term rentals** — Airbnb / Vrbo and similar (by DMA)

---

## Tours, modes, and skims

Each visiting party's day is built as tours from its lodging location, with stops
and trips just like the resident model. For air arrivals, **rental-car egress
shares** for the major airports (e.g. OIA, MIA), collected by FDOT, are applied as
the egress mode from the airport to the lodging/destination zone.

The **skim** (produced by the Skimmy step) provides the distances used throughout;
the `DISTANCE` table is required.

> **Tip:** Resident and Visitor can be run together (one run, shared skim read) or
> independently — use the **Models to run** checkboxes.
