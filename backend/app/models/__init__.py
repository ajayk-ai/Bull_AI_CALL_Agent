"""Importing this package registers every table on Base.metadata (needed by Alembic)."""

from app.models.audit import AuditLog
from app.models.calls import Call, CallEvent, CallQueueItem, Recording, Transcript
from app.models.campaigns import Campaign, CampaignApproval, CampaignContact, CampaignImport
from app.models.contacts import ConsentRecord, Contact, DoNotCall
from app.models.extraction import ExtractedResult, ExtractionFieldEvidence, FollowupTask
from app.models.integrations import IntegrationConfig, VoiceProviderAccount
from app.models.org import Department, User
from app.models.scripts import Script, ScriptVersion

__all__ = [
    "AuditLog",
    "Call",
    "CallEvent",
    "CallQueueItem",
    "Campaign",
    "CampaignApproval",
    "CampaignContact",
    "CampaignImport",
    "ConsentRecord",
    "Contact",
    "Department",
    "DoNotCall",
    "ExtractedResult",
    "ExtractionFieldEvidence",
    "FollowupTask",
    "IntegrationConfig",
    "Recording",
    "Script",
    "ScriptVersion",
    "Transcript",
    "User",
    "VoiceProviderAccount",
]
