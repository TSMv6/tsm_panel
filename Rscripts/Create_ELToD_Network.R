
library(tidyverse)
library(data.table) 
library(foreign)
library(sf)


#===============================================================================
# ELToD Scenario File
#===============================================================================
sf_walked      <- setDT(sf_fl)
sf_walked_node <- setDT(sf_fl_Nodes)

# Add geometry distance as length
fields_to_exist <- c("A", "B", "ST_NAME",  "from_county", "to_county","from_model", "to_model",
                     "DISTANCE", "Dir", "FACTYPE", "AREATYPE", "POSTSPEED", "NLANES", "TOLL")

if(keep_Counts) fields_to_exist <- c(fields_to_exist, count_fields[-1])
if(keep_reverse_flex_lanes) fields_to_exist <- c(fields_to_exist, "REVERSE", "FLEX")


dt_link <- sf_walked[, ..fields_to_exist] 
setnames(dt_link, "FACTYPE", "FTYPE")

# # Remove duplicate links
# dt_link <- dt_link[, flag := c(1:.N), by = c("A", "B")]
# dt_link <- dt_link[flag == 1, ]

# VDF parameters
dt_vdf <- data.table( FNAME = c("Limited", 	"Div-Arterial",	"Undiv-Arterial",	"Collector", "Centroid_Conn",	"Tolls", "Ramps", "Other"),
                      ALPHA = c(0.382, 0.422,	0.430,	0.438, 0.100, 0.430, 0.15, 0.15),
                      BETA =  c(5.840, 4.280,	3.800,	3.320, 2.500, 6.400, 4.00, 4.00))

# Append capacities
df_cap <- fread(file_QLOS_capacities, stringsAsFactors = FALSE)
colnames(df_cap) <- c("FNAME", "NLANES", "CAPACITY")

# Add Area Types
# dt_link <- dt_link[, ANAME := fcase(AREATYPE %in% c(10:19) , "1_CBD",
#                                     AREATYPE %in% c(20:30) , "2_Fringe",
#                                     AREATYPE %in% c(30:40) , "3_Residential",
#                                     AREATYPE %in% c(40:50) , "4_OBD",
#                                     AREATYPE > 49 , "5_Rural",
#                                     default = "3_Residential")]

dt_link <- dt_link[, ANAME := fcase(AREATYPE == 1 , "1_Urban",
                                    AREATYPE == 2, "2_Fringe",
                                    AREATYPE == 3 , "3_Rural",
                                    default = "3_Residential")]

# Add FTYPES (these are FSUTMS standard types)
dt_link <- dt_link[ ,FNAME := fcase(FTYPE %in% c(10:19, 87:89), "Limited",
                                    FTYPE %in% c(50:59) , "Centroid_Conn",
                                    FTYPE %in% c(20:29, 60:69) , "Div-Arterial",
                                    FTYPE %in% c(30:39) , "Undiv-Arterial",
                                    FTYPE %in% c(40:49) , "Collector",
                                    FTYPE %in% c(70:79) , "Ramps",
                                    FTYPE %in% c(90:99, 80:86) , "Tolls",
                                    default =  "Other")]

# Compute Freeflow speeds based on area type & facility 
dt_link <- dt_link[, SPEED := POSTSPEED,]
dt_link <- dt_link[, SPEED := fcase((FNAME == "Limited" & ANAME == "3_Rural" ) | FNAME ==  "Tolls"  , pmin(0.81 * POSTSPEED + 26.5, 1.10 * POSTSPEED), 
                                    FNAME %in% c("Limited", "Div-Arterial", "Undiv-Arterial") & ANAME != "3_Rural" , 0.85 * POSTSPEED,
                                    FNAME =="Ramps" & DISTANCE <= 0.5, pmax(25, pmin(0.8 * POSTSPEED, POSTSPEED - 15)),
                                    FNAME =="Ramps" & DISTANCE > 0.5 & DISTANCE <= 1,  pmax(25, pmin(0.9 * POSTSPEED, POSTSPEED - 10)), 
                                    FNAME =="Ramps" & DISTANCE > 1 & ANAME != "3_Rural",  pmax(25, 0.9 * POSTSPEED),
                                    POSTSPEED <= 35 & FNAME %in% c("Div-Arterial", "Undiv-Arterial", "Collector") , POSTSPEED - 8,
                                    POSTSPEED > 35 & FNAME %in% c("Div-Arterial", "Undiv-Arterial", "Collector") & ANAME != "5_Rural" , POSTSPEED * 0.80,
                                    POSTSPEED > 35 & !(FNAME %in% c("Div-Arterial", "Limited") & ANAME == "3_Rural") , POSTSPEED * 0.80,
                                    POSTSPEED > 35 & FNAME == "Div-Arterial" & ANAME == "3_Rural", POSTSPEED * 0.90,
                                    ANAME %in% c("1_Urban", "2_Fringe")  , POSTSPEED * 0.8,
                                    ANAME %in% c("3_Residential","4_OBD")  , POSTSPEED * 0.85,
                                    FNAME == "Other" | ANAME == "3_Rural",  1.0 * POSTSPEED)]

# SPEED checks, minimum speed of 
#  - 25 MPH on all facilities
#  - 50 MPH on Limited and Tolls facilities
dt_link[SPEED < 50 & FNAME %in% c('Tolls',  'Limited'), SPEED := 50]  
dt_link[SPEED < 25, SPEED := 25]  

# dt_link <- dt_link[is.na(SPEED),  SPEED := POSTSPEED, ]
dt_link <- dt_link[A <= maxZones | B <= maxZones, SPEED := 10]

dt_link <- merge(dt_link, dt_vdf, by = "FNAME", all.x = TRUE)
# dt_link[is.na(ALPHA),]
# dt_link[is.na(BETA),]

# Add delay impact factors for Free-way Off-Ramps (to reflect signal delays)
# Un-divided impact factors for high speed at high volumes
# Divided facilities that are short (under 1/2 mile) would have other turn lanes
dt_link <- dt_link[, c("IMPFAC", "DELAY_FLAG") := list(0,0)]
dt_link[FTYPE %in% c(75, 76), c("IMPFAC", "DELAY_FLAG") := list(1,1)]
dt_link[FNAME =="Undiv-Arterial" & NLANES == 1, c("IMPFAC", "DELAY_FLAG") := list(1,1)]

df_link2 <- merge(dt_link, df_cap, by = c("FNAME", "NLANES"), all.x = TRUE)
# df_link2[FNAME == "Div-Arterial" & POSTSPEED > 35, CAPACITY :=  1.18 * CAPACITY]
df_link2[FNAME == "Centroid_Conn", CAPACITY :=  99999]

# Update FTYPES 96 to 99 are EL and ELToD will run a dynamic pricing and to avoid it, use generic codes.
# df_link2[FTYPE > 95, FTYPE := 95] 

# Remove duplicate links
df_link2 <- df_link2[, flag := c(1:.N), by = c("A", "B")]
df_link2 <- df_link2[flag == 1, ]
df_link2 <- df_link2[, flag := NULL]

if(overwrite_prj_speed){
  prj_AB <- sf_walked[LINK_ID %in% prj_link_ids, c("A", "B")]
  prj_AB[, retainPOSTSPEED := 1]
  df_link2 <- merge(df_link2, prj_AB, by = c("A", "B"), all.x = TRUE)
  df_link2[retainPOSTSPEED == 1, SPEED := POSTSPEED]
  # df_link2[, retainPOSTSPEED = NULL]
}

# Tolls for 3AB mainline and ramps are different than in the original file
# if(overwriteTolls){
#   # Update network with right Tolls (mainline $1.34 and ramps = 0.80)
#  df_link2[ (A == 127026 & B == 127086) | (A == 127085 & B == 127025), TOLL := 1.34 ]
#  df_link2[ (A == 127027 & B == 127029) | (A == 127030 & B == 127028), TOLL := 0.80 ]
# 
# }

# Write link file
fwrite(df_link2, output_link)
# foreign::write.dbf(setDF(df_link2), gsub(".csv", ".dbf", output_link))

# Keep a shape file
# sf_walked_t    <- sf_walked[, c("POSTSPEED", "NLANES", "AREATYPE", "TOLL") := NULL]
# if(keep_Counts) sf_walked_t  <- sf_walked_t[,  COUNT := NULL]
# if(keep_reverse_flex_lanes) sf_walked_t  <- sf_walked_t[,  c("REVERSE", "FLEX") := NULL]

dt_geo_lnk <- merge(sf_walked[, c("A", "B", "geometry")], df_link2, by = c("A", "B"), all.x = TRUE)
dt_geo_lnk <- st_as_sf(dt_geo_lnk)
st_crs(dt_geo_lnk) <- 26917 
st_write(dt_geo_lnk, out_eltod_shp, append = FALSE)


# Node file
# dt_node <- sf_walked_node[, c("N", "X", "Y")]
sf_walked_node[, c("DTA_Type", "DNGRP") := 0]
# sf_walked_node[N %in% c(1: max_internal_zones, 11501:11560), DTA_Type := 99]
sf_walked_node[N %in% c(1: maxZones), DTA_Type := 99]
sf_walked_node <- sf_walked_node[, c("N", "X", "Y", "DTA_Type", "DNGRP", "geom")]
st_write(st_as_sf(sf_walked_node), out_eltod_node_shp, append = FALSE)
dt_node <- sf_walked_node[, c("N", "X", "Y", "DTA_Type", "DNGRP")]

# Write node file
fwrite(dt_node, output_node)
# foreign::write.dbf(setDF(dt_node), gsub(".csv", ".dbf", output_node))

# # Write Link /Node for Skimmy (untill Skimy is fixed to read all attributes)
# dt_node[DTA_Type == 99, zone := TRUE]
# dt_node[, Signal := NA]
# fwrite(dt_node[, c("N", "zone", "Signal")], gsub(".csv", "_for_Skimmy.csv", output_node))

# # updated the code to account for the current Links & Nodes .CSV design needed for Skimmy to run
# dt_link_s <- df_link2[, c("A", "B", "DIST", "SPEED", "TOLL")]
# setnames(dt_link_s, c("from", "to", "distance", "SPEED", "TOLL"))
# fwrite(dt_link_s, gsub(".csv", "_for_Skimmy.csv", output_link))       
         

#===============================================================================


