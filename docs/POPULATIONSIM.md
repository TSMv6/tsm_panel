# PopulationSIM — population synthesis

PopulationSIM builds a **synthetic population** of households and persons that
matches the zonal control totals in the land-use data while preserving the rich
attribute detail of the survey (PUMS) seed. Every modeled person in SDT and LDT
comes from this synthetic population.

**Standard run:** land-use data (households + population with sub-category
controls) → **synthesized households** and **synthesized persons**.

---

## How the balancing works (and what changed)

Population synthesis reweights the seed records so that, aggregated to each zone,
they reproduce the control totals (households, persons, income, size, workers,
age, etc.). The method used to find those weights is what sets this version apart.

**This version — sequential Sinkhorn list balancing.** Controls are satisfied one
at a time, sweeping repeatedly (iterative proportional fitting on the seed list).
It is the same family of robust, list-based balancing used in **PopSyn-III**, the
most widely used population synthesizer in travel modeling. It scales to the
statewide control set and converges reliably.

**Previous TSM versions (v5 and older)** relied on the older Anaconda/Python
PopulationSIM, which used a **simultaneous balancer (Newton–Raphson)**. In
principle a simultaneous solver should converge quickly, but for the TSM control
set it did not: the Python inverse-matrix (Jacobian) computation was very slow and
the solution **oscillated** rather than settling, so it failed to converge. The
sequential Sinkhorn balancer replaces that approach and removes the Anaconda/Python
dependency entirely.

---

## Group Quarters (GQ)

PopulationSIM is run twice — once for households (HH) and once for Group Quarters
(GQ) — and the two are merged. GQ uses its own count control so GQ population is
synthesized separately from the household population and combined into the final
files.

---

## Incremental run

An incremental run synthesizes only the **delta** between a base-year and a
future-year land use — and only for the household/population count control, not the
full sub-category control set. Building that delta land use is handled by a
separate utility; the incremental run then applies PopulationSIM to just those
changes and updates the existing synthetic population accordingly.
