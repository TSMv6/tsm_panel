
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
      value <- gsub('\"', '', value)
      
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
# settings_file <-   "C:/Projects/temp_geoMaster_coding/r_script_subarea_settings.txt"
# settings_file <- args[1]
# print(settings_file)
# settings <- read_properties(settings_file)

landuse_layer_path     <- args[1]
tsm_location           <- args[2]
scenario_directory     <- args[3]
bool_run_incremental   <- args[4]
ref_landuse_layer_path <- args[5]

popSIM_ctl_file      <- paste0(tsm_location, "/PopSim/Florida/Setup/configs/HH/controls_standard.csv")
popSIM_lu_file       <- paste0(tsm_location, "/PopSim/Florida/Setup/Setup/data/SE_data.csv")
  
# CFL_SE_dir <- "M:/Models/StateWide/TSM_NextGen/900 CAD GIS Modeling/940 Modeling/working_dir/SE_Data/v5.0/v1"
# landuse_layer_path <- paste0(CFL_SE_dir, "TSMv5_MPO_full_2035.GPKG", sep = "/")

# Get popsim required fields
popSIM_ctl_fields <- fread(popSIM_ctl_file)
ctl_fields <- c("TAZ", popSIM_ctl_fields$control_field, "Group_quarters_pop_noninstitutionalized")

dt <- st_read(landuse_layer_path) %>% setDT()
dt[, geom := NULL]

# Function to compute differences
getDiff <- function(dt_tsmfut, dt_tsmbase){
  dt_tsmbase <- melt(dt_tsmbase[, ..ctl_fields], id.vars = c( "TAZ"))
  dt_tsmfut <- melt(dt_tsmfut[, ..ctl_fields], id.vars = c( "TAZ"))
  dt_delta <- merge(dt_tsmfut, dt_tsmbase, by = c("TAZ", "variable"))
  dt_delta[, diff := value.x - value.y]
  dt_delta <- dt_delta[diff > 0, c("TAZ", "variable", "diff")]
  dt_delta <- dcast(dt_delta, TAZ ~ variable, value.var = "diff", fill = 0)
  
  return(dt_delta)
}

if(bool_run_incremental){
  
  ref_landuse_layer_path <- paste0(CFL_SE_dir, "TSMv5_MPO_full_2023.GPKG", sep = "/")
  
  dt_ref <- st_read(landuse_layer_path) %>% setDT()
  dt_ref[, geom := NULL]
  dt_delta <- getDiff(dt, dt_ref)
  # dt_delta[, lapply(.SD, sum), .SDcols = c("POP", "TotHH")]
  fwrite(dt_delta, popSIM_lu_file)
} else{
  
  fwrite(dt_tsmbase, popSIM_lu_file)
}

