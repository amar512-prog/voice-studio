from functools import lru_cache
from pathlib import Path
import os


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("DATA_DIR", "data"))
        self.static_dir = Path(os.getenv("STATIC_DIR", "frontend/dist"))
        self.elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
        self.elevenlabs_base_url = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io/v1")
        self.elevenlabs_model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_v3")
        self.elevenlabs_language_code = os.getenv("ELEVENLABS_LANGUAGE_CODE", "en")
        self.huggingface_token = os.getenv("HUGGINGFACE_TOKEN", "").strip()
        self.omnivoice_base_url = os.getenv(
            "OMNIVOICE_BASE_URL",
            "https://salmanbvps-omnivoice-batch-tts.hf.space",
        ).rstrip("/")
        self.omnivoice_timeout_seconds = max(30, int(os.getenv("OMNIVOICE_TIMEOUT_SECONDS", "240")))
        # Rows sent to the OmniVoice space per /batch call (true batched inference).
        # Keep modest so a single ZeroGPU request stays within its time budget.
        self.omnivoice_batch_chunk = min(20, max(1, int(os.getenv("OMNIVOICE_BATCH_CHUNK", "6"))))
        self.max_duration_seconds = int(os.getenv("LINKEDIN_MAX_SECONDS", "60"))
        self.default_target_seconds = int(os.getenv("DEFAULT_TARGET_SECONDS", "55"))
        self.default_wpm = int(os.getenv("DEFAULT_WPM", "135"))
        self.auth_mode = os.getenv("AUTH_MODE", "google").lower()
        if self.auth_mode not in {"development", "google"}:
            raise RuntimeError("AUTH_MODE must be development or google")

        self.google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        if self.auth_mode == "google" and not self.google_client_id:
            raise RuntimeError("GOOGLE_CLIENT_ID is required when AUTH_MODE=google")

        self.google_allowed_domains = tuple(
            domain.strip().lower()
            for domain in os.getenv("GOOGLE_ALLOWED_DOMAINS", "").split(",")
            if domain.strip()
        )
        self.session_secret = os.getenv("SESSION_SECRET", "")
        if len(self.session_secret) < 32:
            raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
        self.session_secure = os.getenv("SESSION_SECURE", "true").lower() == "true"

        # Username/password login (optional, works alongside Google/development).
        self.basic_auth_username = os.getenv("AUTH_USERNAME", "")
        self.basic_auth_password = os.getenv("AUTH_PASSWORD", "")
        # Static API key for machine/Swagger access via the X-API-Key header.
        self.api_key = os.getenv("API_KEY", "")

        # Generation guardrails: bound parallel ffmpeg/TTS work and batch size so a
        # large upload can't exhaust CPU/memory or run up provider cost.
        # Keep MAX_CONCURRENT_GENERATIONS <= your ElevenLabs plan's concurrency limit
        # (Free 2, Starter 3, Creator 5, Pro 10, Scale/Business 15) to avoid 429s.
        self.max_concurrent_generations = max(1, int(os.getenv("MAX_CONCURRENT_GENERATIONS", "2")))
        self.max_batch_rows = max(1, int(os.getenv("MAX_BATCH_ROWS", "200")))

    @property
    def password_enabled(self) -> bool:
        return bool(self.basic_auth_username and self.basic_auth_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
