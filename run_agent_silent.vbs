Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c venv\Scripts\python.exe jarvis_agent.py", 0, False
