"""The structured result of a call, extracted after it ends: a LangChain chain over a Gemini text model.

Input: the script's objective and result schema, the call's lines (e.g. PO lines), the answers recorded live
through the scenario graph, and the transcript. Output: JSON in the script's own schema, checked with
jsonschema. Model output, the validated result and any problems are stored separately (ExtractedResult), so a
person can review and correct a result without losing what the model said.

A result needs review when it fails the schema, the model is not confident, or the call ended before every
question was asked.
"""

import json
import logging
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.calls import Call, Transcript
from app.models.enums import ExtractionStatus
from app.models.extraction import ExtractedResult
from app.models.scripts import ScriptVersion

log = logging.getLogger(__name__)

REVIEW_BELOW_CONFIDENCE = 0.7

PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You turn a phone call into a structured record. Use only what the person on the call actually said. "
            "The recorded answers were captured during the call and are reliable; use the transcript for "
            "everything else and to check them. If something was not said, use null (or false where the schema "
            "needs a boolean) and lower your confidence. Never invent dates, numbers or reasons. Reply with one JSON "
            'object only: {{"result": <object matching the schema>, "summary": "<two sentences for the team>"}}.',
        ),
        (
            "human",
            "Purpose of the call:\n{objective}\n\nResult schema (JSON Schema):\n{schema}\n\n"
            "Lines discussed in the call:\n{lines}\n\nAnswers recorded during the call:\n{answers}\n\n"
            "How the call ended: {outcome}\n\nTranscript:\n{transcript}",
        ),
    ]
)


@cache
def get_extraction_llm() -> BaseChatModel | None:
    """The Gemini text model, or None when no API key is configured (extraction is then skipped)."""
    settings = get_settings()
    if not settings.gemini_api_key or not settings.gemini_api_key.get_secret_value():
        return None
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=settings.gemini_text_model,
        api_key=settings.gemini_api_key.get_secret_value(),
        temperature=0,
        response_mime_type="application/json",
        timeout=settings.extraction_timeout_seconds,
        max_retries=2,
    )


def _transcript_text(turns: list[dict[str, Any]]) -> str:
    return "\n".join(f"[{t.get('turn_id')}] {t.get('speaker')}: {t.get('text')}" for t in turns) or "(nothing said)"


def _validate(schema: dict[str, Any], result: Any) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(result)'}: {error.message}"
        for error in sorted(validator.iter_errors(result), key=lambda e: list(e.absolute_path))
    ][:50]


async def extract(session: AsyncSession, call_id) -> ExtractedResult | None:
    """Runs the extraction for one finished call and stores it. Returns None when there is nothing to extract."""
    llm = get_extraction_llm()
    call = await session.get(Call, call_id)
    transcript = await session.scalar(select(Transcript).where(Transcript.call_id == call_id))
    turns = transcript.turns if transcript else []
    if llm is None or call is None or not turns:
        return None
    version = await session.get(ScriptVersion, call.script_version_id)
    schema = version.extraction_schema or {}
    answers = call.answers or {}
    record = ExtractedResult(
        call_id=call.id, script_version_id=version.id, model=getattr(llm, "model", None) or type(llm).__name__
    )

    chain = PROMPT | llm | JsonOutputParser()
    try:
        output = await chain.ainvoke(
            {
                "objective": version.config.get("objective", ""),
                "schema": json.dumps(schema, indent=1),
                "lines": json.dumps((call.context or {}).get("items") or [], indent=1, default=str),
                "answers": json.dumps(
                    {"call": answers.get("answers", {}), "lines": answers.get("lines", [])}, indent=1, default=str
                ),
                "outcome": f"{call.outcome or 'unknown'} ({call.end_reason or 'unknown'})",
                "transcript": _transcript_text(turns),
            }
        )
    except Exception as exc:
        log.exception("Extraction failed for call %s", call.id)
        record.status = ExtractionStatus.NEEDS_REVIEW
        record.validation_errors = [f"extraction failed: {type(exc).__name__}: {str(exc)[:300]}"]
        session.add(record)
        await session.commit()
        return record

    output = output if isinstance(output, dict) else {"result": output}
    result = output.get("result", output)
    record.raw = output
    record.summary = str(output.get("summary") or "")[:2000] or None
    errors = _validate(schema, result) if schema else []
    record.validation_errors = errors
    confidence = result.get("confidence") if isinstance(result, dict) else None
    record.confidence = float(confidence) if isinstance(confidence, int | float) else None
    if not errors:
        record.validated = result
    incomplete = call.outcome == "completed" and not answers.get("complete", True)
    if incomplete:
        record.validation_errors = [*errors, "the call ended before every question was asked"]
    needs_review = errors or incomplete or record.confidence is None or record.confidence < REVIEW_BELOW_CONFIDENCE
    record.status = ExtractionStatus.NEEDS_REVIEW if needs_review else ExtractionStatus.VALIDATED
    session.add(record)
    await session.commit()
    return record
