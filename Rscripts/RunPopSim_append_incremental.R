
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
settings_file <- args[1]
# settings_file <-   "C:/TSM_NextGen_v5/Base/TSMv5_default/settings_PopSim.txt"
# settings_file <- "C:/Users/kn815vs/OneDrive - Florida Department of Transportation/FTE TSM v5/Base/Base Year 2023/settings_PopSim.txt"
settings <- read_properties(settings_file)
print(settings)

# landuse_layer_path     <- "M:/Models/StateWide/TSM_NextGen/900 CAD GIS Modeling/940 Modeling/working_dir/SE_Data/v5.0/v1/TSMv5_MPO_full_2035.GPKG"
# tsm_location           <- "C:/TSM_NextGen_v5"
# scenario_directory     <- "c"
# bool_run_incremental   <- TRUE
# ref_landuse_layer_path <- "M:/Models/StateWide/TSM_NextGen/900 CAD GIS Modeling/940 Modeling/working_dir/SE_Data/v5.0/v1/TSMv5_MPO_full_2023.GPKG"
# 
# synHH_path     <- "C:/TSM_NextGen_v5/Base/TSMv5_default/synthetic_households_35.csv" # Final output
# synPer_path    <- "C:/TSM_NextGen_v5/Base/TSMv5_default/synthetic_persons_35.csv"    # Final output
# refSynHH_path  <- "C:/TSM_NextGen_v5/Base/TSMv5_default/synthetic_households_23.csv"
# refSynPer_path <- "C:/TSM_NextGen_v5/Base/TSMv5_default/synthetic_persons_23.csv"

# landuse_layer_path     <- args[1]
# tsm_location           <- args[2]
# scenario_directory     <- args[3]
# bool_run_incremental   <- args[4]
# ref_landuse_layer_path <- args[5]
# synHH_path             <- args[6]
# synPer_path            <- args[7]
# refSynHH_path          <- args[8]
# refSynPer_path         <- args[9]

landuse_layer_path     <- settings$landuse_layer_path
tsm_location           <- settings$tsm_location
scenario_directory     <- settings$scenario_directory
bool_run_incremental   <- settings$str_bool_run_incremental 
ref_landuse_layer_path <- settings$ref_landuse_layer_path
synHH_path             <- settings$synHH_path
synPer_path            <- settings$synPer_path
refSynHH_path          <- settings$refSynHH_path
refSynPer_path         <- settings$refSynPer_path
bool_GQ_in_POP         <- settings$str_bool_GQ_in_POP

popSIM_combined_dir <- paste0(tsm_location, "/PopSim/Florida/Setup/output/Combined")
popSIM_combined_HH <-  paste0(popSIM_combined_dir, "/synthetic_households.csv")
popSIM_combined_PER <-  paste0(popSIM_combined_dir, "/synthetic_persons.csv")

# Read POPSIM outfile
dt_pop_temp <- fread(popSIM_combined_PER)
dt_hh_temp <- fread(popSIM_combined_HH)

if(bool_run_incremental %in% c("TRUE", "true", "T")){
  # Read reference households and person 
  dt_pop_ref <- fread(refSynPer_path)
  dt_hh_ref <- fread(refSynHH_path)
  max_hhid <- dt_hh_ref[, max(household_id)]
  
  pop_fnames <- colnames(dt_pop_ref)
  hh_fnames <- colnames(dt_hh_ref)
  
  # update hh id in households & persons tables
  setnames(dt_hh_temp, "household_id", "old_hhid")
  dt_hh_temp[, household_id := .I + max_hhid]
  
  setnames(dt_pop_temp, "household_id", "old_hhid")
  dt_pop_temp <- merge(dt_pop_temp, dt_hh_temp[, c("household_id", "old_hhid")], by = "old_hhid", all.x = T)
  
  #=============================================================================
  # Remove decremented population 
  dt <- st_read(landuse_layer_path) %>% setDT()
  setnames(dt, "TSM_NG", "TAZ")
  replace_NA(dt)
  
  dt_ref <- st_read(ref_landuse_layer_path) %>% setDT()
  setnames(dt_ref, "TSM_NG", "TAZ")
  replace_NA(dt_ref)
  
  # if GQ is included in POP, remove it 
  if(bool_GQ_in_POP){
    dt[, POP_wo_GQ := POP - GQ ]
    dt[POP_wo_GQ < 0, POP_wo_GQ := 0 ]
    setnames(dt, c("POP", "POP_wo_GQ"), c("TotPOP", "POP"))
    
    dt_ref[, POP_wo_GQ := POP - GQ ]
    dt_ref[POP_wo_GQ < 0, POP_wo_GQ := 0 ]
    setnames(dt_ref, c("POP", "POP_wo_GQ"), c("TotPOP", "POP"))
  }
  
  dt_tsm <-  dt[, lapply(.SD, sum), .SDcols = c("TotHH", "POP", "GQ"), by = "TAZ"]
  dt_ref_tsm <-  dt_ref[, lapply(.SD, sum), .SDcols = c("TotHH", "POP", "GQ"), by = "TAZ"]
  
  dt_tsm_compare <- merge(dt_ref_tsm, dt_tsm, by = "TAZ", all = T)
  replace_NA(dt_tsm_compare)
  dt_tsm_compare[, c("POP.diff", "HH.diff", "GQ.diff") := list(POP.x - POP.y,
                                                               TotHH.x - TotHH.y,
                                                               GQ.x - GQ.y)]
  
  # remove the households
  dt_hh_to_remove <- dt_tsm_compare[HH.diff > 1 , c("TAZ", "HH.diff")]
  # if(nrow(hh_to_remove) > 0 ) {
  if (!is.null(nrow(dt_hh_to_remove)) & nrow(dt_hh_to_remove) > 0 ){
    zones <- dt_hh_to_remove$TAZ
    for(t in zones){
      size = dt_hh_to_remove[TAZ == t, ceiling(HH.diff)]
      x <- dt_hh_ref[TAZ == t,  household_id]
      if(length(x) > 0){
        hh_to_remove <- sample(x, size)
        dt_hh_ref <- dt_hh_ref[!(household_id %in% hh_to_remove), ]
      }
    }
    dt_pop_ref <- dt_pop_ref[household_id %in% dt_hh_ref$household_id, ]
  }
  #=============================================================================
  # Append incremental 
  dt_pop_appened <- rbindlist(list(dt_pop_ref, dt_pop_temp[, ..pop_fnames]), use.names = T, fill = T)
  dt_hh_appended <- rbindlist(list(dt_hh_ref, dt_hh_temp[, ..hh_fnames]), use.names = T, fill = T)
  
  fwrite(dt_pop_appened, synPer_path)
  fwrite(dt_hh_appended, synHH_path)
  
} else{
  fwrite(dt_pop_temp, synPer_path)
  fwrite(dt_hh_temp, synHH_path)
  
}



