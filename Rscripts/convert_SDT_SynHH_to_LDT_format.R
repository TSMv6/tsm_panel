library(data.table)
library(tidyverse)

args            <- commandArgs(trailingOnly = TRUE)
print(args)

# Use FL Syn Houhseolds for LDT Res model
# Update Auto Ownership first for SDT Syn households
# Input files
syn_fl_all_file <- args[1] # FL Syn HH file
syn_fl_veh_file <- args[2] # FL Households, output for SDT - Residents 
LDT_households_template <- args[3]
output_FL_Syn <- args[4] # Output FL Syn HH file

# TSM v4 popsim file (FL state)
# syn_fl_all_file <- "C:/TSM_NextGen_v5/Base/TSMv5_2035//CFL_Update_TSM_synthetic_households_35.csv" # PopSIM output
# syn_fl_veh_file <- "C:/TSM_NextGen_v5/Base/TSMv5_2035/households_1.csv" # Post model run auto ownership for FL
# LDT_households_template <- "C:/Users/kn815vs/AppData/Roaming/QGIS/QGIS3/profiles/default/python/plugins/tsm_panel/templates/ldt_syn_hh_template.dat"
# output_FL_Syn <- "C:/TSM_NextGen_v5/Base/TSMv5_default/LDT_FL_Syn_hh.dat"

dt_AO <- fread(syn_fl_veh_file)
dt_hh <- fread(syn_fl_all_file)

dt_ldt_template <- fread(LDT_households_template)

# Update autos
dt_hh <- merge(dt_hh, dt_AO[, c( "hh_id", "autos")], by.x = "household_id", by.y = "hh_id", all.x = T)

dt_hh[ , VEH := autos]
dt_hh[VEH > 4, VEH := 4]
dt_hh[, autos := NULL]

dt_hh <- dt_hh[, c("BLD", "hh_id_pums", "HH") := NULL] 
dt_hh[, c("avgWorkDist", "totWorkDist") := list(0,0)]
sdt_names <- colnames(dt_hh)

# dt_nh_v4[ ,Year := 23]
ldt_names <- colnames(dt_ldt_template)
setnames(dt_hh, sdt_names, ldt_names)

dt_hh[, hhincome := as.integer(hhincome)]
dt_hh <- dt_hh[order(hhnuma), ]
dt_hh[, hhid := c(1:.N)]

fwrite(dt_hh, output_FL_Syn, sep = "\t")





