library(data.table)
library(tidyverse)
library(openxlsx)
library(R.utils)
library(sf)

# args = [Link file, volume file, loaded file, stats file, version]

args            <- commandArgs(trailingOnly = TRUE)
print(args)


link_GPKG     <- args[1]
vol_file      <- args[2]
loaded_GPKG   <- args[3]
bool_str_subarea     <- args[4]
bool_validation     <- args[5]
excel_out     <- args[6]

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
df_daily_trips[, Total := rowSums(.SD), .SDcols = c(3: (2 + nClasses))]

# Get hourly volumes
dt[, Total := rowSums(.SD), .SDcols = c(4: (2 + nClasses))]

dt_hourly <- dcast(dt[, c("A", "B", "START", "Total")], A + B ~ START, value.var = "Total")
setcolorder(dt_hourly, c("A", "B", paste0(c(1:24),":00")))
setnames(dt_hourly, paste0(c(1:24),":00"), paste0("VOL_", c(1:24),":00"))

# Congested speeds by hour
dt_speed <- dcast(dt[, c("A", "B", "START", "SPEED")], A + B ~ START, value.var = "SPEED")
setcolorder(dt_speed, c("A", "B", paste0(c(1:24),":00")))
setnames(dt_speed, paste0(c(1:24),":00"), paste0("SPD_", c(1:24),":00"))

# Get daily VMT, VHT and VHD
setnames(dt_sf, "SPEED", "SPEED_FF")
dt <- merge(dt, dt_sf[, c("A", "B", "DISTANCE", "SPEED_FF")], by = c("A", "B"), all.x = TRUE)
dt[, VHD := fcase(A > 11560 & B > 11560, (VHT - (Total * DISTANCE / SPEED_FF)), 
                  default = 0)]

df_daily_VMT <- dt[!is.na(VMT), lapply(.SD, sum), .SDcols = c("VMT"), by = c("A", "B")]
df_daily_VHT <- dt[!is.na(VHT), lapply(.SD, sum), .SDcols = c("VHT"), by = c("A", "B")]
df_daily_VHD <- dt[!is.na(VHD), lapply(.SD, sum), .SDcols = c("VHD", "Total"), by = c("A", "B")]
df_daily_VHD <- df_daily_VHD[, Delay := fcase(!is.na(Total) & Total > 0, VHD/Total, 
                                              default = 0)]
df_daily_VHD[, Total := NULL]

dt2 <- merge(dt_sf, df_daily_trips, by = c("A", "B"), all.x = TRUE)
dt2 <- merge(dt2, dt_hourly, by = c("A", "B"), all.x = TRUE)
dt2 <- merge(dt2, dt_speed, by = c("A", "B"), all.x = TRUE)
dt2 <- merge(dt2, df_daily_VMT, by = c("A", "B"), all.x = TRUE)
dt2 <- merge(dt2, df_daily_VHT, by = c("A", "B"), all.x = TRUE)
dt2 <- merge(dt2, df_daily_VHD, by = c("A", "B"), all.x = TRUE)

# Write loaded network
st_write(dt2, loaded_GPKG, append = F)
df_daily_trips <- copy(dt2)
df_daily_trips[, geom := NULL]
fwrite(df_daily_trips, gsub(".gpkg", "_daily.csv", loaded_GPKG, ignore.case = TRUE))

if(bool_validation %in% c("TRUE", "true", "True", "T")){
  df <- dt2 %>%  setDF() %>%
    rename(Counts = COUNT, Volume = Total) %>% 
    mutate(Volume = ifelse(is.na(Volume), 0, Volume)) %>%
    filter(!is.na(Counts) & Counts > 1 & Volume > 1) 
  
  ################################################################################
  # Functions to compute R-Square, RMSE and Scatter Plots
  ################################################################################
  # Compute stats by vol group    
  ComputeStats <- function(df) {
    
    stats <- df %>% 
      summarise(
        RMSE = round(ModelMetrics::rmse(Counts, Volume),2),
        Model.Est = round(sum(Volume),0),
        Obs.Count = round(sum(Counts),0),
        Links = n(),
        # PRMSE = round(100 * RMSE * Links / Model.Est, 4), 
        PRMSE = round(100 * RMSE * Links / Obs.Count, 4), 
        R.Squared = round(cor(Counts, Volume)^2,4),
        Vol_Cnt = round(Model.Est / Obs.Count, 2)
      )  
    
    return(stats)
  }
  
  
  ################################################################################
  # Compute volume groups
  df <- df %>% 
    mutate(volBin = case_when(.$Counts %in% c(1:5000) ~ " 1 - 5,000",
                              .$Counts %in% c(5001:10000)  ~ " 5,000 - 10,000",
                              .$Counts %in% c(10001:20000) ~ " 10,000 - 20,000",
                              .$Counts %in% c(20001:30000) ~ " 20,000 - 30,000",
                              .$Counts %in% c(30001:40000) ~ " 30,000 - 40,000",
                              .$Counts %in% c(40001:50000) ~ " 40,000 - 50,000",
                              .$Counts %in% c(50001:60000) ~ " 50,000 - 60,000",
                              .$Counts %in% c(60001:70000) ~ " 60,000 - 70,000",
                              # .$Counts %in% c(70001:80000) ~ " 70,000 - 80,000",
                              # .$Counts %in% c(80001:90000) ~ " 80,000 - 90,000",
                              # .$Counts %in% c(90001:100000) ~ " 90,000 - 100,000",
                              # .$Counts > 100000 ~ " above 100,000 ")
                              .$Counts > 60000 ~ " above 60,000 ")
    ) 
  
  # Add difference fields
  df <- df %>% 
    mutate(volCnt_Diff = round(abs(Volume - Counts), -2),
           VolCNt_Ratio = round(abs(Counts/Volume - 1), 2))
  
  
  #-------------------------------------------------------------------------------
  # Daily stats
  summary_all <- df %>% ComputeStats() %>%
    mutate(volBin = "All")
  
  # Volume Groups
  volGroupsPeriod <-  df %>% 
    group_by(volBin) %>%
    ComputeStats() %>%
    separate(volBin, c("low", "junk"), "-", extra = "drop", remove = F) %>%
    mutate(low = as.integer(gsub(",", "", low)))%>%
    arrange(low)%>%
    select(-junk, -low)
  
  volGroupsPeriod <- bind_rows(volGroupsPeriod, summary_all)
  
  #-------------------------------------------------------------------------------
  # Facility type
  ByFtypeDaily <-  df %>% 
    group_by(FNAME) %>%
    ComputeStats()
  
  ################################################################################
  # Write to Excel
  # Delete output file (if exist)
  if (file.exists(excel_out)) {unlink(excel_out)}
  
  # Describe startin"g rows for data (Excel Template)
  df_export <- list(
    "Volume_Group" = volGroupsPeriod, 
    "Facility_Types" =  ByFtypeDaily
  )
  
  # write to excel
  write.xlsx(df_export, excel_out, startCol = 1, startRow = 1, overwrite = TRUE) 
}



