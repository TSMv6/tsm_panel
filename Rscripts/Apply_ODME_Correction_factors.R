
library(data.table)
library(sf)
library(tidyverse)

# Read Arguments
args            <- commandArgs(trailingOnly = TRUE)
print(args)
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
# Apply ODME correction factors
fut_tt <- args[1]
odme_tt <- args[2]
odme_factors <- args[3]
replacement_zones <- args[4]

# replacement_zones <- "C:/TSM_NextGen_v5/Base/TSMv5_55/Revised/TSMv5_55/Subarea/Subarea_new_Nodes.csv"

# fut_tt <- "C:/Projects/Wekiwa_2025/subarea/Subarea/Wekiwa_Subarea_TripTable.csv"
# odme_tt <- "C:/Projects/Wekiwa_2025/subarea/Subarea/ODME_Future_TT.csv"
# odme_factors <- "C:/Projects/Wekiwa_2025/subarea/Subarea/ODME_Correction_factors.csv"


dt_tt_fut <- fread(fut_tt)

# Normalize the headers
dt_tt_fut <- normalize_headers(dt_tt_fut, header_aliases)

fnames <- colnames(dt_tt_fut)
dt_tt_fut <- melt(dt_tt_fut, id.vars = c("ORG", "DES", "START"))

dt_tt_corr_factors <- fread(odme_factors)

# Update correction factors with future year node replacements
if(file.exists(replacement_zones)){
  dt_replace <- fread(replacement_zones)
  dt_replace <- dt_replace[!is.na(base_N), ]

  if(nrow(dt_replace) > 0){
    for(r in seq_len(nrow(dt_replace))){
      dt_tt_corr_factors[ORG == dt_replace[r, base_N], ORG := dt_replace[r, N]]
      dt_tt_corr_factors[DES == dt_replace[r, base_N], DES := dt_replace[r, N]]
    }
  }
}

dt_tt_fut30 <- merge(dt_tt_fut, dt_tt_corr_factors, by = c("ORG", "DES", "START", "variable"), all = T)
dt_tt_fut30[is.na(delta), delta:= 0]
dt_tt_fut30[is.na(value), value:= 0]
dt_tt_fut30[, value2 := value + delta]
dt_tt_fut30[value2 < 0, value2 := 0]
dt_tt_fut30 <- dt_tt_fut30[, lapply(.SD, sum), by = c("START", "ORG", "DES", "variable"), .SDcols = "value2"]

dt_tt_fut30 <- dcast(dt_tt_fut30,  START + ORG + DES  ~ variable, value.var = "value2", fill = 0)
setcolorder(dt_tt_fut30, fnames)
dt_tt_fut30[, HOUR := tstrsplit(START, ":", fixed=TRUE)[[1]]]
setorderv(dt_tt_fut30, c("HOUR", "ORG", "DES"))
dt_tt_fut30[, HOUR := NULL]
fwrite(dt_tt_fut30, odme_tt)

################################################################################