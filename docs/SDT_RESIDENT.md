# Resident Simulated Daily Travel (SDT)

The resident SDT is an **activity- and tour-based microsimulation** of a typical
weekday for every synthetic household and person in the region. Instead of moving
zone-to-zone trip tables, it builds each person's **day as a chain of tours**, and
each tour as a sequence of **trips** linked by **stops**. Because travel is modeled
per person and per tour, it responds realistically to household structure, auto
availability, time of day, tolls, and value of time.

**Inputs:** synthetic households + persons (from PopSyn), zonal land use
(`tsm_landuse.csv`), and the distance/level-of-service skim. **Outputs:** household,
person, tour, and trip records that feed the trip-table and assignment steps.

---

## How a tour-based model works

A **tour** is a closed loop that starts and ends at an anchor (usually home), e.g.
*home → work → home*. Tours can carry intermediate **stops** (*home → daycare →
work → store → home*), and each leg between stops is a **trip** with its own mode.

The phases run **in sequence**, and each one **conditions** the next: auto
ownership shapes mode choice; the chosen primary destination and time of day
constrain where and when stops can be added; stops define the individual trips.
This conditioning is why the phases must normally run together.

---

## What each phase does

- **Work from Home** — decides which workers work from home on the simulation day,
  removing their commute. Reflects the selected telework policy share.
- **Auto Ownership** — number of vehicles available to each household.
- **Vehicle Type** — the body type/age class of each household vehicle, used for
  operating cost, toll, and value-of-time effects.
- **Mandatory** — generation, primary destination, time of day, and mode for the
  **anchor tours**: work and school. These are scheduled first because they frame
  the rest of the day.
- **Tour** — generation, destination, time of day, and mode for **non-mandatory**
  tours (shopping, personal business, social/recreation, escort).
- **Stop** — how many intermediate stops each tour has, **where** they are, and
  **when** — turning each tour into a realistic multi-stop chain.
- **Trip** — mode and details for each individual trip between stops, producing the
  final trip records.

---

## Running specific phases

By default **Run all phases** is on and the individual phases are locked — this is
the correct setting for a full model run, because each phase depends on the ones
before it. Uncheck **Run all phases** only when you want to **re-run or report on a
specific phase** while reusing the upstream results (for diagnostics or calibration
reporting). Selecting a downstream phase without its prerequisites will not produce
a valid full-day result.

> **Tip:** Resident and Visitor can be run together (one run, shared skim read) or
> independently — use the **Models to run** checkboxes.
