
#----------------------------------------------------------------------------------------------
library(tidyverse)
library(data.table) 
library(sf)

# Read Arguments
args            <- commandArgs(trailingOnly = TRUE)
print(args)

#----------------------------------------------------------
# Read Properties

# Function to read the settings file and parse arguments
read_properties <- function(file_path) {
  # Read file lines
  settings <- readLines(file_path)
  
  # Create an empty list to store parsed values
  settings_list <- list()
  
  # Loop through each line to extract key-value pairs
  for (line in settings) {
    # Remove whitespace and split by '='
    parts <- strsplit(trimws(line), "=", fixed = TRUE)[[1]]
    
    if (length(parts) == 2) {
      key <- trimws(parts[1])
      value <- trimws(parts[2])
      
      # Remove double quotes if present
      value <- gsub('\\"', '', value)
      
      # Convert numeric values where applicable
      if (grepl("^[0-9]+$", value)) {
        value <- as.numeric(value)
      }
      
      # Store in list
      settings_list[[key]] <- value
    }
  }
  
  return(settings_list)
}
#----------------------------------------------------------

replace_NA = function(DT) {
  for (j in names(DT))
    set(DT,which(is.na(DT[[j]])),j,0)
}

#----------------------------------------------------------
# settings_file <- args[1]
# settings_file <-   "C:/TSM_NextGen_v6/Base/TSMv6_2024/settings_PopSim.txt"
# settings <- read_properties(settings_file)
# print(settings)
# landuse_layer_path     <- settings$landuse_layer_path
# tsm_location           <- settings$tsm_location
# scenario_directory     <- settings$scenario_directory
# bool_run_incremental   <- settings$str_bool_run_incremental
# ref_landuse_layer_path <- settings$ref_landuse_layer_path
# bool_GQ_in_POP         <- settings$str_bool_GQ_in_POP


# landuse_layer_path     <- "M:/Models/StateWide/TSM_NextGen/900 CAD GIS Modeling/940 Modeling/working_dir/SE_Data/v5.0/v4/TSMv5_MPO_full_2035.GPKG"
# tsm_location           <- "C:/TSM_NextGen_v5"
# scenario_directory     <- "C:/TSM_NextGen_v5/Base/TSMv5_default"
# bool_run_incremental   <- "TRUE"
# ref_landuse_layer_path <- "M:/Models/StateWide/TSM_NextGen/900 CAD GIS Modeling/940 Modeling/working_dir/SE_Data/v5.0/v1/TSMv5_MPO_full_2023.GPKG"
# bool_GQ_in_POP <- "TRUE"

landuse_layer_path     <- args[1]
tsm_location           <- args[2]
scenario_directory     <- args[3]
bool_run_incremental   <- args[4]
ref_landuse_layer_path <- args[5]
bool_GQ_in_POP         <- args[6]

# if(bool_GQ_in_POP %in% c("true", "TRUE", "True")) {
#   str_bool_GQ_in_POP <- TRUE
# } else{
#   str_bool_GQ_in_POP <- FALSE
# }
# 
# if(bool_run_incremental %in% c("true", "TRUE", "True")) {
#   str_bool_run_incremental <- TRUE
# } else{
#   str_bool_run_incremental <- FALSE
# }


# Input from POPSIM directory
popSIM_ctl_file      <- paste0(tsm_location, "/PopSim/Florida/Setup/configs/HH/controls_standard.csv")
geocrosswalk_state_file         <- paste0(tsm_location, "/PopSim/Florida/Setup/data/TSM_geo_Crosswalk_Statewide.csv")

# Outfile to popsim data directory
popSIM_lu_file       <- paste0(tsm_location, "/PopSim/Florida/Setup/data/SE_data.csv")
GQ_CW_file           <- paste0(tsm_location, "/PopSim/Florida/Setup/data/TSM_GQ_geo_Crosswalk.csv")
geocrosswalk         <- paste0(tsm_location, "/PopSim/Florida/Setup/data/TSM_geo_Crosswalk.csv")


# Get popsim required fields
popSIM_ctl_fields <- fread(popSIM_ctl_file)
ctl_fields <- c("TAZ", popSIM_ctl_fields$control_field, "Group_quarters_pop_noninstitutionalized")

dt <- st_read(landuse_layer_path) %>% setDT()
dt[, geom := NULL]
setnames(dt, "TSM_NG", "TAZ")  # TSMv5
# setnames(dt, "tsm_id", "TAZ") 


# if GQ is included in POP, remove it 
if(bool_GQ_in_POP){
  dt[, POP_wo_GQ := POP - GQ ]
  dt[POP_wo_GQ < 0, POP_wo_GQ := 0 ]
  setnames(dt, c("POP", "POP_wo_GQ"), c("TotPOP", "POP"))
}

replace_NA(dt)
aggr_cols <- c(popSIM_ctl_fields$control_field, "Group_quarters_pop_noninstitutionalized")

dt_tsm <-  dt[, lapply(.SD, sum), .SDcols = aggr_cols, by = "TAZ"]
  
# For GQ keep only the PUMA that have GQ
dt_cw <- fread(geocrosswalk_state_file)

# Function to compute differences
getDiff <- function(dt_tsmfut, dt_tsmbase){
  dt_tsmbase <- melt(dt_tsmbase[, ..ctl_fields], id.vars = c( "TAZ"))
  dt_tsmfut <- melt(dt_tsmfut[, ..ctl_fields], id.vars = c( "TAZ"))
  dt_delta <- merge(dt_tsmfut, dt_tsmbase, by = c("TAZ", "variable"))
  dt_delta[, diff := round(value.x - value.y, 0)]
  dt_delta <- dt_delta[diff > 0, c("TAZ", "variable", "diff")]
  dt_delta <- dcast(dt_delta, TAZ ~ variable, value.var = "diff", fill = 0)
  
  return(dt_delta)
}

if(bool_run_incremental){
  
  # ref_landuse_layer_path <- paste(CFL_SE_dir, "TSMv5_MPO_full_2023.GPKG", sep = "/")
  
  dt_ref <- st_read(ref_landuse_layer_path) %>% setDT()
  dt_ref[, geom := NULL]
  setnames(dt_ref, "TSM_NG", "TAZ")
  replace_NA(dt)
  
  if(bool_GQ_in_POP){
    dt_ref[, POP_wo_GQ := POP - GQ ]
    dt_ref[POP_wo_GQ < 0, POP_wo_GQ := 0 ]
    setnames(dt_ref, c("POP", "POP_wo_GQ"), c("TotPOP", "POP"))
  }
  
  dt_ref_tsm <-  dt_ref[, lapply(.SD, sum), .SDcols = aggr_cols, by = "TAZ"]
  
  dt_delta <- getDiff(dt_tsm, dt_ref_tsm)
  
  # Add missing GQ field to delta table
  if(!("Group_quarters_pop_noninstitutionalized" %in% colnames(dt_delta))) {
    dt_delta[,Group_quarters_pop_noninstitutionalized := 0]
  }
  
  # dt_delta[, lapply(.SD, sum), .SDcols = c("POP", "TotHH")]
  fwrite(dt_delta, popSIM_lu_file)
  
  # Write a cross walk files only for the ones needed
  GQ_TAZ <- dt_delta[Group_quarters_pop_noninstitutionalized > 0, TAZ]
  # dt_gq_cw <- dt_cw[TAZ %in% GQ_TAZ, ]
  # fwrite(dt_gq_cw, GQ_CW_file)
  TAZ_with_POP <- dt_delta[POP > 0, TAZ]
  
} else {
  dt_tsmbase <- dt[POP > 0, ..ctl_fields]
  
  # Fix decimals issue (should be integers)
  num_cols <- names(dt_tsmbase)[sapply(dt_tsmbase, is.numeric)]
  dt_tsmbase[, (num_cols) := lapply(.SD, as.integer), .SDcols = num_cols]

  dt_tsmbase <-  dt_tsmbase[POP > 0, lapply(.SD, sum), .SDcols = aggr_cols, by = "TAZ"]
  
  fwrite(dt_tsmbase, popSIM_lu_file)
  
  GQ_TAZ <- dt_tsmbase[Group_quarters_pop_noninstitutionalized > 0, TAZ]
  TAZ_with_POP <- dt_tsm[POP > 0, TAZ]

}

# Write Cross walk files for zones with either GQ or POP
dt_gq_cw <- dt_cw[TAZ %in% GQ_TAZ, ]
fwrite(dt_gq_cw, GQ_CW_file)

dt_pop_cw <- dt_cw[TAZ %in% TAZ_with_POP, ]
fwrite(dt_pop_cw, geocrosswalk)

