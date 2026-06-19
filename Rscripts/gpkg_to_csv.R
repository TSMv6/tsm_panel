library(sf)
library(data.table)
library(tidyverse)

options(scipen = 999)

# Read Arguments
args            <- commandArgs(trailingOnly = TRUE)
print(args)

GPKG_file     <- args[1]
CSV_file      <- args[2]
is_subarea    <- args[3]

dt_sf <- st_read(GPKG_file) %>% setDT()
if(is_subarea %in% c("True", "true", "T", "TRUE")){
   dt_sf <- dt_sf[, c("A", "B") := NULL]
   setnames(dt_sf, c("Sub_A", "Sub_B"), c("A", "B"))
}

dt_sf[, geom := NULL]
fwrite(dt_sf, CSV_file)


