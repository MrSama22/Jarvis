import os
import uuid
import logging
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, Header, Query, Request, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse

from app.config import (
    JARVIS_API_KEY,
    TEMP_AUDIO_DIR,
    AI_PROVIDER,
    OPENAI_MODEL,
    GEMINI_MODEL
)
from app.services.tts_service import tts_service
from app.services.chroma_service import memory_service
from app.services.openai_service import openai_service
from app.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)
router = APIRouter()

def cleanup_file(path: Path):
    """Elimina archivos temporales de audio tras completar la respuesta."""
    try:
        if path.exists():
            path.unlink()
            logger.debug(f"Archivo temporal eliminado: {path}")
    except Exception as e:
        logger.warning(f"No se pudo eliminar el archivo temporal {path}: {e}")

def verify_token(token: Optional[str]):
    """Verifica el token contra JARVIS_API_KEY de forma flexible (ignora comillas y espacios)."""
    if not JARVIS_API_KEY or not JARVIS_API_KEY.strip():
        return True

    expected = JARVIS_API_KEY.strip().strip('"').strip("'")
    provided = (token or "").strip().strip('"').strip("'")

    if not provided or provided != expected:
        logger.warning(f"Acceso no autorizado. Recibido: '{provided}', Esperado: '{expected}'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acceso no autorizado: API Key inválida o ausente."
        )
    return True

@router.get("/health")
async def health_check():
    """Endpoint de estado del servidor."""
    active_model = OPENAI_MODEL if AI_PROVIDER == "openai" else GEMINI_MODEL
    return {
        "status": "online",
        "service": "JARVIS AI Brain",
        "ai_provider": AI_PROVIDER,
        "active_model": active_model,
        "chroma_status": "ready" if memory_service.collection is not None else "in-memory-fallback",
        "voice": tts_service.voice
    }

@router.post("/jarvis")
async def jarvis_voice_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(..., description="Archivo de audio grabado por MacroDroid"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """
    Endpoint principal de voz:
    Soporta autenticación mediante cabecera 'X-API-Key', 'Authorization: Bearer <key>' o query '?api_key=<key>'.
    """
    # 1. Extraer token de múltiples fuentes (headers case-insensitive o query)
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else None

    token_to_verify = (
        x_api_key
        or request.headers.get("x-api-key")
        or request.headers.get("X-API-Key")
        or bearer_token
        or api_key
    )

    verify_token(token_to_verify)

    # 2. Guardar archivo de audio entrante
    input_suffix = Path(audio.filename or "recording.m4a").suffix or ".m4a"
    temp_input_filename = f"input_{uuid.uuid4().hex[:8]}{input_suffix}"
    temp_input_path = TEMP_AUDIO_DIR / temp_input_filename

    try:
        content = await audio.read()
        if not content:
            raise HTTPException(status_code=400, detail="El archivo de audio está vacío.")

        with open(temp_input_path, "wb") as f:
            f.write(content)
        
        logger.info(f"Audio recibido ({len(content)} bytes), guardado en {temp_input_path}")

        # Programar limpieza del audio de entrada
        background_tasks.add_task(cleanup_file, temp_input_path)

        # 3. Procesar audio según el proveedor activo
        if AI_PROVIDER == "openai":
            user_transcript, assistant_reply = openai_service.process_voice_message(temp_input_path)
        else:
            user_transcript, assistant_reply = gemini_service.process_voice_message(temp_input_path)

        logger.info(f"Usuario: {user_transcript} | Jarvis: {assistant_reply}")

        # 4. Sintetizar respuesta con Edge-TTS
        output_audio_path = await tts_service.generate_audio(assistant_reply)

        # Programar limpieza del audio de salida tras enviarse
        background_tasks.add_task(cleanup_file, output_audio_path)

        # 5. Retornar archivo de audio MP3 físico
        return FileResponse(
            path=output_audio_path,
            media_type="audio/mpeg",
            filename="jarvis_response.mp3",
            headers={
                "X-Jarvis-Transcript": user_transcript.replace("\n", " ")[:200],
                "X-Jarvis-Reply": assistant_reply.replace("\n", " ")[:200],
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error procesando petición en /jarvis: {e}", exc_info=True)
        if temp_input_path.exists():
            cleanup_file(temp_input_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno en JARVIS: {str(e)}"
        )
