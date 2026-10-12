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
    MAX_RESPONSE_TOKENS,
    TIMEZONE_OFFSET
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
    clean = text.lower().replace("-", " ").replace(".", " ").replace(",", " ")
    valid_variations = [
        "1012",
        "10 12",
        "diez doce",
        "mil doce",
        "uno cero uno dos",
        "diez y doce",
        "1 0 1 2"
    ]
    pin_env = os.getenv("SECURITY_PIN", "").strip()
    if pin_env and pin_env not in valid_variations:
        valid_variations.append(pin_env.lower())
    return any(v in clean for v in valid_variations)

def numero_a_palabras_es(n: int) -> str:
    unidades = ['', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve', 'diez',
                'once', 'doce', 'trece', 'catorce', 'quince', 'dieciséis', 'diecisiete', 'dieciocho', 'diecinueve']
    decenas = ['', '', 'veinte', 'treinta', 'cuarenta', 'cincuenta']
    if n < 20:
        return unidades[n]
    if n == 20:
        return 'veinte'
    if 21 <= n <= 29:
        return 'veinti' + unidades[n - 20]
    d = n // 10
    u = n % 10
    if u == 0:
        return decenas[d]
    return f"{decenas[d]} y {unidades[u]}"

def format_natural_time(dt: Any) -> str:
    h = dt.hour % 12
    if h == 0:
        h = 12
    m = dt.minute

    prefijo = "Es la una" if h == 1 else f"Son las {numero_a_palabras_es(h)}"
    if m == 0:
        min_str = "en punto"
    elif m == 1:
        min_str = "y un minuto"
    elif m == 15:
        min_str = "y cuarto"
    elif m == 30:
        min_str = "y media"
    else:
        min_str = f"y {numero_a_palabras_es(m)}"

    if 0 <= dt.hour < 12:
        periodo = "de la mañana"
    elif 12 <= dt.hour < 19:
        periodo = "de la tarde"
    else:
        periodo = "de la noche"

    return f"{prefijo} {min_str} {periodo}, Jhulian."

def format_natural_date(dt: Any) -> str:
    dias_sem = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
    meses_nom = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
    return f"Hoy es {dias_sem[dt.weekday()]}, {dt.day} de {meses_nom[dt.month-1]} de {dt.year}, Jhulian."

SYSTEM_PROMPT = """
Eres JARVIS, el asistente personal inteligente de Jhulian. Tu respuesta será leída en voz alta por un sintetizador de voz (TTS).
Posees amplio conocimiento, capacidad de cálculo y control total sobre las computadoras de Jhulian (Windows y Mac) y su música.

Dispositivos:
- PC Principal (Windows): MAC D8-43-AE-F8-81-6E, IP 192.168.1.8
- Mac PC (macOS): MAC FC:45:96:79:EE:7D

Protocolo de Seguridad:
- El control de hardware (apagar o encender computadoras) requiere autorización por cámara (reconocimiento facial) o mediante la contraseña maestra (PIN 1012).
- Si el usuario intenta apagar o encender computadoras y el sistema se encuentra BLOQUEADO, responde con action "SECURITY_CHALLENGE" diciendo: "Protocolo de seguridad activo. ¿Cuál es la contraseña o posiciónate frente a la cámara para autorizar la orden, Jhulian?"
- Si el usuario proporciona la contraseña correcta, el sistema autoriza y ejecuta la acción solicitada.
- Si el usuario pide "bloquear", "bloquea el sistema", "bloquea las pc" o "bloqueo de seguridad", confirma el bloqueo con action "SECURITY_LOCK".
- La música NUNCA requiere seguridad de cámara: pausar, reproducir o reanudar música SIEMPRE está permitido sin bloqueos.

Reglas de respuesta y flexibilidad acústica:
1. Sé inteligente, flexible y MUY TOLERANTE a imperfecciones de transcripción, ruido de fondo, palabras cortadas o errores del micrófono del teléfono celular (por ejemplo si la transcripción dice "pausala", "pasa la musica", "pausa", "dale play", "despausa", "apagar compu", "apaga pc", "pon musica", "continua", etc.). Deduce la intención real de Jhulian a partir del contexto en vez de descartarla.
2. Únicamente debes responder "No entendí tu comando." (con action: "NONE") si el texto es literalmente letras aleatorias sin significado o ruido completamente irreconocible.
3. Responde a CUALQUIER pregunta que te haga Jhulian: preguntas básicas, la hora, fecha, cálculos matemáticos, conceptos, ciencia o conversación casual con action: "NONE".
4. Responde siempre de forma concisa, inteligente, natural, fluida y directa (máximo 1 a 2 oraciones, ideal para voz).
5. Saludos y llamada por nombre: Si Jhulian solo dice "Jarvis", "Hola Jarvis", "Oye Jarvis" o te saluda sin dar una orden, responde de forma breve y atenta esperando su orden: "Dime, Jhulian, te escucho."
6. Ejecución directa: NUNCA hagas preguntas confirmatorias innecesarias (como "¿Estás seguro?") cuando Jhulian te dé una orden clara. Ejecútala de inmediato.
7. No uses asteriscos, negritas, listas ni símbolos de Markdown.
8. Precisión temporal y fecha en tiempo real: La fecha y hora exacta actual de Jhulian está provista en el contexto del sistema. Si el usuario pregunta la hora o la fecha, utiliza ÚNICAMENTE esa hora y fecha exacta en tiempo real. NUNCA inventes minutos, NUNCA redondees y NUNCA uses horas mencionadas en turnos anteriores del historial de conversación.
9. SIEMPRE debes retornar un JSON válido con esta estructura:
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
- "WOL_BOTH": Encender ambas computadoras ("enciende las pcs", "enciende las computadoras", "prende ambas", "enciende todo").
- "SHUTDOWN_WINDOWS": Apagar la PC principal (Windows).
- "SHUTDOWN_MAC": Apagar la Mac.
- "SHUTDOWN_BOTH": Apagar ambas computadoras ("apaga las pcs", "apaga las computadoras", "apaga los equipos", "apaga ambas", "apaga todo").
- "SECURITY_LOCK": Activar protocolo de seguridad / bloquear hardware.
- "SECURITY_CHALLENGE": Si Jhulian intenta apagar o encender computadoras y se requiere contraseña o cámara.
- "SECURITY_UNLOCK": Si Jhulian proporciona la contraseña de seguridad o desbloquea.
- "SECURITY_DENIED": Si la contraseña ingresada es incorrecta o acceso rechazado.
- "NONE": Para cualquier otra consulta general, informativa o saludo.
"""

class OpenAIService:
    def __init__(self):
        self.client = None
        self.pending_hardware_action: Optional[Dict[str, Any]] = None
        self._init_client()

    def has_valid_pending_action(self, max_age_seconds: float = 90.0) -> bool:
        """Verifica si existe una orden de hardware pendiente reciente esperando autorización."""
        if not self.pending_hardware_action:
            return False
        import time
        age = time.time() - self.pending_hardware_action.get("timestamp", 0)
        if age > max_age_seconds:
            self.pending_hardware_action = None
            return False
        return True

    def consume_pending_hardware_action(self, max_age_seconds: float = 90.0) -> Optional[Dict[str, Any]]:
        """Obtiene y consume la orden pendiente si no ha expirado."""
        if self.has_valid_pending_action(max_age_seconds):
            action = self.pending_hardware_action
            self.pending_hardware_action = None
            return action
        self.pending_hardware_action = None
        return None

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
            "apaga las pcs, apagar las pcs, apaga las pc, apaga la pc, apaga las compus, apaga todo, "
            "apagar computadoras, apaga Windows, apaga Mac, encender computadoras, prender pc, prender mac, "
            "pausa la música, pausar, pausala, dale play, reanudar música, reproducir, pon música, para la música, despausa, "
            "bloquear seguridad, desbloquear, verificar cámara, cancelar."
        )

        with open(audio_path, "rb") as audio_file:
            transcript_response = self.client.audio.transcriptions.create(
                model=OPENAI_TRANSCRIBE_MODEL,
                file=audio_file,
                language="es",
                prompt=prompt_guia,
                temperature=0.0
            )
        return getattr(transcript_response, "text", "").strip()

    def generate_response_and_action(self, user_text: str) -> Tuple[str, str, Dict[str, Any]]:
        """Determina la respuesta y ejecuta las acciones correspondientes."""
        if not self.client:
            raise ValueError("OPENAI_API_KEY no configurada.")

        esta_bloqueado = agent_queue.verificar_seguridad()

        # Obtener fecha y hora local precisa de Jhulian según TIMEZONE_OFFSET (UTC-5 por defecto)
        import datetime
        tz_local = datetime.timezone(datetime.timedelta(hours=TIMEZONE_OFFSET))
        ahora = datetime.datetime.now(tz_local)
        hora_natural = format_natural_time(ahora)
        fecha_natural = format_natural_date(ahora)

        user_text_lower = user_text.lower()

        # Detección directa e infalible de preguntas sobre la hora y fecha (0ms de latencia, 100% de precisión matemática sin alucinaciones de LLM)
        clean_q = user_text_lower
        for ch in "¿?.,¡!":
            clean_q = clean_q.replace(ch, "")
        clean_q = clean_q.replace("jarvis", "").replace("por favor", "").replace("oye", "").strip()

        es_pregunta_hora = clean_q in [
            "qué hora es", "que hora es", "qué horas son", "que horas son",
            "la hora", "dime la hora", "dame la hora", "tienes la hora",
            "qué hora tienes", "que hora tienes", "me dices la hora", "me das la hora",
            "hora actual", "cuál es la hora", "cual es la hora", "qué horas tenemos",
            "que horas tenemos", "sabes la hora", "sabes qué hora es", "sabes que hora es",
            "qué hora será", "que hora sera"
        ] or (
            ("hora" in clean_q or "horas" in clean_q)
            and any(clean_q.startswith(p) for p in ["qué hora", "que hora", "qué horas", "que horas", "dime la hora", "dame la hora", "la hora"])
            and not any(k in clean_q for k in ["en ", "del ", "de la ", "vuelo", "partido", "abren", "cierran", "película", "serie", "sale", "llega", "termina"])
        )

        es_pregunta_fecha = clean_q in [
            "qué día es hoy", "que dia es hoy", "qué día es", "que dia es",
            "qué fecha es hoy", "que fecha es hoy", "qué fecha es", "que fecha es",
            "cuál es la fecha", "cual es la fecha", "fecha de hoy", "fecha actual",
            "a qué estamos hoy", "a que estamos hoy", "a cuántos estamos", "a cuantos estamos"
        ]

        if es_pregunta_hora:
            action = "NONE"
            payload = {"status": "time_reported", "time": ahora.strftime("%H:%M")}
            return hora_natural, action, payload

        if es_pregunta_fecha:
            action = "NONE"
            payload = {"status": "date_reported", "date": ahora.strftime("%Y-%m-%d")}
            return fecha_natural, action, payload

        dias_sem = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
        meses_nom = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
        hora_str = ahora.strftime('%I:%M %p').lstrip('0')
        fecha_completa = f"{dias_sem[ahora.weekday()]}, {ahora.day} de {meses_nom[ahora.month-1]} de {ahora.year}, hora actual {hora_str} ({hora_natural})"

        es_consulta_directa = any(k in user_text_lower for k in [
            "hora", "horas", "fecha", "día", "dia", "pausa", "play", "música", "musica",
            "apaga", "apagar", "prende", "prender", "enciende", "bloquea", "desbloquea",
            "silencio", "mute", "cancela", "cancelar"
        ])
        relevant_memory = "" if es_consulta_directa else memory_service.search_context(user_text, n_results=2)
        recent_history = memory_service.get_recent_history_context()

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        context_notes = [
            f"Fecha y hora actual local de Jhulian (TIEMPO REAL EXACTO): {fecha_completa}",
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
            temperature=0.2,
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

        # 2. Detección de comandos de hardware
        is_lock_command = ("desbloque" not in user_text_lower) and any(k in user_text_lower for k in ["bloquear", "bloquea", "bloqueo", "bloqueo de seguridad", "activar seguridad", "activa seguridad", "cerrar sesión"])
        intento_apagar = any(k in user_text_lower for k in [
            "apaga", "apagar", "apague", "apágala", "apágalo", "apágalas", "apagalas", "apaguen", "apáguenlas", "apáguelos", "apaguelos"
        ])
        intento_prender = any(k in user_text_lower for k in [
            "prende", "prender", "prenda", "enciende", "encender", "encienda", "despierta", "préndela", "préndelas", "prendelas", "enciéndelas", "enciendelas", "prendan", "enciendan"
        ])
        intento_hardware = intento_apagar or intento_prender or (action in CRITICAL_HARDWARE_ACTIONS)

        plurales_pcs = [
            "pcs", "las pc", "las pcs", "las compus", "computadoras", "computadores", "las computadoras",
            "los computadores", "equipos", "los equipos", "máquinas", "maquinas", "las máquinas",
            "las maquinas", "ambas", "ambos", "las dos", "los dos", "todo", "todas"
        ]
        es_ambas = (("mac" in user_text_lower and "windows" in user_text_lower)
                    or any(p in user_text_lower for p in plurales_pcs)
                    or action in ["SHUTDOWN_BOTH", "WOL_BOTH"])

        # 3. Control de PIN y respuesta a retos de seguridad
        pin_valido = check_pin_authorization(user_text)

        # Si el usuario solo dice el PIN o código para desbloquear (sin una orden de hardware nueva)
        if pin_valido and not intento_hardware:
            agent_queue.desbloquear()
            pending = self.consume_pending_hardware_action()
            if pending:
                action_to_run = pending["action"]
                target = pending.get("target", "both")
                logger.info(f"[SEGURIDAD] PIN verificado. Ejecutando acción pendiente: {action_to_run} -> {target}")

                if action_to_run == "SHUTDOWN_BOTH":
                    agent_queue.add_command("SHUTDOWN", target="both")
                    reply = "Contraseña confirmada. Apagando ambas computadoras de inmediato, Jhulian."
                    action = "SHUTDOWN_BOTH"
                    payload = {"status": "executed", "action": "SHUTDOWN_BOTH", "target": "both", "auth": "pin"}
                elif action_to_run == "SHUTDOWN_WINDOWS":
                    agent_queue.add_command("SHUTDOWN", target="windows")
                    reply = "Contraseña confirmada. Apagando la PC principal de inmediato, Jhulian."
                    action = "SHUTDOWN_WINDOWS"
                    payload = {"status": "executed", "action": "SHUTDOWN_WINDOWS", "target": "windows", "auth": "pin"}
                elif action_to_run == "SHUTDOWN_MAC":
                    agent_queue.add_command("SHUTDOWN", target="mac")
                    reply = "Contraseña confirmada. Apagando la Mac de inmediato, Jhulian."
                    action = "SHUTDOWN_MAC"
                    payload = {"status": "executed", "action": "SHUTDOWN_MAC", "target": "mac", "auth": "pin"}
                elif action_to_run == "WOL_BOTH":
                    reply = "Contraseña confirmada. Encendiendo ambas computadoras, Jhulian."
                    action = "WOL_BOTH"
                    payload = {"devices": [DEVICES["WINDOWS"], DEVICES["MAC"]], "auth": "pin"}
                elif action_to_run == "WOL_WINDOWS":
                    reply = "Contraseña confirmada. Encendiendo la PC principal, Jhulian."
                    action = "WOL_WINDOWS"
                    payload = DEVICES["WINDOWS"]
                elif action_to_run == "WOL_MAC":
                    reply = "Contraseña confirmada. Encendiendo la Mac, Jhulian."
                    action = "WOL_MAC"
                    payload = DEVICES["MAC"]

                return reply, action, payload
            else:
                action = "SECURITY_UNLOCK"
                reply = "Código de seguridad verificado. Protocolo levantado, sistemas autorizados, Jhulian."
                payload = {"status": "unlocked", "method": "pin"}
                return reply, action, payload

        # Si había una acción pendiente pero el PIN no fue dicho (cancelación o intento incorrecto)
        elif self.has_valid_pending_action() and not intento_hardware:
            if any(k in user_text_lower for k in ["cancela", "cancelar", "cancel", "olvidalo", "olvídalo", "abortar", "no hagas nada"]):
                self.pending_hardware_action = None
                action = "CANCEL"
                agent_queue.add_command("SPOTIFY_PLAY", target="both")
                reply = "Comando cancelado, Jhulian."
                payload = {"status": "cancelled"}
                return reply, action, payload
            elif not any(k in user_text_lower for k in ["apaga", "prende", "enciende", "bloquea"]):
                pending = self.pending_hardware_action
                desc = pending.get("description", "la orden")
                action = "SECURITY_DENIED"
                reply = f"Contraseña incorrecta. Por favor, di la contraseña correcta o posiciónate frente a la cámara para autorizar {desc}, Jhulian."
                payload = {"status": "denied", "reason": "invalid_pin", "require": "auth"}
                return reply, action, payload

        if intento_hardware or (action in CRITICAL_HARDWARE_ACTIONS):
            if intento_apagar or action.startswith("SHUTDOWN"):
                if es_ambas:
                    target_action = "SHUTDOWN_BOTH"
                    target_dest = "both"
                    target_desc = "el apagado de ambas computadoras"
                    confirm_reply = "Apagando ambas computadoras de inmediato, Jhulian."
                elif "mac" in user_text_lower or action == "SHUTDOWN_MAC":
                    target_action = "SHUTDOWN_MAC"
                    target_dest = "mac"
                    target_desc = "el apagado de la Mac"
                    confirm_reply = "Apagando la Mac de inmediato, Jhulian."
                else:
                    target_action = "SHUTDOWN_WINDOWS"
                    target_dest = "windows"
                    target_desc = "el apagado de la PC principal"
                    confirm_reply = "Apagando la PC principal de inmediato, Jhulian."
            else: # Encender / WOL
                if es_ambas:
                    target_action = "WOL_BOTH"
                    target_dest = "both"
                    target_desc = "el encendido de ambas computadoras"
                    confirm_reply = "Encendiendo ambas computadoras, Jhulian."
                elif "mac" in user_text_lower or action == "WOL_MAC":
                    target_action = "WOL_MAC"
                    target_dest = "mac"
                    target_desc = "el encendido de la Mac"
                    confirm_reply = "Encendiendo la Mac, Jhulian."
                else:
                    target_action = "WOL_WINDOWS"
                    target_dest = "windows"
                    target_desc = "el encendido de la PC principal"
                    confirm_reply = "Encendiendo la PC principal, Jhulian."

            # Si el sistema está bloqueado y no se proporcionó el PIN en este mismo mensaje
            if esta_bloqueado and not pin_valido:
                import time
                self.pending_hardware_action = {
                    "action": target_action,
                    "target": target_dest,
                    "description": target_desc,
                    "timestamp": time.time()
                }
                action = "SECURITY_CHALLENGE"
                reply = f"Protocolo de seguridad activo. ¿Cuál es la contraseña o posiciónate frente a la cámara para autorizar {target_desc}, Jhulian?"
                payload = {
                    "status": "security_challenge",
                    "pending_action": target_action,
                    "require": "auth"
                }
                return reply, action, payload

            # Si el PIN es válido o el sistema ya estaba despejado:
            if pin_valido and esta_bloqueado:
                agent_queue.desbloquear()
                logger.info("[SEGURIDAD] Autorización concedida vía PIN maestro 1012 en comando directo.")

            action = target_action
            reply = confirm_reply

            if action == "SHUTDOWN_BOTH":
                agent_queue.add_command("SHUTDOWN", target="both")
                payload = {"target": "both"}
            elif action == "SHUTDOWN_WINDOWS":
                agent_queue.add_command("SHUTDOWN", target="windows")
                payload = {"target": "windows"}
            elif action == "SHUTDOWN_MAC":
                agent_queue.add_command("SHUTDOWN", target="mac")
                payload = {"target": "mac"}
            elif action == "WOL_BOTH":
                payload = {"devices": [DEVICES["WINDOWS"], DEVICES["MAC"]]}
            elif action == "WOL_WINDOWS":
                payload = DEVICES["WINDOWS"]
            elif action == "WOL_MAC":
                payload = DEVICES["MAC"]

            return reply, action, payload

        # 4. Comando explícito de bloqueo
        elif action == "SECURITY_LOCK" or is_lock_command:
            agent_queue.bloquear()
            self.pending_hardware_action = None
            action = "SECURITY_LOCK"
            reply = "Protocolo de seguridad activado. Sistemas bloqueados, se requerirá contraseña o cámara para el control de hardware."
            payload = {"status": "locked", "require": "auth"}
            return reply, action, payload

        # 5. Intentos de desbloqueo verbal
        elif "desbloquear" in user_text_lower or "desbloquea" in user_text_lower or "código" in user_text_lower or "codigo" in user_text_lower or action == "SECURITY_UNLOCK":
            if esta_bloqueado:
                action = "SECURITY_DENIED"
                reply = "Acceso denegado. Por favor, di tu código de seguridad o acércate a la cámara para verificar tu identidad, Jhulian."
                payload = {"status": "denied", "reason": "auth_required", "require": "auth"}
            else:
                action = "NONE"
                reply = "El sistema ya se encuentra validado y operativo, Jhulian."
                payload = {"status": "already_unlocked"}
            return reply, action, payload

        return reply, action, payload

    def process_voice_message(self, audio_path: Path) -> Tuple[str, str, str, Dict[str, Any]]:
        transcript = self.transcribe_audio(audio_path)
        transcript_clean = transcript.strip().strip(".?!¿¡ ").lower()

        # Alucinaciones comunes de Whisper cuando hay silencio o subtítulos generados
        alucinaciones_silencio = {
            "", "you", "...", "thank you", "gracias por ver", "subtítulos", "subtitulos"
        }
        keywords_silencio = [
            "amara.org", "subtítulo", "subtitulo", "suscríb", "suscrib", "gracias por ver", "canal"
        ]
        is_silence = (
            not transcript_clean
            or len(transcript_clean) < 2
            or transcript_clean in alucinaciones_silencio
            or any(kw in transcript_clean for kw in keywords_silencio)
        )
        if is_silence:
            logger.info(f"[JARVIS BRAIN] Silencio o audio vacío detectado: '{transcript}'")
            reply = ""
            action = "NONE"
            payload = {"status": "silence"}
            return "Silencio", reply, action, payload

        # Respuestas de cortesía directa si dice gracias
        if transcript_clean in ["gracias", "muchas gracias", "gracias jarvis"]:
            reply = "Con gusto, Jhulian."
            action = "NONE"
            payload = {"status": "courtesy"}
            return transcript, reply, action, payload

        # Saludo directo / llamada por nombre (evita latencia y llamadas innecesarias a GPT)
        if transcript_clean in ["jarvis", "oye jarvis", "hola jarvis", "hola", "dime jarvis", "estás ahí", "estas ahi"]:
            reply = "Dime, Jhulian, te escucho."
            action = "NONE"
            payload = {"status": "listening"}
            memory_service.save_turn(user_text=transcript, assistant_text=reply)
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
