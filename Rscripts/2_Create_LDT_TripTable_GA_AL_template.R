
library(data.table)
library(tidyverse)
library(openxlsx)
library(sf)

# Read Arguments
args            <- commandArgs(trailingOnly = TRUE)
print(args)
catalog_dir     <- args[1]               # [1] "C:\\TSM_NextGen_v3"
scenario_dir    <- args[2]             # "C:\\TSM_NextGen_v3\\Base\\TSMv4_2022"
year            <- as.integer(args[3]) - 2000 # "23"

# catalog_dir     <- "C:\\TSM_NextGen_v5"
# scenario_dir    <- "C:\\TSM_NextGen_v5\\Base\\TSMv5_2023"
# year            <- 23
# incremental     <- 0


  # TODO remove it from the final version
  fl_ldt_tours <- paste0(scenario_dir, "/FL_LD_tour_out.csv") # see TSMv5_2023/tsv5 sub directory for 2023
  os_ldt_tours <- paste0(scenario_dir, "/OS_LD_tour_out.csv")
  
  dt_fl <- fread(fl_ldt_tours)
  # dt_fl <- fread(fl_ldt_tours)[, trVehicle := NULL]
  dt_os <- fread(os_ldt_tours)
  dt_prev <- rbindlist(list(dt_fl, dt_os))
  
  # LDT output
  future_output        <- paste0(scenario_dir, "/LD_tour_out.csv") # see TSMv5_2023/tsv5 sub directory for 2023
  fwrite(dt_prev, future_output)


# Manual Run (2023 run with version 1.6)
# future_output <- paste0(scenario_dir, "/tsmv4/LD_tour_out_2023.csv")

# Lookup tables
# airport_ext_shares <- "Inputs/external_counts/External_Auto_Internal_Airport_Zone_distributions.csv"
airport_ext_shares    <- paste0(catalog_dir, "/Inputs/external_counts/External_Auto_Internal_Airport_Zone_Shares.xlsx")
time_of_day_file      <- paste0(catalog_dir, "/Inputs/tod/TimeSegment_distributions.xlsx")
external_destinations <- paste0(catalog_dir, "/Inputs/external_counts/GA_AL_LDT_Destinations.xlsx")
cbm_external_lookup   <- paste0(catalog_dir, "/Inputs/external_counts/CrossBorder_TAZ_to_Externals_TSMv4.xlsx")

# Interim Outputs:
# 1. TAZ shape file: TAZ, STL_ID, County, DMA
# 2. Landuse file: Use 8 DMAs instead of 7 FDOT districts
# 3. US States shape file: 

# Original files:
# TAZ_shapes2 <- paste0(catalog_dir,"/Inputs/zone_shapeFiles/Florida_Zones_appended_STL.shp")
TAZ_shapes2 <- paste0(catalog_dir,"/Inputs/zone_shapeFiles/Florida_Zones_appended_STL_TSMv4.csv")

# tsm_stl    <- "Inputs/zone_shapeFiles/TSM_2_STL_SE_Data_v2.csv"
# us_states  <- "Output/US_States.shp"
# landuse    <- "inputs/rJourney_Landuse.dat"

# Updated files:
# TAZ_shapes2 <- gsub(".shp", "_appended_STL.shp", TAZ_shapes)
# us_states2  <- gsub(".shp", "_2.shp", us_states)
# landuse2    <- gsub(".dat", "_dma.dat",landuse)

# Output file
# merged_tourList <- gsub(".csv", "_previous.csv",  future_output)
tripList_output <- paste0(scenario_dir, "/LD_tour_out_processed.csv")
trips_output    <- paste0(scenario_dir, "/LD_tour_out_processed_ToD_Trips.csv")

# Exclude non-Interstate external flows (Visitor Flows to FL and FL residents to out-of-state )
apply_originState_based_externals <- TRUE
use_cbm_external_lookup           <- TRUE
separate_res_markets              <- TRUE  # Separates out LDT Res II vs IE markets

# External Count Checks
exclude_non_Interstate            <- FALSE
remove_NorthFL_res_trips          <- FALSE

# Optional for LDT assignment
compute_LDT_TT      <- TRUE
ELTOD_LDT_output    <- paste0(scenario_dir,"/ELTOD_LDT_tt.csv")

#===============================================================================
# rJourney output file definitions
# hhId	        Sequential hh ID from synthetic population (link to HH file)
# trNo	        Sequential tour number within HH
# trMonth	      tour month (1=Jan, …. , 12=Dec)
# trPurpose	    tour purpose code (see codes below)
# trPartySize	  tour party size (number of people, 6=6+)
# trNightsAway	tour nights away from home (see codes below)
# trMode	      tour mode code (see codes below)
# trOState	    tour origin state FIPS code 
# trDState	    tour destination state FIPS code 
# trOZone	      tour origin zone ID (NUMA system)
# trDZone	      tour destination zone ID (NUMA system)
# trAutoDistance	tour round trip auto distance (miles by auto network, regardless of chosen mode)
# trTravelTime	tour round trip travel time (minutes by chosen mode)
# trTravelCost	tour round trip travel cost (dollars by chosen mode)
# trExpFactor	  tour expansion factor  (= factor from synthetic population * subsample rate)
# trOrigStation   tour origin station
# trDestStation   tour destination station
# trORegion       tour orign region
# tDORegion       tour destination region
# trVOT           value of time
# hhHeadAge       hh header age
# hhIncome        hh income

# Codes for tour mode (trMode)
# 1 auto
# 2 bus
# 3 rail
# 4 air

# Codes for tour purpose (trPurpose)
# 1 personal business
# 2 visit friends or relatives
# 3 leisure/vacation
# 4 commute
# 5 employer's business

# Codes for nights-away category (trNightsCategory)
# 1 - Day Trip
# 2 - one-to-two nights away
# 3 - three-to-six nights away
# 4 - a week or more nights away 

#===============================================================================
# 1. Append Tour types and DMA's
#===============================================================================
# Read DMA by TAZ
# sf_dma     <- st_read(TAZ_shapes2)
# dt_dma     <- setDT(sf_dma)

dt_dma     <- fread(TAZ_shapes2)
dt_dma     <- dt_dma[, c("TAZ", "DMA")]

# Read external destinations (AL/GA crossborder TAZs)
dt_ALGA <- read.xlsx(external_destinations) %>% 
  mutate(DMA = 10) %>%
  select(TAZ, DMA) %>%
  setDT()

# Update DMA
dt_dma <- rbindlist(list(dt_dma, dt_ALGA))

# Read ldt output (Incremental)
# if(merge_base_n_future){
#   
#   # Read 2019 new hhs based LDT results
#   dt_tours   <- fread(future_output)
#   
#   # Load base year tours
#   dt_tours15 <- fread(base_output)
# 
#   # Remove hhs that aren't in 2019 
#   combine_removable_hhs_ids <- fread("hh15_not_in_2019.csv")
#   dt_tours15 <- dt_tours15[!(hhId %in%  combine_removable_hhs_ids$combine_removable_hhs_ids), ]
#   
#   # merge old and new hhs
#   dt_tours <- rbindlist(list(dt_tours15, dt_tours))
#   fwrite(dt_tours,merged_tourList)
#   
# } else{
#   
#   dt_tours <- fread(merged_tourList)
#   
# }

# Read ldt output
dt_tours   <- fread(future_output)

# Append DMA regions
dt_tours <- merge(dt_tours, dt_dma, by.x = "trDZone", by.y = "TAZ", all.x = TRUE)
setnames(dt_tours, "DMA", "des_DMA")
dt_tours <- merge(dt_tours, dt_dma, by.x = "trOZone", by.y = "TAZ", all.x = TRUE)
setnames(dt_tours, "DMA", "org_DMA")

dt_tours[is.na(org_DMA), org_DMA:= 0 ]
dt_tours[is.na(des_DMA), des_DMA:= 0 ]

# Code IE, II, EI and EE trips (there shouldn't be any EE trips)
dt_tours <- dt_tours[, type := fcase(trOState == 12 & trDState == 12, "II",
                                     trOState == 12 & trDState != 12, "IE",
                                     trOState != 12 & trDState == 12, "EI",
                                     trOState != 12 & trDState != 12, "EE",
                                     default = "none")]


# If there are air tour within same DMA then convert them to Auto trips.
# While this is possible, some would fly within DMAs it's quite not practical
InterDMA_air <- dt_tours[trMode == 4, .N, by = c("org_DMA", "des_DMA")]
# dcast(InterDMA_air,org_DMA ~ des_DMA)
InterDMA_air[org_DMA == des_DMA, ]

dt_tours[trMode == 4 & org_DMA == des_DMA, trMode := 1]

# There are too many central florida tours to central florida tours
# This requires breaking up of CFL DMA into multiple markets,
fineCalib <- FALSE

if(fineCalib){
  #  for now reduce the total tours by 40% (based on vol/counts) at I-4 (west of US 27), I-4 (at I-95), Turnpike near I-75
  CFL_ldt_res_ii_ntours <- dt_tours[trORegion == 5 & trDRegion == 5, .N]
  dt_tours[trORegion == 5 & trDRegion == 5, sel := sample(c(NA,-1), prob = c(0.6, 0.4), CFL_ldt_res_ii_ntours, replace = TRUE)]

  # Similarly reduce trips to/from Tampa to Daytona (there is no data, but part of model validation / SL links suggessts there cannot be 16K daily trips I-4 end-to-end)
  TPA_to_Daytona_ldt_res_ntours <- dt_tours[trORegion == 6 & trDRegion == 4, .N]
  dt_tours[trORegion == 6 & trDRegion == 4, sel := sample(c(NA,-2), prob = c(0.1, 0.9), TPA_to_Daytona_ldt_res_ntours, replace = TRUE)]

  # Reduce trips to/from Orlando to Daytona (there is no data, but part of model validation / SL links on I-4)
  Orl_to_Daytona_ldt_res_ntours <- dt_tours[(trORegion == 5 & trDRegion == 4 ) | (trORegion == 4 & trDRegion == 5), .N]
  dt_tours[(trORegion == 5 & trDRegion == 4 ) | (trORegion == 4 & trDRegion == 5),
              sel := sample(c(NA,-3), prob = c(0.5, 0.5), Orl_to_Daytona_ldt_res_ntours, replace = TRUE)]

  # Reduce trips to/from Orlando to Jacksonville / St.Johns (there is no data, but part of model validation / SL links on I-4)
  Orl_to_JacksonStJohns_ldt_res_ntours <- dt_tours[(trORegion == 5 & trDRegion == 3 ) | (trORegion == 3 & trDRegion == 5), .N]
  dt_tours[(trORegion == 5 & trDRegion == 3 ) | (trORegion == 3 & trDRegion == 5),
              sel := sample(c(NA,-4), prob = c(0.5, 0.5), Orl_to_JacksonStJohns_ldt_res_ntours, replace = TRUE)]

  # Reduce internal SFL trips (there is no data, but part of model validation / SL links on Turnpike / HEFT)
  SFL_to_SFL_ldt_res_ntours <- dt_tours[trORegion == 8 & trDRegion == 8 , .N]
  dt_tours[trORegion == 8 & trDRegion == 8,
              sel := sample(c(NA,-5), prob = c(0.5, 0.5), SFL_to_SFL_ldt_res_ntours, replace = TRUE)]

  dt_tours[!is.na(sel), .N, by = "sel"] # to remove
  dt_tours <- dt_tours[is.na(sel), ]
  dt_tours <- dt_tours[, sel := NULL]

}

# Print internal DMA-to-DMA flows 
d2d <- dcast(dt_tours[trMode == 1, .N, by = c("trORegion", "trDRegion")],
      trORegion ~ trDRegion , value.var = "N")
print(d2d)

#===============================================================================
# 2. Assign an External Station for EI/IE Auto Tours 
#===============================================================================
# Add Origin and Destination TAZ and access / egress modes for airport trips
# otaz         : tour origin or airport in FL or external station at the border
# dtaz         : tour destination or airport in FL or external station at the border 
# entry_ext    : external TAZ - entry point for visitor (EI) Auto tours
# exit_ext     : external TAZ - exit point for resident (IE) Auto tours
# entry_airpt  : airport TAZ - entry point for visitor (EI) Air tours
# exit_airpt   : airport TAZ - exit point for resident (IE) Air tours
# accMode      : airport access mode (only for airports in FL) for Air tours
# egrMode      : airport egress mode (only for airports in FL) for Air tours
# tripMode     : for airport access/egress trips (either accMode or egrMode) 

dt_tours2  <- dt_tours[, c("entry_ext", "exit_ext", "entry_airpt", "exit_airpt",
                           "accMode", "egrMode",  "otaz", "dtaz", "tripMode") := 
                          list(0, 0, 0, 0, "Auto", "Auto", trOZone, trDZone, "Auto")]

# read external auto and airport shares by DMA
# dt_shares <- fread(airport_ext_shares)
dt_shares_ext_CBM  <- read.xlsx(airport_ext_shares, sheet = "External_Auto") %>% setDT()
dt_shares_air      <- read.xlsx(airport_ext_shares, sheet = "Airport")  %>% setDT()
dt_shares_cruise   <- read.xlsx(airport_ext_shares, sheet = "CanaveralCruiseTrips")  %>% setDT()

#===============================================================================
# 0. Add Port Cape Canaveral Trips (unlike other ports such as Miami, FLL and Tampa, the origins are farther away over 50 miles and so not modeled in any markets)
# Introduce cape canaveral trips from hotel rooms (SDT nor LDT model doesn't include this market)
TAZ_port_parking   <- 4381
Cruise_Trips       <- 5500 # One-way 2 person vehicle trips (4 million passengers in 2022 -> 11k persons -> 5500 vehicle trips )

dt_cruiseTrips <- dt_tours[1:Cruise_Trips, ]
dt_cruiseTrips[, trOZone := sample( dt_shares_cruise$NextGen_TAZ, Cruise_Trips, prob = dt_shares_cruise$HotelRoom_Share, replace = TRUE)] 
dt_cruiseTrips[, trDZone := TAZ_port_parking] 
dt_cruiseTrips[, c("des_DMA","org_DMA", "trMode", "otaz", "dtaz") := list(5,4,1, trOZone, trDZone)]

#===============================================================================
# a) EI / IE: Auto Tours
dt_shares_ext <- dt_shares_ext_CBM[CBM == 0, ]
prob          <- dt_shares_ext$share
values        <- dt_shares_ext$NextGen_TAZ

# Assume external station based on Origin State (instead of random probability)
# I-10 ->  11504
# I-75 ->  11548
# I-95 ->  11560

if(apply_originState_based_externals) {
  # EI - External - Auto (pick an external station for visitor entry)
  states_I10 <- c(1, 4, 22, 48)
  states_I75 <- c(5, 35, 6, 8, 16, 17, 18, 19, 20, 21, 26, 27, 28, 29, 31, 32, 38, 39, 40, 41, 47, 49, 55, 56)

  dt_tours2_ei_auto <- dt_tours2[trMode == 1 & type == "EI", ]
  dt_tours2_ei_auto[ , entry_ext := fcase(trOState %in% states_I10, 11504,
                                         trOState %in% states_I75, 11548, 
                                         default = 11560 )]
  
} else {

  # EI - External - Auto (pick an external station for visitor entry)
  dt_tours2_ei_auto <- dt_tours2[trMode == 1 & type == "EI", ]
  size              <- nrow(dt_tours2_ei_auto)
  
  set.seed(1L)
  dt_tours2_ei_auto[, entry_ext := sample(values, size, prob, replace = TRUE)]
  set.seed(NULL)
  
  # Loop over NorthFlorida DMAs (Panhandle to Jacksonville: DMA 1, 2, 3)
  # for(c in c(1:3)){
  #   dt_shares_cbm <- dt_shares_ext[CBM == 0 & DMA == c, ]
  #   dt_tours2_ei_auto[des_DMA == c, entry_ext := dt_shares_cbm$NextGen_TAZ]
  # }
  
}

# IE - External - Auto (pick an external station for resident exit)
dt_tours2_ie_auto <- dt_tours2[trMode == 1 & type == "IE" & !(org_DMA < 4 & des_DMA == 10), ]
size              <- nrow(dt_tours2_ie_auto)

set.seed(1L)
dt_tours2_ie_auto[, exit_ext := sample(values, size, prob, replace = TRUE)]
set.seed(NULL)

# IE - External crossborder 
# Option - 1 - Use lookup to assign externals

 if(use_cbm_external_lookup) {
    dt_cbmExt <- read.xlsx(cbm_external_lookup) %>%
      select(TAZ, CBM_Ext) %>%
      setDT()
    
    dt_tours2_cbm_auto <- dt_tours2[trMode == 1 & type == "IE" & org_DMA < 4 & des_DMA == 10, ]
    dt_tours2_cbm_auto <- merge(dt_tours2_cbm_auto, dt_cbmExt, by.x = "otaz", by.y = "TAZ", all.x = TRUE)
    dt_tours2_cbm_auto[, exit_ext := CBM_Ext]
    dt_tours2_cbm_auto[, CBM_Ext := NULL]
  
  } else{ 
    
    # Option - 2 - Use random probabilities based on external counts
    # Note: this will end-up sending trips along I-10 which results in overestimating I-10 corridor
    dt_tours2_cbm_auto <- dt_tours2[trMode == 1 & type != "II" & 
                                      (org_DMA == 10 | des_DMA == 10), ]
    
    # For DMAs (Central & South FL, Use DMA 2)
    dt_shares_cbm <- dt_shares_ext_CBM[CBM == 2, ]
    prob          <- dt_shares_cbm$share
    values        <- dt_shares_cbm$NextGen_TAZ
    size <- dt_tours2_cbm_auto[(org_DMA > 3 | des_DMA > 3), .N, by = "type"]
    
    set.seed(1L)
    dt_tours2_cbm_auto[type == "IE" & (org_DMA > 3 ), 
                       exit_ext := sample(values, size[type == "IE", N], prob, replace = TRUE)]
    
    dt_tours2_cbm_auto[type == "EI" & (des_DMA > 3 ), 
                       entry_ext := sample(values, size[type == "EI", N], prob, replace = TRUE)]
    
    # Loop over NorthFlorida DMAs (Panhandle to Jacksonville: DMA 1, 2, 3)
    for(c in c(1:3)){
      
      dt_shares_cbm <- dt_shares_ext_CBM[CBM == c, ]
      prob          <- dt_shares_cbm$share
      values        <- dt_shares_cbm$NextGen_TAZ
      
      
      size <- dt_tours2_cbm_auto[(org_DMA == c | des_DMA == c), .N, by = "type"]
      
      set.seed(1L)
      dt_tours2_cbm_auto[type == "IE" & (org_DMA == c | des_DMA == c), 
                         exit_ext := sample(values, size[type == "IE", N], prob, replace = TRUE)]
      
      dt_tours2_cbm_auto[type == "EI" & (org_DMA == c | des_DMA == c), 
                         entry_ext := sample(values, size[type == "EI", N], prob, replace = TRUE)]
      set.seed(NULL)
      
    }
  
  }


#===============================================================================
# 3. Assign an Airport TAZ for EI & II Airport Tours 
#===============================================================================
# Assign at the origin end 
dt_tours2_ei_air <- dt_tours2[trMode == 4 & type =="EI", ]

# Assign at the destination end
dt_tours2_ie_air <- dt_tours2[trMode == 4 & type == "IE", ]

# Assign at the both origin and destination ends
dt_tours2_ii_air <- dt_tours2[trMode == 4 & type == "II", ]

# a) EI / IE / II: airport Tours
# dt_shares_air <- dt_shares[DMA > 0, ]

# Add additional row with same for sample() to work
err_row <- list("Airport", 3, 7536,  0.01)
dt_shares_air <- rbindlist(list(dt_shares_air, err_row))

# Disney DMA is same as Central FL DMA and so duplicate DMA 5 as DMA 9 for Airport access shares
dt_shares_air_DMA9 <- dt_shares_air[DMA == 5, ]
dt_shares_air_DMA9[, DMA := 9]
dt_shares_air <- rbindlist(list(dt_shares_air, dt_shares_air_DMA9))

# c) Aiport Access / Egress Mode Shares (D5 - 2015 GOAA survey)
#
# Code GOAA Mode Shares (FDOT D5)	       		 Shares
# 11	Rental Cars 	                   			  0.34
# 11	Drop Off/Pick up at OIA Terminals			  0.20
# 12	Disney Magical Express (DME)	   			  0.11
# 11	Taxi	                           			  0.11
# 11	On-site Parking (on OIA property)			  0.09
# 11	Off-site Parking (near OIA)	       			0.05
# 12	Other MEARS (Shuttle / Taxi)	   			  0.03
# 12	Public transit	                   			0.01
# 11	Other modes (Uber / Lyft / Hotel Shuttles)	  0.06

# Updated 2024 Airport Survey (from D5)
#
# Mode           : Resident : Visitor
# Rental Cars    : 12.8%    , 43.5% 
# Parking Onsite : 57.2%    , 9.1%
# Ridehare/TNC   : 6%       , 15.6%
# Private Drop-off : 11.1%  , 7.1%
# Mears (Bus)    : 1.3%     , 9.6%
# Shuttles       : 2.5%     , 8.7%
# Taxi           : 4.5%     , 5.6%
# Parking Offsite: 4.6%     , 0.5%
# Bus/FG+Bus     : 0.0%      , 0.2

# Derived Resident, Visitor
# Auto - 96.2% , 81.5%
# Bus/Shuttle - 3.8%,  18.3%
# Other Transit - 0%, 0.2%

# For assignment purposes, it is 84% Auto mode and 16% other modes.
# 16% is due to 11.4% Disney Magical Express service share.
# For all other airports, it is 96% Auto mode and 4% other modes.

airport_mode       <- list()
airport_mode$label <- c("Auto", "DME", "Other")
airport_mode$code  <- c(11, 12, 13)
airport_mode$share <- c(0.815, 0.183, 0.02)

# Loop for each of 8 DMA's Airport Trips (note DMA 9 is same as DMA 5)
# for(d in c(1:length(unique(dt_shares_air$DMA)))){  
for(d in c(1:9)){  
  # subset tours and shares by DMA
  prob          <- dt_shares_air[DMA == d, share]
  values        <- dt_shares_air[DMA == d, NextGen_TAZ]
  size_d        <- dt_tours2_ei_air[des_DMA == d, .N]
  size_o        <- dt_tours2_ie_air[org_DMA == d, .N]
  size_od1       <- dt_tours2_ii_air[des_DMA == d, .N]
  size_od2       <- dt_tours2_ii_air[org_DMA == d, .N]
  
  # In the destination DMA, pick airport zone as origin taz
  dt_tours2_ei_air[des_DMA == d & org_DMA != d, exit_airpt := sample(values, size_d, prob, replace = TRUE)]
  dt_tours2_ii_air[des_DMA == d & org_DMA != d, exit_airpt := sample(values, size_od1, prob, replace = TRUE)]
  
  # In the origin DMA, pick airport zone as destination taz 
  dt_tours2_ie_air[org_DMA == d & des_DMA != d, entry_airpt := sample(values, size_o, prob, replace = TRUE)]
  dt_tours2_ii_air[org_DMA == d & des_DMA != d, entry_airpt := sample(values, size_od2, prob, replace = TRUE)]
  
  # Pick airport access / egress trip-mode
  dt_tours2_ei_air[des_DMA == d & org_DMA != d, egrMode := sample(airport_mode$label, size_d, airport_mode$share, replace = TRUE)]
  dt_tours2_ii_air[des_DMA == d & org_DMA != d, egrMode := sample(airport_mode$label, size_od1, airport_mode$share, replace = TRUE)]
  
  dt_tours2_ie_air[org_DMA == d & des_DMA != d, accMode := sample(airport_mode$label, size_o, airport_mode$share, replace = TRUE)]
  dt_tours2_ii_air[org_DMA == d & des_DMA != d, accMode := sample(airport_mode$label, size_od2, airport_mode$share, replace = TRUE)]
  
  # TODO:: Access mode-choice model based on distance, time, cost
  # Exceptions - QA / QC 
  # Since no other airport other than OIA has DME mode, replace this with drop-off / pick-up
  dt_tours2_ei_air[exit_airpt != 4657 & egrMode == "DME",  egrMode := "Auto"]
  dt_tours2_ii_air[exit_airpt != 4657 & egrMode == "DME",  egrMode := "Auto"]
  dt_tours2_ie_air[entry_airpt != 4657 & accMode == "DME",  accMode := "Auto"]
  dt_tours2_ii_air[entry_airpt != 4657 & accMode == "DME",  accMode := "Auto"]
  
  # Make sure DME is only available for Disney Resorts
  Disney_zones <- c(4232, 4235, 4589, 4590, 4592, 4594, 4607, 4610, 4611, 4620, 4621, 4632)
  Universal_zones <- c(5764, 5771, 5787, 5796, 5797, 5799)
  
  dt_tours2_ei_air[exit_airpt == 4657 & !(trDZone %in% Disney_zones) & egrMode == "DME", egrMode := "Auto"]
  dt_tours2_ii_air[exit_airpt == 4657 & !(trDZone %in% Disney_zones) & egrMode == "DME", egrMode := "Auto"]
  dt_tours2_ie_air[entry_airpt == 4657 & !(trOZone %in% Disney_zones) & accMode == "DME", accMode := "Auto"]
  dt_tours2_ii_air[entry_airpt == 4657 & !(trOZone %in% Disney_zones) & accMode == "DME", accMode := "Auto"]
  
  # if both trip ends are within the same DMA, then it's an auto trip, not an air travel
  dt_tours2_ei_air[des_DMA == org_DMA, trMode := 1]
  dt_tours2_ii_air[des_DMA == org_DMA, trMode := 1]
  dt_tours2_ie_air[des_DMA == org_DMA, trMode := 1]
  dt_tours2_ii_air[des_DMA == org_DMA, trMode := 1]
  
}

#===============================================================================
# 4. Assign an Rail & Bus TAZ for Other Tours 
#===============================================================================
dt_tours2_other <- dt_tours2[trMode %in% c(2,3), ]
# For now ignore this market and treat them as non-assignable due to its small share of total trips
# Revisit this for BrightLine and add BrightLine stations and their probability of choosing when data is available.


#===============================================================================
# 5. Consolidate tours across all markets 
#===============================================================================
# Add unaltered market
dt_tours2_ii_auto <- dt_tours2[trMode == 1 & type == "II", ]

# For airport trips, add the access and egress legs (II - duplicate the tour record for access and egress trips)
dt_trips2_ii_air_accessLeg <- copy(dt_tours2_ii_air)
dt_trips2_ii_air_accessLeg[, c("exit_airpt","dtaz", "tripMode") := list(0, entry_airpt, accMode)]

dt_trips2_ii_air_egressLeg <- copy(dt_tours2_ii_air)
dt_trips2_ii_air_egressLeg[, c("entry_airpt","otaz", "tripMode") := list(0, exit_airpt, egrMode)]

dt_tours2_ie_air[, c("exit_airpt","dtaz", "tripMode") := list(0, entry_airpt, accMode)]
dt_tours2_ei_air[, c("entry_airpt","otaz", "tripMode") := list(0, exit_airpt, egrMode)]

# For external trips, add external zones as starting and ending zones for the tour
dt_tours2_ei_auto[, c("exit_ext","otaz") := list(0, entry_ext)]
dt_tours2_ie_auto[, c("entry_ext","dtaz") := list(0, exit_ext)]
# dt_tours2_cbm_auto[type =="EI",c("exit_ext","otaz") := list(0, entry_ext)]
dt_tours2_cbm_auto[type =="IE",c("entry_ext","dtaz") := list(0, exit_ext)]

dt_tours2_ei_auto[, .N, by = "entry_ext"]

# Consolidate
dt_tours3 <- rbindlist(list(dt_tours2_ii_auto, 
                            dt_tours2_ei_auto, 
                            dt_tours2_ie_auto,
                            dt_tours2_cbm_auto,
                            dt_tours2_ie_air, 
                            dt_tours2_ei_air, 
                            dt_trips2_ii_air_accessLeg,
                            dt_trips2_ii_air_egressLeg,
                            dt_cruiseTrips), use.names=TRUE)

# Check the tours by mode to ensure all tours are accounted
before <- dt_tours2[, .N, by = c("type", "trMode")]
dcast(before, trMode ~ type)

after <- dt_tours3[, .N, by = c("type", "trMode")]
dcast(after, trMode ~ type)

# Check tours by sub-modes (access / egress modes)
z <- dt_tours3[, .N, by = c("accMode", "egrMode")]
dcast(z, accMode ~ egrMode)

#===============================================================================
# 6. VOT: Apply Based on HH Income
#===============================================================================
# VOT from the properties
 vot_thresholds <- c(6.51, 11.68)  # LDT Model uses old VOT thresholds (2015)
# vot_thresholds <- c(12.81, 22.83) # The post COVID is only used in routing model once the trip enters the state.

# Get VOT classes 
dt_tours3 <- dt_tours3[ ,vot := fcase( type == "EI" & trVOT <= vot_thresholds[1], "LDT_Vis_Low",
                                       type == "EI" & trVOT  > vot_thresholds[1] & trVOT <= vot_thresholds[2], "LDT_Vis_Med",
                                       type == "EI" & trVOT  > vot_thresholds[2], "LDT_Vis_Hig",
                                       type != "EI" & trVOT <= vot_thresholds[1], "LDT_Res_Low",
                                       type != "EI" & trVOT  > vot_thresholds[1] & trVOT <= vot_thresholds[2], "LDT_Res_Med",
                                 default = "LDT_Res_Hig")]

fwrite(dt_tours3, tripList_output)

# Check DMA to DMA
dcast(dt_tours3[, .N, by = c("org_DMA", "des_DMA", "vot")], vot + org_DMA ~ des_DMA, value.var = "N", fill = 0)


#===============================================================================
# 7. Reverse: Flip the tours to create reverse bound
#===============================================================================
dt_trips          <- copy(dt_tours3)
dt_trips_reverse  <- copy(dt_tours3)

dt_trips         <- dt_trips[, dir := "tour_dir"]
dt_trips_reverse <- dt_trips_reverse[, c("otazR", "dtazR", "org_DMAR", "des_DMAR", "dir") := 
                                       list(dtaz, otaz, des_DMA, org_DMA, "return_dir")]
dt_trips_reverse <- dt_trips_reverse[, c("otaz", "dtaz", "des_DMA", "org_DMA") := NULL]
setnames(dt_trips_reverse, c("otazR", "dtazR", "org_DMAR", "des_DMAR"),c("otaz", "dtaz", "org_DMA", "des_DMA")) 

dt_trips_both <- rbindlist(list(dt_trips, dt_trips_reverse), use.names=TRUE)

#===============================================================================
# 8. Time of Day: Use StreetLight Data Distributions based on Market distribution
#===============================================================================
# Get departure_time from STL and Toll - axles
dt_tod <- read.xlsx(time_of_day_file) %>% 
  setDT()

# Trip Time of Day by Market Segment
period_lab <- dt_tod$TimeSeg_96

size_res   <- dt_trips_both[type != "EI", .N]
prob_res   <- dt_tod$Res_Long

size_vis   <- dt_trips_both[type == "EI", .N]
prob_vis   <- dt_tod$Vis_Long

set.seed(1L)
dt_trips_both <- dt_trips_both[type != "EI", period := sample(period_lab, size_res, prob_res, replace = TRUE)]
dt_trips_both <- dt_trips_both[type == "EI", period := sample(period_lab, size_vis, prob_vis, replace = TRUE)]
set.seed(NULL)

#===============================================================================
# 9. Check externals 
#===============================================================================
# Visitor trips from non-Interstates were loading onto Interstates (I-75) in much higher volumes, 
# implying these trips must never be destined to Central or Southern DMAs
# TODO: Non-Interstates externals should be used for LDT assignment. So, tow options:
# 1. Re-calibrate LDT Visitors to match to only 3 Interstate Counts (I-10, I-75 and I-95)
# 2. Since it's already calibrated to match 3 + other 7 non-interstates, just remove these non-interstate O-Ds (quick fix).

interstates_exts <- c(11560, 11548, 11504, 11558, 11542, 11540 , 11538, 11529, 11516, 11509)
# exts <- c(11558, 11542, 11540 , 11538, 11529, 11516, 11509)

if(exclude_non_Interstate){
  
  dt_trips_both <- dt_trips_both[ (otaz %in% interstates_exts | dtaz %in% interstates_exts), ]

}

if(remove_NorthFL_res_trips){
  dt_trips_both <- dt_trips_both[ !(org_DMA %in% c(1,2,3, 10) & des_DMA %in% c(1,2,3, 10)), ]
}


fwrite(dt_trips_both, trips_output)

#===============================================================================
# 9. ELToD Trip Table:
#===============================================================================
if(compute_LDT_TT){
  
  # Separate out Resident II and IE for validation
  if(separate_res_markets){
    
    dt_trips_both <- dt_trips_both[ ,vot := fcase( type == "EI" & trVOT <= vot_thresholds[1], "LDT_Vis_Low",
                                                   type == "EI" & trVOT  > vot_thresholds[1] & trVOT <= vot_thresholds[2], "LDT_Vis_Med",
                                                   type == "EI" & trVOT  > vot_thresholds[2], "LDT_Vis_Hig",
                                                   type == "II" & trVOT <= vot_thresholds[1], "LDT_ResII_Low",
                                                   type == "II" & trVOT  > vot_thresholds[1] & trVOT <= vot_thresholds[2], "LDT_ResII_Med",
                                                   type == "II" & trVOT  > vot_thresholds[2], "LDT_ResII_Hig",
                                                   type == "IE" & trVOT <= vot_thresholds[1], "LDT_Res_Low",
                                                   type == "IE" & trVOT  > vot_thresholds[1] & trVOT <= vot_thresholds[2], "LDT_Res_Med",
                                                   type == "IE" & trVOT  > vot_thresholds[2], "LDT_Res_Hig",
                                                   default = "None")]
  }
  
  tt <- dt_trips_both[ tripMode == "Auto", .N, by = c("otaz", "dtaz", "period", "vot")]
  # tt <- dt_trips_both[ tripMode == "Auto" & dir == "tour_dir", .N, by = c("otaz", "dtaz", "period", "vot")]
  
  # For residents use 50% after transposing (Visitors are calibrated to external counts inbound direction)
  # dt_trips_both[, vehTrips := fcase(type == "II", 0.5,
  #                                   default = 1)]
  # 
  # tt <- dt_trips_both[ tripMode == "Auto", sum(vehTrips), by = c("otaz", "dtaz", "period", "vot")]
  

  tt <- dcast(tt, otaz +  dtaz + period ~ vot)
  
  # replace NAs
  f_repalceNA <- function(DT) {
    for (i in names(DT))
      DT[is.na(get(i)), (i):=0]
  }
  
  f_repalceNA(tt)
  
  setorder(tt, period, otaz, dtaz)
  setnames(tt, c("otaz", "dtaz"), c("O", "D"))
  fwrite(tt, ELTOD_LDT_output)
  
}


#===============================================================================
# 10. Check trips at the external stations 
#===============================================================================

# entry <- dcast(dt_tours3[tripMode == "Auto", .N, by = c("entry_ext","des_DMA")], entry_ext ~ des_DMA)
# exit  <- dcast(dt_tours3[tripMode == "Auto", .N, by = c("exit_ext","org_DMA")], exit_ext ~ org_DMA)






