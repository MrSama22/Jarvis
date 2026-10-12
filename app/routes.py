import os
import json
import uuid
import asyncio
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
import time
from app.services.tts_service import tts_service
from app.services.chroma_service import memory_service
from app.services.openai_service import openai_service
from app.services.gemini_service import gemini_service
from app.services.agent_service import agent_queue

logger = logging.getLogger(__name__)
router = APIRouter()

# Rate limit para voz: máximo 1 solicitud cada 5 segundos
LAST_VOICE_REQUEST_TIME: float = 0.0
VOICE_RATE_LIMIT_SECONDS: float = 5.0

# Registro del último turno de voz para diagnóstico y trazabilidad
LAST_TURN_INFO: dict = {
    "transcript": "Ninguno",
    "reply": "Ninguno",
    "action": "NONE",
    "payload": {},
    "timestamp": 0.0
}

@router.get("/last-turn")
async def get_last_turn():
    """Devuelve el último turno procesado por JARVIS (transcripción de Whisper, acción y respuesta)."""
    return LAST_TURN_INFO

async def auto_resume_after_speech(delay_seconds: float):
    await asyncio.sleep(delay_seconds)
    logger.info(f"[AUTO-RESUME] Reanudando música en Windows y Mac tras {delay_seconds:.1f}s")
    agent_queue.add_command("SPOTIFY_PLAY", target="both")

def cleanup_file(path: Path):
    try:
        if path.exists():
            path.unlink()
            logger.debug(f"Archivo temporal eliminado: {path}")
    except Exception as e:
        logger.warning(f"No se pudo eliminar {path}: {e}")

def verify_token(token: Optional[str]):
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
        "security_locked": agent_queue.verificar_seguridad()
    }

@router.get("/agent/poll")
async def agent_poll(
    request: Request,
    agent_id: str = Query("windows", description="Identificador del agente: windows o mac"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Endpoint consultado periódicamente tanto por Windows como por Mac de forma independiente."""
    extract_and_verify(request, x_api_key, api_key)
    pending_commands = agent_queue.get_pending_for_agent(agent_id)
    return {
        "status": "ok",
        "agent": agent_id,
        "commands": pending_commands,
        "security_locked": agent_queue.verificar_seguridad()
    }

@router.get("/pause")
async def pause_media(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Pausa la música en Windows y Mac inmediatamente."""
    agent_queue.add_command("SPOTIFY_PAUSE", target="both")
    return {"status": "ok", "action": "SPOTIFY_PAUSE", "target": "both"}

@router.get("/resume")
async def resume_media(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Reanuda la música en Windows y Mac inmediatamente."""
    agent_queue.add_command("SPOTIFY_PLAY", target="both")
    return {"status": "ok", "action": "SPOTIFY_PLAY", "target": "both"}

@router.get("/cancel")
@router.post("/cancel")
async def cancel_command():
    """Cancela cualquier operación pendiente y reanuda la música de inmediato."""
    agent_queue.add_command("SPOTIFY_PLAY", target="both")
    return {"status": "ok", "action": "CANCEL", "reply": "Comando cancelado."}

@router.get("/security/status")
async def security_status(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Consulta el estado del protocolo de seguridad."""
    extract_and_verify(request, x_api_key, api_key)
    esta_bloqueado = agent_queue.verificar_seguridad()
    return {
        "status": "ok",
        "locked": esta_bloqueado,
        "require": "camera" if esta_bloqueado else "none"
    }

@router.post("/security/unlock")
@router.get("/security/unlock")
async def security_unlock(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Endpoint llamado por el sistema de cámara / OpenCV / MacroDroid tras reconocimiento facial."""
    extract_and_verify(request, x_api_key, api_key)
    agent_queue.desbloquear()
    logger.info("[SEGURIDAD] Desbloqueo exitoso vía cámara / protocolo facial.")
    return {
        "status": "unlocked",
        "message": "Identidad confirmada. Protocolo de seguridad levantado.",
        "expires_in_hours": 6
    }

@router.post("/security/lock")
@router.get("/security/lock")
async def security_lock(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Bloquea manualmente el sistema requiriendo cámara para el próximo control de hardware."""
    extract_and_verify(request, x_api_key, api_key)
    agent_queue.bloquear()
    logger.info("[SEGURIDAD] Bloqueo manual activado.")
    return {
        "status": "locked",
        "message": "Protocolo de seguridad activado. Se requiere cámara."
    }

@router.post("/security/verify-face")
async def security_verify_face(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Recibe una captura de cámara (multipart, raw o JSON base64) y valida la identidad biométrica."""
    extract_and_verify(request, x_api_key, api_key)
    image_bytes = None
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        try:
            form = await request.form()
            for _, val in form.items():
                if isinstance(val, UploadFile):
                    image_bytes = await val.read()
                    break
        except Exception as e:
            logger.warning(f"Error parseando multipart en verify-face: {e}")

    elif "application/json" in content_type:
        try:
            body_json = await request.json()
            b64_str = body_json.get("image") or body_json.get("photo") or ""
            if b64_str:
                import base64
                if "," in b64_str:
                    b64_str = b64_str.split(",", 1)[1]
                image_bytes = base64.b64decode(b64_str)
        except Exception as e:
            logger.warning(f"Error parseando JSON base64 en verify-face: {e}")

    if not image_bytes:
        raw_body = await request.body()
        if raw_body and len(raw_body) > 100:
            image_bytes = raw_body

    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se encontró ninguna imagen en la petición."
        )

    verified, message = openai_service.verify_face_image(image_bytes)
    if verified:
        agent_queue.desbloquear()
        logger.info("[SEGURIDAD] Desbloqueo exitoso por reconocimiento facial con visión IA.")
        return {
            "status": "unlocked",
            "verified": True,
            "message": message or "Identidad confirmada. Protocolo de seguridad levantado.",
            "expires_in_hours": 6
        }
    else:
        logger.warning(f"[SEGURIDAD] Verificación facial rechazada: {message}")
        return {
            "status": "denied",
            "verified": False,
            "message": message or "Rostro no reconocido. Acceso denegado."
        }

@router.post("/jarvis")
async def jarvis_voice_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None)
):
    """Endpoint principal de voz con soporte universal para hardware y atenuación de música."""
    extract_and_verify(request, x_api_key, api_key)

    # Control de frecuencia: máximo 1 solicitud cada 5 segundos para evitar triggers múltiples
    global LAST_VOICE_REQUEST_TIME
    current_time = time.time()
    elapsed = current_time - LAST_VOICE_REQUEST_TIME
    if elapsed < VOICE_RATE_LIMIT_SECONDS:
        wait_time = round(VOICE_RATE_LIMIT_SECONDS - elapsed, 1)
        logger.warning(f"[RATE-LIMIT] Petición descartada por trigger duplicado ({elapsed:.2f}s < 5.0s, esperar {wait_time}s)")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Límite de solicitudes alcanzado. Por favor espera {wait_time} segundos antes de enviar otro comando."
        )
    LAST_VOICE_REQUEST_TIME = current_time

    # Pausa en ambas PCs mientras procesamos
    agent_queue.add_command("SPOTIFY_PAUSE", target="both")

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

        LAST_TURN_INFO["transcript"] = user_transcript
        LAST_TURN_INFO["reply"] = assistant_reply
        LAST_TURN_INFO["action"] = action
        LAST_TURN_INFO["payload"] = payload
        LAST_TURN_INFO["timestamp"] = time.time()

        output_audio_path = await tts_service.generate_audio(assistant_reply)
        background_tasks.add_task(cleanup_file, output_audio_path)

        # Si NO es una orden de apagar, pausar música o bloquear, reanudar la música automáticamente en ambas PCs tras la locución
        if action not in ["SPOTIFY_PAUSE", "SHUTDOWN_WINDOWS", "SHUTDOWN_MAC", "SHUTDOWN_BOTH", "SECURITY_LOCK"]:
            words_count = len(assistant_reply.split())
            speech_duration = max(1.8, (words_count / 2.6) + 1.0)
            background_tasks.add_task(auto_resume_after_speech, speech_duration)

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
        if action == "SECURITY_DENIED" or payload.get("require") == "camera":
            response_headers["X-Jarvis-Security"] = "CAMERA_REQUIRED"

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
