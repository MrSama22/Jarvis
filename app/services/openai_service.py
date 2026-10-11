import os
import json
import logging
from pathlib import Path
from typing import Tuple, Dict, Any
from openai import OpenAI

from app.config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    OPENAI_TRANSCRIBE_MODEL,
    MAX_RESPONSE_TOKENS
)
from app.services.chroma_service import memory_service
from app.services.agent_service import agent_queue

logger = logging.getLogger(__name__)

DEVICES = {
    "WINDOWS": {
        "name": "PC Principal",
        "mac": "D8-43-AE-F8-81-6E",
        "ip": "192.168.1.8",
        "broadcast": "192.168.1.255",
        "port": 9
    },
    "MAC": {
        "name": "Mac PC",
        "mac": "FC:45:96:79:EE:7D",
        "ip": "192.168.1.255",
        "broadcast": "192.168.1.255",
        "port": 9
    }
}

SYSTEM_PROMPT = """
Eres JARVIS, el asistente personal de Jhulian. Tu respuesta será leída por un sintetizador de voz (TTS).
Tienes el control total de las computadoras de Jhulian (Windows y Mac) y de su música.

Dispositivos:
- PC Principal (Windows): MAC D8-43-AE-F8-81-6E, IP 192.168.1.8
- Mac PC (macOS): MAC FC:45:96:79:EE:7D

Reglas de respuesta:
1. Responde de forma concisa, inteligente, natural y directa (máximo 1 a 2 oraciones).
2. No uses asteriscos, negritas, listas ni símbolos de Markdown.
3. SIEMPRE debes retornar un JSON válido con esta estructura:
{
  "action": "ACCION_DETECTADA",
  "reply": "Tu respuesta hablada para Jhulian"
}

Acciones posibles para el campo "action":
- "WOL_WINDOWS": Encender la PC principal (Windows).
- "WOL_MAC": Encender la Mac.
- "WOL_BOTH": Encender ambas computadoras / las dos.
- "SHUTDOWN_WINDOWS": Apagar la PC principal (Windows).
- "SHUTDOWN_MAC": Apagar la Mac.
- "SHUTDOWN_BOTH": Apagar ambas computadoras / todo el laboratorio.
- "SPOTIFY_PAUSE": Pausar música o bajar volumen.
- "SPOTIFY_PLAY": Reanudar música o restaurar volumen.
- "SECURITY_LOCK": Activar protocolo de seguridad / bloqueo.
- "SECURITY_UNLOCK": Desbloquear seguridad.
- "NONE": Conversación general sin orden de hardware.
"""

class OpenAIService:
    def __init__(self):
        self.client = None
        self._init_client()

    def _init_client(self):
        if OPENAI_API_KEY:
            self.client = OpenAI(
                api_key=OPENAI_API_KEY,
                base_url=OPENAI_BASE_URL
            )
            logger.info(f"Cliente OpenAI inicializado en {OPENAI_BASE_URL}")
        else:
            logger.warning("OPENAI_API_KEY no configurada.")

    def transcribe_audio(self, audio_path: Path) -> str:
        """Transcribe el audio usando Whisper-1."""
        if not self.client:
            raise ValueError("OPENAI_API_KEY no configurada en .env.")

        with open(audio_path, "rb") as audio_file:
            transcript_response = self.client.audio.transcriptions.create(
                model=OPENAI_TRANSCRIBE_MODEL,
                file=audio_file,
                language="es"
            )
        return getattr(transcript_response, "text", "").strip()

    def generate_response_and_action(self, user_text: str) -> Tuple[str, str, Dict[str, Any]]:
        """Determina la respuesta y ejecuta las acciones correspondientes."""
        if not self.client:
            raise ValueError("OPENAI_API_KEY no configurada.")

        esta_bloqueado = agent_queue.verificar_seguridad()

        relevant_memory = memory_service.search_context(user_text, n_results=2)
        recent_history = memory_service.get_recent_history_context()

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        context_notes = [f"Estado de seguridad actual: {'BLOQUEADO' if esta_bloqueado else 'DESPEJADO'}"]
        if relevant_memory:
            context_notes.append(f"Memorias:\n{relevant_memory}")
        if recent_history:
            context_notes.append(f"Turnos recientes:\n{recent_history}")

        messages.append({"role": "system", "content": "\n".join(context_notes)})
        messages.append({"role": "user", "content": user_text})

        response = self.client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=MAX_RESPONSE_TOKENS,
            temperature=0.5,
        )

        content = response.choices[0].message.content.strip()
        action = "NONE"
        reply = "Entendido, Jhulian."

        try:
            parsed = json.loads(content)
            action = parsed.get("action", "NONE").upper()
            reply = parsed.get("reply", reply)
        except Exception as e:
            logger.warning(f"Error parseando JSON de GPT: {e}")
            reply = content

        payload = {}

        # Validación del protocolo de seguridad
        if action == "SECURITY_LOCK":
            agent_queue.bloquear()
            reply = "Protocolo de seguridad activado. Sistemas bloqueados hasta su validación."
            payload = {"status": "locked"}

        elif action == "SECURITY_UNLOCK":
            agent_queue.desbloquear()
            reply = "Identidad confirmada. Protocolo de seguridad levantado, bienvenido Jhulian."
            payload = {"status": "unlocked"}

        elif esta_bloqueado and ("SHUTDOWN" in action or "SPOTIFY" in action):
            action = "SECURITY_DENIED"
            reply = "Acceso denegado, Jhulian. El protocolo de seguridad está activo."
            payload = {"status": "denied"}

        elif action == "WOL_WINDOWS":
            payload = DEVICES["WINDOWS"]
        elif action == "WOL_MAC":
            payload = DEVICES["MAC"]
        elif action == "WOL_BOTH":
            payload = {"devices": [DEVICES["WINDOWS"], DEVICES["MAC"]]}

        # Encolar para el agente local de Windows/Mac
        elif action == "SHUTDOWN_WINDOWS":
            agent_queue.add_command("SHUTDOWN", target="windows")
            payload = {"target": "windows"}

        elif action == "SHUTDOWN_MAC":
            agent_queue.add_command("SHUTDOWN", target="mac")
            payload = {"target": "mac"}

        elif action == "SHUTDOWN_BOTH":
            agent_queue.add_command("SHUTDOWN", target="both")
            payload = {"target": "both"}

        elif action == "SPOTIFY_PAUSE":
            agent_queue.add_command("SPOTIFY_PAUSE", target="windows")
            payload = {"status": "paused"}

        elif action == "SPOTIFY_PLAY":
            agent_queue.add_command("SPOTIFY_PLAY", target="windows")
            payload = {"status": "resumed"}

        return reply, action, payload

    def process_voice_message(self, audio_path: Path) -> Tuple[str, str, str, Dict[str, Any]]:
        transcript = self.transcribe_audio(audio_path)
        if not transcript:
            return "Silencio", "No logré escucharte con claridad, Jhulian. ¿Podrías repetirlo?", "NONE", {}

        reply, action, payload = self.generate_response_and_action(transcript)
        memory_service.save_turn(user_text=transcript, assistant_text=reply)

        logger.info(f"[JARVIS BRAIN] Usuario: '{transcript}' | Acción: '{action}' | Respuesta: '{reply}'")
        return transcript, reply, action, payload

openai_service = OpenAIService()
