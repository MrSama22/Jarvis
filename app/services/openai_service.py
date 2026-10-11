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
        "ip": "192.168.1.12",
        "broadcast": "192.168.1.255",
        "port": 9
    }
}

CRITICAL_HARDWARE_ACTIONS = {
    "SHUTDOWN_WINDOWS",
    "SHUTDOWN_MAC",
    "SHUTDOWN_BOTH",
    "WOL_WINDOWS",
    "WOL_MAC",
    "WOL_BOTH"
}

def check_pin_authorization(text: str) -> bool:
    """Verifica si el texto contiene el PIN maestro de seguridad 1012 en formato número o texto."""
    clean = text.lower().replace("-", " ").replace(".", " ")
    valid_variations = [
        "1012",
        "10 12",
        "diez doce",
        "mil doce",
        "uno cero uno dos"
    ]
    return any(v in clean for v in valid_variations)

SYSTEM_PROMPT = """
Eres JARVIS, el asistente personal inteligente de Jhulian. Tu respuesta será leída en voz alta por un sintetizador de voz (TTS).
Posees amplio conocimiento, capacidad de cálculo y control total sobre las computadoras de Jhulian (Windows y Mac) y su música.

Dispositivos:
- PC Principal (Windows): MAC D8-43-AE-F8-81-6E, IP 192.168.1.8
- Mac PC (macOS): MAC FC:45:96:79:EE:7D

Protocolo de Seguridad:
- El código de autorización maestro es 1012.
- Las acciones críticas de hardware (apagar o encender las PC) requieren autorización o que el sistema esté desbloqueado.
- Si el usuario menciona "1012", "código 1012" o "desbloquear" con su código, confirma el desbloqueo con action "SECURITY_UNLOCK".
- Si el usuario pide "bloquear", "bloquea el sistema", "bloquea las pc" o activar seguridad, confirma el bloqueo con action "SECURITY_LOCK".

Reglas de respuesta:
1. Responde a CUALQUIER pregunta que te haga Jhulian: preguntas básicas, la hora, fecha, cálculos matemáticos, conceptos, datos curiosos, ciencia, dudas cotidianas o conversación casual.
2. Si el mensaje es ininteligible, puro ruido o no logras entenderlo con claridad, responde exactamente: "No entendí tu comando." con action: "NONE".
3. Responde siempre de forma concisa, inteligente, natural, fluida y directa (máximo 1 a 2 oraciones, ideal para voz).
4. No uses asteriscos, negritas, listas ni símbolos de Markdown.
5. SIEMPRE debes retornar un JSON válido con esta estructura:
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
- "CANCEL": Si Jhulian dice "cancela", "cancelar", "cancel", "olvídalo", "cancela la llamada", "abortar" o "no hagas nada". Responde brevemente con "Comando cancelado, Jhulian." o similar.
- "SECURITY_LOCK": Activar protocolo de seguridad / bloquear hardware.
- "SECURITY_UNLOCK": Desbloquear seguridad con código 1012.
- "SECURITY_DENIED": Si Jhulian intenta apagar o encender computadoras y el sistema se encuentra BLOQUEADO sin el código 1012. Responde solicitando el código de autorización.
- "NONE": Para CUALQUIER pregunta básica, informativa, cálculo, fecha/hora, o conversación general sin orden de encendido/apagado/música.
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

        # Obtener fecha y hora local precisa de Jhulian (UTC-5)
        import datetime
        tz_local = datetime.timezone(datetime.timedelta(hours=-5))
        ahora = datetime.datetime.now(tz_local)
        dias_sem = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
        meses_nom = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
        hora_str = ahora.strftime('%I:%M %p').lstrip('0')
        fecha_completa = f"{dias_sem[ahora.weekday()]}, {ahora.day} de {meses_nom[ahora.month-1]} de {ahora.year}, hora actual {hora_str}"

        relevant_memory = memory_service.search_context(user_text, n_results=2)
        recent_history = memory_service.get_recent_history_context()

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        context_notes = [
            f"Fecha y hora actual local de Jhulian: {fecha_completa}",
            f"Estado de seguridad del hardware: {'BLOQUEADO (requiere PIN 1012 para apagar o prender)' if esta_bloqueado else 'DESPEJADO (acciones de hardware autorizadas)'}"
        ]
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
        has_valid_pin = check_pin_authorization(user_text)
        user_text_lower = user_text.lower()
        is_lock_command = any(k in user_text_lower for k in ["bloquear", "bloquea", "bloqueo", "activar seguridad", "activa seguridad", "cerrar sesión"])
        intento_apagar = any(k in user_text_lower for k in ["apaga", "apagar", "apague"])
        intento_prender = any(k in user_text_lower for k in ["prende", "prender", "prenda", "enciende", "encender", "encienda", "despierta"])
        intento_hardware = intento_apagar or intento_prender or (action in CRITICAL_HARDWARE_ACTIONS)

        # 1. Acciones de hardware (Apagar o Prender computadoras)
        if intento_hardware or (action in CRITICAL_HARDWARE_ACTIONS):
            if esta_bloqueado and not has_valid_pin:
                action = "SECURITY_DENIED"
                reply = "Acceso denegado. Protocolo de seguridad activo para control de hardware. Por favor confirme su código de autorización, señor."
                payload = {"status": "denied", "reason": "security_protocol_active"}
            else:
                # Si estaba bloqueado pero vino con el PIN en la misma orden, desbloquear sesión
                if esta_bloqueado and has_valid_pin:
                    agent_queue.desbloquear()
                    logger.info("[SEGURIDAD] PIN 1012 verificado inline con acción crítica. Sesión desbloqueada.")

                # Determinar acción exacta si venía como NONE, SECURITY_UNLOCK o SECURITY_DENIED
                if action not in CRITICAL_HARDWARE_ACTIONS:
                    if intento_apagar:
                        if "mac" in user_text_lower and ("windows" in user_text_lower or "ambas" in user_text_lower or "todo" in user_text_lower):
                            action = "SHUTDOWN_BOTH"
                        elif "mac" in user_text_lower:
                            action = "SHUTDOWN_MAC"
                        else:
                            action = "SHUTDOWN_WINDOWS"
                    elif intento_prender:
                        if "mac" in user_text_lower and ("windows" in user_text_lower or "ambas" in user_text_lower or "dos" in user_text_lower):
                            action = "WOL_BOTH"
                        elif "mac" in user_text_lower:
                            action = "WOL_MAC"
                        else:
                            action = "WOL_WINDOWS"

                if action == "WOL_WINDOWS":
                    payload = DEVICES["WINDOWS"]
                elif action == "WOL_MAC":
                    payload = DEVICES["MAC"]
                elif action == "WOL_BOTH":
                    payload = {"devices": [DEVICES["WINDOWS"], DEVICES["MAC"]]}
                elif action == "SHUTDOWN_WINDOWS":
                    agent_queue.add_command("SHUTDOWN", target="windows")
                    payload = {"target": "windows"}
                elif action == "SHUTDOWN_MAC":
                    agent_queue.add_command("SHUTDOWN", target="mac")
                    payload = {"target": "mac"}
                elif action == "SHUTDOWN_BOTH":
                    agent_queue.add_command("SHUTDOWN", target="both")
                    payload = {"target": "both"}

        # 2. Comando explícito de bloqueo
        elif action == "SECURITY_LOCK" or is_lock_command:
            agent_queue.bloquear()
            action = "SECURITY_LOCK"
            reply = "Protocolo de seguridad activado. Control de hardware bloqueado, señor."
            payload = {"status": "locked"}

        # 3. Comando explícito de desbloqueo o ingreso de PIN
        elif action == "SECURITY_UNLOCK" or has_valid_pin:
            agent_queue.desbloquear()
            action = "SECURITY_UNLOCK"
            reply = "Código 1012 verificado. Protocolo de seguridad levantado por seis horas, bienvenido Jhulian."
            payload = {"status": "unlocked"}

        # 4. Intento de desbloqueo sin PIN o con PIN incorrecto
        elif "desbloquear" in user_text_lower or "desbloquea" in user_text_lower:
            action = "SECURITY_DENIED"
            reply = "Acceso denegado. Se requiere el código de autorización de cuatro dígitos para desbloquear, Jhulian."
            payload = {"status": "denied", "reason": "pin_required"}

        # 5. Control de música y cancelación (no requieren PIN de hardware)
        elif action == "SPOTIFY_PAUSE" or (any(k in user_text_lower for k in ["pausa", "pausar", "deten la musica", "para la musica"]) and "musica" in user_text_lower):
            action = "SPOTIFY_PAUSE"
            agent_queue.add_command("SPOTIFY_PAUSE", target="both")
            payload = {"status": "paused"}

        elif action == "SPOTIFY_PLAY" or (any(k in user_text_lower for k in ["reanuda", "reanudar", "reproduce", "continua la musica", "pon musica"]) and "musica" in user_text_lower):
            action = "SPOTIFY_PLAY"
            agent_queue.add_command("SPOTIFY_PLAY", target="both")
            payload = {"status": "resumed"}

        elif action == "CANCEL" or any(k in user_text_lower for k in ["cancela", "cancelar", "cancel", "olvidalo", "olvídalo", "abortar"]):
            action = "CANCEL"
            # Reanuda la música de inmediato y no ejecuta ninguna orden de hardware
            agent_queue.add_command("SPOTIFY_PLAY", target="both")
            payload = {"status": "cancelled"}

        return reply, action, payload

    def process_voice_message(self, audio_path: Path) -> Tuple[str, str, str, Dict[str, Any]]:
        transcript = self.transcribe_audio(audio_path)
        transcript_clean = transcript.strip().strip(".?!¿¡ ").lower()

        # Alucinaciones comunes de Whisper cuando hay silencio o ruido de fondo
        alucinaciones_silencio = {
            "", "silencio", "you", "gracias",
            "subtítulos por la comunidad de amara.org",
            "suscríbete al canal", "..."
        }
        if not transcript_clean or transcript_clean in alucinaciones_silencio:
            logger.info(f"[JARVIS BRAIN] Audio vacío o ininteligible: '{transcript}'")
            reply = "No entendí tu comando."
            action = "NONE"
            payload = {"status": "unrecognized"}
            return "Vacío", reply, action, payload

        reply, action, payload = self.generate_response_and_action(transcript)
        memory_service.save_turn(user_text=transcript, assistant_text=reply)

        logger.info(f"[JARVIS BRAIN] Usuario: '{transcript}' | Acción: '{action}' | Respuesta: '{reply}'")
        return transcript, reply, action, payload

openai_service = OpenAIService()
