# Combine Short-distance and Long-distance O-D Trips
# Prepare ELToD Trip Table by sub-market segment and VOT classes

# if (!"omxr" %in% installed.packages()) {
#   if (!"devtools" %in% installed.packages()) install.packages("devtools", repos='http://cran.us.r-project.org')
#   library(devtools)
#   devtools::install_github("gregmacfarlane/omxr")
#   library(omxr)
# }

library(data.table)
library(tidyverse)
library(openxlsx)
library(sf)
# library(omxr)

# Read Arguments
args            <- commandArgs(trailingOnly = TRUE)
print(args)
catalog_dir     <- args[1]  
scenario_dir    <- args[2]  # 
fut_year        <- as.integer(args[3]) - 2000
feedback_loop   <- args[4] # "1"
sdt_syn_hh      <- args[5]
trip_table_out  <- args[6]

# catalog_dir     <- "C:\\TSM_NextGen_v5"
# scenario_dir    <- "C:\\TSM_NextGen_v5\\Base\\TSMv5_default"
# fut_year        <- "23"
# feedback_loop   <- "1"

# Inputs
# sdt_output         <- "Inputs_2019/sdt/tours_3.csv"
# sdt_res_output       <- paste0(scenario_dir, "/trips_",feedback_loop,".csv")
sdt_res_output       <- paste0(scenario_dir, "/trips_",feedback_loop,".csv") # TSMv4 version wo Telework
sdt_vis_output       <- paste0(scenario_dir, "/visitorTrips.csv")
LDT_output           <- paste0(scenario_dir, "/LD_tour_out_processed_ToD_Trips.csv")
# LDT_output           <- paste0(scenario_dir, "/tsmv5/LD_tour_out_processed_ToD_Trips_2023.csv")

# Add Synthetic Population with Industry Category for TeleWork & Work Flexibility
# syn_person_IndCat    <- paste0(scenario_dir, "/person_Industry_type.csv")

# Add county by home zone to the resident trip list to subset ELTOD_triptable by regions
# syn_HH_counties      <- paste0(scenario_dir, "/hhID_by_county.csv")

# Add HH Income for both short and long distance trips
# sdt_syn_hh <- paste0(scenario_dir, "/short_distance_hh.csv")
# sdt_syn_hh <- paste0(scenario_dir, "/synthetic_households_",fut_year,".csv") 
# sdt_syn_hh <- paste0(scenario_dir, "/CFL_Update_TSM_synthetic_households_",fut_year,".csv")

commerical_acitivity <- paste0(catalog_dir, "/Inputs/local_commercial/localized_commercial_activity.csv")
# Freight_output       <- paste0(catalog_dir, "/Inputs/trk_ODME/ODME_tt_v7.csv")       
# Freight_output       <- paste0(catalog_dir, "/Inputs/trk_ODME/ODME_tt_v7_integer_list.csv") 
Freight_output       <- paste0(catalog_dir, "/Inputs/trk_ODME/TSMv5_Truck_ODME_TT.csv") 

# Time of Day
time_of_day_file     <- paste0(catalog_dir, "/Inputs/tod/TimeSegment_distributions.xlsx")

# read skims
LOS_matrix           <- paste0(catalog_dir, "/Inputs/distance_skim/Skim_distbased.csv")

# ELToD Trip Table
# output_hourly          <- paste0(scenario_dir, "/ELTOD_tt_hourly.csv")
output_hourly          <- trip_table_out
# output_hourly          <- paste0(scenario_dir, "/ELTOD_tt_HourClock.csv")
write_HourClock_format <- TRUE
output_hourly_newMkt   <- paste0(scenario_dir, "/ELTOD_tt_newMarket_hourly.csv")
output_hourly_tripList <- paste0(scenario_dir, "/ELTOD_tt_List_hourly.csv.gz")
output_SDT_Res_hourly  <- paste0(scenario_dir, "/ELTOD_SDT_Res_hourly.csv.gz")
# output_15min_TRANSIMS  <- paste0(scenario_dir, "/woWFH_woTele/TRANSIMS_List_15min.csv")

# VOT thresholds
# vot_thresholds <- c(6.51, 11.68)
vot_thresholds <- c(12.81, 22.83)

#  Based on toll data (Finance Interactice cube traffic data by axle, 2019) share and tod were developed
trk_mode_split <- c(0.3, 0.28, 0.42) # Light(3-axle), med (4-axle), heavy(5+ axle)
base_year  <- 23
fut_year   <- as.integer(fut_year)

# For additional trip modes
track_sdt_grt50M <- FALSE    # Adds 1 mode for SDT Commuter Tours
track_AirTours   <- TRUE     # Adds 3 modes for LDT Air Tours
appendNewMkt     <- FALSE    # Append local commerical busniess trips
aggreage_purp    <- FALSE    # if True then Work = c("Work", "At_Work"), SchUnivEscort = c("School", "University", "Escort"), DiscMaint = c("Maintenance", "Discretionary")
telework         <- FALSE     # Model is based off PreCOVID surveys and Telework is not part of it, thus account for some work trips could telework
LimitCounties    <- FALSE     # Limits SDT res and visitor trips to these counties, useful for select link analysis or suabrea modeling

# list_counties <- c("Miami-Dade", "Broward", "Palm Beach")
# list_counties <- c( "St. Lucie" , "Martin" , "Indian River")
# list_counties <- c("Hillsborough", "Pinellas")
# list_counties <- c("Orange", "Seminole")
list_counties <- c("Sumter", "Lake", "Alachua", "Marion", "Citrus", "Levy")

#=====================================================================================================
# Process passenger Trips

#-------------------------------------------------------------------------------
# read ODME truck trip table (matrix)
dt_truck <- fread(Freight_output)

# Truck scaling factor (1% annual growth, linear is fine, 2030 = 15% and 2050 = 30% )
# trk_scale = 1.0

trk_totals <- dt_truck[, lapply(.SD, sum), .SDcols = c(4:6)]

trk_scale <- 1 + (fut_year - base_year)/100

if(trk_scale > 1){
  vnames <- c("heavy",  "light",   "medium")
  dt_truck[, (vnames) := lapply(.SD, function(x){  x * trk_scale}), .SDcols = vnames]
}


# Scale up truck trip table (global factor till a good freight model is developed)

# Old method of scaling trip table
# dt_truck <- dt_truck[, vehTrips := vehTrips * trk_scale]

# New method Sample "new" trcuk trips
# set.seed(10)
# dt_truck_new <- dt_truck[sample(ceiling(nrow(dt_truck)*(trk_scale-1))), ]
# set.seed(NULL)
# 
# dt_truck <- rbindlist(list(dt_truck, dt_truck_new))



#-------------------------------------------------------------------------------
# Read OMX skims for distance (note these are round-trip distances)
use_distance_skims <- TRUE
if(track_AirTours | track_sdt_grt50M) {
  use_distance_skims <- TRUE
} else {
  use_distance_skims <- FALSE
}

# Read OMX distance skims only when atleast one of the above is true
if(use_distance_skims){
  
  dt_skim <- fread(LOS_matrix)
  dt_skim <- setnames(dt_skim[, c(1:3)], c("originTaz", "destinationTaz", "distance"))
  
  # list_omx( LOS_matrix )
  # dt_skim1 <- read_omx(LOS_matrix, "DISTANCE", c(1:8721), c(1:8721))
  # dt_skim2 <- matrix(dt_skim1, ncol = 1)
  # dt_skim  <- expand.grid(otaz = c(1:8721), dtaz = c(1:8721))
  # dt_skim["carDist"] <- round(dt_skim2,0) 
  # dt_skim <- as.data.table(dt_skim)
  # setnames(dt_skim, c("originTaz", "destinationTaz", "distance"))
}

#-------------------------------------------------------------------------------
# Resident Model Trip Purpose
# 1. Work
# 2. University
# 3. School
# 4. Escort
# 5. Maintenance
# 6. Discretionary
# 7. AtWork

# Visitor Model Trip Purpose
# 1. Work
# 2. Recreate
# 3. Shop
# 4. Eatout

# Read visitor trip lists
dt_vis <- fread(sdt_vis_output)

# Read passenger trip lists
dt_res <- fread(sdt_res_output)

# low_vot <- quantile(dt_res$valueOfTime, probs = .33)
# med_vot <- quantile(dt_res$valueOfTime, probs = .66)
# high_vot <- quantile(dt_res$valueOfTime, probs = .95)
# C(low_vot, med_vot, high_vot)

# Subset to Counties
if(LimitCounties){

  # change output file names
  output_hourly  <- gsub("ELTOD",  paste(list_counties, collapse = "_"), output_hourly)
  output_SDT_Res_hourly  <- gsub("ELTOD",  paste(list_counties, collapse = "_"), output_SDT_Res_hourly)

  dt_hh_lu <- fread(syn_HH_counties)
  limit_taz <- dt_hh_lu[County %in% list_counties, TAZ]
  limit_hhs <- dt_hh_lu[County %in% list_counties, household_id]
  
  dt_vis   <- dt_vis[originTaz %in% limit_taz | destinationTaz %in% limit_taz, ]
  dt_truck <- dt_truck[O %in% limit_taz | D %in% limit_taz, ]
  dt_res   <- dt_res[hh_id %in% limit_hhs, ]
}



# Add trip purpose based on destinations
dt_vis[ , purpose := fcase(destinationPurpose == 0, "WorkVis",
                           destinationPurpose == 1, "Recreate",
                           destinationPurpose == 2, "Shop",
                           destinationPurpose == 3, "Eatout",
                           destinationPurpose == -1 & originPurpose == 0, "WorkVis",
                           destinationPurpose == -1 & originPurpose == 1, "Recreate",
                           destinationPurpose == -1 & originPurpose == 2, "Shop",
                           destinationPurpose == -1 & originPurpose == 3, "Eatout",
                           default = "None"
)]

dt_vis[, .N, by = "purpose"]
dt_vis <- dt_vis[ ,vot := fcase(valueOfTime <= vot_thresholds[1], "SDT_Vis_Low",
                                valueOfTime  > vot_thresholds[1] & valueOfTime <= vot_thresholds[2], "SDT_Vis_Med",
                                valueOfTime  > vot_thresholds[2], "SDT_Vis_Hig")]




# Add trip purpose based on destinations
dt_res[ , purpose := fcase(destinationPurpose == 0, "Work",
                           destinationPurpose == 1, "University",
                           destinationPurpose == 2, "School",
                           destinationPurpose == 3, "Escort",
                           destinationPurpose == 4, "Maintenance",
                           destinationPurpose == 5, "Discretionary",
                           destinationPurpose == 6, "AtWork",
                           destinationPurpose == -1 & originPurpose == 0, "Work",
                           destinationPurpose == -1 & originPurpose == 1, "University",
                           destinationPurpose == -1 & originPurpose == 2, "School",
                           destinationPurpose == -1 & originPurpose == 3, "Escort",
                           destinationPurpose == -1 & originPurpose == 4, "Maintenance",
                           destinationPurpose == -1 & originPurpose == 5, "Discretionary",
                           destinationPurpose == -1 & originPurpose == 6, "AtWork",
                           default = "None"
)]
dt_res[, .N, by = "purpose"]

res_tod <- dcast(dt_res[, .N, by = c("purpose", "period")], period ~ purpose, fill = 0)
# fwrite(res_tod, "tod_sdt_res_purpose.csv")

# Get VOT classes
dt_res <- dt_res[ ,vot := fcase(valueOfTime <= vot_thresholds[1], "SDT_Res_Low",
                                valueOfTime  > vot_thresholds[1] & valueOfTime <= vot_thresholds[2], "SDT_Res_Med",
                                valueOfTime  > vot_thresholds[2], "SDT_Res_Hig")]

# Add SDT_trips > 50 miles as a new mode to check I-10 impact
# Append skims to SDT resident model to check trips > 50 miles

if(track_sdt_grt50M){
  dt_res <-  merge(dt_res, dt_skim, by = c("originTaz", "destinationTaz"), all.x = TRUE)
  dt_res <- dt_res[, vot := ifelse(distance > 50, "SDT_grt50Mile", vot)]

}


# Process for Auto - Vehicle Trips (SDT Models)
fields <- c("originTaz", "destinationTaz", "period", "vot", "vehTrips")
dt_res_auto <- dt_res[tripMode <= 6, ]
dt_res_auto <- dt_res_auto[ , occupancy := fcase(tripMode %in% c(3,4) , 2,
                                                 tripMode %in% c(5,6) , 3.2,
                                                 default = 1)]  
dt_res_auto <- dt_res_auto[, vehTrips := expansionFactor / occupancy ]

# 40% of these 4 Industries could Telework (Census shows Telework increase by 10%)
if(telework){
  # Telework / Work Felxibity for Admin, Prof.Services, IMF, Financial Industries
  dt_synper_IND <- fread(syn_person_IndCat)
  setnames(dt_synper_IND,"TAZ", "HTAZ")
  
  dt_res_auto <- merge(dt_res_auto, dt_synper_IND, by.x = c( "hh_id", "person_id"), 
                  by.y = c("household_id", "per_num"), all.x = TRUE)
  
  preCovid <- dt_res_auto[originTaz != destinationTaz, sum(vehTrips), by = "purpose"]
  dt_res_auto <- dt_res_auto[purpose %in% c("Work", "AtWork") & INDPCat %in%  c("ADM", "FIN", "INF", "PRF"), vehTrips := vehTrips * 0.6] 
  TeleWork <- dt_res_auto[originTaz != destinationTaz, sum(vehTrips), by = "purpose"]
  compare <- merge(preCovid, TeleWork, by = "purpose")
  setnames(compare,c("purpose", "All", "TeleWork"))
  compare
}

# dt_res_auto <- dt_res_auto[, ..fields ]

dt_vis_auto <- dt_vis[tripMode <= 6, ]
dt_vis_auto <- dt_vis_auto[ , occupancy := fcase(tripMode %in% c(3,4) , 2,
                                                 tripMode %in% c(5,6) , 3.2,
                                                 default = 1)]  

dt_vis_auto <- dt_vis_auto[, vehTrips := expansionFactor / occupancy ]
# dt_vis_auto <- dt_vis_auto[, ..fields ]


# Recode half hour period into 15 min scale
# Periods into ts & hours
dt_tod <- data.table(per = rep(c(1:48), each = 2), prob = rep(0.5, each = 2, times = 48), ts = c(1:96))

# Resident - period to time segments
for(p in c(1:48)){
  choices <- dt_tod[per == p, ts]
  probs <- dt_tod[per == p, ts]
  n <- dt_res_auto[period == p, .N]
  if(n > 0){
    dt_res_auto[period == p, ts := sample(choices, n, probs, replace = TRUE)]
  }
}

# Apply normal distribution if period == 0 
n <- dt_res_auto[period == 0, .N]
dt_res_auto[period == 0, ts := sample(c(1:96), n, replace = TRUE)]


# Visitor - period to time segments
for(p in c(1:48)){
  choices <- dt_tod[per == p, ts]
  probs <- dt_tod[per == p, ts]
  n <- dt_vis_auto[period == p, .N]
  if(n > 0){
    dt_vis_auto[period == p, ts := sample(choices, n, probs, replace = TRUE)]
  }
}

# Apply normal distribution if period == 0 
n <- dt_vis_auto[period == 0, .N]
dt_vis_auto[period == 0, ts := sample(c(1:96), n, replace = TRUE)]

# Rename half-hour periods to TourPeriods and TimeSegments to period
setnames(dt_res_auto, c("period", "ts"), c("TourPeriod", "period"))
setnames(dt_vis_auto, c("period", "ts"), c("TourPeriod", "period"))

# Recode half hour period into 15 min scale
# Resident - period
#  size        <- nrow(dt_res_auto)
#  prob        <- dt_tod$`Res_Short`
#  values      <- dt_tod$TimeSeg_96
#  set.seed(4L)
#  dt_res_auto <- dt_res_auto[, period := sample(values, size, prob, replace = TRUE)]
#  set.seed(NULL)
#  
#  Visitor - period
#  size        <- nrow(dt_vis_auto)
#  prob        <- dt_tod$`Vis_Short`
#  values      <- dt_tod$TimeSeg_96
#  set.seed(5L)
#  dt_vis_auto <- dt_vis_auto[, period := sample(values, size, prob, replace = TRUE)]
#  set.seed(NULL)

# dt_res_auto1 <- dt_res_auto[, vehTrips := vehTrips / 2]
# dt_vis_auto1 <- dt_vis_auto[, vehTrips := vehTrips / 2]
# 
# dt_res_auto2 <- copy(dt_res_auto1)
# dt_vis_auto2 <- copy(dt_vis_auto1)
# 
# dt_res_auto2 <- dt_res_auto2[, period := period * 2]
# dt_vis_auto2 <- dt_vis_auto2[, period := period * 2]
# 
# dt_res_auto12 <- rbindlist(list(dt_res_auto1, dt_res_auto2))
# dt_vis_auto12 <- rbindlist(list(dt_vis_auto1, dt_vis_auto2))

dt_res_auto_OD <- dt_res_auto[, sum(vehTrips), by = c("originTaz", "destinationTaz", "period", "vot")]
dt_vis_auto_OD <- dt_vis_auto[, sum(vehTrips), by = c("originTaz", "destinationTaz", "period", "vot")]

setnames(dt_res_auto_OD, c("originTaz", "destinationTaz", "V1"), c("otaz", "dtaz", "vehTrips"))
setnames(dt_vis_auto_OD, c("originTaz", "destinationTaz", "V1"), c("otaz", "dtaz", "vehTrips"))

# Save list for later
dt_res_auto[, valueOfTime := as.integer(valueOfTime)]
dt_vis_auto[, valueOfTime := as.integer(valueOfTime)]
dt_res_auto_List <- dt_res_auto[ , c("hh_id", "person_id", "tour_id", "trip_id", "valueOfTime", "purpose", "period", "originTaz", "destinationTaz", "vot", "vehTrips", "occupancy")]
dt_vis_auto_List <- dt_vis_auto[ , c("tour_id", "trip_id", "valueOfTime", "purpose", "period", "originTaz", "destinationTaz", "vot", "vehTrips", "occupancy")]

# Provide some hh_id 
min_HHID <- 15000000
dt_vis_auto_List[, c("hh_id", "person_id", "tour_id") := list(min_HHID + .I, 1, tour_id - 1000000)]

#-------------------------------------------------------------------------------
# Create a purpose and vot combiation for SDT only assignment
if(aggreage_purp){
  dt_res_auto[ ,purpose2 := fcase(purpose %in% c("Work", "AtWork"), "Work",
                                  purpose %in% c("School", "University", "Escort"), "SchUnivEscort",
                                  default = "DiscMaint")]

  dcast(dt_res_auto[, sum(vehTrips), by = c("purpose", "purpose2")], purpose ~ purpose2)

  dt_res_auto[ ,purp_vot := fcase(valueOfTime <= vot_thresholds[1], paste0(purpose2, "_Low"),
                                  valueOfTime  > vot_thresholds[1] & valueOfTime <= vot_thresholds[2], paste0(purpose2, "_Med"),
                                  valueOfTime  > vot_thresholds[2], paste0(purpose2, "_Hig"))]
} else {
  dt_res_auto[ ,purp_vot := fcase(valueOfTime <= vot_thresholds[1], paste0(purpose, "_Low"),
                                  valueOfTime  > vot_thresholds[1] & valueOfTime <= vot_thresholds[2], paste0(purpose, "_Med"),
                                  valueOfTime  > vot_thresholds[2], paste0(purpose, "_Hig"))]
}

dt_res_auto[, hour := (period * 15 / 60) - ((period * 15 / 60) %% 1)]
dt_res_auto[hour == 0, hour := 24]

dcast(dt_res_auto[originTaz != destinationTaz, sum(vehTrips), by = c("purpose", "vot")], purpose ~ vot)

dcast(dt_res_auto[, sum(vehTrips), by = c("purpose", "hour")], hour ~ purpose)

dt_res_purp_OD <- dt_res_auto[, sum(vehTrips), by = c("originTaz", "destinationTaz", "hour", "purp_vot")]
setnames(dt_res_purp_OD, c("originTaz", "destinationTaz", "hour", "V1" ), c("O", "D", "period", "vehTrips"))

dt_res_purp_OD <- dcast(dt_res_purp_OD,   period + O + D ~ purp_vot, 
                       value.var = "vehTrips", fill = 0)
setorder(dt_res_purp_OD, period, O, D)

dt_res_auto[, sum(vehTrips), by = vot]
fwrite(dt_res_purp_OD, output_SDT_Res_hourly)


##############################################################################################
# Long Distance Trips.
# Note to use tripMode == Auto and since each tour is made by the entire household, each tour represent a vehicle trip 
# So, no need to use PartySize to convert based on Occupancy. All members of the party travel together for LDT
# tt <- dt_trips_both[ tripMode == "Auto", .N, by = c("otaz", "dtaz", "period", "vot")]

dt_ldt <- fread(LDT_output)

# Codes for tour purpose (trPurpose)
# 1 personal business
# 2 visit friends or relatives
# 3 leisure/vacation
# 4 commute  (modeled under SDT-Resident work for FL and AL/GA to FL is LDT commute)
# 5 employer's business
dt_ldt[, .N, by = "trPurpose"]
dt_ldt[(org_DMA == 10 & des_DMA < 10) | (org_DMA < 10 & des_DMA == 10) & trPurpose == 5,  trPurpose := 4]

dt_ldt[, purpose := fcase(trPurpose == 1, "PersonalBusiness",
                          trPurpose == 2, "VistFriendFamily",
                          trPurpose == 3, "LeisureVacation",
                          trPurpose == 4, "CrossBorderCommute",
                          trPurpose == 5, "EmployerBusiness",
                          default = "None")]


if(track_AirTours){
  dt_ldt <- dt_ldt[trMode == 4, vot := "LDT_Res_Air"]
  dt_ldt <- dt_ldt[type == "EI" & trMode == 4, vot := "LDT_Vis_Air"]
  
  # Check if LDT air trips access > 25 miles (airport to destination)
  dt_ldt <- merge(dt_ldt, dt_skim, by.x = c("otaz", "dtaz"),  by.y = c("originTaz", "destinationTaz"), all.x = TRUE)
  dt_ldt[vot %in% c("LDT_Vis_Air", "LDT_Res_Air") & distance > 25, .N]

  # Don't assign airport access trips > 25 miles since most people likely don't choose their final destinations (hotel) far away from the airport 
  # (under 25 - 35 miles is pretty much in the city and anything over 35 miles is less likely and 50 miles is definitely a no as they need to spend a hour from airport)
  
  # To track
  dt_ldt <- dt_ldt[vot %in% c("LDT_Vis_Air", "LDT_Res_Air") & distance > 25, vot:= "LDT_Air_AccEgr25M"]
  
  # To remove
  # dt_ldt <- dt_ldt[!(vot %in% c("LDT_Vis_Air", "LDT_Res_Air") & distance > 25), ] 
  dt_ldt <- dt_ldt[, distance := NULL]
}

# dt_ldt_auto_OD <- dt_ldt[ tripMode == "Auto", .N , by = c("otaz", "dtaz", "period", "vot")]
dt_ldt_auto_OD <- dt_ldt[ , .N , by = c("otaz", "dtaz", "period", "vot")]  # Allow Other and DME trips as they are mostly non-personal vehicle trips 
setnames(dt_ldt_auto_OD, "N", "vehTrips")

# For residents use 50% after transposing (Visitors are calibrated to external counts inbound direction)
# dt_ldt[, vehTrips := fcase(type == "II", 0.5,
#                            default = 1)]

# dt_ldt_auto_OD <- dt_ldt[ tripMode == "Auto", sum(vehTrips), by = c("otaz", "dtaz", "period", "vot")]
# setnames(dt_ldt_auto_OD, "V1", "vehTrips")

# Hold for tripList format
dt_ldt[, valueOfTime := as.integer(trVOT)]

# TODO update this in the LDT file
min_HHID <- 15000000
dt_ldt[trOState != 12 , hhId := min_HHID + .I]

dt_ldt_auto_List <- dt_ldt[ , .N , by = c("hhId", "valueOfTime", "purpose", "period", "otaz", "dtaz", "vot", "hhIncome", "trPartySize")]
setnames(dt_ldt_auto_List, c("N","otaz", "dtaz", "hhId", "trPartySize"), c("vehTrips", "originTaz", "destinationTaz", "hh_id", "occupancy"))

dt_ldt_auto_List[, c("person_id", "tour_id", "trip_id") := list(1, 1, 1)]

#=====================================================================================================
# Process Trucks and Commercial Vehicle Trips

# 1. Split trucks into Light, Medium and Heavy duty trucks
# Assign truck trips by OD (should assign each trip instead of O-D sets but time constraints)
# size     <- nrow(dt_truck)
# set.seed(3L)
# dt_truck <- dt_truck[ , mode := sample(c("light", "medium", "heavy"), size, trk_mode_split, replace = TRUE)]
# set.seed(NULL)
# dt_truck[, sum(vehTrips), by = "mode"]

#-----------------------------------------------------------------------------------------------------
# 2. Append period to trucks
# Get departure_time from STL and Toll - axles
dt_tod <- read.xlsx(time_of_day_file) %>% setDT()

# # Light trucks - period
 # dt_truck_lt <- dt_truck[mode == "light", ]
 dt_truck_lt <- dt_truck[light > 0, c("O", "D", "light")]
 size        <- nrow(dt_truck_lt)
 prob        <- dt_tod$`3_Axles`
 values      <- dt_tod$TimeSeg_96
 set.seed(4L)
 dt_truck_lt <- dt_truck_lt[, period := sample(values, size, prob, replace = TRUE)]
 set.seed(NULL)

 # Medium trucks - period
 # dt_truck_md <- dt_truck[mode == "medium", ]
 dt_truck_md <- dt_truck[medium > 0, c("O", "D", "medium")]
 size        <- nrow(dt_truck_md)
 prob        <- dt_tod$`4_Axles`
 values      <- dt_tod$TimeSeg_96
 set.seed(5L)
 dt_truck_md <- dt_truck_md[, period := sample(values, size, prob, replace = TRUE)]
 set.seed(NULL)

 # Heavy trucks - period
 # dt_truck_hv <- dt_truck[mode == "heavy", ]
 dt_truck_hv <- dt_truck[heavy > 0, c("O", "D", "heavy")]
 size        <- nrow(dt_truck_hv)
 prob        <- dt_tod$`5p_Axles`
 values      <- dt_tod$TimeSeg_96
 set.seed(6L)
 dt_truck_hv <- dt_truck_hv[, period := sample(values, size, prob, replace = TRUE)]
 set.seed(NULL)
 
 # Put them together
 dt_truck_hv[, mode := "heavy"]
 dt_truck_md[, mode := "medium"]
 dt_truck_lt[, mode := "light"]
 setnames(dt_truck_hv, "heavy", "vehTrips")
 setnames(dt_truck_md, "medium", "vehTrips")
 setnames(dt_truck_lt, "light", "vehTrips")
 dt_truck2 <- rbindlist(list(dt_truck_hv, dt_truck_md, dt_truck_lt))
 dt_truck2[, sum(vehTrips), by = "mode"]
 setnames(dt_truck2, c( "O", "D","mode"), c("otaz", "dtaz", "vot"))

# setnames
# dt_truck2 <- copy(dt_truck)
# setnames(dt_truck2, c( "O", "D","mode", "ts"), c("otaz", "dtaz", "vot", "period"))

#=====================================================================================================
# ELToD TT: Merge Trips from all Sub-markets 
#-----------------------------------------------------------------------------------------------------
dt_nextGen <- rbindlist(list(dt_res_auto_OD, dt_vis_auto_OD, dt_ldt_auto_OD, dt_truck2), use.names = TRUE)
dt_nextGen[, sum(vehTrips), by = "vot"]
dt_nextGen[, sum(vehTrips), by = "period"][order(period), ]

# Append Hour
# dt_nextGen[, hour := ceiling(period/4)]
dt_nextGen[, hour := (period * 15 / 60) - ((period * 15 / 60) %% 1)]
dt_nextGen[hour == 0, hour := 24]
dt_nextGen[, sum(vehTrips), by = "hour"][order(hour), ]

# Review
O_tripEnds <- dt_nextGen[, sum(vehTrips), by = "otaz"]
D_tripEnds <- dt_nextGen[, sum(vehTrips), by = "dtaz"]
OD_TripEnds <- merge(O_tripEnds, D_tripEnds, by.x = "otaz", by.y = "dtaz", all.both = TRUE)

# Calibrate externals 
# Scaling factors
I10_scale <- 1.089312
I95_scale <- 0.8951645
I75_scale <- 0.7947358

dt_nextGen[ otaz == 11560 | dtaz == 11560, vehTrips := vehTrips * I95_scale ]
dt_nextGen[ otaz == 11548 | dtaz == 11548, vehTrips := vehTrips * I75_scale ]
dt_nextGen[ otaz == 11504 | dtaz == 11504, vehTrips := vehTrips * I10_scale ]

# Format to trip table
use_hour <- TRUE
if(use_hour){
  dt_nextGen_OD <- dt_nextGen[,  sum(vehTrips), by = c("otaz", "dtaz", "hour", "vot")]
  setnames(dt_nextGen_OD, "hour", "period")
} else{
  dt_nextGen_OD <- dt_nextGen[,  sum(vehTrips), by = c("otaz", "dtaz", "period", "vot")]
}


dt_nextGen_OD <- dcast(dt_nextGen_OD,   period + otaz + dtaz ~ vot, 
                       value.var = "V1", fill = 0)
setorder(dt_nextGen_OD, period, otaz, dtaz)
setnames(dt_nextGen_OD,  c("otaz", "dtaz"), c( "O", "D"))


if(write_HourClock_format){
  dt_nextGen_OD[, period := paste0(str_pad(period, 2, pad = "0", "left"),
                          ":00")]
  setnames(dt_nextGen_OD, "period", "STARTTIME")
  fwrite(dt_nextGen_OD, gsub("_hourly.csv", "_HourClock.csv", output_hourly))
} else {
  fwrite(dt_nextGen_OD, output_hourly)
}

# get trips by puprose
t1 <- dt_nextGen_OD[, lapply(.SD, sum), .SDcols = c(4:ncol(dt_nextGen_OD))]
data.table(purpose = names(t1), trips = t(t1))

#-----------------------------------------------------------------------------------------------------
# Save as trip list for future applications
setnames(dt_truck2, c("otaz", "dtaz", "vot"), c("originTaz", "destinationTaz", "purpose"))

# generate normal distribution for truck valueOfTime around mean time and cost coefficient with sd of 0.650, 0.692, 0.896
dt_truck2[, vot := purpose]

trk_purp <- c("heavy","medium", "light") 
trk_sd   <- c(0.650, 0.692, 0.896)
trk_cost_Coef <- c(2.88, 5.42, 7.5)
trk_time_Coef <- c(0.9, 0.9, 0.7)
trk_axle_scale <- 3.5

for(p in 1:length(trk_purp)){
  n <- dt_truck2[purpose == trk_purp[p], .N] 
  x <- seq(0, 1, length.out = n)
  y <- qnorm(x, mean = trk_time_Coef[p], sd = trk_sd[p])                         # mean of time coefficient
  trk_vot <- y[y > 0 & !is.infinite(y)] * 60 * trk_axle_scale / trk_cost_Coef[p]   # distributed vot
  dt_truck2[purpose == trk_purp[p], valueOfTime := as.integer(sample(trk_vot, n, replace = TRUE))]
}

# Update trucks hh_id based on 13 to 15 million
# Provide some hh_id 
min_trk_HHID <- 13000000
dt_truck2[, c("hh_id", "person_id", "tour_id", "trip_id") := list(min_trk_HHID + .I, 1,1,1)]

dt_truck2[, mean(valueOfTime), by = "purpose"]


# Append SDT Income  
dt_sdt_hh <- fread(sdt_syn_hh)
dt_res_auto_List <- merge(dt_res_auto_List, dt_sdt_hh[, c("household_id", "HHINCADJ")], by.x = "hh_id", by.y = "household_id", all.x = T)
setnames(dt_res_auto_List, "HHINCADJ", "hhIncome")
rm(dt_sdt_hh)

# Combine all markets
dt_nextGen_List <- rbindlist(list(dt_res_auto_List, dt_vis_auto_List, dt_ldt_auto_List, dt_truck2), use.names = TRUE, fill = TRUE)
dt_nextGen_List[, hour := (period * 15 / 60) - ((period * 15 / 60) %% 1)]
dt_nextGen_List[hour == 0, hour := 24]

# dt_nextGen_List_OD <- dt_nextGen_List[,  sum(vehTrips), by = c("originTaz", "destinationTaz", "hour", "valueOfTime", "vot", "purpose")]
setnames(dt_nextGen_List, c("originTaz", "destinationTaz", "vot"), c("O", "D", "market"))
setorder(dt_nextGen_List, hour, O, D)

# Separate markets
setnames(dt_nextGen_List, "market", "marketVot")
dt_nextGen_List[,market:= gsub("(_Med)|(_Low)|(_Hig)","", marketVot)]
dt_nextGen_List[marketVot %in% c("LDT_Air_AccEgr25M", "LDT_Vis_Air",  "LDT_Res_Air"), market := "LDT_Air"]

# Leave party size or occupancy to compute total person trips
dt_nextGen_List[purpose %in% c("heavy", "medium", "light"), c("occupancy", "market") := list(vehTrips, "Truck")]
dt_nextGen_List[, lapply(.SD, sum), .SDcols = c("occupancy", "vehTrips"), by = c("market", "purpose")][order(market),]

# Each trip is a row, total rows gives person trips occupancy duplicates the persons as the same person is counted again.
# dt_nextGen_List[O == D, lapply(.SD, sum), .SDcols = c("occupancy", "vehTrips"), by = c("market", "purpose")][order(market),]
dt_nextGen_List[O == D, list(.N, sum(vehTrips)), by = c("market", "purpose")][order(market),]
dt_nextGen_List[ , list(.N, sum(vehTrips)), by = c("market", "purpose")][order(market),]


# Calibrate at externals (2023 Count to External Volume)
# I95Cnt  <- 75636
# I95_scale <- I95Cnt/(dt_nextGen_List[ O == 11560 | D == 11560, sum(vehTrips) ])
# I75Cnt  <- 48054
# I75_scale <- I75Cnt/(dt_nextGen_List[ O == 11548 | D == 11548, sum(vehTrips) ])
# I10Cnt  <- 36000
# I10_scale <- I10Cnt/(dt_nextGen_List[ O == 11504 | D == 11504, sum(vehTrips) ])

# Scaling factors
I10_scale <- 1.089312
I95_scale <- 0.8951645
I75_scale <- 0.7947358

dt_nextGen_List[ O == 11560 | D == 11560, vehTrips := vehTrips * I95_scale ]
dt_nextGen_List[ O == 11548 | D == 11548, vehTrips := vehTrips * I75_scale ]
dt_nextGen_List[ O == 11504 | D == 11504, vehTrips := vehTrips * I10_scale ]

# Add household for trucks
fwrite(dt_nextGen_List, output_hourly_tripList)

#-------------------------------------------------------------------------------
# Format for TRANSIMS
doTransims <- F 
if(doTransims){
  dt_TRANSIMS <- copy(dt_nextGen_List)
  
  max_id <- dt_TRANSIMS[!is.na(hh_id),max(hh_id)]
  dt_TRANSIMS[is.na(hh_id), hh_id := max_id + .I]
  dt_TRANSIMS[is.na(person_id), person_id := 1]
  dt_TRANSIMS[is.na(tour_id), tour_id := 1]
  dt_TRANSIMS[is.na(trip_id), trip_id := 1]
  
  new_names <- c("HHOLD", "PERSON", "TOUR", "TRIP", "TRIPS", "ORIGIN", "DESTINATION", "VOT" )
  old_names <- c("hh_id", "person_id", "tour_id", "trip_id", "vehTrips", "O", "D", "valueOfTime" ) 
  setnames(dt_TRANSIMS, old_names, new_names)
  
  dt_TRANSIMS[, c("ORG_TYPE", "DES_TYPE",  "MODE",  "CONSTRAINT", "PRIORITY","VEHICLE", "VEH_TYPE",
                  "START",   "END", "TYPE") := 
                list("ZONE", "ZONE", "DRIVE", "NONE", "NO", 1, 1,
                     (period - 1) * 900, (period - 1) * 900 + 4 * 3600, 1)
  ]
  
  # SI_MAP1
  dt_purpose_map <- data.table (purpose = c("AtWork",
                                            "CrossBorderCommute",
                                            "Discretionary",
                                            "Eatout",
                                            "EmployerBusiness",
                                            "Escort",
                                            "heavy",
                                            "LeisureVacation",
                                            "light",
                                            "Maintenance",
                                            "medium",
                                            "PersonalBusiness",
                                            "Recreate",
                                            "School",
                                            "Shop",
                                            "University",
                                            "VistFriendFamily",
                                            "Work",
                                            "WorkVis"),
                                PURPOSE = c(1:19)
  )
  
  dt_TRANSIMS <- merge(dt_TRANSIMS, dt_purpose_map, by = "purpose", all.x = T)

  fnames <- c("HHOLD", "PERSON", "TOUR", "TRIP", "START", "END",
              "ORIGIN", "DESTINATION", "PURPOSE", "MODE", "CONSTRAINT", "VEH_TYPE",   
              "TYPE", "VOT", "TRIPS" )
  dt_TRANSIMS <- dt_TRANSIMS[, ..fnames]
  
  fwrite(dt_TRANSIMS, output_15min_TRANSIMS)
}




#-------------------------------------------------------------------------------
# Trip Summaries - PURPOSE
sum_per_purp <- dt_nextGen_List[, .N, by = "purpose"]
sum_purp <- dt_nextGen_List[, sum(vehTrips), by = "purpose"]
sum_purp_intrazonal <- dt_nextGen_List[O == D, sum(vehTrips), by = "purpose"]
sum_purp <- merge(sum_per_purp, sum_purp, by = "purpose", all = TRUE)
sum_purp <- merge(sum_purp, sum_purp_intrazonal, by = "purpose", all = TRUE)
setnames(sum_purp, c("purpose", "PersonTrips", "VehicleTrips", "IntrazonalTrips"))

sum_hour_purpose <- dcast(dt_nextGen_List[, sum(vehTrips), by = c("hour", "purpose")], hour ~ purpose, fill = 0)

# fwrite(sum_hour_purpose, paste0(scenario_dir, "/woWFH_woTele/trips_by_hour_purpose.csv"))

# Trip Summaries - Hour
sum_hour <- dt_nextGen_List[, sum(vehTrips), by = "hour"]


#-----------------------------------------------------------------------------------------------------
# Add New Market (do not grow the market)
if(appendNewMkt){
  dt_nm <- fread(commerical_acitivity)
  dt_nm <- dt_nm[Other > 0, c("O", "D", "period", "Other")]
  
  dt_nextGen_OD2 <- merge(dt_nextGen_OD, dt_nm, by = c("O", "D", "period"), all = TRUE)
  
  replace_NA = function(DT) {
    for (j in names(DT))
      set(DT,which(is.na(DT[[j]])),j,0)
  }
  
  replace_NA(dt_nextGen_OD2)
  
  setorder(dt_nextGen_OD2, period, O, D)
  fwrite(dt_nextGen_OD2, output_hourly_newMkt)
  
}






