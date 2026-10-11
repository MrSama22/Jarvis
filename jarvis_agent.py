"""
JARVIS Universal Local Agent (Windows & macOS)
Este mismo script corre tanto en Windows como en macOS.
Detecta automáticamente el sistema operativo y se comunica de forma independiente con Render.

Si la PC Principal (Windows) está apagada, la Mac responderá directamente.
Si la Mac está apagada, Windows responderá directamente.
Si ambas están encendidas, ambas actuarán coordinadas.
"""
import os
import sys
import time
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv()

# Detectar Sistema Operativo
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
AGENT_ID = "mac" if IS_MAC else "windows"

# Configuración del Backend en la Nube
SERVER_URL = os.getenv("RENDER_URL", "https://jarvis-fbff.onrender.com")
API_KEY = os.getenv("JARVIS_API_KEY", "jarvis_secret_key_12345")
POLL_INTERVAL = 0.8

def ejecutar_comando_local(comando: str):
    try:
        subprocess.run(comando, shell=True, check=True)
    except Exception as e:
        print(f"[!] Error ejecutando comando: {e}")

def toggle_audio_windows():
    """Envía la pulsación de tecla de Mute/Play instantáneamente en 0ms sin lag."""
    try:
        import ctypes
        VK_VOLUME_MUTE = 0xAD
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_KEYUP, 0)
    except Exception as e:
        print(f"[!] Error con ctypes: {e}")
        ejecutar_comando_local('schtasks /Run /TN "PausarSpotify"')

def ejecutar_applescript(script: str):
    """Ejecuta un AppleScript directamente en macOS."""
    try:
        subprocess.run(["osascript", "-e", script], check=True)
    except Exception as e:
        print(f"[!] Error AppleScript en Mac: {e}")

def pausar_musica():
    """Pausa la música en el sistema operativo actual de forma instantánea."""
    if IS_WINDOWS:
        print("[Música] Pausando en Windows (instantáneo)...")
        toggle_audio_windows()

    elif IS_MAC:
        print("[Música] Pausando música directamente en Mac (Spotify y Music)...")
        ejecutar_applescript('if application "Spotify" is running then tell application "Spotify" to pause')
        ejecutar_applescript('if application "Music" is running then tell application "Music" to pause')

def reanudar_musica():
    """Reanuda la música en el sistema operativo actual de forma instantánea."""
    if IS_WINDOWS:
        print("[Música] Reanudando en Windows (instantáneo)...")
        toggle_audio_windows()

    elif IS_MAC:
        print("[Música] Reanudando música directamente en Mac (Spotify y Music)...")
        ejecutar_applescript('if application "Spotify" is running then tell application "Spotify" to play')
        ejecutar_applescript('if application "Music" is running then tell application "Music" to play')

def apagar_sistema(target: str):
    """Apaga el sistema correspondiente."""
    if IS_WINDOWS:
        if target in ["windows", "both"]:
            print("[Hardware] Apagando PC Principal (Windows)...")
            ejecutar_comando_local("shutdown /s /t 2 /c \"JARVIS: Apagando Windows\"")

    elif IS_MAC:
        if target in ["mac", "both"]:
            print("[Hardware] Apagando Mac directamente...")
            ejecutar_applescript('tell application "System Events" to shut down')

def procesar_comando(cmd: dict):
    accion = cmd.get("action", "")
    target = cmd.get("target", "both")
    print(f"\n[JARVIS ACCIÓN RECIBIDA] Acción: {accion} | Target: {target} | En: {AGENT_ID.upper()}")

    if accion == "SPOTIFY_PAUSE":
        pausar_musica()
    elif accion == "SPOTIFY_PLAY":
        reanudar_musica()
    elif accion == "SHUTDOWN":
        apagar_sistema(target)

def iniciar_agente():
    poll_url = f"{SERVER_URL}/agent/poll?agent_id={AGENT_ID}"
    headers = {"X-API-Key": API_KEY}

    print("==================================================")
    print(f"   JARVIS UNIVERSAL AGENT ({AGENT_ID.upper()})    ")
    print("==================================================")
    print(f"[+] Conectado a: {SERVER_URL}")
    print(f"[+] Plataforma activa: {AGENT_ID.upper()}")
    print("[+] Escuchando órdenes en segundo plano...\n")

    while True:
        try:
            resp = requests.get(poll_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                comandos = data.get("commands", [])
                for cmd in comandos:
                    procesar_comando(cmd)
            elif resp.status_code == 401:
                print("[!] Error 401: API Key incorrecta.")
                time.sleep(5)

        except requests.exceptions.RequestException:
            pass
        except Exception as e:
            print(f"[!] Error: {e}")

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    iniciar_agente()
