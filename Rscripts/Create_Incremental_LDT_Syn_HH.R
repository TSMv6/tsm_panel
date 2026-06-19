library(data.table)
library(tidyverse)

args            <- commandArgs(trailingOnly = TRUE)
print(args)


# Input files
syn_us_all_file <- args[1] # FL Syn HH file
scenario_year <- args[2] # FL Households, output for SDT - Residents 
reference_year <- args[3]
output_LDT_Syn <- args[4] # Output FL Syn HH file

# syn_us_all_file <- "C:/TSM_NextGen_v5/Inputs/LDT_Skims_LU_SynHH/TSMv5_LDT_OS_Syn_HH_All_Years.csv.gz"
# scenario_year   <- "2045"
# reference_year  <- "2023"
# output_LDT_Syn  <- "C:/TSM_NextGen_v5/Base/TSMv5_default/LDT_OS_Syn_hh.dat"

dt_US_hh <- fread(syn_us_all_file)
# run incrementally
if(scenario_year > reference_year){
  dt_hh <- dt_US_hh[(Year > (as.integer(reference_year) - 2000)) & (Year <= (as.integer(scenario_year) - 2000)) & hhnuma > 8721, ]
  
}

# run absolute till this year: ex: 2023 or 2024
if(scenario_year == reference_year){
  dt_hh <- dt_US_hh[(Year <= (as.integer(scenario_year) - 2000)) & hhnuma > 8721, ]
}


dt_hh[ ,Year := NULL]
dt_hh[, c("avgWorkDist", "totWorkDist") := list(0,0)]

dt_hh <- dt_hh[order(hhnuma), ]
dt_hh[, hhid := c(1:.N)]
fwrite(dt_hh, output_LDT_Syn, sep = "\t")
