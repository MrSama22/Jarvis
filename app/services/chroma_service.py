import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.config import CHROMA_PERSIST_DIR

logger = logging.getLogger(__name__)

class ChromaMemoryService:
    def __init__(self):
        self.client = None
        self.collection = None
        self.recent_turns: List[Dict[str, str]] = []  # Buffer de turnos recientes en memoria
        self.max_recent_turns = 6
        self._init_chroma()

    def _init_chroma(self):
        try:
            import chromadb
            self.client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
            self.collection = self.client.get_or_create_collection(
                name="jarvis_memory",
                metadata={"description": "Memoria episódica y contextual de JARVIS"}
            )
            logger.info(f"ChromaDB inicializado con éxito en {CHROMA_PERSIST_DIR}. Colección activa: 'jarvis_memory'")
        except Exception as e:
            logger.error(f"Error al inicializar ChromaDB: {e}. Se utilizará buffer de memoria en caliente.")
            self.client = None
            self.collection = None

    def search_context(self, query: str, n_results: int = 3) -> str:
        """
        Busca memorias relevantes semánticamente en ChromaDB.
        """
        if not self.collection or not query or not query.strip():
            return ""

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=min(n_results, max(1, self.collection.count()))
            )
            
            documents = results.get("documents", [[]])[0]
            if not documents:
                return ""

            context_items = [f"- {doc}" for doc in documents if doc]
            if context_items:
                return "\n".join(context_items)
            return ""
        except Exception as e:
            logger.warning(f"Error al consultar ChromaDB: {e}")
            return ""

    def get_recent_history_context(self) -> str:
        """
        Devuelve los últimos turnos de la conversación actual.
        """
        if not self.recent_turns:
            return ""
        
        history_lines = []
        for turn in self.recent_turns:
            history_lines.append(f"Usuario: {turn.get('user', '')}")
            history_lines.append(f"Jarvis: {turn.get('assistant', '')}")
        return "\n".join(history_lines)

    def save_turn(self, user_text: str, assistant_text: str):
        """
        Guarda el turno en el buffer reciente (instantáneo en RAM) y en ChromaDB
        en segundo plano para no demorar la respuesta de voz al usuario.
        """
        # Guardar en buffer deslizante en RAM (0ms)
        self.recent_turns.append({
            "user": user_text,
            "assistant": assistant_text,
            "timestamp": datetime.now().isoformat()
        })
        if len(self.recent_turns) > self.max_recent_turns:
            self.recent_turns.pop(0)

        # Guardar en ChromaDB de forma asíncrona/hilo en segundo plano
        if self.collection and user_text.strip():
            import threading

            def _persist_to_chroma(u_text: str, a_text: str):
                try:
                    doc_text = f"Usuario preguntó: {u_text}\nJarvis respondió: {a_text}"
                    doc_id = str(uuid.uuid4())
                    self.collection.add(
                        documents=[doc_text],
                        metadatas=[{
                            "timestamp": datetime.now().isoformat(),
                            "user_query": u_text[:150],
                            "source": "voice_interaction"
                        }],
                        ids=[doc_id]
                    )
                    logger.info(f"Nuevo recuerdo guardado en ChromaDB con ID: {doc_id}")
                except Exception as e:
                    logger.error(f"Error al guardar memoria en ChromaDB: {e}")

            threading.Thread(target=_persist_to_chroma, args=(user_text, assistant_text), daemon=True).start()

# Instancia singleton del servicio
memory_service = ChromaMemoryService()
