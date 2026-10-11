import asyncio
import os
from pathlib import Path
import requests
import edge_tts

async def create_sample_audio(text: str, filename: str) -> str:
    """Crea un archivo de audio simulando la voz del usuario."""
    communicate = edge_tts.Communicate(text, "es-MX-JorgeNeural")
    await communicate.save(filename)
    return filename

def test_jarvis_endpoint():
    print("--- Probando pipeline de JARVIS ---")
    sample_file = "test_user_question.mp3"

    try:
        # 1. Crear audio de prueba
        print("[1/3] Generando audio de prueba: 'Jarvis, recuerda que mi color favorito es el azul metalizado.'")
        asyncio.run(create_sample_audio("Jarvis, recuerda que mi color favorito es el azul metalizado.", sample_file))

        # 2. Enviar petición HTTP POST
        print("[2/3] Enviando petición a http://localhost:8000/jarvis...")
        headers = {
            "X-API-Key": "jarvis_secret_key_12345"
        }
        with open(sample_file, "rb") as f:
            files = {"audio": (sample_file, f, "audio/mp3")}
            response = requests.post("http://localhost:8000/jarvis", headers=headers, files=files)

        if response.status_code == 200:
            output_file = "test_jarvis_response.mp3"
            with open(output_file, "wb") as f:
                f.write(response.content)

            print("[3/3] ¡Éxito rotundo! Respuesta recibida.")
            print(f" -> Transcripción detectada: {response.headers.get('X-Jarvis-Transcript')}")
            print(f" -> Respuesta de Jarvis: {response.headers.get('X-Jarvis-Reply')}")
            print(f" -> Audio guardado en: {output_file}")
        else:
            print(f"[!] Error del servidor ({response.status_code}): {response.text}")

    finally:
        if os.path.exists(sample_file):
            os.remove(sample_file)

if __name__ == "__main__":
    test_jarvis_endpoint()
