"""Turns a published script version, the contact and the campaign data into the agent's instructions.

Nothing here is campaign-specific: questions, rules, languages and fields all come from the script version.
"""

import re
from typing import Any

from app.voice.scenario import RECORD_ANSWER_TOOL

LANGUAGE_NAMES = {
    "ta-IN": "Tamil",
    "en-IN": "English (India)",
    "hi-IN": "Hindi",
    "te-IN": "Telugu",
    "kn-IN": "Kannada",
    "ml-IN": "Malayalam",
    "mr-IN": "Marathi",
    "bn-IN": "Bengali",
}

# The only action the agent can take. It cannot place calls or change records: the call controller decides what
# happens after the call, using the outcome reported here.
OUTCOMES = ["completed", "wrong_person", "callback_requested", "opted_out", "refused", "unreachable", "other"]
END_CALL_TOOL = {
    "name": "end_call",
    "description": (
        "End the phone call. Call this only after you have finished speaking your closing words; the line is "
        "hung up as soon as your last words have played."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "enum": OUTCOMES, "description": "Why the call is ending."},
            "note": {"type": "string", "description": "One short sentence for the record."},
        },
        "required": ["outcome"],
    },
}
# record_answer feeds the scenario graph (app/voice/scenario.py), which decides what to ask next.
TOOLS = [END_CALL_TOOL, RECORD_ANSWER_TOOL]

GREETING_TRIGGER = "The call has just been answered. Start now with your introduction."
SILENCE_NUDGE = "The caller has been silent for a while. Check politely whether they can still hear you."
WRAP_UP_NUDGE = (
    "The call has reached its time limit. Thank the caller, say the closing statement now, then call end_call "
    "with outcome 'other' and note 'time limit'."
)

_PLACEHOLDER = re.compile(r"\{(contact|agent)\.([a-z0-9_]+)\}")


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def _render(text: str, values: dict[str, dict[str, str]]) -> str:
    """Fills {contact.x} and {agent.x}. {context.x} stays: it names a field of the line being discussed."""
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)].get(m.group(2)) or "(not known)", text)


def _question_line(q: dict[str, Any], render) -> str:
    parts = [f"[{q['id']}] {render(q['prompt'])} (answer: {q['type'].replace('_', '/')}"]
    if q.get("choices"):
        parts.append(f"; one of: {', '.join(q['choices'])}")
    if not q.get("required", True):
        parts.append("; optional")
    parts.append(")")
    condition = q.get("condition")
    if condition:
        equals = condition["equals"]
        shown = {True: "yes", False: "no"}.get(equals, equals) if isinstance(equals, bool) else equals
        parts.append(f" Ask only if the answer to [{condition['question_id']}] was {shown}.")
    validation = q.get("validation") or {}
    if validation.get("not_before_context_field"):
        parts.append(f" The date must not be earlier than {{context.{validation['not_before_context_field']}}}.")
    if validation.get("min") is not None or validation.get("max") is not None:
        parts.append(f" Must be between {validation.get('min', '-')} and {validation.get('max', '-')}.")
    return "".join(parts)


def build_instructions(
    config: dict[str, Any],
    contact: dict[str, str | None],
    items: list[dict[str, Any]],
    language: str | None,
) -> str:
    agent = config["agent"]
    values = {
        "contact": {"name": contact.get("name") or "", "company": contact.get("company") or ""},
        "agent": {"name": agent["name"], "organisation": agent["organisation"]},
    }

    def render(text: str) -> str:
        return _render(text, values)

    languages = config["languages"]
    start = language or languages["default"]
    allowed = ", ".join(language_name(c) for c in languages["allowed"])
    fields = config.get("context_fields") or []
    labels = {f["key"]: f["label"] for f in fields}

    sections = [render(config["system_instructions"]), ""]
    sections += [
        "## Who you are",
        f"You are {agent['name']} from {agent['organisation']}, an automated calling assistant.",
        "",
        "## Purpose of the call",
        render(config["objective"]),
        "",
        "## The person you are calling",
        f"Name: {values['contact']['name'] or '(not known)'}",
        f"Company: {values['contact']['company'] or '(not known)'}",
    ]
    if items:
        sections += ["", "## Lines to cover in this call (go through them one at a time)"]
        for number, item in enumerate(items, start=1):
            described = "; ".join(f"{labels.get(k, k)} ({k}): {v}" for k, v in item.items() if v not in (None, ""))
            sections.append(f"{number}. {described}")
        sections.append("In the questions, {context.<field>} means that field of the line being discussed.")

    steps = [
        f'Open with: "{render(agent["introduction"])}"',
        "Ask these questions in order. Skip a question whose condition is not met. As soon as the person "
        "answers, call record_answer with the question's id (and the line number for per-line questions). Its "
        "result says whether the answer was accepted and what to ask next: follow it.",
    ]
    sub: dict[int, list[str]] = {1: [_question_line(q, render) for q in config["questions"]]}
    if config.get("business_rules"):
        steps.append("Follow these rules:")
        sub[len(steps) - 1] = [render(r) for r in config["business_rules"]]
    closing = config["closing"]
    if closing.get("confirm_before_close"):
        steps.append("Before closing, read back what you recorded and ask the person to confirm or correct it.")
    steps.append(f'Close with: "{render(closing["statement"])}" Then call end_call with outcome "completed".')
    sections += ["", "## How to run the call"]
    for index, step in enumerate(steps):
        sections.append(f"{index + 1}. {step}")
        sections += [f"   - {line}" for line in sub.get(index, [])]

    sections += [
        "",
        "## Ending the call early",
        "- Wrong person, or the person cannot talk: ask for the right person or a better time, close politely, "
        'then end_call with outcome "wrong_person" or "callback_requested".',
        "- The person asks not to be called again: acknowledge it, apologise for the disturbance, then end_call "
        'with outcome "opted_out".',
        '- The person refuses to continue: thank them, then end_call with outcome "refused".',
    ]
    escalation = config.get("escalation") or {}
    if escalation.get("triggers"):
        message = render(escalation.get("message") or "A member of our team will call you back.")
        sections += [f'- In these situations say "{message}" then end_call with outcome "callback_requested":']
        sections += [f"  - {render(t)}" for t in escalation["triggers"]]

    limits = config.get("limits") or {}
    sections += [
        "",
        "## Language and style",
        f"Start in {language_name(start)}. Languages you may use: {allowed}.",
        "If the person speaks another of these languages, or mixes them, reply in the language they use."
        if languages.get("allow_switching", True)
        else f"Stay in {language_name(start)} even if the person switches language.",
        "Speak naturally and briefly: one question at a time, short sentences, no lists or symbols.",
        f"Keep the whole call under {max(1, round(limits.get('max_call_seconds', 300) / 60))} minutes.",
        "Never invent answers, dates or commitments. Never say you are a human.",
    ]
    return "\n".join(sections)
