library(tidyverse)
library(data.table) 
library(foreign)
library(sf)
library(walkTheGraph)

# library(Rcpp)
# sourceCpp("C:/Projects/rPackage/walk_the_graph_v5_RPM.cpp")
# sourceCpp(paste0(plugin_dir, "/Rscripts/walk_the_graph_v5_RPM.cpp"))
options(scipen = 999) # Don't use scientific notation

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
      value <- gsub('/"', '', value)
      
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

# Example usage
settings_file <-  args[1]
settings_file <-   "C:/TSM_NextGen_v6/Base/TSMv6_2024_fullrun/link_consolidation_settings.txt"

settings <- read_properties(settings_file)

# Accessing values
scenario_name             <- settings$scenario_name
# Navteq_line_layer         <- settings$Navteq_line_layer
# Navteq_node_layer         <- settings$Navteq_node_layer
# TSM_centroid_layer        <- settings$TSM_centroid_layer
# TSM_centroid_con_layer    <- settings$TSM_centroid_con_layer 
# RPM_centroid_layer        <- settings$RPM_centroid_layer
# RPM_centroid_con_layer    <- settings$RPM_centroid_con_layer 

Geomaster_line_layer      <- settings$Geomaster_line_layer
Geomaster_node_layer      <- settings$Geomaster_node_layer
Geomaster_centroid_layer  <- settings$Geomaster_centroid_layer
Geomaster_cencon_layer    <- settings$Geomaster_cencon_layer 

max_internal_zones    <- settings$max_internal_zones
year                  <- as.integer(settings$year) - 2000
plugin_dir            <- settings$plugin_dir

model_resolution      <- settings$model_resolution  # Options = 1: TSM, 2: RPM, 3: MSR
msr_subarea           <- settings$msr_subarea       # Subarea polygon for MSR
out_msr_lookup_table  <- settings$msr_lookup        # This table is used in MSR process 
  
# Check lanes are now default to TRUE and no longer a user option
# check_lanes   <- settings$check_lanes
check_lanes   <- TRUE
write_interim <- settings$write_interim
keep_Counts   <- settings$keep_Counts
if(settings$keep_thruLanes %in% c('true', 'True', 'TRUE')) tunrOff_thruLanes <- FALSE

# Outputs
output_dir_main       <- settings$output_dir
out_tsm_link_file     <- settings$TSM_Link_File  # change to projectName
out_tsm_node_file     <- settings$TSM_Node_File  # change to projectName

# Log file (increases run time from 6 seconds to 10 mins)
debug   <- 0

# compile RCPP
# sourceCpp(paste0(plugin_dir, "/Rscripts/walk_the_graph_v5_RPM.cpp"))

# Capacities File
file_QLOS_capacities <- paste0(plugin_dir, "/Rscripts/QLOS_capacities.csv") 

# SCENARIO SETTINGS
scen_use_fields     <- c("CARTOLL", "FTYPE", "ATYPE", "LANE", "SPEED", "TwoWay")

DT_NavteqLinks <- st_read(Geomaster_line_layer, promote_to_multi = FALSE) 
DT_NavteqNodes <- st_read(Geomaster_node_layer, promote_to_multi = FALSE) %>% setDT()

DT_centroids <- st_read(Geomaster_centroid_layer) %>% setDT()
DT_cencon    <- st_read(Geomaster_cencon_layer) %>% setDT()

if (st_geometry_type(DT_NavteqLinks$geom[1]) == 'MULTILINESTRING') {
  DT_NavteqLinks$geom <- st_cast(DT_NavteqLinks$geom, "LINESTRING")
  setDT(DT_NavteqLinks)
}

#===============================================================================
# UPDATE for XFROM, YFROM XTO, YTO coordinates
# TODO fix this in the Navteq database
# DT_NavteqLinks[, CARTOLL_24 := Toll_Rate]
# st_write(DT_NavteqLinks, Navteq_line_layer, append = F)

update_coords_from_geom <- function(dt, geom_col = "geom", layer_type = c("line", "point"), overwrite = FALSE) {
  layer_type <- match.arg(layer_type)
  
  if (layer_type == "line") {
    # Extract coordinates from line geometry
    dt_coords  <- as.data.table(st_coordinates(dt[[geom_col]]))
    from_coords <- dt_coords[, .SD[1], by = "L1"]
    to_coords   <- dt_coords[, .SD[.N], by = "L1"]
    
    if (overwrite) {
      dt[, c("XFROM", "YFROM", "XTO", "YTO") := list(
        from_coords$X, from_coords$Y,
        to_coords$X,   to_coords$Y
      )]
    } else {
      dt[is.na(XFROM), c("XFROM", "YFROM", "XTO", "YTO") := list(
        from_coords$X, from_coords$Y,
        to_coords$X,   to_coords$Y
      )]
    }
    
  } else if (layer_type == "point") {
    # Extract coordinates from point geometry
    dt_coords <- as.data.table(st_coordinates(dt[[geom_col]]))
    
    if (overwrite) {
      dt[, c("X", "Y") := list(dt_coords$X, dt_coords$Y)]
    } else {
      dt[is.na(X), c("X", "Y") := list(dt_coords$X, dt_coords$Y)]
    }
  }
  
  dt[]
}

#===============================================================================

select_link_fields <- c(c("NAV_LINK_ID", "FROM_NODEID",  "TO_NODEID", "Dir",
                          "F_ZLEV", "T_ZLEV",  "XFROM", "YFROM", "XTO", "YTO"),
                    paste(c("FTYPE", "ATYPE", "TwoWay", "LANE", "SPEED", "CARTOLL"), year, sep ="_"), "geom", 
                    "TSMV5.COSITE", "TSMV5.AADT","TSMv5.COUNT_24", "TSMV5.TRKPCT", 
                    "TSMV5.ASCDIR", "TSMV5.ASCADT", "TSMV5.DSCDIR", "TSMV5.DSCADT")

select_node_fields <- c("NODE_ID",  "X",   "Y",  "geom")

# TODO Stop and report if there are missing fields

if(model_resolution %in% c("TSM", "MSR")){
  
  # DT_cc  <- st_read(Geomaster_cencon_layer, promote_to_multi = FALSE) %>% setDT()
  # DT_cc <- DT_cc[, c("TSM_NG", "NODE_ID", "geom")]
  # setnames(DT_cc, c("TSM_NG", "NODE_ID"), c("FROM_NODEID", "TO_NODEID"))
  
  # dt_centroids <- st_read(Geomaster_centroid_layer) %>% setDT()
  # dt_centroids <- dt_centroids[, c("TSM_NG", "geom")]
  # setnames(dt_centroids, "TSM_NG", "NODE_ID")
  
  DT_cc <- DT_cencon[type  == "TSM", ]
  dt_centroids <- DT_centroids[type == "TSM", ]
  
  DT_ALL <- DT_NavteqLinks[useinTSM == 1, ..select_link_fields]
  dt_allNodes <- DT_NavteqNodes[useinTSM == 1, ..select_node_fields]
  
  maxZones <- 11560
  
  # Load MSR RPM zones and network on top of TSM
  if(model_resolution == "MSR"){
    
    dt_msr_subarea_boundary <- st_read(msr_subarea) 
    
    dt_RPM_centroids <- DT_centroids[type  == "RPM", ]
    dt_RPM_centroids <- DT_cencon[type  == "RPM", ]
    
    # select RPM zones within the subarea polygon
    RPM_zones_within_subarea <- st_as_sf(dt_RPM_centroids)[dt_msr_subarea_boundary, ]
   
    # Add RPM level links for subarea zones
    tsm_suabrea_zones <- unique(RPM_zones_within_subarea$TSM_NG)
    DT_addon_MSR <- DT_NavteqLinks[useinRPM == 1 & useinTSM == 0 & 
                     (from_tsm_ng %in% tsm_suabrea_zones |  to_tsm_ng %in% tsm_suabrea_zones), ..select_link_fields]
    
    dt_Nodes_addon_MSR <- DT_NavteqNodes[useinRPM == 1 & useinTSM == 0 & 
                                           rpm_tsm_ng %in% tsm_suabrea_zones, ..select_node_fields]
    
    # Replace TSM Centroid connectors with RPM Centroid Connectors for these zones
    setDT(RPM_zones_within_subarea)
    RPM_zones_within_subarea[, MSR_ID := maxZones + .I]
    fwrite(RPM_zones_within_subarea[, c("MSR_ID", "TSM_NG", "TAZ_REG.v6",  "County")], out_msr_lookup_table)  # This is used in disaggregation later on
    
    # Update Centroid adn centroid connetor zone numbering to new lookup
    DT_RPM_cc <- merge(DT_RPM_cc, RPM_zones_within_subarea[, c("N", "MSR_ID")], by = "N")

    # DT_RPM_cc[, length(unique(N))] == nrow(RPM_zones_within_subarea) # check if all centroid connectors are subset
    DT_RPM_cc <- DT_RPM_cc[, c("MSR_ID", "NODE_ID", "geom")]
    setnames(DT_RPM_cc, c("MSR_ID", "NODE_ID"), c("FROM_NODEID", "TO_NODEID"))
    
    # Remove TSM Centroid connectors & Add RPM Centroid Connectors
    DT_cc <- DT_cc[!(FROM_NODEID %in% tsm_suabrea_zones), ]
    DT_cc <- rbindlist(list(DT_cc, DT_RPM_cc))
    
    # Add additional detail (RPM related raodway network)
    DT_ALL <- rbindlist(list(DT_ALL, DT_addon_MSR))
    
    # all MSR nodes together
    RPM_zones_within_subarea <- RPM_zones_within_subarea[, c("MSR_ID", "geom")]
    setnames(RPM_zones_within_subarea, "MSR_ID", "NODE_ID")
    dt_centroids <- rbindlist(list(dt_centroids, RPM_zones_within_subarea), use.names = T)
    
    dt_allNodes <- rbindlist(list(dt_allNodes, dt_Nodes_addon_MSR[, ..select_node_fields]))
    maxZones <- max(dt_centroids$NODE_ID)
  }  
  
} 


if(model_resolution == "RPM"){
  
  # dt_centroids <- st_read(RPM_centroid_layer, promote_to_multi = FALSE) %>% setDT()
  # DT_cc  <- st_read(RPM_centroid_con_layer) %>% setDT()
  # 
  # dt_centroids <- dt_centroids[, c("N", "geom")]
  # setnames(dt_centroids, "N", "NODE_ID")
  # 
  # DT_cc <- DT_cc[, c("N", "NODE_ID", "geom")]
  # setnames(DT_cc, c("N", "NODE_ID"), c("FROM_NODEID", "TO_NODEID"))
  
  dt_RPM_centroids <- DT_centroids[type  == "RPM", ]
  dt_RPM_centroids <- DT_cencon[type  == "RPM", ]
  
  DT_ALL <- DT_NavteqLinks[useinRPM == 1, ..select_link_fields]
  dt_allNodes <- DT_NavteqNodes[useinRPM == 1, ..select_node_fields]

  maxZones <- 30060
}  

# Append fields
DT_cc[, c("NAV_LINK_ID", paste(c("FTYPE", "ATYPE", "TwoWay", "LANE", "SPEED", "CARTOLL"), year, sep ="_")) := 
        list(.I, 51, 1, "B", 1, 25, 0.0)]

DT_cc[, c("F_ZLEV", "T_ZLEV") := list(0, 0)]

# Add XFROM,  YFROM, XTO, YTO fields
DT_cc <- update_coords_from_geom(DT_cc, layer_type = "line", overwrite = TRUE)

DT_ALL <- rbindlist(list(DT_cc, DT_ALL), use.names = T, fill = T)
dt_allNodes <- rbindlist(list(dt_allNodes, dt_centroids), use.names = T, fill = T)

dt_allNodes <- update_coords_from_geom(dt_allNodes, layer_type = "point", overwrite = TRUE)

setnames(dt_allNodes, "NODE_ID", "N")
setnames(DT_ALL, c("FROM_NODEID",  "TO_NODEID"), c("A", "B"))

# Check for column "project" to see if it is standard or project
# TODO make it a function argument (wrapper.R <type = project|standard>)
# if(colnames(DT_ALL)[colnames(DT_ALL) == "Project"] == "Project"){ 
if( "Project" %in% colnames(DT_ALL)){
    type <- "project"
  } else {
    type <- "standard"
  }

if(type == "project"){

  project_scenarios <- DT_ALL[!is.na(Project), unique(Project)]
  for(s in project_scenarios){

    DT_geo <- DT_ALL[is.na(Project) | Project == s, ]
      # run the link considation
    scenario <- paste0("Project_", s)
      # Check if the scenario folder exists, if not create it
    output_dir <- paste(output_dir_main,"/", scenario, sep = "")
    dir.create(file.path(output_dir), showWarnings = FALSE)

    out_tsm_link_file <- paste0(output_dir,"/TSM_Link.GPKG")
    out_tsm_node_file <- paste0(output_dir,"/TSM_Node.GPKG")
    source(paste0(plugin_dir, "/Rscripts/Walk_the_graph.R"))

  }
} else{
   DT_geo <- DT_ALL              # redundant
   output_dir <- output_dir_main # redundant
   # run the link consolidation

  source(paste0(plugin_dir, "/Rscripts/Walk_the_graph.R"))
}
   




