import re
import uuid
import logging
from pathlib import Path
import edge_tts

from app.config import TEMP_AUDIO_DIR, VOICE_NAME

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

class TTSService:
    def __init__(self, voice: str = VOICE_NAME):
        self.voice = voice

    async def generate_audio(self, text: str) -> Path:
        """
        Sintetiza texto a voz usando edge-tts y guarda un archivo MP3 temporal.
        Retorna la ruta absoluta del archivo generado.
        """
        cleaned_text = clean_text_for_speech(text)
        if not cleaned_text:
            cleaned_text = "No he recibido una respuesta para sintetizar."

        filename = f"response_{uuid.uuid4().hex[:8]}.mp3"
        output_path = TEMP_AUDIO_DIR / filename

        logger.info(f"Generando audio con voz '{self.voice}' en {output_path}...")
        communicate = edge_tts.Communicate(text=cleaned_text, voice=self.voice)
        await communicate.save(str(output_path))
        
        return output_path

# Instancia singleton del servicio
tts_service = TTSService()
