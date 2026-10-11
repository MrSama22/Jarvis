import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.config import HOST, PORT
from app.routes import router

# Configurar logging detallado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("jarvis")

app = FastAPI(
    title="JARVIS AI Assistant Backend",
    description="Backend multimodal con Gemini 1.5 Flash, ChromaDB y Edge-TTS",
    version="1.0.0"
)

# Habilitar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar rutas
app.include_router(router)

@app.get("/")
def root():
    return {
        "message": "JARVIS Brain está operativo.",
        "docs_url": "/docs",
        "endpoint": "/jarvis"
    }

if __name__ == "__main__":
    logger.info(f"Iniciando servidor JARVIS en http://{HOST}:{PORT}")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
