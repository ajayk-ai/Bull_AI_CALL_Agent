"""Script builder configuration.

A script version's `config` is validated against ScriptConfig and its `extraction_schema` must be a JSON Schema
(draft 2020-12) describing an object. Prompts may reference per-call data with placeholders:
    {contact.name}  {contact.company}  {agent.name}  {context.<field key>}
"""

import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.core.config import get_settings
from app.models.enums import ScriptVersionStatus
from app.schemas.common import LanguageCode, Name, ORMModel

Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\.([a-z0-9_]+)\}")
_CONTACT_FIELDS = {"name", "company"}
_AGENT_FIELDS = {"name", "organisation"}


class FieldType(StrEnum):
    STRING = "string"
    NUMBER = "number"
    DATE = "date"


class QuestionType(StrEnum):
    YES_NO = "yes_no"
    TEXT = "text"
    DATE = "date"
    NUMBER = "number"
    CHOICE = "choice"


class AgentIdentity(BaseModel):
    name: ShortText
    organisation: ShortText = "Bull Machines"
    introduction: Text


class LanguageConfig(BaseModel):
    default: LanguageCode
    allowed: list[LanguageCode] = Field(min_length=1)
    auto_detect: bool = True
    allow_switching: bool = True

    @model_validator(mode="after")
    def _check(self) -> Self:
        supported = set(get_settings().supported_languages)
        unsupported = [code for code in self.allowed if code not in supported]
        if unsupported:
            raise ValueError(f"unsupported languages {unsupported}; supported: {sorted(supported)}")
        if self.default not in self.allowed:
            raise ValueError("default language must be one of the allowed languages")
        if len(set(self.allowed)) != len(self.allowed):
            raise ValueError("allowed languages contain duplicates")
        return self


class VoiceConfig(BaseModel):
    provider: Annotated[str, StringConstraints(min_length=1, max_length=32)] = "gemini"
    voice_name: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class ContextField(BaseModel):
    """Per-contact data a campaign supplies for each call, e.g. PO number."""

    key: Key
    label: ShortText
    type: FieldType = FieldType.STRING
    required: bool = True


class Condition(BaseModel):
    """Ask the question only when an earlier question's answer equals `equals`."""

    question_id: Key
    equals: str | bool | int | float


class AnswerValidation(BaseModel):
    min: float | None = None
    max: float | None = None
    pattern: Annotated[str, StringConstraints(max_length=200)] | None = None
    # For date answers: must not be earlier than this context field's date, e.g. "original_delivery_date".
    not_before_context_field: Key | None = None

    @field_validator("pattern")
    @classmethod
    def _regex(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"invalid regular expression: {exc}")
        return value


class Question(BaseModel):
    id: Key
    prompt: Text
    type: QuestionType
    required: bool = True
    choices: list[ShortText] | None = None
    condition: Condition | None = None
    validation: AnswerValidation | None = None
    # Field in the extraction schema the answer feeds, e.g. "items[].revised_delivery_date".
    maps_to: Annotated[str, StringConstraints(max_length=200)] | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.type == QuestionType.CHOICE and not self.choices:
            raise ValueError(f"question {self.id}: choice questions need choices")
        if self.type != QuestionType.CHOICE and self.choices:
            raise ValueError(f"question {self.id}: only choice questions take choices")
        return self


class CallLimits(BaseModel):
    max_call_seconds: int = Field(300, ge=30, le=1800)
    silence_timeout_seconds: int = Field(8, ge=2, le=60)
    max_silence_prompts: int = Field(2, ge=0, le=5)
    max_turns: int = Field(40, ge=4, le=200)


class Closing(BaseModel):
    confirm_before_close: bool = True
    statement: Text


class Escalation(BaseModel):
    human_transfer_enabled: bool = False
    # Situations in which the agent offers a human callback or transfer, in plain language.
    triggers: list[ShortText] = Field(default_factory=list)
    message: Text | None = None


class ScriptConfig(BaseModel):
    objective: Text
    agent: AgentIdentity
    system_instructions: Text
    languages: LanguageConfig
    voice: VoiceConfig
    context_fields: list[ContextField] = Field(default_factory=list)
    questions: list[Question] = Field(min_length=1)
    business_rules: list[ShortText] = Field(default_factory=list)
    limits: CallLimits = Field(default_factory=CallLimits)
    closing: Closing
    escalation: Escalation = Field(default_factory=Escalation)

    @model_validator(mode="after")
    def _cross_checks(self) -> Self:
        context_keys = [f.key for f in self.context_fields]
        if len(set(context_keys)) != len(context_keys):
            raise ValueError("context field keys must be unique")
        seen: dict[str, Question] = {}
        for question in self.questions:
            if question.id in seen:
                raise ValueError(f"question id {question.id} is used twice")
            if question.condition:
                parent = seen.get(question.condition.question_id)
                if parent is None:
                    raise ValueError(
                        f"question {question.id}: condition must refer to an earlier question, "
                        f"not {question.condition.question_id!r}"
                    )
                if parent.type == QuestionType.CHOICE and question.condition.equals not in (parent.choices or []):
                    raise ValueError(
                        f"question {question.id}: {question.condition.equals!r} is not a choice of {parent.id}"
                    )
            validation = question.validation
            if validation and validation.not_before_context_field:
                if question.type != QuestionType.DATE:
                    raise ValueError(f"question {question.id}: not_before_context_field applies to date questions")
                if validation.not_before_context_field not in context_keys:
                    raise ValueError(
                        f"question {question.id}: unknown context field {validation.not_before_context_field}"
                    )
            seen[question.id] = question

        texts = [self.agent.introduction, self.system_instructions, self.closing.statement]
        texts += [q.prompt for q in self.questions] + ([self.escalation.message] if self.escalation.message else [])
        allowed = {"contact": _CONTACT_FIELDS, "agent": _AGENT_FIELDS, "context": set(context_keys)}
        for text in texts:
            for scope, name in _PLACEHOLDER.findall(text):
                if name not in allowed.get(scope, set()):
                    raise ValueError(f"unknown placeholder {{{scope}.{name}}}")
        return self


def check_extraction_schema(schema: dict[str, Any]) -> dict[str, Any]:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"extraction_schema is not a valid JSON Schema: {exc.message}")
    if schema.get("type") != "object" or not schema.get("properties"):
        raise ValueError("extraction_schema must describe an object with properties")
    return schema


class ScriptVersionBody(BaseModel):
    config: ScriptConfig
    extraction_schema: dict[str, Any]

    @field_validator("extraction_schema")
    @classmethod
    def _schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return check_extraction_schema(value)


class ScriptCreate(ScriptVersionBody):
    department_id: uuid.UUID | None = None
    name: Name
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ScriptUpdate(BaseModel):
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    is_archived: bool | None = None


class ReviewDecision(BaseModel):
    comments: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ScriptVersionOut(ORMModel):
    id: uuid.UUID
    script_id: uuid.UUID
    version_no: int
    status: ScriptVersionStatus
    config: dict
    extraction_schema: dict
    created_by_id: uuid.UUID | None
    approved_by_id: uuid.UUID | None
    approved_at: datetime | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScriptVersionSummary(ORMModel):
    id: uuid.UUID
    version_no: int
    status: ScriptVersionStatus
    created_by_id: uuid.UUID | None
    published_at: datetime | None
    created_at: datetime


class ScriptOut(ORMModel):
    id: uuid.UUID
    department_id: uuid.UUID
    name: str
    description: str | None
    is_archived: bool
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    versions: list[ScriptVersionSummary] = []
