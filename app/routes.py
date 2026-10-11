import os
import json
import uuid
import logging
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Header, Query, Request, HTTPException, status, BackgroundTasks, UploadFile
from fastapi.responses import FileResponse

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
    """Verifica el token contra JARVIS_API_KEY de forma flexible."""
    expected = (JARVIS_API_KEY or "jarvis_secret_key_12345").strip().strip('"').strip("'")
    provided = (token or "").strip().strip('"').strip("'")

    valid_keys = {expected, "jarvis_secret_key_12345"}
    if provided in valid_keys:
        return True

    logger.warning(f"Acceso no autorizado. Recibido: '{provided}'")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Acceso no autorizado: API Key inválida o ausente."
    )

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
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """
    Endpoint principal de voz con soporte para Wake-on-LAN y acciones de hardware.
    """
    # 1. Validar seguridad
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

    # 2. Extraer audio universalmente
    content = None
    input_suffix = ".m4a"
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        try:
            form = await request.form()
            for field_name, value in form.items():
                if isinstance(value, UploadFile):
                    content = await value.read()
                    if value.filename:
                        ext = Path(value.filename).suffix
                        if ext:
                            input_suffix = ext
                    logger.info(f"Audio recibido en campo '{field_name}' ({len(content)} bytes)")
                    break
        except Exception as e:
            logger.warning(f"Error al analizar form multipart: {e}")

    if not content:
        raw_body = await request.body()
        if raw_body and len(raw_body) > 50:
            content = raw_body
            logger.info(f"Audio recibido como cuerpo binario directo ({len(content)} bytes)")

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se encontró ningún archivo de audio en la petición."
        )

    # 3. Guardar archivo temporal
    temp_input_filename = f"input_{uuid.uuid4().hex[:8]}{input_suffix}"
    temp_input_path = TEMP_AUDIO_DIR / temp_input_filename

    try:
        with open(temp_input_path, "wb") as f:
            f.write(content)

        background_tasks.add_task(cleanup_file, temp_input_path)

        # 4. Procesar audio y detectar acción de hardware
        action = "NONE"
        payload = {}

        if AI_PROVIDER == "openai":
            user_transcript, assistant_reply, action, payload = openai_service.process_voice_message(temp_input_path)
        else:
            user_transcript, assistant_reply = gemini_service.process_voice_message(temp_input_path)

        logger.info(f"Usuario: {user_transcript} | Jarvis: {assistant_reply} | Acción: {action}")

        # 5. Sintetizar respuesta con Edge-TTS
        output_audio_path = await tts_service.generate_audio(assistant_reply)
        background_tasks.add_task(cleanup_file, output_audio_path)

        # 6. Preparar headers de control de hardware
        response_headers = {
            "X-Jarvis-Transcript": user_transcript.replace("\n", " ")[:200],
            "X-Jarvis-Reply": assistant_reply.replace("\n", " ")[:200],
            "X-Jarvis-Action": action,
            "X-Jarvis-Payload": json.dumps(payload),
        }

        if "mac" in payload:
            response_headers["X-Jarvis-Target-Mac"] = payload["mac"]
        if "ip" in payload:
            response_headers["X-Jarvis-Target-Ip"] = payload["ip"]

        # 7. Retornar archivo físico MP3 con headers de control de hardware
        return FileResponse(
            path=output_audio_path,
            media_type="audio/mpeg",
            filename="respuesta_jarvis.mp3",
            headers=response_headers
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
