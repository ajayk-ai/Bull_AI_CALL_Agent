"""The scenario controller: a LangGraph graph that runs the script's questions during a live call.

Gemini Live does the listening and speaking. Each time the caller answers a question, the agent calls the
record_answer tool; the graph checks the answer against the script (type, choices, ranges, "not before" dates),
stores it and works out what to ask next: the next question for this line, the first question for the next line,
the closing questions, or the read-back and close. The tool result tells the agent exactly that, so the order of
the call is decided here, deterministically, and not by the model.

Nothing is campaign-specific: questions, conditions, validation and the per-line ("items[]") questions all come
from the published script version.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

RECORD_ANSWER_TOOL = {
    "name": "record_answer",
    "description": (
        "Record the person's answer to one of the script's questions as soon as they give it. The result says "
        "whether the answer was accepted and what to say or ask next; follow it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question_id": {"type": "string", "description": "The question's id, shown in [brackets] in your plan."},
            "value": {
                "type": "string",
                "description": "The answer: yes or no; a date as YYYY-MM-DD; a number; one of the listed "
                "choices; or the person's words for a free-text question. Use 'unknown' if they do not know.",
            },
            "line": {
                "type": "integer",
                "description": "For questions about a specific line, its number in your list (1 for the first).",
            },
        },
        "required": ["question_id", "value"],
    },
}

UNKNOWN = "unknown"
_YES = {"yes", "y", "true", "haan", "ha", "aama", "aamaa", "ok", "sari", "confirmed"}
_NO = {"no", "n", "false", "illa", "illai", "nahi", "nahin", "not"}


class ScenarioState(TypedDict, total=False):
    """Everything the graph knows about the call so far. Kept on the controller between tool calls."""

    answers: dict[str, Any]  # call-level question id -> value
    line_answers: list[dict[str, Any]]  # one dict per line: question id -> value
    line: int  # 0-based index of the line being discussed
    pending: str | None  # question id expected next; None once everything is asked
    complete: bool
    # Input of one step:
    incoming: dict[str, Any] | None
    # Output of one step:
    accepted: bool
    problem: str | None
    next: str


def _is_line_question(q: dict[str, Any]) -> bool:
    return str(q.get("maps_to") or "").startswith("items[]")


def _parse(q: dict[str, Any], raw: Any, line_context: dict[str, Any]) -> tuple[Any, str | None]:
    """The stored value, or a problem to put to the caller."""
    text = str(raw).strip() if raw is not None else ""
    if text.lower() in (UNKNOWN, "unsure", "not sure", "don't know", "dont know"):
        return None, None  # recorded as not known; extraction marks it so
    kind = q.get("type", "text")
    if kind == "yes_no":
        word = text.lower().strip(".! ")
        if word in _YES:
            return True, None
        if word in _NO:
            return False, None
        return None, f"'{text}' is not a yes or no answer"
    if kind == "date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return None, "the date must be given as YYYY-MM-DD"
        try:
            value = date.fromisoformat(text)
        except ValueError:
            return None, f"{text} is not a real date"
        field = (q.get("validation") or {}).get("not_before_context_field")
        if field and line_context.get(field):
            try:
                floor = date.fromisoformat(str(line_context[field]))
            except ValueError:
                floor = None
            if floor and value < floor:
                return None, f"{value.isoformat()} is earlier than the {field.replace('_', ' ')} ({floor.isoformat()})"
        return value.isoformat(), None
    if kind == "number":
        try:
            value = float(text)
        except ValueError:
            return None, f"'{text}' is not a number"
        validation = q.get("validation") or {}
        if validation.get("min") is not None and value < validation["min"]:
            return None, f"the number must be at least {validation['min']}"
        if validation.get("max") is not None and value > validation["max"]:
            return None, f"the number must be at most {validation['max']}"
        return int(value) if value.is_integer() else value, None
    if kind == "choice":
        choices = {c.lower(): c for c in q.get("choices") or []}
        if text.lower() not in choices:
            return None, f"the answer must be one of: {', '.join(choices.values())}"
        return choices[text.lower()], None
    if not text:
        return None, "the answer is empty"
    return text[:1000], None


def _applies(q: dict[str, Any], answers: dict[str, Any]) -> bool:
    condition = q.get("condition")
    if not condition:
        return True
    return condition["question_id"] in answers and answers[condition["question_id"]] == condition["equals"]


class Scenario:
    """The script's questions in call order: opening call-level ones, then per line, then closing ones."""

    def __init__(self, config: dict[str, Any], items: list[dict[str, Any]]):
        self.config = config
        self.items = items
        questions = config.get("questions") or []
        self.by_id = {q["id"]: q for q in questions}
        line_qs = [q for q in questions if _is_line_question(q)]
        first_line_q = questions.index(line_qs[0]) if line_qs else len(questions)
        self.opening = [q for q in questions[:first_line_q] if not _is_line_question(q)]
        self.per_line = line_qs if items else []
        self.closing = [q for q in questions[first_line_q:] if not _is_line_question(q)]

    def initial_state(self) -> ScenarioState:
        state: ScenarioState = {
            "answers": {},
            "line_answers": [{} for _ in self.items],
            "line": 0,
            "pending": None,
            "complete": False,
            "incoming": None,
            "accepted": True,
            "problem": None,
            "next": "",
        }
        state.update(self._advance(state))
        return state

    # ---- the order of questions ----

    def _scope(self, q: dict[str, Any], state: ScenarioState, line: int) -> dict[str, Any]:
        """Answers a question's condition is checked against: the line's own answers for per-line questions."""
        if _is_line_question(q):
            return {**state["answers"], **state["line_answers"][line]}
        return state["answers"]

    def _next_question(self, state: ScenarioState) -> tuple[str | None, int]:
        for q in self.opening:
            if q["id"] not in state["answers"] and _applies(q, state["answers"]):
                return q["id"], state["line"]
        for line in range(state["line"], len(self.items)):
            for q in self.per_line:
                if q["id"] not in state["line_answers"][line] and _applies(q, self._scope(q, state, line)):
                    return q["id"], line
        for q in self.closing:
            if q["id"] not in state["answers"] and _applies(q, state["answers"]):
                return q["id"], len(self.items)
        return None, len(self.items)

    def _advance(self, state: ScenarioState) -> ScenarioState:
        pending, line = self._next_question(state)
        if pending is None:
            return {"pending": None, "line": line, "complete": True, "next": self._closing_instruction()}
        q = self.by_id[pending]
        return {"pending": pending, "line": line, "complete": False, "next": self._ask(q, line, state)}

    def _describe_line(self, line: int) -> str:
        item = self.items[line]
        labels = {f["key"]: f["label"] for f in self.config.get("context_fields") or []}
        return "; ".join(f"{labels.get(k, k)}: {v}" for k, v in item.items() if v not in (None, ""))

    def _ask(self, q: dict[str, Any], line: int, state: ScenarioState) -> str:
        prompt = q["prompt"]
        if _is_line_question(q):
            item = self.items[line]
            prompt = re.sub(r"\{context\.([a-z0-9_]+)\}", lambda m: str(item.get(m.group(1), "")), prompt)
            moved_on = line > 0 and not state["line_answers"][line]
            where = f"Now line {line + 1} of {len(self.items)} ({self._describe_line(line)}). " if moved_on else ""
            return f"{where}Ask [{q['id']}] for line {line + 1}: {prompt}"
        return f"Ask [{q['id']}]: {prompt}"

    def _closing_instruction(self) -> str:
        closing = self.config.get("closing") or {}
        steps = []
        if closing.get("confirm_before_close"):
            steps.append(
                "All questions are answered. Read back briefly what you recorded and ask the person to "
                "confirm or correct it (record any correction with record_answer)."
            )
        else:
            steps.append("All questions are answered.")
        steps.append(
            f'Then close with: "{closing.get("statement", "Thank you. Goodbye.")}" and call end_call '
            'with outcome "completed".'
        )
        return " ".join(steps)

    # ---- graph nodes ----

    def record(self, state: ScenarioState) -> ScenarioState:
        incoming = state.get("incoming") or {}
        qid = str(incoming.get("question_id") or "")
        q = self.by_id.get(qid)
        if q is None:
            return {"accepted": False, "problem": f"there is no question [{qid}]", "next": state["next"]}
        if _is_line_question(q):
            raw_line = incoming.get("line")
            try:
                line = int(raw_line) - 1 if raw_line is not None else state["line"]
            except TypeError, ValueError:
                line = state["line"]
            if not 0 <= line < len(self.items):
                return {"accepted": False, "problem": f"there is no line {raw_line}", "next": state["next"]}
            value, problem = _parse(q, incoming.get("value"), self.items[line])
            if problem:
                return {"accepted": False, "problem": problem, "next": f"Read it back and ask [{qid}] again."}
            line_answers = [dict(a) for a in state["line_answers"]]
            line_answers[line][qid] = value
            # A changed answer can make later answers on that line irrelevant (e.g. now on time: no delay reason).
            for other in self.per_line:
                if other["id"] in line_answers[line] and not _applies(
                    other, {**state["answers"], **line_answers[line]}
                ):
                    del line_answers[line][other["id"]]
            return {"accepted": True, "problem": None, "line_answers": line_answers, "line": min(state["line"], line)}
        value, problem = _parse(q, incoming.get("value"), {})
        if problem:
            return {"accepted": False, "problem": problem, "next": f"Read it back and ask [{qid}] again."}
        answers = {**state["answers"], qid: value}
        for other in self.opening + self.closing:
            if other["id"] in answers and not _applies(other, answers):
                del answers[other["id"]]
        return {"accepted": True, "problem": None, "answers": answers}

    def advance(self, state: ScenarioState) -> ScenarioState:
        return self._advance(state)


def build_graph(scenario: Scenario):
    graph = StateGraph(ScenarioState)
    graph.add_node("record", scenario.record)
    graph.add_node("advance", scenario.advance)
    graph.add_edge(START, "record")
    graph.add_conditional_edges("record", lambda s: "advance" if s["accepted"] else END, ["advance", END])
    graph.add_edge("advance", END)
    return graph.compile()


class ScenarioController:
    """One per call. Holds the graph's state between record_answer calls."""

    def __init__(self, config: dict[str, Any], items: list[dict[str, Any]]):
        self.scenario = Scenario(config, items)
        self.graph = build_graph(self.scenario)
        self.state = self.scenario.initial_state()
        self.log: list[dict[str, Any]] = []

    def first_instruction(self) -> str:
        return self.state["next"]

    async def record(self, args: dict[str, Any]) -> dict[str, Any]:
        incoming = {k: args.get(k) for k in ("question_id", "value", "line")}
        out = await self.graph.ainvoke({**self.state, "incoming": incoming})
        self.state = {**out, "incoming": None}
        self.log.append({**incoming, "accepted": out["accepted"], "problem": out.get("problem")})
        if not out["accepted"]:
            return {"accepted": False, "problem": out["problem"], "next": out["next"]}
        return {"accepted": True, "next": out["next"]}

    def snapshot(self) -> dict[str, Any]:
        """Stored on the call: what was recorded, per line, and whether every applicable question was asked."""
        return {
            "answers": self.state["answers"],
            "lines": [
                {"line": i + 1, "context": item, "answers": self.state["line_answers"][i]}
                for i, item in enumerate(self.scenario.items)
            ],
            "complete": self.state["complete"],
            "pending": self.state["pending"],
            "log": self.log,
        }
