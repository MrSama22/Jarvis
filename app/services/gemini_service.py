import os
import json
import logging
from pathlib import Path
from typing import Tuple, Optional
import google.generativeai as genai

from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.services.chroma_service import memory_service

logger = logging.getLogger(__name__)

# Configuración inicial de Gemini API
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY no está configurada. Debes configurarla en el archivo .env.")

SYSTEM_INSTRUCTION = """
Eres JARVIS, el asistente de inteligencia artificial personal y leal de Jhulian.
Jhulian se comunica contigo mediante notas de voz desde su teléfono celular.

Directrices clave:
1. Responde de forma concisa, inteligente, servicial y fluida.
2. Tu respuesta será convertida directamente a voz (TTS). Evita listas largas, viñetas, asteriscos, código fuente largo o formatos que suenen extraños al ser hablados.
3. Sé respetuoso, dinámico y amigable con Jhulian.
4. Si hay información en el contexto histórico de memoria o en turnos previos, utilízala de forma natural para demostrar que recuerdas sus conversaciones y preferencias.

Formato de salida obligatorio:
Debes responder SIEMPRE en formato JSON válido con esta estructura:
{
  "transcript": "Transcripción fiel de lo que dijo Jhulian en el audio",
  "response": "Tu respuesta directa y conversacional para ser leída por voz"
}
"""

def detect_mime_type(file_path: Path) -> str:
    """Detecta el MIME type del archivo de audio para la API de Gemini."""
    ext = file_path.suffix.lower()
    mapping = {
        ".mp3": "audio/mp3",
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
        ".wav": "audio/wav",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".amr": "audio/amr",
        ".3gp": "audio/3gpp",
    }
    return mapping.get(ext, "audio/mp3")

class GeminiService:
    def __init__(self):
        self.model_name = GEMINI_MODEL

    def process_voice_message(self, audio_path: Path) -> Tuple[str, str]:
        """
        Envía el audio a Gemini 1.5 Flash junto con el contexto histórico de ChromaDB.
        Retorna: (transcripción_usuario, respuesta_jarvis)
        """
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY no configurada. Revisa tu archivo .env")

        mime_type = detect_mime_type(audio_path)
        logger.info(f"Procesando audio multimodal con Gemini: {audio_path.name} ({mime_type})")

        # 1. Recuperar contexto reciente de la conversación
        recent_history = memory_service.get_recent_history_context()

        # 2. Construir el prompt con la memoria inyectada
        prompt_parts = []

        context_prompt = (
            "--- CONTEXTO Y MEMORIA ---\n"
            f"Nombre del usuario: Jhulian\n"
        )
        if recent_history:
            context_prompt += f"\nTurnos recientes de la conversación:\n{recent_history}\n"

        prompt_parts.append(context_prompt)

        # 3. Adjuntar el archivo de audio como dato binario inline
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        audio_part = {
            "mime_type": mime_type,
            "data": audio_bytes
        }
        prompt_parts.append(audio_part)

        # 4. Llamada al modelo Gemini
        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=SYSTEM_INSTRUCTION
        )

        try:
            # Solicitar generación en JSON
            generation_config = genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.7
            )
            response = model.generate_content(prompt_parts, generation_config=generation_config)
            response_text = response.text.strip()
            logger.info(f"Respuesta bruta de Gemini: {response_text}")

            # 5. Parsear JSON
            data = json.loads(response_text)
            transcript = data.get("transcript", "Mensaje de voz").strip()
            reply = data.get("response", "Entendido, Jhulian.").strip()

        except Exception as e:
            logger.warning(f"Error parseando JSON de Gemini ({e}), usando fallback de texto...")
            # Fallback en caso de que no venga en formato JSON puro
            raw_text = getattr(response, "text", "He procesado tu mensaje.")
            transcript = "Audio de Jhulian"
            reply = raw_text

        # 6. Almacenar el intercambio en ChromaDB para enriquecer la memoria futura
        memory_service.save_turn(user_text=transcript, assistant_text=reply)

        return transcript, reply

gemini_service = GeminiService()
