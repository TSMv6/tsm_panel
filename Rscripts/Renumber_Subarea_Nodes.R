
#----------------------------------------------------------------------------------------------
library(tidyverse)
library(data.table) 
library(sf)

options(scipen = 999)

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
#----------------------------------------------------------

replace_NA = function(DT) {
  for (j in names(DT))
    set(DT,which(is.na(DT[[j]])),j,0)
}

#----------------------------------------------------------


# settings_file <-   "C:/Projects/temp_geoMaster_coding/r_script_subarea_settings.txt"
settings_file <- args[1]
print(settings_file)
settings <- read_properties(settings_file)

check_readCW <- settings$check_readCW
check_saveCW <- settings$check_saveCW
readCW_file  <- settings$readCW_file
saveCW_file  <- settings$saveCW_file

tsm_link_file  <- settings$link_layer
tsm_node_file  <- settings$node_layer
subarea_link_file  <- settings$output_linkfile
subarea_node_file  <- settings$output_nodefile

dt_tsmlinks <- st_read(tsm_link_file) %>% setDT()
dt_sublinks <- st_read(subarea_link_file) %>% setDT()

# Subarea: Compute number of links by A Node and B Node
sublinks_by_A <- dt_sublinks[ , .N, by = "A"]
sublinks_by_B <- dt_sublinks[ , .N, by = "B"]

dt_subNodes <- merge(sublinks_by_A, sublinks_by_B, by.x = "A", by.y = "B", all = T)
setnames(dt_subNodes, c("N", "Sub_A", "Sub_B"))

# TSM: Compute number of links by A Node and B Node if they are in Subarea
tsmlinks_by_A <- dt_tsmlinks[A %in% dt_subNodes$N, .N, by = "A"]
tsmlinks_by_B <- dt_tsmlinks[B %in% dt_subNodes$N, .N, by = "B"]

dt_tsmNodes <- merge(tsmlinks_by_A, tsmlinks_by_B, by.x = "A", by.y = "B", all = T)
setnames(dt_tsmNodes, c("N", "TSM_A", "TSM_B"))

# Compare number of nodes with reduced link count
dt_compare <- merge(dt_tsmNodes, dt_subNodes, by = "N", all.x = T)
replace_NA(dt_compare)

dt_compare[, node_type := fcase(N <= 11560, 1,
                           # Sub_A == 0 | Sub_B == 0, 2,
                           (TSM_A != Sub_A) | (TSM_B != Sub_B), 2, 
                           default = 0)]

# Recode Subarea Node Numbers
if(check_readCW){
  dt_prev_lookup <- fread(readCW_file)
  dt_compare <- merge(dt_compare, dt_prev_lookup, by = "N", all.x = T)
  max_existing_zone <- dt_compare[node_type > 0 & !is.na(Sub_N), max(Sub_N)]
  # do we care if new externals or internal show up in a mixed order? 
  #Anyway at this point they are higher than previous external numbers 
  dt_compare[node_type > 0 & is.na(Sub_N), Sub_N := max_existing_zone + .I] 
} else{
  dt_compare[node_type == 1, Sub_N := .I]
  max_sub_iz <- dt_compare[!is.na(Sub_N), max(Sub_N)]
  dt_compare[node_type == 2, Sub_N := max_sub_iz + .I]
}

dt_lookup <- dt_compare[node_type > 0, c("N", "Sub_N")]

if(check_saveCW){
  fwrite(dt_lookup, saveCW_file)
}

# Update Subarea Links
checK_subfnames <- colnames(dt_sublinks) 
checK_subfnames <- checK_subfnames[!(checK_subfnames %in%  c("Sub_A", "Sub_B"))]
dt_sublinks <- dt_sublinks[, ..checK_subfnames]

dt_sublinks2 <- merge(dt_sublinks, dt_lookup, by.x = "A", by.y = "N", all.x = T)
setnames(dt_sublinks2, "Sub_N", "Sub_A")
dt_sublinks2[is.na(Sub_A), Sub_A := A]
dt_sublinks2 <- merge(dt_sublinks2, dt_lookup, by.x = "B", by.y = "N", all.x = T)
setnames(dt_sublinks2, "Sub_N", "Sub_B")
dt_sublinks2[is.na(Sub_B), Sub_B := B]

st_write(dt_sublinks2, subarea_link_file, append = F)

# Write a subarea boundary list for trip table extraction 
dt_linklist <- dt_sublinks2[, c("A", "B", "Sub_A", "Sub_B")]
setnames(dt_linklist, c("OLD_A", "OLD_B", "NEW_A", "NEW_B"))
fwrite(dt_linklist, gsub( "_Link.GPKG", "_Boundary_LinkList.csv", subarea_link_file))

dt_sublinks2[, c("A", "B", "geom") := NULL]
setnames(dt_sublinks2, c("Sub_A", "Sub_B"), c("A", "B"))

fnames <- checK_subfnames[!(checK_subfnames %in% "geom")]
fwrite(dt_sublinks2[, ..fnames], gsub(".GPKG", ".csv", subarea_link_file))

# Collect Subarea Nodes from TSM
dt_tsmnodes <- st_read(tsm_node_file) %>% setDT()
dt_subNodes <- merge(dt_compare[, c("N", "Sub_N", "node_type")], dt_tsmnodes, by = "N", all.x = T)
dt_subNodes[!is.na(Sub_N), DTA_Type := 99]
dt_subNodes[is.na(Sub_N), Sub_N := N]

fnames <- c(colnames(dt_tsmnodes), "node_type")
dt_subNodes[, N := NULL]
setnames(dt_subNodes, "Sub_N", "N")
setcolorder(dt_subNodes, fnames)

st_write(dt_subNodes, subarea_node_file, append = F)
fwrite(dt_subNodes[, geom := NULL], gsub(".GPKG", ".csv", subarea_node_file))


