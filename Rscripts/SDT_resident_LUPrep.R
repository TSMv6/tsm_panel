
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
      value <- gsub('//"', '', value)
      
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
# landuse_layer_path     <- "M:/Models/StateWide/TSM_NextGen/900 CAD GIS Modeling/940 Modeling/working_dir/TSMv5_workingDir/QGIS_netedit/demo_files/Landuse/TSMv5_MPO_full_2023.gpkg"
# tsm_landuse_path       <- "C:/TSM_NextGen_v5/Base/TSMv5_2023/parking_to_discretionary_issue/tsm_landuse.csv"
# tsm_default_data       <- "C:/Users/kn815vs/AppData/Roaming/QGIS/QGIS3/profiles/default/python/plugins/tsm_panel/Rscripts/tsm_landuse_default.csv"
# landuse_layer_path     <-  "M:/Models/StateWide/TSM_NextGen/900 CAD GIS Modeling/940 Modeling/working_dir/SE_Data/v6.0/v1/Final Result/TSM_updated_2024_Final_TSMv5Compatible.gpkg"
# tsm_landuse_path       <- "C:/TSM_NextGen_v6/Base/TSMv6_2024_fullrun/tsm_landuse.csv"
# 

landuse_layer_path   <- args[1]
tsm_landuse_path     <- args[2]
tsm_default_data     <- args[3]

dt_mpo <- st_read(landuse_layer_path)%>% setDT()
setnames(dt_mpo, c("TSM_NG", "EMP"), c("TAZ", "totEMP"))

dt_mpo[, c("geom", "TAZ_REG", "PopSyn_Index", "County", "District") := NULL]

dt_default <- fread(tsm_default_data)

required_fields <- colnames(dt_default)
mpo_data_fields <- colnames(dt_mpo)
mpo_data_fields <- mpo_data_fields[!(mpo_data_fields %in% "TAZ")]

# Get other fields
default_fields <- required_fields[!(required_fields %in% mpo_data_fields)]

# Check and remove "Model" field
mpo_data_fields <- mpo_data_fields[!(mpo_data_fields %in% c("MODEL", "Model", "model"))]
# TODO check all character fields and remove them

dt_mpo_aggregate <- dt_mpo[, lapply(.SD, sum), by = "TAZ", .SDcols = mpo_data_fields]

# Integerize (remove decimals if any)
dt_mpo_aggregate <- dt_mpo_aggregate[, lapply(.SD, as.integer), .SDcols = is.numeric]

dt_mpo_aggregate <- merge(dt_mpo_aggregate, dt_default[, ..default_fields], by = "TAZ", all.x = T)
replace_NA(dt_mpo_aggregate)
setcolorder(dt_mpo_aggregate, required_fields)
fwrite(dt_mpo_aggregate, tsm_landuse_path)











