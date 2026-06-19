@echo off
echo Setting up "PopulationSIM" environment...
CD /D "C:\TSM_NextGen_v5\PopSim\Florida"

CALL "C:\TSM_NextGen_v5\PopSim\Florida\Setup\software\Anaconda2\Scripts\activate.bat" popsim

SET PATH=%PATH%;C:\Windows\System32\WindowsPowerShell\v1.0
SET LOGFILE=C:\TSM_NextGen_v5\PopSim\Florida\Setup\Logs\popsim_full_run.log

echo Running HH simulation...
powershell -Command "python 'C:\TSM_NextGen_v5\PopSim\Florida\Setup\run_populationsim.py' --config 'C:\TSM_NextGen_v5\PopSim\Florida\Setup\configs\HH' --o 'C:\TSM_NextGen_v5\PopSim\Florida\Setup\output\HH' 2>&1 | Tee-Object -FilePath '%LOGFILE%' -Append"

echo Running GQ simulation...
powershell -Command "python 'C:\TSM_NextGen_v5\PopSim\Florida\Setup\run_populationsim.py' --config 'C:\TSM_NextGen_v5\PopSim\Florida\Setup\configs\GQ' --o 'C:\TSM_NextGen_v5\PopSim\Florida\Setup\output\GQ' 2>&1 | Tee-Object -FilePath '%LOGFILE%' -Append"

echo Running merge script...
powershell -Command "python 'C:\TSM_NextGen_v5\PopSim\Florida\Scripts\mergeHHandGQ.py' 'C:\TSM_NextGen_v5\PopSim\Florida\Data\parameters.csv' 2>&1 | Tee-Object -FilePath '%LOGFILE%' -Append"

echo Running Rscript to append incremental to reference data...
powershell -Command " & "C:\TSM_NextGen_v5\PopSim\Florida\Setup\software\R\R-4.1.1\bin\Rscript.exe" C:\Users\kn815vs\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\tsm_panel\Rscripts\RunPopSim_append_incremental.R C:/TSM_NextGen_v5/Base/TSMv5_default\settings_PopSim.txt"
