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
- La ÚNICA validación autorizada para el control de hardware (apagar o encender computadoras) es mediante la cámara (reconocimiento facial).
- Si el usuario intenta apagar o encender computadoras y el sistema se encuentra BLOQUEADO, responde con action "SECURITY_DENIED" diciendo exactamente: "Acceso denegado. Por favor, acércate a la cámara para verificar tu identidad."
- Si el usuario pide desbloquear por voz o menciona contraseñas, responde con action "SECURITY_DENIED" indicando que la única validación es por cámara.
- Si el usuario pide "bloquear", "bloquea el sistema", "bloquea las pc" o "bloqueo de seguridad", confirma el bloqueo con action "SECURITY_LOCK".
- La música NUNCA requiere seguridad de cámara: pausar, reproducir o reanudar música SIEMPRE está permitido sin bloqueos.

Reglas de respuesta y flexibilidad acústica:
1. Sé inteligente, flexible y MUY TOLERANTE a imperfecciones de transcripción, ruido de fondo, palabras cortadas o errores del micrófono del teléfono celular (por ejemplo si la transcripción dice "pausala", "pasa la musica", "pausa", "dale play", "despausa", "apagar compu", "apaga pc", "pon musica", "continua", etc.). Deduce la intención real de Jhulian a partir del contexto en vez de descartarla.
2. Únicamente debes responder "No entendí tu comando." (con action: "NONE") si el texto es literalmente vacío, letras aleatorias sin significado o ruido completamente irreconocible.
3. Responde a CUALQUIER pregunta que te haga Jhulian: preguntas básicas, la hora, fecha, cálculos matemáticos, conceptos, ciencia o conversación casual con action: "NONE".
4. Responde siempre de forma concisa, inteligente, natural, fluida y directa (máximo 1 a 2 oraciones, ideal para voz).
5. No uses asteriscos, negritas, listas ni símbolos de Markdown.
6. SIEMPRE debes retornar un JSON válido con esta estructura:
{
  "action": "ACCION_DETECTADA",
  "reply": "Tu respuesta hablada para Jhulian"
}

Acciones posibles para el campo "action":
- "SPOTIFY_PAUSE": Si Jhulian pide pausar música, parar audio, silencio, mute, pausala, apaga la música, para la música.
- "SPOTIFY_PLAY": Si Jhulian pide reanudar música, reproducir, dale play, continuar, despausar, pon música.
- "CANCEL": Si Jhulian dice "cancela", "cancelar", "cancel", "olvídalo", "abortar". Responde "Comando cancelado, Jhulian."
- "WOL_WINDOWS": Encender la PC principal (Windows).
- "WOL_MAC": Encender la Mac.
- "WOL_BOTH": Encender ambas computadoras.
- "SHUTDOWN_WINDOWS": Apagar la PC principal (Windows).
- "SHUTDOWN_MAC": Apagar la Mac.
- "SHUTDOWN_BOTH": Apagar ambas computadoras.
- "SECURITY_LOCK": Activar protocolo de seguridad / bloquear hardware.
- "SECURITY_DENIED": Si Jhulian intenta apagar o encender computadoras y el sistema se encuentra BLOQUEADO.
- "NONE": Para cualquier otra consulta general, informativa o saludo.
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
        """Transcribe el audio usando Whisper-1 con prompt contextual para máxima tolerancia a ruido y micrófono de celular."""
        if not self.client:
            raise ValueError("OPENAI_API_KEY no configurada en .env.")

        prompt_guia = (
            "Comandos de voz del usuario Jhulian para su asistente JARVIS: "
            "Jarvis, pausa la música, pausar, pausala, dale play, reanudar música, reproducir, pon música, para la música, despausa, "
            "apagar PC Windows, apagar Mac, apagar ambas computadoras, prender PC, prender Mac, "
            "bloquear seguridad, desbloquear, verificar cámara, cancelar llamada, qué hora es, cómo estás."
        )

        with open(audio_path, "rb") as audio_file:
            transcript_response = self.client.audio.transcriptions.create(
                model=OPENAI_TRANSCRIBE_MODEL,
                file=audio_file,
                language="es",
                prompt=prompt_guia,
                temperature=0.2
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
            f"Estado de seguridad del hardware: {'BLOQUEADO (la única validación autorizada es acercarse a la cámara)' if esta_bloqueado else 'DESPEJADO (validado por cámara, acciones autorizadas)'}"
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
        user_text_lower = user_text.lower()

        # 1. Detección de música y reproducción (prioritaria: NUNCA requiere validación de cámara ni apaga hardware)
        palabras_pausa = [
            "pausa", "pausar", "pausala", "páusala", "deten", "detén", "para la musica", "para la música",
            "para musica", "para el audio", "para la canción", "para la cancion", "silencio",
            "mute", "mutear", "callate", "cállate", "apaga la musica", "apaga la música",
            "apaga el audio", "quita la musica", "quita la música", "quitar musica", "baja la musica"
        ]
        palabras_play = [
            "reanuda", "reanudar", "reanudala", "reproduce", "reproducir", "reprodúcela",
            "continua", "continúa", "dale play", "play", "despausa", "despausar",
            "pon musica", "pon la musica", "pon música", "pon la música",
            "sigue con la musica", "sigue la musica"
        ]
        palabras_cancel = [
            "cancela", "cancelar", "cancel", "olvidalo", "olvídalo", "abortar", "no hagas nada"
        ]

        es_play_musica = (action == "SPOTIFY_PLAY") or any(k in user_text_lower for k in palabras_play)
        es_pausa_musica = ("despaus" not in user_text_lower) and ((action == "SPOTIFY_PAUSE") or any(k in user_text_lower for k in palabras_pausa))
        es_cancel = (action == "CANCEL") or any(k in user_text_lower for k in palabras_cancel)

        if es_cancel:
            action = "CANCEL"
            agent_queue.add_command("SPOTIFY_PLAY", target="both")
            reply = "Comando cancelado, Jhulian."
            payload = {"status": "cancelled"}
            return reply, action, payload

        elif es_play_musica:
            action = "SPOTIFY_PLAY"
            agent_queue.add_command("SPOTIFY_PLAY", target="both")
            if "reanud" not in reply.lower() and "músic" not in reply.lower() and "play" not in reply.lower():
                reply = "Reanudando música, Jhulian."
            payload = {"status": "resumed"}
            return reply, action, payload

        elif es_pausa_musica:
            action = "SPOTIFY_PAUSE"
            agent_queue.add_command("SPOTIFY_PAUSE", target="both")
            if "paus" not in reply.lower() and "músic" not in reply.lower():
                reply = "Música pausada, Jhulian."
            payload = {"status": "paused"}
            return reply, action, payload

        # 2. Control de hardware (Apagar / Prender computadoras - requiere cámara si está bloqueado)
        is_lock_command = ("desbloque" not in user_text_lower) and any(k in user_text_lower for k in ["bloquear", "bloquea", "bloqueo", "bloqueo de seguridad", "activar seguridad", "activa seguridad", "cerrar sesión"])
        intento_apagar = any(k in user_text_lower for k in ["apaga", "apagar", "apague", "apágala", "apágalo"])
        intento_prender = any(k in user_text_lower for k in ["prende", "prender", "prenda", "enciende", "encender", "encienda", "despierta", "préndela"])
        intento_hardware = intento_apagar or intento_prender or (action in CRITICAL_HARDWARE_ACTIONS)

        if intento_hardware or (action in CRITICAL_HARDWARE_ACTIONS):
            if esta_bloqueado:
                action = "SECURITY_DENIED"
                reply = "Acceso denegado. Por favor, acércate a la cámara para verificar tu identidad, Jhulian."
                payload = {"status": "denied", "reason": "camera_verification_required", "require": "camera"}
            else:
                # Sistema validado previamente por cámara (sesión activa de 6 horas)
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

        # 3. Comando explícito de bloqueo
        elif action == "SECURITY_LOCK" or is_lock_command:
            agent_queue.bloquear()
            action = "SECURITY_LOCK"
            reply = "Protocolo de seguridad activado. Sistemas bloqueados, se requerirá cámara para el control de hardware."
            payload = {"status": "locked", "require": "camera"}

        # 4. Intentos de desbloqueo verbal (Se deniegan: la única validación es la cámara)
        elif "desbloquear" in user_text_lower or "desbloquea" in user_text_lower or "código" in user_text_lower or "codigo" in user_text_lower or action == "SECURITY_UNLOCK":
            if esta_bloqueado:
                action = "SECURITY_DENIED"
                reply = "Acceso denegado. La única validación autorizada es mediante la cámara. Por favor acércate a ella, Jhulian."
                payload = {"status": "denied", "reason": "camera_verification_required", "require": "camera"}
            else:
                action = "NONE"
                reply = "El sistema ya se encuentra validado y operativo por cámara, Jhulian."
                payload = {"status": "already_unlocked"}

        return reply, action, payload

    def process_voice_message(self, audio_path: Path) -> Tuple[str, str, str, Dict[str, Any]]:
        transcript = self.transcribe_audio(audio_path)
        transcript_clean = transcript.strip().strip(".?!¿¡ ").lower()

        # Alucinaciones comunes de Whisper cuando hay silencio o subtítulos generados
        alucinaciones_silencio = {
            "", "you", "subtítulos por la comunidad de amara.org",
            "suscríbete al canal", "suscribete al canal", "...", "suscríbete",
            "subtítulos", "subtitulos"
        }
        if not transcript_clean or transcript_clean in alucinaciones_silencio or len(transcript_clean) < 2:
            logger.info(f"[JARVIS BRAIN] Audio vacío o ininteligible: '{transcript}'")
            reply = "No entendí tu comando."
            action = "NONE"
            payload = {"status": "unrecognized"}
            return "Vacío", reply, action, payload

        # Respuestas de cortesía directa si dice gracias
        if transcript_clean in ["gracias", "muchas gracias", "gracias jarvis"]:
            reply = "Con gusto, Jhulian."
            action = "NONE"
            payload = {"status": "courtesy"}
            return transcript, reply, action, payload

        reply, action, payload = self.generate_response_and_action(transcript)
        memory_service.save_turn(user_text=transcript, assistant_text=reply)

        logger.info(f"[JARVIS BRAIN] Usuario: '{transcript}' | Acción: '{action}' | Respuesta: '{reply}'")
        return transcript, reply, action, payload

    def verify_face_image(self, image_bytes: bytes) -> Tuple[bool, str]:
        """Analiza la foto capturada por la cámara para verificar presencia de Jhulian / rostro humano."""
        if not self.client:
            raise ValueError("OPENAI_API_KEY no configurada.")
        import base64
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            "Eres el módulo de seguridad biométrica de JARVIS. Analiza esta imagen capturada por la cámara.\n"
            "Verifica si aparece una persona real frente a la cámara (el usuario Jhulian) de forma clara y atenta.\n"
            "Responde únicamente en formato JSON con esta estructura:\n"
            '{"verified": true/false, "reason": "breve explicación en 1 oración"}'
        )
        try:
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64_img}",
                                    "detail": "low"
                                }
                            }
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                max_tokens=100,
                temperature=0.2
            )
            content = response.choices[0].message.content.strip()
            parsed = json.loads(content)
            is_verified = bool(parsed.get("verified", False))
            reason = parsed.get("reason", "Verificación completada.")
            return is_verified, reason
        except Exception as e:
            logger.error(f"Error analizando imagen con OpenAI Vision: {e}")
            return False, f"Error en análisis de imagen: {str(e)}"

openai_service = OpenAIService()
