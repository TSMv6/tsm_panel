import os, subprocess

cmd_file = r"C:\TSM_NextGen_v5\PopSim\Florida\run_popsim_all2.cmd"

# Start from scratch but include SYSTEM-level essentials and PATH
clean_env = {
    "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
    "COMSPEC": os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
    "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
    "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
    "PATH": os.environ.get("PATH")  
}

# Start new CMD window and run your batch file
result2 = subprocess.Popen(f'start "" cmd.exe /C "{cmd_file}"', shell=True, env=clean_env)