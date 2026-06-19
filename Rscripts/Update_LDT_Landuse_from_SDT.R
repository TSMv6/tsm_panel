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

# settings_file <- args[1]
# settings_file <-   "C:/TSM_NextGen_v5/Base/TSMv5_default/settings_PopSim.txt"
# settings <- read_properties(settings_file)
# print(settings)
# landuse_layer_path     <- settings$landuse_layer_path
# US_lu_default          <- settings$US_lu_default
# out_file_lu            <- settings$out_file_lu

# Prepare FL LDT Syn HH & Landuse

landuse_layer_path     <- args[1]
US_lu_default          <- args[2]
out_file_lu            <- args[3]

# landuse_layer_path     <- "M:/Models/StateWide/TSM_NextGen/900 CAD GIS Modeling/940 Modeling/working_dir/SE_Data/v5.0/v4/TSMv5_MPO_full_2055.gpkg"
# US_lu_default          <- "C:/TSM_NextGen_v5/Inputs/LDT_Skims_LU_SynHH/2055_landuse.dat"
# out_file_lu            <- "C:/TSM_NextGen_v5/Base/TSMv5_default/LDT_landuse.dat" 

dt_fl_lu    <- st_read(landuse_layer_path) %>% setDT()
dt_fl_lu[, geom := NULL]

dt_us_lu <- fread(US_lu_default)

# Check HH for US & FL (OS = US - FL)
# years <- c(2023, 2025, 2030, 2035, 2040, 2045, 2050, 2055)
# os_hh <- list()
# fl_hh <- list()
# for(y in 1:length(years)){
#   os_lu <- paste0("C:/TSM_NextGen_v5/Inputs/LDT_Skims_LU_SynHH/", years[y], "_landuse.dat")
#   dt_os_lu <- fread(os_lu)
#   N_os_hh <- dt_os_lu[StateFIPS != 12, sum(TotHH)]
#   N_fl_hh <- dt_os_lu[StateFIPS == 12, sum(TotHH)]
#   os_hh[[as.character(years[y])]] <- N_os_hh
#   fl_hh[[as.character(years[y])]] <- N_fl_hh
# }

# Function to update LDT FL zonal landuse from SDT data
update_InState <- function(dt_us, dt_fl){
  
  # In-state land-use
  dt_us_FL <- dt_us[StateFIPS == 12, ]
  dt_us_OS <- dt_us[StateFIPS != 12, ]
  
  flds_sdt <- colnames(dt_fl)
  flds_ldt <- colnames(dt_us_FL)
  sdt_emp_flds <- flds_sdt[grep("emp$", flds_sdt)]
  ldt_emp_flds <- flds_ldt[grep("Emp$", flds_ldt)]
  ldt_emp_flds <- ldt_emp_flds[!(ldt_emp_flds %in% "TotalEmp")]
  sdt_emp_flds <- sdt_emp_flds[order(sdt_emp_flds)]
  ldt_emp_flds <- ldt_emp_flds[order(ldt_emp_flds)]
  
  # Common fields 
  setnames(dt_fl, c(sdt_emp_flds, "EMP", "TSM_NG"), 
                   c(ldt_emp_flds, "TotalEmp", "ZoneID"))
  
  
  fields_from_sdt <- c(ldt_emp_flds, "TotalEmp","TotHH", "UnivEnr")
  dt_fl_aggr <- dt_fl[, lapply(.SD, sum), .SDcols = fields_from_sdt, by = "ZoneID"]
  
  dt_curr_fut_FL <- merge(dt_us_FL[, c("ZoneID", "NTracts", "LandSqm", "StateFIPS", "ParkSqm",
                                         "NUMALat", "NUMALong",  "MinStDist", "MinAPDist",  
                                         "BusStats", "RailStats", "Airports", "lnChargePerCap", "masPop")],
                          dt_fl_aggr, by = "ZoneID", all.x = T)
  
  setcolorder(dt_curr_fut_FL, flds_ldt)
  
  dt_lu_updated <- rbindlist(list(dt_curr_fut_FL, dt_us_OS), use.names = T) 
  return(dt_lu_updated)
}

# Append FL and Out-of-State together
dt_lu_updated <- update_InState(dt_us_lu, dt_fl_lu)

# Write output file
fwrite(dt_lu_updated, out_file_lu, sep = "\t")

