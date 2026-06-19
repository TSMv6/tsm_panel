# agentPlans config — fixed distributions & lookups

These are the **config** files the agentPlans (Trip List -> Table) step reads — not
per-scenario inputs. They are bundled with the plugin so the GUI is self-contained.
Place the following CSVs here (the dialog references this folder, config/agentPlan/):

- tod_distributions.csv          (time-of-day shares)
- external_auto_shares.csv
- airport_shares.csv
- canaveral_cruise.csv
- ga_al_ldt_destinations.csv     (GA/AL crossborder destinations)
- cbm_external_lookup.csv
- Florida_Zones_appended_STL_TSMv4.csv   (taz_dma)   [bundled]
- TSMv5_Truck_ODME_TT.csv        (truck ODME matrix; large — place here or symlink)

The per-scenario INPUTS (SDT/LDT demand, distance skim, synthetic households) are
chosen in the dialog's "Input files" list and are NOT kept here.
