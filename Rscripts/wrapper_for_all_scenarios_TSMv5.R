library(tidyverse)
library(data.table) 
library(foreign)
library(sf)
library(walkTheGraph)

library(Rcpp)
# sourceCpp("C:/Projects/rPackage/walk_the_graph_v6.cpp") # doesn't crash but also forgives coding errors

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

# Example usage
settings_file <-  args[1]
# settings_file <-   "C:/TSM_NextGen_v5/Base/TSMv5_default/tbn_gm_v13/fix_gm/settings.txt"

settings <- read_properties(settings_file)

# Accessing values
scenario_name         <- settings$scenario_name
line_layer            <- settings$line_layer
node_layer            <- settings$node_layer
max_internal_zones    <- settings$max_internal_zones
year                  <- as.integer(settings$year) - 2000
plugin_dir            <- settings$plugin_dir

# Check lanes are now default to TRUE and no longer a user option
# check_lanes   <- settings$check_lanes
check_lanes   <- TRUE
write_interim <- settings$write_interim
keep_Counts   <- settings$keep_Counts
tunrOff_thruLanes <- settings$keep_thruLanes

# Outputs
output_dir_main       <- settings$output_dir
out_tsm_link_file     <- settings$TSM_Link_File  # change to projectName
out_tsm_node_file     <- settings$TSM_Node_File  # change to projectName


# Log file (increases run time from 6 seconds to 10 mins)
debug   <- 0

# Capacities File
file_QLOS_capacities <- paste0(plugin_dir, "/Rscripts/QLOS_capacities.csv") 


# SCENARIO SETTINGS
scen_use_fields     <- c("CARTOLL", "FTYPE", "ATYPE", "LANE", "SPEED")

DT_ALL <- st_read(line_layer) %>% setDT()

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
    source(paste0(plugin_dir, "/Rscripts/Walk_the_graph_TSMv5.R"))

  }
} else{
   DT_geo <- DT_ALL
   output_dir <- output_dir_main
   # run the link considation

  source(paste0(plugin_dir, "/Rscripts/Walk_the_graph_TSMv5.R"))
}
   




