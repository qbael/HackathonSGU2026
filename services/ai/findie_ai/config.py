"""Server-side model and transport configuration; no secrets in status output."""

from dataclasses import dataclass, field
import ipaddress
import os
import re
from urllib.parse import urlsplit


QUERY_INSTRUCTION = (
    "Given a Vietnamese lost-item description, retrieve matching found-item posts, "
    "preserving object details and precise finding locations."
)


def loopback(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Settings:
    service_token: str = field(repr=False)
    search_dsn: str = field(default="", repr=False)
    rabbitmq_url: str = field(default="", repr=False)
    redis_url: str = field(default="", repr=False)
    search_cache_ttl_seconds: int = 60
    ollama_base_url: str = field(default="http://127.0.0.1:11434", repr=False)
    ollama_api_key: str = field(default="", repr=False)
    model_id: str = "qwen3-embedding:4b"
    revision: str = ""
    dimensions: int = 2048
    query_instruction: str = QUERY_INSTRUCTION
    search_profile: str = "text-description-v1"
    semantic_weight: float = 0.6
    min_image_similarity: float = 0.6
    min_text_similarity: float = 0.6
    relative_score_ratio: float = 0.75
    reranker_model: str = "Qwen/Qwen3-VL-Reranker-2B"
    reranker_revision: str = ""
    rerank_min_image_score: float = 0.5
    rerank_min_text_score: float = 0.5
    index_queue: str = "findie.ai.commands"
    result_queue: str = "findie.api.results"
    query_queue: str = "findie.ai.query"
    image_queue: str = "findie.ai.image"
    materials_queue: str = "findie.api.materials"
    materials_reply_queue: str = "findie.ai.materials.results"
    image_search_enabled: bool = False
    image_search_profile: str = "image-only-v1"
    redaction_model: str = "qwen3-vl:4b-instruct"
    redaction_revision: str = ""

    def __post_init__(self):
        if not self.service_token:
            raise ValueError("AI_SERVICE_TOKEN must be configured.")
        if not 1 <= self.dimensions <= 16000:
            raise ValueError("AI_EMBEDDING_DIMENSIONS must be between 1 and 16000.")
        if not 1 <= self.search_cache_ttl_seconds <= 3600:
            raise ValueError("AI_SEARCH_CACHE_TTL_SECONDS must be between 1 and 3600.")
        if not 0 <= self.semantic_weight <= 1:
            raise ValueError("AI_SEARCH_SEMANTIC_WEIGHT must be between 0 and 1.")
        for kind in ("image", "text"):
            if not 0 <= getattr(self, f"min_{kind}_similarity") <= 1:
                raise ValueError(f"AI_SEARCH_MIN_{kind.upper()}_SIMILARITY must be between 0 and 1.")
            if not 0 <= getattr(self, f"rerank_min_{kind}_score") <= 1:
                raise ValueError(f"AI_RERANK_MIN_{kind.upper()}_SCORE must be between 0 and 1.")
        if not 0 <= self.relative_score_ratio <= 1:
            raise ValueError("AI_SEARCH_RELATIVE_SCORE_RATIO must be between 0 and 1.")
        if self.reranker_revision and not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", self.reranker_revision):
            raise ValueError("AI_RERANKER_REVISION must pin the model fingerprint SHA-256.")
        if not self.reranker_model:
            raise ValueError("AI_RERANKER_MODEL must be nonblank.")
        if self.redis_url:
            endpoint = urlsplit(self.redis_url)
            if (endpoint.scheme not in {"redis", "rediss"} or not endpoint.hostname
                    or endpoint.query or endpoint.fragment
                    or endpoint.scheme == "redis" and not loopback(endpoint.hostname)):
                raise ValueError("AI_REDIS_URL requires rediss outside loopback and no query or fragment.")
        if self.revision and not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", self.revision):
            raise ValueError("AI_EMBEDDING_REVISION must pin the model fingerprint SHA-256.")
        if self.redaction_revision and not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", self.redaction_revision):
            raise ValueError("AI_REDACTION_REVISION must pin the Ollama manifest SHA-256.")
        if (not self.model_id or not self.search_profile or not self.image_search_profile
                or not self.redaction_model or len(self.query_instruction) > 2000):
            raise ValueError("Invalid model/search profile configuration.")
        endpoint = urlsplit(self.ollama_base_url)
        if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
            raise ValueError("Invalid OLLAMA_BASE_URL.")
        if not loopback(endpoint.hostname) and (endpoint.scheme != "https" or not self.ollama_api_key):
            raise ValueError("Remote Ollama requires HTTPS and OLLAMA_API_KEY on an authenticated gateway.")
        if self.rabbitmq_url:
            broker = urlsplit(self.rabbitmq_url)
            if (broker.scheme not in {"amqp", "amqps"} or not broker.hostname
                    or broker.scheme == "amqp" and not loopback(broker.hostname)):
                raise ValueError("RabbitMQ requires AMQPS outside loopback.")
        queues = (self.index_queue, self.result_queue, self.query_queue, self.image_queue,
                  self.materials_queue, self.materials_reply_queue)
        if len(set(queues)) != len(queues) or any(not q or len(q.encode()) > 255 for q in queues):
            raise ValueError("AI queue names must be distinct and valid.")

    @property
    def enabled(self) -> bool:
        return bool(self.search_dsn and self.rabbitmq_url and self.revision)

    @classmethod
    def from_env(cls):
        try:
            semantic_weight = float(os.environ.get("AI_SEARCH_SEMANTIC_WEIGHT", "0.6"))
        except ValueError:
            raise ValueError("AI_SEARCH_SEMANTIC_WEIGHT must be a number between 0 and 1.") from None
        image_search = os.environ.get("AI_IMAGE_SEARCH_ENABLED", "false").lower()
        if image_search not in {"true", "false"}:
            raise ValueError("AI_IMAGE_SEARCH_ENABLED must be true or false.")
        return cls(
            service_token=os.environ.get("AI_SERVICE_TOKEN", "").strip(),
            search_dsn=os.environ.get("AI_SEARCH_DSN", ""),
            rabbitmq_url=os.environ.get("AI_RABBITMQ_URL", os.environ.get("RabbitMq__Uri", "")),
            redis_url=os.environ.get("AI_REDIS_URL", "").strip(),
            search_cache_ttl_seconds=int(os.environ.get("AI_SEARCH_CACHE_TTL_SECONDS", "60")),
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_api_key=os.environ.get("OLLAMA_API_KEY", ""),
            model_id=os.environ.get("AI_EMBEDDING_MODEL", "qwen3-embedding:4b"),
            revision=os.environ.get("AI_EMBEDDING_REVISION", ""),
            dimensions=int(os.environ.get("AI_EMBEDDING_DIMENSIONS", "2048")),
            query_instruction=os.environ.get("AI_EMBEDDING_QUERY_INSTRUCTION", QUERY_INSTRUCTION),
            search_profile=os.environ.get("AI_TEXT_SEARCH_PROFILE", "text-description-v1"),
            semantic_weight=semantic_weight,
            min_image_similarity=float(os.environ.get("AI_SEARCH_MIN_IMAGE_SIMILARITY", "0.6")),
            min_text_similarity=float(os.environ.get("AI_SEARCH_MIN_TEXT_SIMILARITY", "0.6")),
            relative_score_ratio=float(os.environ.get("AI_SEARCH_RELATIVE_SCORE_RATIO", "0.75")),
            reranker_model=os.environ.get("AI_RERANKER_MODEL", "Qwen/Qwen3-VL-Reranker-2B"),
            reranker_revision=os.environ.get("AI_RERANKER_REVISION", ""),
            rerank_min_image_score=float(os.environ.get("AI_RERANK_MIN_IMAGE_SCORE", "0.5")),
            rerank_min_text_score=float(os.environ.get("AI_RERANK_MIN_TEXT_SCORE", "0.5")),
            materials_queue=os.environ.get("AI_MATERIALS_QUEUE", "findie.api.materials"),
            materials_reply_queue=os.environ.get("AI_MATERIALS_REPLY_QUEUE", "findie.ai.materials.results"),
            image_search_enabled=image_search == "true",
            image_search_profile=os.environ.get("AI_IMAGE_SEARCH_PROFILE", "image-only-v1"),
            redaction_model=os.environ.get("AI_REDACTION_MODEL", "qwen3-vl:4b-instruct"),
            redaction_revision=os.environ.get("AI_REDACTION_REVISION", ""),
            **{f"{kind}_queue": os.environ.get(f"AI_{kind.upper()}_QUEUE", default)
               for kind, default in (("index", "findie.ai.commands"), ("result", "findie.api.results"),
                                     ("query", "findie.ai.query"), ("image", "findie.ai.image"))},
        )
