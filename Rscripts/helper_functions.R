#-------------------------------------------------------------------------------
# Function to maintain trip table header consistency
#-------------------------------------------------------------------------------
# Define header aliases: canonical name -> possible alternatives
header_aliases <- list(
  ORG   = c("O", "ORIGIN", "FROM"),
  DES   = c("D", "DEST", "DESTINATION", "TO"),
  START = c("STARTTIME", "START_TIME", "DEPARTURE")
)

# Read the CSV
df <- read.csv("your_file.csv", stringsAsFactors = FALSE)

# Normalize headers: rename any alias to its canonical name
normalize_headers <- function(df, aliases) {
  current_names <- toupper(names(df))  # compare case-insensitively
  
  for (canonical in names(aliases)) {
    alts <- toupper(aliases[[canonical]])
    match_idx <- which(current_names %in% alts)
    
    if (length(match_idx) > 0) {
      names(df)[match_idx] <- canonical  # rename to canonical
    }
  }
  return(df)
}

df <- normalize_headers(df, header_aliases)

#-------------------------------------------------------------------------------



