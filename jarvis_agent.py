"""
JARVIS Local Agent Bridge
Script ligero que corre en segundo plano en Windows.
Escucha las órdenes del Cerebro en la nube (Render) para:
- Apagar la PC principal (Windows)
- Apagar la Mac vía SSH (osascript)
- Controlar Spotify (PausarSpotify / ReproducirSpotify)
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
POLL_INTERVAL = 1.5  # Consulta cada 1.5 segundos

# Configuración de Dispositivos Locales
MAC_IP = os.getenv("MAC_SSH_DESTINO", "Jhulian@192.168.1.255")

def ejecutar_comando_local(comando: str):
    """Ejecuta un comando en Windows."""
    try:
        print(f"[AGENTE] Ejecutando local: {comando}")
        subprocess.run(comando, shell=True, check=True)
    except Exception as e:
        print(f"[!] Error ejecutando comando local: {e}")

def ejecutar_ssh_mac(comando: str):
    """Ejecuta un comando remoto en la Mac vía SSH."""
    try:
        print(f"[AGENTE] Ejecutando SSH en Mac ({MAC_IP}): {comando}")
        resultado = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", MAC_IP, comando],
            capture_output=True, text=True, timeout=10
        )
        if resultado.returncode != 0:
            print(f"[!] Error SSH Mac: {resultado.stderr}")
        else:
            print("[+] Comando ejecutado con éxito en Mac.")
    except Exception as e:
        print(f"[!] Excepción SSH Mac: {e}")

def procesar_comando(cmd: dict):
    accion = cmd.get("action", "")
    target = cmd.get("target", "windows")
    print(f"\n[JARVIS ACCIÓN RECIBIDA] Acción: {accion} | Objetivo: {target}")

    # 1. Control de Música (Spotify)
    if accion == "SPOTIFY_PAUSE":
        print("[Música] Pausando Spotify...")
        ejecutar_comando_local('schtasks /Run /TN "PausarSpotify"')

    elif accion == "SPOTIFY_PLAY":
        print("[Música] Reanudando Spotify...")
        ejecutar_comando_local('schtasks /Run /TN "ReproducirSpotify"')

    # 2. Apagado de Computadoras
    elif accion == "SHUTDOWN":
        if target in ["mac", "both"]:
            print("[Hardware] Enviando orden de apagado a la Mac vía SSH...")
            # En macOS, AppleScript apaga el sistema limpiamente sin pedir contraseña de root
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
    print("[+] Escuchando órdenes de apagado y Spotify...")
    print("[+] Presiona Ctrl + C para detener.\n")

    while True:
        try:
            resp = requests.get(poll_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                comandos = data.get("commands", [])
                for cmd in comandos:
                    procesar_comando(cmd)
            elif resp.status_code == 401:
                print("[!] Error 401: API Key incorrecta. Revisa tu archivo .env")
                time.sleep(5)

        except requests.exceptions.RequestException:
            # Reintentar silenciosamente si hay un micro-corte de red
            pass
        except Exception as e:
            print(f"[!] Error inesperado: {e}")

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    iniciar_agente()
