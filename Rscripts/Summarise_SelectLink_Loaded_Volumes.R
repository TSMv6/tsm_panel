library(data.table)
library(tidyverse)
library(openxlsx)
library(R.utils)
library(sf)

# args = [Link file, volume file, loaded file, stats file, version]

args            <- commandArgs(trailingOnly = TRUE)
print(args)


link_GPKG           <- args[1]
vol_file_1          <- args[2]
vol_file_2          <- args[3]
loaded_GPKG         <- args[4]
bool_str_subarea    <- args[5]

# link_GPKG     <- "C:/Projects/temp_geoMaster_coding/Subarea_test/Subarea_Link_1.GPKG"
# vol_file      <- "C:/Projects/temp_geoMaster_coding/Subarea_test/Subarea_loaded_v11_new_geometry.csv"
# loaded_GPKG   <- "C:/Projects/temp_geoMaster_coding/Subarea_test/Subarea_Link_Loaded_1.GPKG"
# bool_str_subarea <- "TRUE"
# bool_validation  <- "FALSE"
# excel_out        <-  ""

# 
# vol_file   <- "C:/TSM_NextGen_v5/Base/TSM_NG_2035/subarea_volume_35.csv" # volume_35.csv")
# link_GPKG  <- "C:/TSM_NextGen_v5/Geomaster/Y35_consolidated/Subarea_35/Subarea_TBN_35/Subarea_LINK.GPKG"

dt_sf  <- st_read(link_GPKG) %>% setDT()

if(bool_str_subarea){
  setnames(dt_sf, c("A", "B", "Sub_A", "Sub_B"), c("TSM_A", "TSM_B", "A", "B"))
}

################################################################################
# read loaded volumes (hourly volumes)
get_SLVol_Daily <- function(vol_file){
  dt       <- fread(vol_file)
  
  # aggregate to daily volumes (aggregated to daily)
  all_possible_classes <-  c("LDT_Air_AccEgr25M", "LDT_Res_Air",       "LDT_Res_Hig",       "LDT_Res_Med",      
                             "LDT_Vis_Air",       "LDT_Vis_Hig",       "LDT_Vis_Med",       "SDT_Res_Hig",      
                             "SDT_Res_Low",       "SDT_Res_Med",       "SDT_Vis_Hig",       "SDT_Vis_Low",      
                             "SDT_Vis_Med",       "heavy",             "light",             "medium",
                             "LDT_Res_Low",       "LDT_Vis_Low") 
  
  current_fields <- colnames(dt)
  current_classes <- current_fields[current_fields %in% all_possible_classes]
  nClasses <- length(current_classes)
  
  df_daily_trips <- dt[, lapply(.SD, sum), by = c("A", "B"), .SDcols = c(4:(3 + nClasses))]
  
  # Get daily trips
  df_daily_trips <- df_daily_trips[, SL_VOL := rowSums(.SD), .SDcols = c(3: (2 + nClasses))]
  return(df_daily_trips)
}

df_daily_trips <- get_SLVol_Daily(vol_file_1)
dt <- merge(dt_sf, df_daily_trips[, c("A", "B", "SL_VOL")], by = c("A", "B"), all.x = TRUE)

# If a second volume file exists
if(vol_file_2 != "None"){
  
  rm(df_daily_trips)
  setnames(dt, "SL_VOL", "SL_VOL1")
  df_daily_trips <- get_SLVol_Daily(vol_file_2)
  dt <- merge(dt, df_daily_trips[, c("A", "B", "SL_VOL")], by = c("A", "B"), all.x = TRUE)
  setnames(dt, "SL_VOL", "SL_VOL2")
}

# Write loaded network
st_write(dt, loaded_GPKG, append = F)

fwrite(df_daily_trips, gsub(".gpkg", "_daily.csv", loaded_GPKG, ignore.case = TRUE))



