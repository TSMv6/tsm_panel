TITLE                                   ELToD 5.14 TSM NextGen
                                        
PROJECT_DIRECTORY                       
DEFAULT_FILE_FORMAT                     COMMA_DELIMITED
PAGE_LENGTH                             99999
MODEL_START_TIME                        1.0
MODEL_END_TIME                          25.0
MODEL_TIME_INCREMENT                    60 minutes
                                        
LINK_FILE                               {scenario_loc}\validation\Link2.csv
LINK_FORMAT                             COMMA_DELIMITED
EXPRESS_FACILITY_TYPES                  196,197,198
                                                                            
NODE_FILE                               {scenario_loc}\validation\Node.csv
NODE_FORMAT                             COMMA_DELIMITED
EXPRESS_ENTRY_TYPES                     90
EXPRESS_EXIT_TYPES                      91
GENERAL_JOIN_TYPES                      94
ZONE_NODE_TYPE                          99
                                        
TRIP_FILE                               {scenario_loc}\ELTOD_tt_HourClock.csv
TRIP_FORMAT                             Comma_Delimited
MINIMUM_TRIP_SPLIT                      0.01
STORE_TRIPS_IN_MEMORY                   FALSE

LINK_TOD_CLOSER_FILE                    {config_loc}\Dummy_Link_TOD_Closer.csv
LINK_TOD_CLOSER_FORMAT                  COMMA_DELIMITED
                                        
TURN_PROHIBITION_FILE                   {config_loc}\Dummy_Turn_Prohibit.csv
TURN_PROHIBITION_FORMAT                 COMMA_DELIMITED                                        
TOLL_FILE                               {config_loc}\Dummy_DMN_Toll_Policies.csv
TOLL_FORMAT                             COMMA_DELIMITED
                                        
TOD_TOLL_FILE                           {config_loc}\Dummy_TOD_Toll.csv
TOD_TOLL_FORMAT                         COMMA_DELIMITED
                                        
TOLL_CONSTANT_FILE                      {config_loc}\Dummy_DMN_Toll_Constants_HourClock.csv
TOLL_CONSTANT_FORMAT                    COMMA_DELIMITED

NUMBER_OF_THREADS                       100
MAXIMUM_ITERATIONS                      10
TRAVEL_TIME_CONVERGENCE                 0.01
EXPRESS_TOLL_CONVERGENCE                0.02
IMPEDANCE_CONVERGENCE                   0.01
MINIMUM_SPEED                           5
                                        
DISTANCE_VALUE                          0.90
TIME_VALUE                              1.631, 1.347, 1.347, 1.347, 1.631, 1.631, 1.631, 1.347, 1.347, 1.347, 1.631, 1.631, 1.631, 1, 1, 1, 1.631  
COST_VALUE                              3.16, 3.50, 3.50, 7.34, 3.16, 3.16, 8.01, 3.50, 14.03, 7.34, 3.16, 16.99, 8.01, 2.88, 7.5, 5.42, 3.16               
MODE_COST_FACTORS                       1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.5, 1.0, 1.25, 1.0
MODE_PCE_FACTORS                        1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 3.5, 1.0, 2.5, 1.0
                                        
TOLL_POLICY_CODES                       1,2,3,4,5
MINIMUM_TOLL                            0.5,0.5,0.5,0.5,0.25
MAXIMUM_TOLL                            10.50,10.50,3.00,1.00,5.00
MAXIMUM_VC_RATIO                        5.0,5.0,5.0,5.0,5.0
VC_RATIO_OFFSET                         0.1,0.15,0.0,0.0,0.1
TOLL_EXPONENT                           6.5,4.5,4.5,8.5,8.5
LOS_B_VC_RATIO                          0,0,0,0,0.3
LOS_C_VC_RATIO                          0,0,0,0,0.6
MAXIMUM_TOLL_CHANGE                     10,10,10,10,10
                                        
MODEL_TIME_FACTOR                       -1.631, -1.347, -1.347, -1.347, -1.631, -1.631, -1.631, -1.347, -1.347, -1.347, -1.631, -1.631, -1.631, -1, -1, -1 
MODEL_TOLL_FACTOR                       -3.43,-3.8,-3.8,-7.57,-3.43,-3.43,-8.26,-3.8,-14.29,-7.57,-3.43,-17.3,-8.26,-1.04,-2.71,-1.96 
MODEL_RELIABILITY_RATIO                 3
MODEL_RELIABILITY_TIME                  0.2
MODEL_RELIABILITY_DISTANCE              0.1
MODEL_PERCEIVED_TIME                    13.67
MODEL_PERCEIVED_MID_VC                  0.693
MODEL_PERCEIVED_MAX_VC                  1.65
MODEL_EXPRESS_WEIGHT                    1.28
MODEL_SCALE_LENGTH                      7.2
MODEL_SCALE_ALPHA                       0
MODEL_MAX_CIRCUITY                      1.5
                                        
PATH_PERCEIVED_TIME                     13.67
PATH_PERCEIVED_MID_VC                   0.693
PATH_PERCEIVED_MAX_VC                   1.2
                                        
DELAY_TIME_FACTOR                       0.25
DELAY_VC_FACTOR                         1.8
DELAY_MIN_VC_RATIO                      0.7
DELAY_MAX_VC_RATIO                      2
                                        
SMOOTH_GROUP_SIZE                       0
PERCENT_MOVED_FORWARD                   20
PERCENT_MOVED_BACKWARD                  20
SMOOTHING_ITERATIONS                    6
CIRCULAR_GROUP_FLAG                     TRUE
DAILY_WRAP_FLAG                         TRUE
ITERATION_VOLUME_FLAG                   FALSE
LAST_VOLUME_FLAG                        FALSE
DUMP_PARAMETER_DATA                     TRUE
IMPEDANCE_SORT_METHOD                   TRUE

SIGNAL_DELAY_PERIOD                     6:00..19:00
SIGNAL_DELAY_VOLUME                     0.0003992129
SIGNAL_DELAY_POSTSPEED                 -0.0036944165
SIGNAL_DELAY_NSIGNALS                   0.0086731976
SIGNAL_DELAY_DISTANCE1                 -0.2616419053
SIGNAL_DELAY_DISTANCE2                 -0.1328176615 
SIGNAL_DELAY_CONSTANT                   0.4283720806
                                        
NEW_VOLUME_FILE                         {scenario_loc}\TSMv5_Volume.csv
NEW_VOLUME_FORMAT                       COMMA_DELIMITED

NEW_MODEL_DATA_FILE                     {tsm_loc}\Logs\Choice_Model_Log_File.csv
NEW_MODEL_DATA_FORMAT                   COMMA_DELIMITED
SELECT_MODEL_PERIODS                    8:00
SELECT_MODEL_ITERATIONS                 LAST
SELECT_MODEL_MODES                      SDT_res_hig, SDT_res_med, SDT_res_low
SELECT_MODEL_NODES                      30352
                                        
NEW_PERIOD_GAP_FILE                     {tsm_loc}\Logs\period_gap_file.csv
NEW_PERIOD_GAP_FORMAT                   COMMA_DELIMITED
NEW_TIME_GAP_FILE                       {tsm_loc}\Logs\time_gap_file.csv
NEW_TOLL_GAP_FILE                       {tsm_loc}\Logs\toll_gap_file.csv
NEW_IMPEDANCE_GAP_FILE                  {tsm_loc}\Logs\impedance_gap_file.csv
NEW_EXPRESS_TOLL_FILE                   {tsm_loc}\Logs\express_toll_file.csv
NEW_EXPRESS_TOLL_FORMAT                 COMMA_DELIMITED
ELTOD_REPORT_1                          TIME_GAP_REPORT
ELTOD_REPORT_2                          TOLL_GAP_REPORT
ELTOD_REPORT_3                          IMPEDANCE_GAP_REPORT
ELTOD_REPORT_4                          CHOICE_DISTRIBUTION

SELECT_LINKS                            93444-93479 
NEW_SELECT_LINK_FILE                    {tsm_loc}\Select_Links_SET1.csv
NEW_SELECT_LINK_FORMAT                  COMMA_DELIMITED
NEW_SELECT_TRIP_FILE                    {tsm_loc}\Select_Links_TripTable_SET1.csv
NEW_SELECT_TRIP_FORMAT                  COMMA_DELIMITED

SELECT_LINKS_1                          93444-93479 
NEW_SELECT_LINK_FILE_1                  {tsm_loc}\Select_Links_SET.csv
NEW_SELECT_LINK_FORMAT_1                COMMA_DELIMITED
SELECT_LINKS_2                          93479-93444
NEW_SELECT_LINK_FILE_2                  {tsm_loc}\Select_Links_SET_2.csv
NEW_SELECT_LINK_FORMAT_2                COMMA_DELIMITED

NEW_SELECT_TRIP_FILE_1                  {tsm_loc}\Select_Trip_SET.csv
NEW_SELECT_TRIP_FORMAT_1                COMMA_DELIMITED
NEW_SELECT_TRIP_FILE_2                  {tsm_loc}\Select_Trip_SET_2.csv
NEW_SELECT_TRIP_FORMAT_2                COMMA_DELIMITED

SUBAREA_LINK_MAP_FILE                   {tsm_loc}\Corridor_Boundary_LinkList.csv
NEW_SUBAREA_FILE                        {tsm_loc}\I4_Corridor_TripTable.csv
NEW_SUBAREA_FORMAT                      COMMA_DELIMITED
MAXIMUM_SUBAREA_ZONE                    293

SELECT_TURN_NODE_FILE                   {tsm_loc}\Turn_NodeList.csv
SELECT_TURN_PERIODS                     1:00..25:00
SELECT_TURN_INCREMENT                   60 minutes
SAVE_ALL_VOLUME_RECORDS                 TRUE
NEW_TURN_MOVEMENT_FILE                  {tsm_loc}\Turning_Movements.csv
NEW_TURN_MOVEMENT_FORMAT                COMMA_DELIMITED

COUNT_FILE                            C:\Projects\some_subarea_project\Input\ODME_Counts.csv
COUNT_FORMAT                          COMMA_DELIMITED
MAXIMUM_PERCENT_CHANGE                0
TRIP_UPDATE_RATE                      5
STORE_TRIPS_IN_MEMORY                 TRUE
NEW_TRIP_FILE                         C:\Projects\some_subarea_project\Input\ODME_TT.csv
NEW_TRIP_FORMAT                       COMMA_DELIMITED
DUMP_COUNT_STATUS                     FALSE
