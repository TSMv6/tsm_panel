@echo off
CD /D "{tsm_loc}\PopSim\Florida"

CALL "{tsm_loc}\PopSim\Florida\Setup\software\Anaconda2\Scripts\activate.bat" popsim

SET PATH=%PATH%;C:\Windows\System32\WindowsPowerShell\v1.0
SET LOGFILE={tsm_loc}\PopSim\Florida\Setup\Logs\popsim_full_run.log

echo Running HH simulation...
powershell -Command "python '{tsm_loc}\PopSim\Florida\Setup\run_populationsim.py' --config '{tsm_loc}\PopSim\Florida\Setup\configs\HH' --o '{tsm_loc}\PopSim\Florida\Setup\output\HH' 2>&1 | Tee-Object -FilePath '%LOGFILE%' -Append"

echo Running GQ simulation...
powershell -Command "python '{tsm_loc}\PopSim\Florida\Setup\run_populationsim.py' --config '{tsm_loc}\PopSim\Florida\Setup\configs\GQ' --o '{tsm_loc}\PopSim\Florida\Setup\output\GQ' 2>&1 | Tee-Object -FilePath '%LOGFILE%' -Append"

echo Running merge script...
powershell -Command "python '{tsm_loc}\PopSim\Florida\Scripts\mergeHHandGQ.py' '{tsm_loc}\PopSim\Florida\Data\parameters.csv' 2>&1 | Tee-Object -FilePath '%LOGFILE%' -Append"


