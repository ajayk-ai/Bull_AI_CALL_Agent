"""The LangGraph scenario controller, run against the real SCM script with two PO lines."""

import copy

from app.seeds import scm_delivery
from app.voice.scenario import ScenarioController

ITEMS = [
    {"po_number": "450001", "material_description": "Hydraulic hose", "original_delivery_date": "2026-11-20"},
    {"po_number": "450002", "material_description": "Seal kit", "original_delivery_date": "2026-11-25"},
]


def controller() -> ScenarioController:
    return ScenarioController(copy.deepcopy(scm_delivery.CONFIG), copy.deepcopy(ITEMS))


async def test_runs_the_script_in_order_line_by_line():
    c = controller()
    assert c.first_instruction().startswith("Ask [identity_confirmed]")

    step = await c.record({"question_id": "identity_confirmed", "value": "yes"})
    assert step["accepted"] and "[po_confirmed] for line 1" in step["next"] and "450001" in step["next"]

    await c.record({"question_id": "po_confirmed", "value": "yes", "line": 1})
    step = await c.record({"question_id": "on_time", "value": "no", "line": 1})
    assert "[delay_reason] for line 1" in step["next"]  # asked only because the line is late
    await c.record({"question_id": "delay_reason", "value": "Raw material shortage", "line": 1})

    # A revised date earlier than the original is refused, and the agent is told to ask again.
    refused = await c.record({"question_id": "revised_date", "value": "2026-11-10", "line": 1})
    assert refused == {
        "accepted": False,
        "problem": "2026-11-10 is earlier than the original delivery date (2026-11-20)",
        "next": "Read it back and ask [revised_date] again.",
    }
    step = await c.record({"question_id": "revised_date", "value": "2026-12-05", "line": 1})
    assert step["next"].startswith("Now line 2 of 2") and "Seal kit" in step["next"]

    await c.record({"question_id": "po_confirmed", "value": "yes", "line": 2})
    step = await c.record({"question_id": "on_time", "value": "yes", "line": 2})
    assert "[support_required]" in step["next"]  # on time: no delay questions for line 2

    step = await c.record({"question_id": "support_required", "value": "no"})
    assert step["next"].startswith("All questions are answered. Read back") and "end_call" in step["next"]

    snap = c.snapshot()
    assert snap["complete"] is True and snap["pending"] is None
    assert snap["answers"] == {"identity_confirmed": True, "support_required": False}
    assert snap["lines"][0]["answers"] == {
        "po_confirmed": True,
        "on_time": False,
        "delay_reason": "Raw material shortage",
        "revised_date": "2026-12-05",
    }
    assert snap["lines"][1]["answers"] == {"po_confirmed": True, "on_time": True}
    assert [entry["accepted"] for entry in snap["log"]].count(False) == 1


async def test_bad_answers_and_corrections():
    c = controller()
    unclear = await c.record({"question_id": "identity_confirmed", "value": "maybe later"})
    assert not unclear["accepted"] and "not a yes or no" in unclear["problem"]
    assert not (await c.record({"question_id": "no_such_question", "value": "yes"}))["accepted"]
    assert not (await c.record({"question_id": "on_time", "value": "yes", "line": 7}))["accepted"]
    assert not (await c.record({"question_id": "revised_date", "value": "5th December", "line": 1}))["accepted"]

    await c.record({"question_id": "identity_confirmed", "value": "Yes"})
    await c.record({"question_id": "po_confirmed", "value": "yes", "line": 1})
    await c.record({"question_id": "on_time", "value": "no", "line": 1})
    await c.record({"question_id": "delay_reason", "value": "Transport strike", "line": 1})
    # The supplier corrects themselves: it will be on time after all. The delay answer no longer applies.
    step = await c.record({"question_id": "on_time", "value": "yes", "line": 1})
    assert c.snapshot()["lines"][0]["answers"] == {"po_confirmed": True, "on_time": True}
    assert step["next"].startswith("Now line 2 of 2")


async def test_unknown_answers_and_no_lines():
    c = ScenarioController(copy.deepcopy(scm_delivery.CONFIG), [])
    await c.record({"question_id": "identity_confirmed", "value": "yes"})
    # Without lines the per-line questions are skipped; "unknown" is accepted and stored as not known.
    step = await c.record({"question_id": "support_required", "value": "unknown"})
    assert step["accepted"] and c.snapshot()["answers"]["support_required"] is None
    assert c.snapshot()["complete"] is True
