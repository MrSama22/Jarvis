import time
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class AgentCommandQueue:
    def __init__(self):
        self.commands: List[Dict[str, Any]] = []
        self.max_queue_size = 50
        self.estado_seguridad = {
            "bloqueado": False,
            "ultima_verificacion": time.time(),
            "tiempo_maximo_sesion": 6 * 3600  # 6 horas
        }

    def verificar_seguridad(self) -> bool:
        """Retorna True si el sistema está bloqueado."""
        if self.estado_seguridad["bloqueado"]:
            return True
        if (time.time() - self.estado_seguridad["ultima_verificacion"]) > self.estado_seguridad["tiempo_maximo_sesion"]:
            self.estado_seguridad["bloqueado"] = True
            return True
        return False

    def bloquear(self):
        self.estado_seguridad["bloqueado"] = True
        logger.info("[SEGURIDAD] Protocolo de bloqueo activado.")

    def desbloquear(self):
        self.estado_seguridad["bloqueado"] = False
        self.estado_seguridad["ultima_verificacion"] = time.time()
        logger.info("[SEGURIDAD] Protocolo de bloqueo levantado.")

    def add_command(self, action: str, target: str = "windows", extra: Dict[str, Any] = None):
        """Agrega un comando a la cola para ser ejecutado por el agente local en la PC/Mac."""
        cmd = {
            "id": int(time.time() * 1000),
            "action": action,
            "target": target,
            "timestamp": time.time(),
            "extra": extra or {}
        }
        self.commands.append(cmd)
        if len(self.commands) > self.max_queue_size:
            self.commands.pop(0)
        logger.info(f"[COMMAND QUEUE] Nuevo comando encolado: {action} -> {target}")
        return cmd

    def pop_commands(self) -> List[Dict[str, Any]]:
        """Devuelve todos los comandos pendientes y vacía la cola."""
        pending = list(self.commands)
        self.commands.clear()
        return pending

agent_queue = AgentCommandQueue()
