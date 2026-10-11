import time
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class AgentCommandQueue:
    def __init__(self):
        # Historial de comandos recientes
        self.commands: List[Dict[str, Any]] = []
        self.max_history = 40
        self.last_seen_timestamps: Dict[str, float] = {
            "windows": time.time(),
            "mac": time.time(),
            "all": time.time()
        }
        self.estado_seguridad = {
            "bloqueado": False,
            "ultima_verificacion": time.time(),
            "tiempo_maximo_sesion": 6 * 3600
        }

    def verificar_seguridad(self) -> bool:
        if self.estado_seguridad["bloqueado"]:
            return True
        if (time.time() - self.estado_seguridad["ultima_verificacion"]) > self.estado_seguridad["tiempo_maximo_sesion"]:
            self.estado_seguridad["bloqueado"] = True
            return True
        return False

    def bloquear(self):
        self.estado_seguridad["bloqueado"] = True
        logger.info("[SEGURIDAD] Bloqueo activado.")

    def desbloquear(self):
        self.estado_seguridad["bloqueado"] = False
        self.estado_seguridad["ultima_verificacion"] = time.time()
        logger.info("[SEGURIDAD] Bloqueo levantado.")

    def add_command(self, action: str, target: str = "both", extra: Dict[str, Any] = None):
        """Agrega un comando con timestamp único para que ni Windows ni Mac se pierdan la orden."""
        now = time.time()
        # Evitar colisiones entre pausa y reproducción inmediata
        if action == "SPOTIFY_PLAY":
            self.commands = [c for c in self.commands if c.get("action") != "SPOTIFY_PAUSE"]
        elif action == "SPOTIFY_PAUSE":
            self.commands = [c for c in self.commands if c.get("action") != "SPOTIFY_PLAY"]

        cmd = {
            "id": int(now * 1000),
            "action": action,
            "target": target,  # "windows", "mac", o "both"
            "timestamp": now,
            "extra": extra or {}
        }
        self.commands.append(cmd)
        if len(self.commands) > self.max_history:
            self.commands.pop(0)
        logger.info(f"[COMMAND QUEUE] Orden registrada: {action} -> {target}")
        return cmd

    def get_pending_for_agent(self, agent_name: str) -> List[Dict[str, Any]]:
        """
        Devuelve las órdenes pendientes específicas para este agente (windows o mac),
        evitando que un agente le borre las órdenes al otro si ambos están encendidos.
        """
        agent_key = agent_name.lower().strip()
        last_seen = self.last_seen_timestamps.get(agent_key, time.time() - 10)
        
        pending = []
        for cmd in self.commands:
            target = cmd.get("target", "both")
            if cmd["timestamp"] > last_seen:
                if target in [agent_key, "both", "all"]:
                    pending.append(cmd)

        self.last_seen_timestamps[agent_key] = time.time()
        return pending

agent_queue = AgentCommandQueue()
