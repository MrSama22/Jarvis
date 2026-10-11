Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "c:\Users\Jhulian\Downloads\JARVIS"
WshShell.Run """c:\Users\Jhulian\Downloads\JARVIS\venv\Scripts\python.exe"" ""c:\Users\Jhulian\Downloads\JARVIS\jarvis_agent.py""", 0, False
