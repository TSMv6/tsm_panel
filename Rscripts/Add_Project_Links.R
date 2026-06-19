library(sf)
library(tidyverse)
library(data.table)

setwd("C:/Projects/TSM_GUI_Scenarios/GeoMaster")

gm_links <- "NextGen_v10_Geomaster_MonarchRanch.GPKG"
gm_nodes <- "NextGen_v10_Nodes_MonarchRanch.GPKG"
project_links <- "Project_I75_TPK_Connector.gpkg"

# Output Nodes
outfile_Nodes <- "NextGen_v10_Nodes_MonarchRanch_with_Project.GPKG"
outfile_Links <- "NextGen_v10_Geomaster_MonarchRanch_with_Project.GPKG"

# Interim files to Review
review_prj_nodes <- "review_prj_nodes.gpkg"
review_prj_links <- "review_prj_links.gpkg"

#-------------------------------------------------------------------------------
# Read all files
dt_prj <- st_read(project_links) %>% setDT()

# TODO : check if this geom or geometry 
setnames(dt_prj, "geometry", "geom")  
dt_prj$geom <- st_cast(dt_prj$geom, "LINESTRING")


dt_GM_links  <- st_read(gm_links) %>% setDT()
dt_GM_nodes  <- st_read(gm_nodes) %>% setDT()

# Get Max Link and Node ID
dt_GM_links[, LINK_ID := as.integer(LINK_ID)]
max_LID <- dt_GM_links[, max(LINK_ID)]
max_NID <- dt_GM_nodes[, max(N)]

# Code LINK_ID for Prj links
dt_prj[, LINK_ID := max_LID + .I]

#-------------------------------------------------------------------------------
# Get Nodes from Project Links
# Extract end points from dt_links (dt_recode)
to_pnts   <- st_line_sample(dt_prj$geom, sample = 1)
from_pnts   <- st_line_sample(dt_prj$geom, sample = 0)

# Get unique nodes
addon_nodes <- as.data.table(rbind(st_coordinates(to_pnts), st_coordinates(from_pnts)))
addon_nodes[, c("Xi", "Yi") := list(floor(100 * X), floor(100 * Y))]
addon_nodes[, flag := c(1:.N), by = c("Xi", "Yi")]
addon_nodes <- addon_nodes[flag == 1, ]
addon_nodes[, c("flag", "L1") := NULL]

# Check if already exist in GM-Node, if not create nodes 
addon_nodes <- merge(addon_nodes, dt_GM_nodes, by = c("Xi", "Yi"), all.x = TRUE)
addon_nodes <- addon_nodes[is.na(N), c("Xi", "Yi", "X.x",  "Y.x", "N")]
addon_nodes[, c("X", "Y", "N", "type") := list(X.x, Y.x, max_NID + .I, "PrjNodes")]

# TODO Add a check to create new nodes if only it exists
addon_nodes_sf = st_as_sf(addon_nodes, coords = c("X.x", "Y.x"), 
                          crs = 26917, agr = "constant") %>% setDT()

setnames(addon_nodes_sf, "geometry", "geom")

# Update GeoMaster Node 
dt_GM_nodes_updated <- rbindlist(list(setDT(addon_nodes_sf),dt_GM_nodes), use.names = TRUE, fill = TRUE)
st_write(st_as_sf(setDF(dt_GM_nodes_updated)), outfile_Nodes, append = FALSE)

#-------------------------------------------------------------------------------
# Update A-B Nodes based on GM-Nodes & Project Nodes
to_pnts   <- st_line_sample(dt_prj$geom, sample = 1)
from_pnts   <- st_line_sample(dt_prj$geom, sample = 0)
from_pnts   <- st_cast(from_pnts, "POINT")
x0 <- do.call(rbind, lapply(from_pnts, function(x){ x[[1]][1]}))
y0 <- do.call(rbind, lapply(from_pnts, function(x){ x[[2]][1]}))
to_pnts   <- st_cast(to_pnts, "POINT")
x1 <- do.call(rbind, lapply(to_pnts, function(x){ x[[1]][1]}))
y1 <- do.call(rbind, lapply(to_pnts, function(x){ x[[2]][1]}))

# Update the new links with v4 nodes
# dt_coords <- st_coordinates(dt_prj$geom)
# dt_coords <- as.data.table(dt_coords)
# from_coords <- dt_coords[, .SD[1], by = "L1"] 
# to_coords <- dt_coords[, .SD[.N], by = "L1"] 

# Code from and to x,y 
dt_prj[, c("XFROM","YFROM", "XTO","YTO")  := list(floor(100 * x0), floor(100 * y0),
                                                  floor(100 * x1), floor(100 * y1))]

# Code A-B Nodes
dt_prj <- merge(dt_prj, dt_GM_nodes_updated[, c("N", "Xi", "Yi")], by.x = c("XFROM","YFROM"), by.y = c("Xi", "Yi"), all.x = TRUE)
setnames(dt_prj, "N", "A")

dt_prj <- merge(dt_prj, dt_GM_nodes_updated[, c("N", "Xi", "Yi")], by.x = c("XTO","YTO"), by.y = c("Xi", "Yi"), all.x = TRUE)
setnames(dt_prj, "N", "B")


# Check if any nodes aren't coded properly
dt_prj[is.na(A)| is.na(B), ]

# write interim project files and node
st_write(st_as_sf(addon_nodes_sf), review_prj_nodes, append = F)
st_write(st_as_sf(dt_prj), review_prj_links, append = F)


# Append to GeoMaster but expand the LANES, SPEED, ...
dt_prj[is.na(TWOWAY), TWOWAY := 0]
setnames(dt_prj, "TWOWAY", "TwoWay")
dt_prj[, c("F_ZLEV", "T_ZLEV") := list(0,0)]

# 
# Clean up fields and keep the ones that are used
# field names
# setnames(dt_prj, c("FTYPE", "ATYPE", "SPEED", "LANES" ),
#                  c("FTYPE_23", "ATYPE_23", "SPEED_23", "LANE_23"))
# 
# fld_order2 <- c("LINK_ID", "A", "B", "XTO", "YTO", "XFROM", "YFROM","F_ZLEV", "T_ZLEV", 
#                 "ST_NAME",  "COUNTY", "DISTRICT", "geom",
#                 "FTYPE_23", "ATYPE_23", "SPEED_23", "LANE_23")
# 
# dt_2_clean <- dt_2[, ..fld_order2]

dt_prj[, ST_NAME := paste0("Project_", as.character(Project))]
dt_prj[FTYPE == 51, ST_NAME := 'Centroid Connector']


dt_prj[, c("FTYPE_24", "ATYPE_24", "SPEED_24", "LANE_24", "CARTOLL_24") := list(FTYPE, ATYPE, SPEED, LANES, CARTOLL)]
dt_prj[, c("FTYPE_25", "ATYPE_25", "SPEED_25", "LANE_25", "CARTOLL_25") := list(FTYPE, ATYPE, SPEED, LANES, CARTOLL)]
dt_prj[, c("FTYPE_30", "ATYPE_30", "SPEED_25", "LANE_30", "CARTOLL_30") := list(FTYPE, ATYPE, SPEED, LANES, CARTOLL)]
dt_prj[, c("FTYPE_25", "ATYPE_35", "SPEED_35", "LANE_35", "CARTOLL_35") := list(FTYPE, ATYPE, SPEED, LANES, CARTOLL)]
dt_prj[, c("FTYPE_50", "ATYPE_50", "SPEED_50", "LANE_50", "CARTOLL_50") := list(FTYPE, ATYPE, SPEED, LANES, CARTOLL)]

dt_prj <- dt_prj[, c("FTYPE", "ATYPE", "SPEED", "LANES", "CARTOLL") := NULL]


# dt_GM_links$geom <- st_cast(dt_GM_links$geom, "LINESTRING")
# st_write(st_as_sf(dt_GM_links), outfile_Links, append = FALSE)

dt_GM_links_updated <- rbindlist(list(dt_prj, dt_GM_links), use.names = TRUE, fill = TRUE)
st_write(st_as_sf(dt_GM_links_updated), outfile_Links, append = FALSE)

#-------------------------------------------------------------------------------





