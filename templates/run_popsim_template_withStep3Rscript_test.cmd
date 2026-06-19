@echo off
echo Setting up "PopulationSIM" environment...
CD /D "{tsm_loc}\PopSim\Florida"

CALL "{tsm_loc}\PopSim\Florida\Setup\software\Anaconda2\Scripts\activate.bat" popsim

SET PATH=%PATH%;C:\Windows\System32\WindowsPowerShell\v1.0
SET LOGFILE={tsm_loc}\PopSim\Florida\Setup\Logs\popsim_full_run.log

echo Running merge script...
powershell -Command "python '{tsm_loc}\PopSim\Florida\Scripts\mergeHHandGQ.py' '{tsm_loc}\PopSim\Florida\Data\parameters.csv' 2>&1 | Tee-Object -FilePath '%LOGFILE%' -Append"

timeout /t 1
echo Running Rscript to append incremental to reference data...
powershell -Command " & '{tsm_loc}\PopSim\Florida\Setup\software\R\R-4.3.2\bin\Rscript.exe' '{plugin_dir}\Rscripts\RunPopSim_append_incremental.R' '{scenario_dir}\settings_PopSim.txt'"

