library(data.table)
library(tidyverse)

args            <- commandArgs(trailingOnly = TRUE)
print(args)


# Input files
incremental_output <- args[1] # scenario specific incremental LDT output
user_reference     <- args[2] # true or false 
user_ref_file      <- args[3] # previous year file user supplied
tsm_location       <- args[4] # to append default data
scenario_dir       <- args[5]
scenario_year      <- as.integer(args[6])

# incremental_output <- "C:/TSM_NextGen_v5/Base/TSMv5_default/OS_LD_increment_tour_out.csv"
# user_reference <- F
# user_ref_file <- "C:/TSM_NextGen_v5/Base/TSMv5_2023/US_LD_tour_out.csv"
# tsm_location <- "C:/TSM_NextGen_v5"
# scenario_dir <- "C:/TSM_NextGen_v5/Base/TSMv5_default"
# scenario_year <- 2045

# Base Year, absolute is increment copy
if(scenario_year == 2023){
  file.copy(from = paste0(scenario_dir, "/OS_LD_increment_tour_out.csv"),
            to   = paste0(scenario_dir, "/OS_LD_tour_out.csv"), overwrite = T)
} else {

  # If no reference year, read previous incremental output
  if(!user_reference %in% c("T", "true", "True")) {
    
    # read outputs from previous incrementally run LDT model
    if(scenario_year > 2023){
      dt_prev     <- fread(paste0(tsm_location, "/Inputs/LDT_Incremental_Output/LD_tour_out_2023.csv"))
    }
    if(scenario_year > 2035){
      dt_prev     <- rbindlist(list(dt_prev,
                                    fread(paste0(tsm_location, "/Inputs/LDT_Incremental_Output/LD_tour_out_2035.csv"))))
    }
    if(scenario_year > 2045){
      dt_prev     <- rbindlist(list(dt_prev,
                                    fread(paste0(tsm_location, "/Inputs/LDT_Incremental_Output/LD_tour_out_2045.csv"))))
    }
    if(scenario_year > 2055){
      dt_prev     <- rbindlist(list(dt_prev,
                                    fread(paste0(tsm_location, "/Inputs/LDT_Incremental_Output/LD_tour_out_2055.csv"))))
    }

  } else {
    # Reference year provided by user
    dt_prev <- fread(user_ref_file)
  }

  previous_output <- paste0(scenario_dir, "/LD_tour_out_previousYears.csv")
  fwrite(dt_prev, previous_output)


  dt_increment_tours <- fread(incremental_output)
  dt_appended <- rbindlist(list(dt_increment_tours, dt_prev), use.names = T, fill = T)

  future_output <- paste0(scenario_dir, "/OS_LD_tour_out.csv")
  fwrite(dt_appended, future_output)

}



