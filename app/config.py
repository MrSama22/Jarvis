import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables del archivo .env
load_dotenv()

# Rutas base
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CHROMA_PERSIST_DIR = Path(os.getenv("CHROMA_PERSIST_DIR", str(DATA_DIR / "chroma")))
TEMP_AUDIO_DIR = Path(os.getenv("TEMP_AUDIO_DIR", str(DATA_DIR / "temp")))

# Asegurar existencia de directorios de almacenamiento
CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Configuraciones de IA
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL_OVERRIDE", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", 180))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# Seguridad y Voz
JARVIS_API_KEY = os.getenv("JARVIS_API_KEY", "jarvis_secret_key_12345")
VOICE_NAME = os.getenv("VOICE_NAME", "es-MX-JorgeNeural")

# Puerto y Host
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))
