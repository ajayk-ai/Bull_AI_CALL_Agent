"""SCM - Supplier Delivery Confirmation: the first campaign script (brief, Section 7).

Loaded as a draft with `python -m app.cli seed-scm-script --department SCM`. It still needs approval before a
campaign can use it. The voice name is the one the HR Absentee agent uses on this server; change it in the
script builder if SCM prefers another.

One call covers all of a supplier's open PO lines in the campaign, so the extraction result is per item.
"""

NAME = "SCM - Supplier Delivery Confirmation"
DESCRIPTION = "Confirms delivery dates for open purchase order lines and records delays, reasons and support needs."

CONFIG = {
    "objective": (
        "Confirm whether each open purchase order line listed for this supplier will be delivered on its original "
        "delivery date. For any delayed line, record the reason and the revised delivery date. Record whether the "
        "supplier needs support from Bull Machines."
    ),
    "agent": {
        "name": "Bull Machines calling assistant",
        "organisation": "Bull Machines",
        "introduction": (
            "Hello, this is the Bull Machines automated calling assistant, calling from the Supply Chain team "
            "about open purchase orders. Am I speaking with {contact.name} from {contact.company}?"
        ),
    },
    "system_instructions": (
        "You are an automated calling assistant for Bull Machines Pvt Ltd, a construction equipment manufacturer "
        "in Coimbatore. You are calling a supplier about purchase order delivery dates. Say clearly at the start "
        "that you are an automated assistant. Be polite, brief and professional. Speak in the supplier's language "
        "and switch if they switch; Tamil-English mixing is normal. Read PO numbers digit by digit and say dates "
        "with the day and month name. Go through the purchase order lines one at a time. Only record what the "
        "supplier actually says; never assume or invent a date or reason. If the supplier is unsure, record that "
        "they are unsure. Do not negotiate prices, quantities or payment terms, and do not make commitments on "
        "behalf of Bull Machines."
    ),
    "languages": {
        "default": "ta-IN",
        "allowed": ["ta-IN", "en-IN", "hi-IN"],
        "auto_detect": True,
        "allow_switching": True,
    },
    "voice": {"provider": "gemini", "voice_name": "Sulafat"},
    "context_fields": [
        {"key": "po_number", "label": "PO Number", "type": "string", "required": True},
        {"key": "material_description", "label": "Material Description", "type": "string", "required": True},
        {"key": "original_delivery_date", "label": "Original Delivery Date", "type": "date", "required": True},
    ],
    "questions": [
        {
            "id": "identity_confirmed",
            "prompt": "Confirm you are speaking with {contact.name} from {contact.company}, or someone who can answer "
            "about their deliveries.",
            "type": "yes_no",
            "maps_to": "supplier_confirmed",
        },
        {
            "id": "po_confirmed",
            "prompt": "For each line, read PO {context.po_number} for {context.material_description}, due on "
            "{context.original_delivery_date}, and ask the supplier to confirm they have this order.",
            "type": "yes_no",
            "maps_to": "items[].po_confirmed",
        },
        {
            "id": "on_time",
            "prompt": "Will this material be delivered on or before {context.original_delivery_date}?",
            "type": "yes_no",
            "maps_to": "items[].delivery_status",
        },
        {
            "id": "delay_reason",
            "prompt": "What is the reason for the delay?",
            "type": "text",
            "condition": {"question_id": "on_time", "equals": False},
            "maps_to": "items[].delay_reason",
        },
        {
            "id": "revised_date",
            "prompt": "What is the revised delivery date?",
            "type": "date",
            "condition": {"question_id": "on_time", "equals": False},
            "validation": {"not_before_context_field": "original_delivery_date"},
            "maps_to": "items[].revised_delivery_date",
        },
        {
            "id": "support_required",
            "prompt": "Do you need any support from Bull Machines to complete these deliveries?",
            "type": "yes_no",
            "maps_to": "support_required",
        },
        {
            "id": "support_details",
            "prompt": "What support do you need?",
            "type": "text",
            "condition": {"question_id": "support_required", "equals": True},
            "maps_to": "support_details",
        },
    ],
    "business_rules": [
        "Ask about every PO line in the call data before closing.",
        "A revised delivery date must not be earlier than the original delivery date; if the supplier gives one, "
        "read it back and ask again.",
        "If the supplier says the material is already delivered, record it as already delivered and do not ask for "
        "a revised date.",
        "If the person is not the right contact, ask for the right person's name and a good time to call, then close.",
        "If the supplier asks to stop receiving these calls, acknowledge it, record the opt-out and close politely.",
    ],
    "limits": {"max_call_seconds": 300, "silence_timeout_seconds": 8, "max_silence_prompts": 2, "max_turns": 40},
    "closing": {
        "confirm_before_close": True,
        "statement": "Thank you for confirming. The Bull Machines Supply Chain team will follow up if needed. "
        "Have a good day.",
    },
    "escalation": {
        "human_transfer_enabled": False,
        "triggers": [
            "The supplier asks to speak to a person",
            "The supplier raises a quality complaint or a payment dispute",
            "The supplier is upset or the conversation cannot continue",
        ],
        "message": "I will ask a member of the Bull Machines Supply Chain team to call you back.",
    },
}

EXTRACTION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["supplier_confirmed", "items", "support_required", "needs_followup", "confidence"],
    "properties": {
        "supplier_name": {"type": ["string", "null"]},
        "supplier_confirmed": {"type": "boolean", "description": "The right supplier contact was reached"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["po_number", "delivery_status"],
                "properties": {
                    "po_number": {"type": "string"},
                    "po_confirmed": {"type": ["boolean", "null"]},
                    "delivery_status": {
                        "type": "string",
                        "enum": ["on_time", "delayed", "already_delivered", "unknown"],
                    },
                    "delay_reason": {"type": ["string", "null"]},
                    "original_delivery_date": {"type": ["string", "null"], "format": "date"},
                    "revised_delivery_date": {"type": ["string", "null"], "format": "date"},
                },
            },
        },
        "support_required": {"type": "boolean"},
        "support_details": {"type": ["string", "null"]},
        "opted_out": {"type": "boolean", "description": "The supplier asked not to receive these calls"},
        "needs_followup": {"type": "boolean"},
        "followup_reason": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}
