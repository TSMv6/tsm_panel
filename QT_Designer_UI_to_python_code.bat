
rem install PyQt5 via pip
rem then run puuic5
pyuic5 ui/tsm_link_consolidator.ui -o tsm_link_consolidator.py

pyuic5 ui/tsm_subarea_extractor.ui -o tsm_subarea_extractor_ui.py
rem to convert icon to resource
pyrcc5 resources.qrc -o resources.py
rem python -m PyQt5.pyrcc_main resources.qrc -o resources.py

cd C:\Users\kn815vs\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\tsm_panel
pyuic5 tsm_main_panel.ui -o tsm_main_panel_ui.py
pyuic5 ui/tsm_subarea_extractor.ui -o tsm_subarea_extractor_ui.py
pyuic5 ui/Project_Settings.ui -o Project_Settings_ui.py
pyuic5 ui/General_Configuration.ui -o General_Configuration_ui.py
pyuic5 ui/PopulationSIM.ui -o PopulationSIM_ui.py
pyuic5 ui/TSM_Assignment.ui -o TSM_Assignment_ui.py
pyuic5 ui/SDT_Resident.ui -o SDT_resident_ui.py
pyuic5 ui/SDT_visitor.ui -o SDT_visitor_ui.py
pyuic5 ui/Skimmy.ui -o Skimmy_ui.py
pyuic5 ui/LDT_Res.ui -o LDT_Res_ui.py
pyuic5 ui/LDT_OS.ui -o LDT_OS_ui.py
pyuic5 ui/trip_list2table.ui -o trip_list2table_ui.py
pyuic5 tsm_panel_add_more2.ui -o tsm_panel_add_more_ui2.py
pyuic5 ui/Subarea_Assignment.ui -o Subarea_Assignment_ui.py
pyuic5 ui/summary_loadedNetwork.ui -o summary_loadedNetwork_ui.py

pyuic5 ui/configurationTable.ui -o configurationTable_ui.py

"C:\Program Files\R\R-4.3.2\bin\Rscript.exe" 
"C:\Users\kn815vs\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\tsm_netmanager_plugin\Walk_the_graph.R" 
C:\Projects\temp_geoMaster_coding\r_script_settings.txt