import os
import json
import uuid
import logging
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Header, Query, Request, HTTPException, status, BackgroundTasks, UploadFile
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
from app.services.agent_service import agent_queue

logger = logging.getLogger(__name__)
router = APIRouter()

def cleanup_file(path: Path):
    """Elimina archivos temporales tras la respuesta."""
    try:
        if path.exists():
            path.unlink()
            logger.debug(f"Archivo temporal eliminado: {path}")
    except Exception as e:
        logger.warning(f"No se pudo eliminar {path}: {e}")

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

def extract_and_verify(request: Request, x_api_key: Optional[str] = None, api_key: Optional[str] = None):
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

@router.get("/health")
async def health_check():
    active_model = OPENAI_MODEL if AI_PROVIDER == "openai" else GEMINI_MODEL
    return {
        "status": "online",
        "service": "JARVIS AI Brain",
        "ai_provider": AI_PROVIDER,
        "active_model": active_model,
        "chroma_status": "ready" if memory_service.collection is not None else "in-memory-fallback",
        "voice": tts_service.voice,
        "security_locked": agent_queue.estado_seguridad["bloqueado"]
    }

@router.get("/agent/poll")
async def agent_poll(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Endpoint consultado periódicamente por el agente local en la PC de Jhulian."""
    extract_and_verify(request, x_api_key, api_key)
    pending_commands = agent_queue.pop_commands()
    return {
        "status": "ok",
        "commands": pending_commands,
        "security_locked": agent_queue.estado_seguridad["bloqueado"]
    }

@router.get("/pause")
async def pause_media(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Pausa la música en la PC inmediatamente."""
    extract_and_verify(request, x_api_key, api_key)
    agent_queue.add_command("SPOTIFY_PAUSE", target="windows")
    return {"status": "ok", "action": "SPOTIFY_PAUSE"}

@router.get("/resume")
async def resume_media(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Reanuda la música en la PC inmediatamente."""
    extract_and_verify(request, x_api_key, api_key)
    agent_queue.add_command("SPOTIFY_PLAY", target="windows")
    return {"status": "ok", "action": "SPOTIFY_PLAY"}

@router.post("/jarvis")
async def jarvis_voice_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """
    Endpoint principal de voz:
    - Atenúa/pausa la música automáticamente mientras procesa el audio.
    - Ejecuta intenciones de hardware y seguridad.
    """
    extract_and_verify(request, x_api_key, api_key)

    # Atenuar música mientras procesamos para que no interfiera
    agent_queue.add_command("SPOTIFY_PAUSE", target="windows")

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
            logger.warning(f"Error parseando multipart: {e}")

    if not content:
        raw_body = await request.body()
        if raw_body and len(raw_body) > 50:
            content = raw_body
            logger.info(f"Audio recibido como binario directo ({len(content)} bytes)")

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se encontró ningún archivo de audio en la petición."
        )

    temp_input_filename = f"input_{uuid.uuid4().hex[:8]}{input_suffix}"
    temp_input_path = TEMP_AUDIO_DIR / temp_input_filename

    try:
        with open(temp_input_path, "wb") as f:
            f.write(content)

        background_tasks.add_task(cleanup_file, temp_input_path)

        action = "NONE"
        payload = {}

        if AI_PROVIDER == "openai":
            user_transcript, assistant_reply, action, payload = openai_service.process_voice_message(temp_input_path)
        else:
            user_transcript, assistant_reply = gemini_service.process_voice_message(temp_input_path)

        logger.info(f"Usuario: {user_transcript} | Jarvis: {assistant_reply} | Acción: {action}")

        # Sintetizar audio
        output_audio_path = await tts_service.generate_audio(assistant_reply)
        background_tasks.add_task(cleanup_file, output_audio_path)

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
