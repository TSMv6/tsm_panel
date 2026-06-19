library(sf)
library(data.table)
library(tidyverse)

options(scipen = 999)

# Read Arguments
args            <- commandArgs(trailingOnly = TRUE)
print(args)

line_layer <- args[1]
out_csv <- args[2]

dt_links <- st_read(line_layer) %>% setDT()

dt_links[, WEIGHT := fcase(FTYPE > 90, 10,
                           FTYPE %in% c(11,12), 8,
                           COUNT > 5000, 7,
                           default = 5)]

# dt_links[, STARTTIME := paste0(str_pad(START, 2, pad = "0", "left"), ":00")]
# dt_links[, ENDTIME := paste0(str_pad(END, 2, pad = "0", "left"), ":00")]

dt_links[, c("STARTTIME", "ENDTIME") := list("01:00", "25:00")]
       
dt_links <- dt_links[COUNT > 0, c("Sub_A", "Sub_B", "COUNT", "STARTTIME", "ENDTIME", "WEIGHT")]
setnames(dt_links, c("Sub_A", "Sub_B"), c("A", "B"))
fwrite(dt_links, out_csv)

