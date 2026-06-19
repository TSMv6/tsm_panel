#=======================================================================================================
#  Main Program
#----------------------------------------------------------------------------------------------
keep_reverse_flex_lanes <- FALSE
recode_FTYPE            <- FALSE
overwrite_prj_speed     <- FALSE

#-------------------------------------------------------------------------------
# SCENARIO SETTINGS
# Output file locations

# dir.create(file.path(paste0(output_dir,"/"), scenario), showWarnings = T)
output_link                       <- paste0(output_dir,"/Link.csv")
output_node                       <- paste0(output_dir,"/Node.csv")
out_eltod_shp                     <- out_tsm_link_file
out_eltod_node_shp                <- out_tsm_node_file

# out_review_nodes                  <- paste0(output_dir,"/review_dangling_nodes.gpkg")
M2O_lookup_file                   <- paste0(output_dir,"/Many_to_One_lookup.csv")

#  Other Output files as required
if(write_interim){
  consoildate_links_ShpFile       <- paste0(output_dir,"/Consolidated_links.GPKG")
  consoildate_links_Node_ShpFile  <- paste0(output_dir,"/Consolidated_nodes.GPKG")
}

if(keep_Counts){
  counts_AB_file                  <- paste0(output_dir,"/Counts_by_Consolidated_AB.csv")
}

if(keep_reverse_flex_lanes){
  reverseflex_AB_file             <- paste0(output_dir,"/reverse_flex_lanes_by_Consolidated_AB.csv")
}

if(debug == 1){
  debug_outFile                   <- paste0(output_dir,"/graphWalk.log") 
}

#----------------------------------------------------------------------------------------------
start_time <- Sys.time()

# Print scenario fields
scen_fields     <- paste(scen_use_fields, year, sep = "_")
scen_fields 

# setnames(DT_cc, "geom", "geometry")
setnames(DT_geo, "geom", "geometry", skip_absent = TRUE)

#-------------------------------------------------------------------------------
setnames(DT_geo, scen_fields , 
                 c("TOLL", "FACTYPE", "AREATYPE", "NLANES", "POSTSPEED", "TwoWay"))

if(check_lanes){
  DT_geo <- DT_geo[NLANES > 0 & !is.na(NLANES) & !is.null(NLANES), ]
  
  # Hot fix, do it in GeoMaster
   DT_geo[POSTSPEED == 0 & NLANES > 0, POSTSPEED := 25]
}


if(tunrOff_thruLanes){
  # Make sure removing ThruLanes capacity is not negative (user coding error)
  DT_geo[!is.na(add_ThruLanesCap) & abs(add_ThruLanesCap) < NLANES , NLANES := NLANES + add_ThruLanesCap ]
}

#-------------------------------------------------------------------------------

# Update ATYPE to few types (UGB for ATYPE) 
# DT_geo[, AREATYPE := fcase(UGB == 0, 2, default = 1)] 

# DT_cc[ , AREATYPE := fcase(AREATYPE > 49, 2, default = 1)] # doesn't matter, just use one number

# Update FTYPE to few types based on capacities / functional class
# Capacity > 2000, FTYPES c(10:19, 90:99) 
# Capacity > 1000, FTYPES c(21, 22, 31, 35)
# Capacity >  700, FTYPES c(23:25,32:34,36, 41:45, 61,71:75)  
# Capacity <  700, FTYPES c(37:39, 46:49,62:69, 72, 75)
# CENTRIODS c(50:59)

# if(recode_FTYPE){
#   DT_geo[ ,FACTYPE := fcase(FACTYPE %in%  c(10:19, 79, 90:99) , 1,
#                             FACTYPE %in% c(21, 22, 31, 35) , 2,
#                             FACTYPE %in% c(23:25,32:34,36, 41:45, 61,71, 73,75), 3,
#                             FACTYPE %in% c(37:39, 46:49,62:69, 72,74, 76:78), 4,  
#                             FACTYPE %in% c(50:59), 5,
#                             default =  6)]
# }

#-------------------------------------------------------------------------------
DT <- copy(DT_geo)  # Another redundancy

########################################## ERROR ###############################################
DT <- DT[, shp_length := st_length(geometry) ] # default to meter units
DT <- DT[, DIST := as.numeric(shp_length * 0.000621371) ] # meters to miles
DT <- DT[, shp_length := NULL,]

DT_master <- copy(DT)  # Another redundancy

DT[is.na(TOLL), TOLL := 0]
DT[is.na(T_ZLEV), T_ZLEV := 0]
DT[is.na(F_ZLEV), F_ZLEV := 0]

#-------------------------------------------------------------------------------
# Flip geometry if coded in reverse
dt_flip <- DT[TwoWay == "T", ]
dt_flip$geometry <- st_reverse(dt_flip$geometry)
dt_flip[, TwoWay := "F"]
setnames(dt_flip, c("A", "B", "XTO",  "YTO", "XFROM", "YFROM", "F_ZLEV", "T_ZLEV"),
                  c("B", "A", "XFROM", "YFROM", "XTO",  "YTO", "T_ZLEV", "F_ZLEV"))

dt_flip[ , Dir := fcase(Dir == "WBSB", "EBNB", 
                         Dir == "EBNB", "WBSB")]

# Add the reverse direction for two-way links and centroid connectors
DT_rev <- DT[TwoWay == "B", ]
DT_rev$geometry <- st_reverse(DT_rev$geometry)
setnames(DT_rev, c("A", "B", "XTO",  "YTO", "XFROM", "YFROM", "F_ZLEV", "T_ZLEV"),
         c("B", "A", "XFROM", "YFROM", "XTO",  "YTO", "T_ZLEV", "F_ZLEV"))

DT_rev[ , Dir := fcase(Dir == "WBSB", "EBNB", 
                       Dir == "EBNB", "WBSB")]

DT <- rbindlist(list(DT[TwoWay != "T"], dt_flip, DT_rev), use.names = TRUE)

#----------------------------------------------------------------------------------------------
# TODO Prune the network
# TODO Move this to walk the graph logic
# See # -----------------------------
# TSM: Prune dead-ends and other dangling  links 
# -----------------------------
# sourceCpp("CurveMatching/prune_dangling_links_one_at_a_time.cpp")
# 
# # Uni-directional is enough
# dt_TSM_edges <- dt_TSM_CC[, c("TSM_NG", "NODE_ID", "geom")]
# setnames(dt_TSM_edges, c("TSM_NG", "NODE_ID"), c("FROM_NODEID", "TO_NODEID"))
# dt_TSM_edges[, c("NAV_LINK_ID", "DISTANCE", "Nav_SPEED", "Rec_FNAME") := 
#                list(c(1:.N), 1, 1, "Centroid_Connector")]
# dt_TSM_edges$geom <- st_cast(dt_TSM_edges$geom, "MULTILINESTRING")
# 
# dt_TSM_edges_reverse <- copy(dt_TSM_edges)
# dt_TSM_edges_reverse$geom <- st_reverse(dt_TSM_edges_reverse$geom)
# setnames(dt_TSM_edges_reverse, c("FROM_NODEID", "TO_NODEID"), c("TO_NODEID","FROM_NODEID"))
# dt_TSM_edges <- rbindlist(list(dt_TSM_edges, dt_TSM_edges_reverse), use.names = T)
# 
# 
# edges <- dt_sf[flag_forTSM== 1, c("NAV_LINK_ID", "FROM_NODEID", "TO_NODEID", "DISTANCE", "Nav_SPEED", "Rec_FNAME", "geom")]
# 
# edges_TSM <- rbindlist(list(edges, dt_TSM_edges), use.names = T)
# 
# setnames(edges_TSM, c("link_id", "from_Node", "to_Node", "length", "speed", "fname", "geom"))
# edges_TSM[is.na(fname), fname := "unspecified"]
# 
# 
# links_dt <- as.data.table(st_drop_geometry(edges_TSM))
# 
# flagged_dt <- as.data.table(
#   prune_dangling_links_cpp(
#     A = as.integer(links_dt$from_Node),
#     B = as.integer(links_dt$to_Node),
#     LINK_ID = as.integer(links_dt$link_id),
#     progress_every = 1000
#   )
# )
# 
# links_dt[, delete_dangling_stub := link_id %in% flagged_dt$flag_link_id]
# edges_TSM$delete_dangling_stub <- links_dt$delete_dangling_stub
# 
# st_write(
#   setDT(links_dt)[delete_dangling_stub == TRUE, ],
#   out_links_tsm_file,
#   layer = "links_flagged",
#   delete_layer = TRUE, 
#   append = F
# )
# 
# fwrite(flagged_dt[, .SD[1], by = "flag_link_id"], out_flag_tsm_links_csv_file)
#----------------------------------------------------------------------------------------------
DT[ TwoWay == "B" , NLANES := ceiling((NLANES/2)) ] 

DT[, DIRECTION := fcase(TwoWay == "B", 1, default = 0)]   
DT[, DIR_TRAVEL_Num := DIRECTION]
# Just Keep the fields of interest
# fields <- c("A", "B", "LINK_ID", "F_ZLEV", "T_ZLEV", "DIST", "FACTYPE", "TOLL", "AREATYPE", "NLANES", "POSTSPEED",
#             "COSITE", "Dir", "DIRECTION", "DIR_TRAVEL_Num", "rev_dir","geometry")
# DT <- DT[, ..fields]

setnames(DT, "NAV_LINK_ID", "LINK_ID")

compare_fields <- c("FACTYPE", "AREATYPE", "NLANES", "POSTSPEED", "DIRECTION")
# compare_fields <- c("FACTYPE", "AREATYPE", "NLANES", "POSTSPEED", "rev_dir")
# List of intersections & next_nodes by Anode
setDT(DT)[ , NumA := .N, by = "A"]
DT[ , bnodes := list(list(B)), by = "A"]

#----------------------------------------------------------------------------------------------
# Create Lookup Lists (data.table is faster than C++ here, since no passing)
# Create a A to NextNode lookup
dt_lookup <- copy(DT)
dim(dt_lookup)
dt_lookup <- dt_lookup[, c("A", "bnodes")]
dt_lookup <- unique(dt_lookup, by = "A")

# Debug:: Flag links with reverse topology
DT_flag <- copy(DT)
DT_flag <- merge(DT_flag, dt_lookup, by.x = "B", by.y = "A", all.x = TRUE)
DT_flag[ , flag := purrr::map_lgl(DT_flag$bnodes, is.null)]
print("Links with Topological errors")
DT_flag[flag == TRUE, c("A", "B", "LINK_ID")]

# Lookup Anodes for B (merge nodes)
dt_merge <- copy(DT)
dt_merge[ , anodes := list(list(A)), by = "B"]
dim(dt_merge)
dt_merge <- dt_merge[, c("B", "anodes")]
dt_merge <- unique(dt_merge, by = "B")

# Create Row_id for quick lookup in C++
setorderv(DT, c("A","B"))
DT[ ,row_id := .I]

# List row_ids by A (use in C++)
DT[ , index_A := list(list(row_id)), by = "A"]
A_lookup <- copy(DT)
dim(A_lookup)
A_lookup <- A_lookup[, c("A", "index_A")]
A_lookup <- unique(A_lookup, by = "A")
DT[ , index_A := NULL]

# List row_ids by B (use in C++)
setorderv(DT, c("A","B"))
DT[ , index_B := list(list(row_id)), by = "B"]
B_lookup <- copy(DT)
dim(B_lookup)
B_lookup <- B_lookup[, c("B", "index_B")]
B_lookup <- unique(B_lookup, by = "B")
B_lookup[is.na(index_B), index_B := 0]
DT[ , index_B := NULL]
DT[ , bnodes := NULL]

# CRITICAL Setting: make sure row_id is same as internal index 
# Makesure it is in the same order for C++ code
setorderv(DT, c("A","B"))

end_time <- Sys.time()
runTime_Cpp_dataStructures <- end_time - start_time


#==============================================================================================
# Main program: walks the networks, identifies how to merge and sequence of merge
start_time <- Sys.time()

# isVisited <- graphWalk(DT, dt_lookup, A_lookup, B_lookup, compare_fields) # _v1, _v3
if(debug == 1){
  sink(debug_outFile)
  isVisited <- graphWalk(DT, dt_lookup, dt_merge, A_lookup, B_lookup, compare_fields, maxZones, debug)
  sink()
} else{
  isVisited <- graphWalk(DT, dt_lookup, dt_merge, A_lookup, B_lookup, compare_fields, maxZones, debug)
}

# DEBUG C++ code
#
# if(debug == 1){
#   lst_Bto   <- createList(dt_lookup, "A" , "bnodes");
#   lst_Bfrom <- createList(dt_merge, "B" , "anodes");
#   index_A   <- createList(A_lookup, "A" , "index_A");
#   index_B   <- createList(B_lookup, "B" , "index_B");
#   Atz       <- createList(DT, "row_id", "T_ZLEV");
#   Bfz       <- createList(DT, "row_id", "F_ZLEV");
#   uni_bi    <- createList(DT, "row_id", "DIR_TRAVEL_Num");
#   AB_dist   <- createList(DT, "row_id", "FACTYPE");
# 
# #   # Case 1: No intersection, consolidate links
#   start_seg_Anode <- 46257 
#   current_Anode   <- 46257 
#   current_Bnode   <- 306716   # 126001
# #
#   debug <- 1
#   Get_next_Bnode(lst_Bfrom, lst_Bto,
#                  start_seg_Anode, current_Anode, current_Bnode,
#                  Atz, Bfz, index_A,  index_B, uni_bi, AB_dist, debug)
# # # 
#   curr_link_index <- find_AB_Index2(index_A, index_B, current_Anode, current_Bnode)
#   a_tz = Atz[curr_link_index][[1]]
#   curr_dir = uni_bi[curr_link_index][[1]]
#   ab_dist = AB_dist[curr_link_index][[1]]
# 
# #   # Find all from A's
#   prev_As = lst_Bfrom[current_Bnode][[1]]
#   prev_As_rmBnode = subset(prev_As, current_Anode)
#   prev_index = find_AB_Index2(index_A, index_B, prev_As_rmBnode, current_Bnode);
#   a_tz2 = Atz[prev_index][[1]]
#   other_dir = uni_bi[prev_index][[1]]
#   ba_dist = AB_dist[prev_index][[1]]
# 
#   next_Bs = lst_Bto[current_Bnode][[1]]
#   next_link_index <- find_AB_Index2(index_A, index_B, 76293, 76298)
# 
# 
#   DT[row_id == 123756, ]
# }

# Append columns
DT <- DT[, GeoMerge_ID := isVisited$ID1]
DT <- DT[, GeoMerge_Order := isVisited$ID2]
DT <- DT[, visited := isVisited$visited]

# review_disconnectedNodes <- isVisited$B_no_next
# print(review_disconnectedNodes)

# Merge segements
DT2 <- copy(DT)

# Change order (note cannot run C++ code without putting back (sort by row_id or A, B))
setorderv(DT2, c("GeoMerge_ID", "GeoMerge_Order"))

end_time <- Sys.time()
runTime_walkTheGraph <- end_time - start_time


#----------------------------------------------------------------------------------------------
# Function to merge all segments
# Merge multi-lineStrings
mergeGeomMLS <- function(geom_vec){
  x <-  st_sfc(st_multilinestring(list(do.call(rbind, lapply(geom_vec, function(x){x[[1]]})))))
  return(x)
}

mergeGeom_LS <- function(geom_vec){
  x <-  st_sfc(st_multilinestring(list(do.call(rbind, lapply(geom_vec, function(x){x})))))
  return(x)
}

merge_start_time <- Sys.time()

# Sort by id, and sequence of links in the segment
setorderv(DT2, c("GeoMerge_ID", "GeoMerge_Order"))

#  Merge geometry across all segments
merged_geometry <- DT2[ ,lapply(.SD, mergeGeom_LS), by = GeoMerge_ID, .SDcols=c("geometry")]

merge_end_time <- Sys.time()
runTime_mergeLineSegments <- merge_end_time - merge_start_time

#-------------------------------------------------------------------------------------------------
# Get First Segment (A) and Last Segment B nodes 
merge_AB_start_time <- Sys.time()
# DT2[ , Dir := "bringInLater"]
# Get first and last A, B and attributes
DT2 <- DT2[, last := .N, by = GeoMerge_ID]
first <- DT2[GeoMerge_Order == 0, ]
first <- first[ , c("B", "T_ZLEV", "geometry") := NULL]
last  <- DT2[GeoMerge_Order == (last - 1), c("B", "T_ZLEV", "GeoMerge_ID")]

# Merge firt Anode, last Bnode and geometry
first_last <- merge(first,last, by.x = "GeoMerge_ID", by.y = "GeoMerge_ID")
first_last_geom <-  merge(first_last, merged_geometry, by.x = "GeoMerge_ID", by.y = "GeoMerge_ID")

# Get A,B by GeoMerge_ID
# Write out consolidation lookup for review and also to get One-to-Many
M2O_lookup    <- DT2[, c("LINK_ID", "GeoMerge_ID", "GeoMerge_Order", "Dir")]
M2O_lookup_AB <- first_last[, c("A", "B", "GeoMerge_ID")]
M2O_lookup    <- merge(M2O_lookup, M2O_lookup_AB, by = "GeoMerge_ID", all.x = TRUE)  
setcolorder(M2O_lookup, c("LINK_ID", "A","B", "GeoMerge_ID", "GeoMerge_Order", "Dir"))
fwrite(M2O_lookup, M2O_lookup_file)

#-------------------------------------------------------------------------------------------------
# ADD NETWORK ATTRIBUTES

# 1. Get Signals from Nodes and append to LINKS (only to_nodes - BNODE)
# read all nodes
# dt_allNodes <- st_read(node_layer) %>% setDT()

# Extract Signals and append to Links TO_NODE (B)
# dt_SignalsTO <- merge(dt_allNodes[Signal == 1, c("N", "Signal")], 
#                       DT2[, c("B", "GeoMerge_ID")], 
#                       by.x = "N", by.y = "B", all.x = TRUE)
# 
# # Count number of signals per conslidated link (GeoMerge ID is the unique consolidted link identifier)
# dt_Signals   <- dt_SignalsTO[, list(NSignals = sum(Signal)), by = "GeoMerge_ID"]
# first_last_geom <- merge(first_last_geom,  dt_Signals, by = "GeoMerge_ID", all.x = TRUE)  
# rm(dt_SignalsTO)

# 2. Add Link TOLL
# Toll links can be maintained separately (do not consolidate) or consolidate but add total across all links
TOLL_by_ID <- DT2[, sum(TOLL), by = "GeoMerge_ID"]
setnames(TOLL_by_ID, "V1", "TOLL")
first_last_geom <- first_last_geom[, TOLL := NULL]
first_last_geom_TOLL <- merge(first_last_geom, TOLL_by_ID, by = "GeoMerge_ID", all.x = TRUE)

first_last_geom_TOLL[ , c("DIR_TRAVEL_Num", "NumA", "row_id", "GeoMerge_Order", "visited", "last") := NULL]


# 3. Add or Skip Counts
if(keep_Counts){
  count_fields <- c("NAV_LINK_ID", "TSMV5.COSITE", "TSMV5.AADT","TSMv5.COUNT_24", "TSMV5.TRKPCT", 
                    "TSMV5.ASCDIR", "TSMV5.ASCADT", "TSMV5.DSCDIR", "TSMV5.DSCADT")

  if(year == 24)  counts_ID <- DT_master[TSMv5.COUNT_24  > 0 & !is.na(TSMv5.COUNT_24), ..count_fields]
  # TTMS vs PTMS cosites
  # if(use_ttsm_over_ptms){
  #   dt_cositeType <- fread(ttms_vs_ptms_cosite)
  #   rm_cosites <- dt_cositeType[is.na(Keep), "LINK_ID"]
  #   counts_ID <- counts_ID[!(LINK_ID %in% rm_cosites$LINK_ID), ]
  # }

  counts_ID_AB <- merge(counts_ID, M2O_lookup, by.x = "NAV_LINK_ID", by.y = "LINK_ID", all.x = TRUE)
  # counts_ID_AB <- merge(counts_ID_AB, DT2[, c("GeoMerge_ID", "rev_dir")], by = "GeoMerge_ID", all.x = T)
  
  if(year == 23) {
    counts_ID_AB[, Count_23 := fcase(rev_dir == 0, DIR_COUNT_23, 
                                    rev_dir == 1, DIR_REV_COUNT_23)]
    
    counts_ID_AB[, Count_TRK_23 := fcase(rev_dir == 0, DIR_TRKCOUNT_23, 
                                    rev_dir == 1, DIR_REV_TRKCOUNT_23)]
    
    counts_ID_AB[Count_23 < 0, Count_23 := 0 ]
    counts_ID_AB[Count_TRK_23 < 0, Count_TRK_23 := 0 ]

    counts_ID_AB         <- counts_ID_AB[, c("GeoMerge_ID", "Count_23", "Count_TRK_23")]
    setnames(counts_ID_AB, c("Count_23","Count_TRK_23"), c("COUNT", "COUNT_TRK")) 
  }

# if(year == 24){
#     counts_ID_AB[TwoWay  == 1, COUNT_24 := round(COUNT_24/ 2, 0)]
#     counts_ID_AB[, Count_TRK_24 := round(COUNT_24 * TFCTR, -1)]
#     counts_ID_AB         <- counts_ID_AB[, c("GeoMerge_ID", "COUNT_24", "Count_TRK_24")]
#     setnames(counts_ID_AB, c("COUNT_24","Count_TRK_24"), c("COUNT", "COUNT_TRK")) 
# }
 
  counts_ID_AB   <- counts_ID_AB[order(-TSMV5.AADT), .SD[1], by = c("GeoMerge_ID")]
  fwrite(counts_ID_AB, counts_AB_file)

  first_last_geom_TOLL <- merge(first_last_geom_TOLL, counts_ID_AB, by = "GeoMerge_ID", all.x = TRUE)
  
}

# first_last_geom_TOLL[, c("REVERSE","FLEX") := list(NA, NA)]
if(keep_reverse_flex_lanes){
  reverse_ID   <- DT_master[REVERSE  == 1, LINK_ID]
  flex_ID   <- DT_master[FLEX  == 1, LINK_ID]
  
  first_last_geom_TOLL[LINK_ID %in% reverse_ID, REVERSE := 1]
  first_last_geom_TOLL[LINK_ID %in% flex_ID, FLEX := 1]
  
  rev_flex_out <-  rbindlist(list( data.table(LINK_ID = reverse_ID, type ="Reverse"),
                                   data.table(LINK_ID = flex_ID, type ="Flex")))
  fwrite(rev_flex_out, reverseflex_AB_file)
} 
  
# 4. Add Network Attributes from Master
# Net_Sel_Attr <- DT_master[, c("NAV_LINK_ID", "ST_NAME", "COUNTY", "DISTRICT")] # add attributes here
Net_Sel_Attr <- DT_NavteqLinks[useinTSM == 1 | useinRPM == 1, c("NAV_LINK_ID", "ST_NAME", 
                                                                "from_county", "to_county",
                                                                "from_model", "to_model")]

Net_Sel_Attr <- Net_Sel_Attr[, .SD[1], by = "NAV_LINK_ID"]  # remove duplicates
first_last_geom_TOLL_Attr <- merge(first_last_geom_TOLL, Net_Sel_Attr,
                                   by.x = "LINK_ID", by.y = "NAV_LINK_ID", all.x = T)

# 5. Compute distance
first_last_geom_TOLL_Attr <- first_last_geom_TOLL_Attr[, DISTANCE := as.numeric(st_length(geometry) * 0.000621371) ] # meters to miles 

# 6. Keep selected link attributes (Remove LINK_ID and GeoMerge_ID)
# first_last_geom_TOLL_Attr <- first_last_geom_TOLL_Attr[, c("LINK_ID", "GeoMerge_ID", "DIRECTION") := NULL]

# this code was added to correct an error reading in the column data, the second group removes "count"
# if (keep_Counts){
#   setcolorder(first_last_geom_TOLL_Attr, c("ST_NAME", "COUNTY", "DISTRICT", "A", "B", "F_ZLEV", "T_ZLEV", 
#                                            "FACTYPE",  "AREATYPE",  "NLANES", "POSTSPEED", "DISTANCE", "TOLL",         
#                                            "NSignals", "COSITE", "COUNT", "REVERSE","FLEX", "geometry"))
#   }else  {
#     setcolorder(first_last_geom_TOLL_Attr, c("ST_NAME", "COUNTY", "DISTRICT", "A", "B", "F_ZLEV", "T_ZLEV", 
#                                            "FACTYPE",  "AREATYPE",  "NLANES", "POSTSPEED", "DISTANCE", "TOLL",         
#                                            "NSignals", "COSITE", "REVERSE","FLEX", "geometry"))
#     }


#--------------------------------------------------------------------------------
# Convert to SF
sf_fl <- st_as_sf(first_last_geom_TOLL_Attr)

merge_AB_end_time <- Sys.time()
runTime_mergeLineSegments_AB <- merge_AB_end_time - merge_AB_start_time

# Write to shape file
write_start_time <- Sys.time()

# Set projection
st_crs(sf_fl) = 26917
if(write_interim){
  st_write(sf_fl, consoildate_links_ShpFile, append = FALSE)
}
#==============================================================================================
# export corresponding nodes for the shape file
dt <- setDT(sf_fl)
sf_fl_Anodes <- unique(dt$A)
sf_fl_Bnodes <- unique(dt$B)
sf_fl_nodes <- unique(c(sf_fl_Anodes, sf_fl_Bnodes))

# read all nodes
# dt_allNodes <- st_read(node_layer) %>% setDT()

# If there are two nodes with same N,then pick MPO nodes for MSR model
# dt_allNodes[, flag := .N, by = "N"]
# dt_allNodes <- dt_allNodes[flag  == 1 | (flag > 1 & type == "subzone"),]
# dt_allNodes <- dt_allNodes[, .SD[1], by = "N",]

# dt_reviewNodes <- dt_allNodes[ N %in% review_disconnectedNodes, ] 
# st_write(dt_reviewNodes, out_review_nodes, append = F)

dt_allNodes <- dt_allNodes[ N %in% sf_fl_nodes, ] 
# setnames(dt_allNodes, "geom", "geometry", skip_absent=TRUE)
# xy <- st_coordinates(dt_allNodes$geom)
# dt_allNodes <- dt_allNodes[, X := xy[1:nrow(xy), 1]]
# dt_allNodes <- dt_allNodes[, Y := xy[1:nrow(xy), 2]]

# Nodes to review


# write node shape file
sf_fl_Nodes <- st_as_sf(dt_allNodes)
st_crs(sf_fl_Nodes) = 26917
if(write_interim){
  st_write(sf_fl_Nodes, consoildate_links_Node_ShpFile, append = FALSE)
}

write_end_time <- Sys.time()
runTime_writeShp <- write_end_time - write_start_time

#==============================================================================================
# Create ELToD Network
write_start_time <- Sys.time()
source(paste0(plugin_dir,"/Rscripts/Create_ELToD_Network.R")) # capacity and other secondary attributes are added here
write_end_time <- Sys.time()
runTime_ELTOD_nets <- write_end_time - write_start_time
#==============================================================================================
# Report Runtime
runTime <- data.table (step = c("Read GPKG|Shapefiles and Create DataTables",    
                    "WalkTheGraph to Find Eligible Links to Consolidate",
                    "Merge Line Segments' Geometries",
                    "Process A-B Nodes, Append TOLL",
                    "Write GPKG|Shape outputs",
                    "Write ELToD Attributes"), 
            runtime = c(
                  runTime_Cpp_dataStructures,
                  runTime_walkTheGraph,
                  runTime_mergeLineSegments,
                  runTime_mergeLineSegments_AB,
                  runTime_writeShp,
                  runTime_ELTOD_nets))

runTime_total <- sum(runTime$runtime)
runTime <- rbindlist(list(runTime, list("Total", runTime_total)))
print(runTime)  

#--------------------------------------------------------------------------------------