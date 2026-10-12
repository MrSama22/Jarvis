import re
import os
import time
import uuid
import logging
import asyncio
from pathlib import Path
import edge_tts

from app.config import TEMP_AUDIO_DIR, VOICE_NAME, OPENAI_API_KEY, OPENAI_BASE_URL

logger = logging.getLogger(__name__)

def clean_text_for_speech(text: str) -> str:
    """
    Limpia formato Markdown y símbolos para que la síntesis de voz suene natural.
    """
    if not text:
        return ""
    # Remover bloques de código
    text = re.sub(r'```[\s\S]*?```', 'código omitido.', text)
    # Remover código en línea `texto`
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Remover negritas, cursivas y asteriscos
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    # Remover enlaces markdown [texto](url) -> texto
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remover encabezados #
    text = re.sub(r'#+\s*', '', text)
    # Remover viñetas y guiones iniciales
    text = re.sub(r'^\s*[-*•]\s*', '', text, flags=re.MULTILINE)
    # Normalizar espacios
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def _generate_silent_mp3(output_path: Path):
    """Genera un archivo MP3 válido de contingencia para que el cliente reciba audio sin fallar."""
    # Frame MPEG-1 Audio Layer 3 (128 kbps, 44.1 kHz, estéreo)
    frame = b"\xff\xfb\x90\x00" + (b"\x00" * 413)
    with open(output_path, "wb") as f:
        f.write(frame * 12)

def _generate_openai_speech(text: str, output_path: Path):
    """Genera audio usando la API oficial de OpenAI TTS (tts-1 con voz onyx estilo Jarvis)."""
    from openai import OpenAI
    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL
    )
    response = client.audio.speech.create(
        model="tts-1",
        voice="onyx",
        input=text
    )
    if hasattr(response, "write_to_file"):
        response.write_to_file(str(output_path))
    elif hasattr(response, "content"):
        with open(output_path, "wb") as f:
            f.write(response.content)
    elif hasattr(response, "stream_to_file"):
        response.stream_to_file(str(output_path))

class TTSService:
    def __init__(self, voice: str = VOICE_NAME):
        self.voice = voice
        self.edge_cooldown_until = 0.0

    async def generate_audio(self, text: str) -> Path:
        """
        Sintetiza texto a voz.
        Intenta primero edge-tts. Si falla (ej. error 403 de Microsoft, rate-limit, red),
        conmuta automáticamente a OpenAI TTS (tts-1 onyx). Si ambos fallan, genera
        un audio de contingencia para que la petición HTTP nunca se caiga con 500.
        """
        cleaned_text = clean_text_for_speech(text)
        if not cleaned_text:
            cleaned_text = "No he recibido una respuesta para sintetizar."

        filename = f"response_{uuid.uuid4().hex[:8]}.mp3"
        output_path = TEMP_AUDIO_DIR / filename

        tts_pref = os.getenv("TTS_PROVIDER", "auto").lower()
        should_try_edge = (tts_pref != "openai") and (time.time() >= self.edge_cooldown_until)

        # 1. Intentar con Edge-TTS (si no está en cooldown por error 403 o red)
        if should_try_edge:
            try:
                logger.info(f"Intentando síntesis TTS con Edge-TTS (voz '{self.voice}')...")
                communicate = edge_tts.Communicate(text=cleaned_text, voice=self.voice)
                await communicate.save(str(output_path))
                if output_path.exists() and output_path.stat().st_size > 0:
                    return output_path
            except Exception as edge_err:
                self.edge_cooldown_until = time.time() + 600  # Cooldown de 10 min ante bloqueo 403
                logger.warning(f"[TTS] Edge-TTS falló ({edge_err}). Cooldown activado (10m). Conmutando a OpenAI TTS...")
        elif time.time() < self.edge_cooldown_until:
            logger.info("[TTS] Edge-TTS en cooldown tras error 403 previo. Usando OpenAI TTS directamente.")

        # 2. Fallback automático a OpenAI TTS (Voz 'onyx')
        if OPENAI_API_KEY:
            try:
                logger.info("Generando audio con OpenAI TTS (tts-1/onyx)...")
                await asyncio.to_thread(_generate_openai_speech, cleaned_text, output_path)
                if output_path.exists() and output_path.stat().st_size > 0:
                    logger.info("Audio sintetizado con OpenAI TTS exitosamente.")
                    return output_path
            except Exception as oai_err:
                logger.error(f"[TTS] Fallback con OpenAI TTS también falló: {oai_err}", exc_info=True)

        # 3. Fallback de contingencia silencioso (garantiza entrega de cabeceras y código HTTP 200)
        logger.warning("[TTS] Usando audio de contingencia para evitar error 500.")
        _generate_silent_mp3(output_path)
        return output_path

# Instancia singleton del servicio
tts_service = TTSService()

