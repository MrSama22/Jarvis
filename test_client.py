import asyncio
import os
import requests
import edge_tts

# URL del servidor desplegado en Render
RENDER_URL = "https://jarvis-fbff.onrender.com/jarvis"
API_KEY = "jarvis_secret_key_12345"

async def create_sample_audio(text: str, filename: str) -> str:
    """Crea un archivo de audio simulando la voz del usuario."""
    communicate = edge_tts.Communicate(text, "es-MX-JorgeNeural")
    await communicate.save(filename)
    return filename

def test_jarvis_endpoint():
    print(f"--- Probando endpoint en la NUBE: {RENDER_URL} ---")
    sample_file = "test_cloud_question.mp3"

    try:
        # 1. Crear audio de prueba
        print("[1/3] Generando audio de prueba: 'Jarvis, confirma que estás activo en la nube y listo para el celular.'")
        asyncio.run(create_sample_audio(
            "Jarvis, confirma que estás activo en la nube y listo para el celular.",
            sample_file
        ))

        # 2. Enviar petición HTTP POST
        print(f"[2/3] Enviando audio a {RENDER_URL}...")
        headers = {
            "X-API-Key": API_KEY
        }
        with open(sample_file, "rb") as f:
            files = {"audio": (sample_file, f, "audio/mp3")}
            response = requests.post(RENDER_URL, headers=headers, files=files, timeout=45)

        if response.status_code == 200:
            output_file = "test_cloud_response.mp3"
            with open(output_file, "wb") as f:
                f.write(response.content)

            print("[3/3] ¡ÉXITO TOTAL! Respuesta recibida de la nube.")
            print(f" -> Transcripción: {response.headers.get('X-Jarvis-Transcript')}")
            print(f" -> Respuesta de Jarvis: {response.headers.get('X-Jarvis-Reply')}")
            print(f" -> Audio guardado en: {output_file} ({len(response.content)} bytes)")
        else:
            print(f"[!] Error del servidor ({response.status_code}): {response.text}")

    finally:
        if os.path.exists(sample_file):
            os.remove(sample_file)

if __name__ == "__main__":
    test_jarvis_endpoint()
