library(sf)
library(data.table)
library(tidyverse)


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
# link_gpkg     <- "C:/TSM_NextGen_v5/Base/TSMv5_default/TSM_Link.GPKG"
# node_gpkg     <- "C:/TSM_NextGen_v5/Base/TSMv5_default/TSM_Node.GPKG"
# link_csv      <- "C:/TSM_NextGen_v5/Base/TSMv5_default/TSM_Link.csv"
# node_csv      <-  "C:/TSM_NextGen_v5/Base/TSMv5_default/TSM_Node.csv"

link_gpkg     <- args[1]
node_gpkg     <- args[2]
link_csv      <- args[3]
node_csv      <- args[4]

options(scipen = 999) # Don't use scientific notation

sf_link <- st_read(link_gpkg) %>% setDT()
in_fieldNames <- c("A", "B", "FACTYPE", "DIST", "SPEED", "TOLL")
out_fieldNames <- c("from",	"to", "ftype",	"distance",	"speed",	"toll")
setnames(sf_link, in_fieldNames, out_fieldNames)
fwrite(sf_link[, ..out_fieldNames], link_csv)


sf_node <- st_read(node_gpkg) %>% setDT()
sf_node[DTA_Type == 99, zone := "true"]
sf_node[, signal := NA]

out_fieldNames <- c("N",	"zone",	"signal")
fwrite(sf_node[, ..out_fieldNames], node_csv)

