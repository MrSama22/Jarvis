"""
JARVIS Local Agent Bridge
Script que corre en segundo plano en Windows.
Escucha las órdenes del Cerebro en la nube (Render) para:
- Apagar Windows y/o Mac
- Pausar y reanudar la música SIMULTÁNEAMENTE en ambas PCs (Windows y Mac)
"""
import os
import sys
import time
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv()

# Configuración del Backend en la Nube
SERVER_URL = os.getenv("RENDER_URL", "https://jarvis-fbff.onrender.com")
API_KEY = os.getenv("JARVIS_API_KEY", "jarvis_secret_key_12345")
POLL_INTERVAL = 1.5

# Configuración de Dispositivos Locales
MAC_IP = os.getenv("MAC_SSH_DESTINO", "Jhulian@192.168.1.255")

def ejecutar_comando_local(comando: str):
    """Ejecuta un comando en Windows."""
    try:
        subprocess.run(comando, shell=True, check=True)
    except Exception as e:
        print(f"[!] Error ejecutando comando local: {e}")

def ejecutar_ssh_mac(comando: str):
    """Ejecuta un comando remoto en la Mac vía SSH con timeout de 3 segundos para no bloquear si está apagada."""
    try:
        resultado = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3", MAC_IP, comando],
            capture_output=True, text=True, timeout=5
        )
        if resultado.returncode != 0:
            print(f"[!] SSH Mac: {resultado.stderr.strip()[:100]}")
        else:
            print("[+] Comando ejecutado en Mac.")
    except Exception as e:
        # Si la Mac está apagada, no interrumpe el flujo de Windows
        print(f"[!] Mac no disponible o apagada: {e}")

def pausar_musica_ambas_pcs():
    """Pausa la música en Windows Y en Mac simultáneamente."""
    print("[Música] Pausando Spotify en PC Principal (Windows)...")
    ejecutar_comando_local('schtasks /Run /TN "PausarSpotify"')

    print("[Música] Pausando Spotify en Mac (AppleScript)...")
    ejecutar_ssh_mac("osascript -e 'if application \"Spotify\" is running then tell application \"Spotify\" to pause'")

def reanudar_musica_ambas_pcs():
    """Reanuda la música en Windows Y en Mac simultáneamente."""
    print("[Música] Reanudando Spotify en PC Principal (Windows)...")
    ejecutar_comando_local('schtasks /Run /TN "ReproducirSpotify"')

    print("[Música] Reanudando Spotify en Mac (AppleScript)...")
    ejecutar_ssh_mac("osascript -e 'if application \"Spotify\" is running then tell application \"Spotify\" to play'")

def procesar_comando(cmd: dict):
    accion = cmd.get("action", "")
    target = cmd.get("target", "both")
    print(f"\n[JARVIS ACCIÓN] Acción: {accion} | Objetivo: {target}")

    # 1. Control Dual de Música (Windows + Mac)
    if accion == "SPOTIFY_PAUSE":
        pausar_musica_ambas_pcs()

    elif accion == "SPOTIFY_PLAY":
        reanudar_musica_ambas_pcs()

    # 2. Apagado de Computadoras
    elif accion == "SHUTDOWN":
        if target in ["mac", "both"]:
            print("[Hardware] Apagando Mac vía SSH...")
            ejecutar_ssh_mac("osascript -e 'tell application \"System Events\" to shut down'")

        if target in ["windows", "both"]:
            print("[Hardware] Apagando PC Principal (Windows)...")
            ejecutar_comando_local("shutdown /s /t 2 /c \"JARVIS: Apagando sistema por orden de Jhulian\"")

def iniciar_agente():
    poll_url = f"{SERVER_URL}/agent/poll"
    headers = {"X-API-Key": API_KEY}

    print("==================================================")
    print("   JARVIS LOCAL AGENT BRIDGE (Windows & Mac)      ")
    print("==================================================")
    print(f"[+] Conectado a: {SERVER_URL}")
    print("[+] Control de audio DUAL activo (Windows + Mac)")
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
