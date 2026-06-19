LINK_FILE                               {tsm_loc}\Base\TSMv5_2023\validation\Link2.csv
NODE_FILE                               {tsm_loc}\Base\TSMv5_2023\validation\Node.csv
TRIP_FILE                               {tsm_loc}\Base\TSMv5_2023\ELTOD_tt_HourClock.csv
NEW_VOLUME_FILE                         {tsm_loc}\Base\TSMv5_2023\validation\TSMv5_Volume.csv

# First set if it meets a preset condition (like python code say yes to write)
SELECT_LINKS                            93444-93479 
NEW_SELECT_LINK_FILE                    {tsm_loc}\Select_Links_SET1.csv
NEW_SELECT_LINK_FORMAT                  COMMA_DELIMITED
SELECT_LINKS_1                          93444-93479 
NEW_SELECT_LINK_FILE_1                  {tsm_loc}\Select_Links_SET.csv
NEW_SELECT_LINK_FORMAT_1                COMMA_DELIMITED
SELECT_LINKS_2                          93479-93444
NEW_SELECT_LINK_FILE_2                  {tsm_loc}\Select_Links_SET_2.csv
NEW_SELECT_LINK_FORMAT_2                COMMA_DELIMITED

# Second set if it meets a preset condition (like python code say yes to write)
SELECT_LINKS                            93444-93479 
NEW_SELECT_TRIP_FILE                    {tsm_loc}\Select_Links_TripTable_SET1.csv
NEW_SELECT_TRIP_FORMAT                  COMMA_DELIMITED

# Third set if it meets a preset condition (like python code say yes to write)
SUBAREA_LINK_MAP_FILE                   {tsm_loc}\Corridor_Boundary_LinkList.csv
NEW_SUBAREA_FILE                        {tsm_loc}\Corridor_TripTable.csv
NEW_SUBAREA_FORMAT                      COMMA_DELIMITED
MAXIMUM_SUBAREA_ZONE                    293

# Fourth set if it meets a preset condition (like python code say yes to write)
SELECT_TURN_NODE_FILE                   {tsm_loc}\Turn_NodeList.csv
SELECT_TURN_PERIODS                     1..25
SELECT_TURN_INCREMENT                   60 minutes
SAVE_ALL_VOLUME_RECORDS                 TRUE
NEW_TURN_MOVEMENT_FILE                  {tsm_loc}\Turning_Movements.csv
NEW_TURN_MOVEMENT_FORMAT                COMMA_DELIMITED

'SELECT_LINKS', 'NEW_SELECT_LINK_FILE', 'NEW_SELECT_LINK_FORMAT',                  
'SELECT_LINKS_1', 'NEW_SELECT_LINK_FILE_1', 'NEW_SELECT_LINK_FORMAT_1',                
'SELECT_LINKS_2', 'NEW_SELECT_LINK_FILE_2',  'NEW_SELECT_LINK_FORMAT_2',                
'SELECT_LINKS', 'NEW_SELECT_TRIP_FILE', 'NEW_SELECT_TRIP_FORMAT',
'NEW_SELECT_TRIP_FILE_1', 'NEW_SELECT_TRIP_FORMAT_1',
'NEW_SELECT_TRIP_FILE_2', 'NEW_SELECT_TRIP_FORMAT_1',
'SUBAREA_LINK_MAP_FILE', 'NEW_SUBAREA_FILE', 'NEW_SUBAREA_FORMAT', 'MAXIMUM_SUBAREA_ZONE',
'SELECT_TURN_NODE_FILE', 'SELECT_TURN_PERIODS', 'SELECT_TURN_INCREMENT', 'SAVE_ALL_VOLUME_RECORDS', 'NEW_TURN_MOVEMENT_FILE', 'NEW_TURN_MOVEMENT_FORMAT'
