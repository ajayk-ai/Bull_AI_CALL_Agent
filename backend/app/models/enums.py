"""Status and type values shared by models, schemas and services."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class ConsentType(StrEnum):
    CALL = "call"
    RECORDING = "recording"
    AI_PROCESSING = "ai_processing"


class ConsentStatus(StrEnum):
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"


class ScriptVersionStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    PUBLISHED = "published"
    RETIRED = "retired"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CampaignContactStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    RETRY_SCHEDULED = "retry_scheduled"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ImportStatus(StrEnum):
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class QueueStatus(StrEnum):
    WAITING = "waiting"
    DISPATCHED = "dispatched"
    CANCELLED = "cancelled"


class CallStatus(StrEnum):
    QUEUED = "queued"
    DIALING = "dialing"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class FollowupStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class ProviderKind(StrEnum):
    TELEPHONY = "telephony"
    SPEECH_TO_SPEECH = "speech_to_speech"
    ASR = "asr"
    TTS = "tts"
    LLM = "llm"
