library(data.table)
library(sf)
library(tidyverse)

# Read Arguments
args            <- commandArgs(trailingOnly = TRUE)
print(args)

################################################################################
# Trip Table Columns
# Input -> SW_TT:: O, D, STARTTIME
# Output -> SW_Volume :: A, B, START
# Output -> SW_ODME:: O, D, STARTTIME
# Output -> subarea_TT :: ORG, DES, START
# 
# input -> subarea_TT:: ORG, DES, START
# Output -> Ssubarea_Volume :: A, B, START
################################################################################

# Define header aliases: elementName -> possible alternatives

header_aliases <- list(
  ORG   = c("O", "ORG", "ORIGIN", "FROM"),
  DES   = c("D", "DEST", "DESTINATION", "TO"),
  START = c("STARTTIME", "START", "PERIOD", "START_TIME", "DEPARTURE")
)


# Normalize headers: rename any alias to its elementName 
normalize_headers <- function(df, aliases) {
  current_names <- toupper(names(df))  # compare case-insensitively

  for (elementName in names(aliases)) {
    alts <- toupper(aliases[[elementName]])
    match_idx <- which(current_names %in% alts)
    
    if (length(match_idx) > 0) {
      names(df)[match_idx] <- elementName  # rename to elementName
    }
  }
  
  return(df)
}

################################################################################
base_tt <- args[1]
odme_tt <- args[2]
odme_factors <- args[3]

# base_tt <- "C:/TSM_NextGen_v5/Base/TSM_NG_2023/ELTOD_tt_HourClock_23.csv"
# odme_tt <- "C:/TSM_NextGen_v5/Base/TSM_NG_2023/SR91_MP0x-94_May2026/ODME_Trips_9.csv"
# odme_factors <- "C:/TSM_NextGen_v5/Base/TSM_NG_2023/SR91_MP0x-94_May2026/ODME_9_final/ODME_Trips_9_Factors.csv"

dt_tt_base <- fread(base_tt)
dt_tt_odme <- fread(odme_tt)

# Normalize the headers
dt_tt_base <- normalize_headers(dt_tt_base, header_aliases)
dt_tt_odme <- normalize_headers(dt_tt_odme, header_aliases)

dt_tt_base <- melt(dt_tt_base, id.vars = c("ORG", "DES", "START"))
dt_tt_odme <- melt(dt_tt_odme, id.vars = c("ORG", "DES", "START"))

dt_tt_compare <- merge(dt_tt_base, dt_tt_odme, 
                       by = c("ORG", "DES", "START", "variable"), 
                       suffixes = c(".base", ".odme"), all = T)

dt_tt_compare[!is.na(value.odme), delta := value.odme - value.base]

dt_tt_corr_factors <- dt_tt_compare[!is.na(delta) & delta != 0, c("ORG", "DES", "START", "variable", "delta")]

fwrite(dt_tt_corr_factors, odme_factors)

################################################################################

