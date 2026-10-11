import os
import logging
from pathlib import Path
from typing import Tuple
from openai import OpenAI

from app.config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    OPENAI_TRANSCRIBE_MODEL,
    MAX_RESPONSE_TOKENS
)
from app.services.chroma_service import memory_service

logger = logging.getLogger(__name__)

# System prompt ultra-compacto: menos de 75 tokens
COMPACT_SYSTEM_PROMPT = (
    "Eres JARVIS, el asistente personal de Jhulian. "
    "Tu respuesta será leída por un sintetizador de voz (TTS). "
    "Responde de forma concisa, inteligente, natural y directa (máximo 1 a 3 oraciones). "
    "No uses asteriscos, negritas, listas ni símbolos de Markdown."
)

class OpenAIService:
    def __init__(self):
        self.client = None
        self._init_client()

    def _init_client(self):
        if OPENAI_API_KEY:
            # Usamos explícitamente base_url para apuntar a la nube oficial de OpenAI
            self.client = OpenAI(
                api_key=OPENAI_API_KEY,
                base_url=OPENAI_BASE_URL
            )
            logger.info(f"Cliente OpenAI inicializado en {OPENAI_BASE_URL}")
        else:
            logger.warning("OPENAI_API_KEY no está configurada en .env.")

    def transcribe_audio(self, audio_path: Path) -> str:
        """
        Transcribe el audio usando Whisper-1.
        Whisper cobra por duración ($0.006/minuto, ej: $0.0005 por 5s) y NO gasta tokens de texto.
        """
        if not self.client:
            raise ValueError("OPENAI_API_KEY no configurada en el archivo .env.")

        logger.info(f"Transcribiendo audio con Whisper: {audio_path.name}")
        with open(audio_path, "rb") as audio_file:
            transcript_response = self.client.audio.transcriptions.create(
                model=OPENAI_TRANSCRIBE_MODEL,
                file=audio_file,
                language="es"
            )
        
        transcript_text = getattr(transcript_response, "text", "").strip()
        logger.info(f"Transcripción detectada: '{transcript_text}'")
        return transcript_text

    def generate_response(self, user_text: str) -> str:
        """
        Genera la respuesta con gpt-4o-mini optimizando el consumo de tokens:
        - System prompt ultra-ligero (~75 tokens).
        - Inyección selectiva de 1 o 2 recuerdos de ChromaDB solo si son relevantes.
        - max_tokens limitado para evitar respuestas largas o costosas.
        """
        if not self.client:
            raise ValueError("OPENAI_API_KEY no configurada en el archivo .env.")

        # 1. Búsqueda semántica en ChromaDB
        relevant_memory = memory_service.search_context(user_text, n_results=2)
        recent_history = memory_service.get_recent_history_context()

        messages = [
            {"role": "system", "content": COMPACT_SYSTEM_PROMPT}
        ]

        # 2. Agregar contexto mínimo solo si existe para no inflar los tokens
        context_notes = []
        if relevant_memory:
            context_notes.append(f"Memorias relevantes:\n{relevant_memory}")
        if recent_history:
            context_notes.append(f"Últimos turnos:\n{recent_history}")

        if context_notes:
            messages.append({
                "role": "system",
                "content": "\n".join(context_notes)
            })

        # 3. Turno actual del usuario
        messages.append({"role": "user", "content": user_text})

        # 4. Generación con gpt-4o-mini
        response = self.client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=MAX_RESPONSE_TOKENS,
            temperature=0.6,
        )

        reply_text = response.choices[0].message.content.strip()
        usage = response.usage
        if usage:
            logger.info(
                f"[Tokens JARVIS] Prompt: {usage.prompt_tokens} | "
                f"Respuesta: {usage.completion_tokens} | Total: {usage.total_tokens}"
            )

        return reply_text

    def process_voice_message(self, audio_path: Path) -> Tuple[str, str]:
        """
        Flujo de voz: Whisper (transcripción) -> GPT-4o-mini (respuesta) -> ChromaDB (almacenamiento)
        """
        # Paso 1: Transcribir el audio grabado
        transcript = self.transcribe_audio(audio_path)
        if not transcript:
            transcript = "Audio no detectado."
            return transcript, "No logré escucharte con claridad, Jhulian. ¿Podrías repetirlo?"

        # Paso 2: Generar respuesta optimizada en tokens
        reply = self.generate_response(transcript)

        # Paso 3: Guardar en ChromaDB para recordar en el futuro
        memory_service.save_turn(user_text=transcript, assistant_text=reply)

        return transcript, reply

openai_service = OpenAIService()
