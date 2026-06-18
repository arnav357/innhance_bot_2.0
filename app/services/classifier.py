"""
Intent classification service.
Uses Claude Haiku 3.5 with tool_use to extract intent + booking slots
from a guest message. Falls back to GPT-4o-mini automatically via llm.py.

The tool_use approach gives us schema-validated output — no JSON parsing,
no crashes on malformed LLM output, no hallucinated field names.
"""

import logging
from app.core import llm
from app.models.schemas import ClassifyRequest, ClassifyResponse, BookingSlots

logger = logging.getLogger(__name__)

# ── Tool schema — the contract the LLM must follow ────────────────────────────
# Every possible intent is a separate tool so the LLM is forced to pick
# exactly one and fill only the relevant slot fields.

CLASSIFY_TOOLS = [
    {
        "name": "booking",
        "description": "Guest wants to make a new hotel room booking. Extract any slot values they have provided.",
        "input_schema": {
            "type": "object",
            "properties": {
                "room_type":   {"type": "string",  "description": "Room type mentioned e.g. 'deluxe', 'suite'"},
                "check_in":    {"type": "string",  "description": "Check-in date in YYYY-MM-DD format"},
                "check_out":   {"type": "string",  "description": "Check-out date in YYYY-MM-DD format"},
                "guest_count": {"type": "integer", "description": "Number of guests"},
                "guest_name":  {"type": "string",  "description": "Guest name if provided"},
                "guest_phone": {"type": "string",  "description": "Guest phone number if provided"},
                "confidence":  {"type": "number",  "description": "Your confidence 0.0–1.0 that this is the correct intent"},
            },
            "required": ["confidence"],
        },
    },
    {
        "name": "check_availability",
        "description": "Guest is asking whether specific dates or room types are available, without committing to book yet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "room_type":   {"type": "string"},
                "check_in":    {"type": "string"},
                "check_out":   {"type": "string"},
                "guest_count": {"type": "integer"},
                "confidence":  {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
    {
        "name": "hotel_question",
        "description": "Guest is asking a factual question about the hotel — policies, amenities, facilities, location, breakfast, parking, etc. This will be answered by RAG retrieval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
    {
        "name": "show_rooms",
        "description": "Guest wants to see room options, photos, types, or pricing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "room_type":  {"type": "string", "description": "Specific room type if mentioned"},
                "confidence": {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
    {
        "name": "existing_booking",
        "description": "Guest is asking about, modifying, or checking on a booking they have already made.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
    {
        "name": "payment",
        "description": "Guest is asking about payment, sending a payment screenshot, or asking for the UPI QR code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
    {
        "name": "human",
        "description": "Guest explicitly wants to speak with a human agent, receptionist, or hotel staff.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
    {
        "name": "greeting",
        "description": "Guest is saying hello, hi, starting the conversation, or sending a greeting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
    {
        "name": "cancel",
        "description": "Guest wants to cancel an existing booking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
    {
        "name": "chitchat",
        "description": "Off-topic conversation — jokes, weather, general chat not related to hotel booking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
    {
        "name": "unknown",
        "description": "Cannot determine the guest's intent from the message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
]


def _build_system_prompt(language: str) -> str:
    lang_note = {
        "hi":       "The guest is writing in Hindi (Devanagari script). Understand naturally.",
        "hinglish": "The guest is writing in Hinglish (Hindi words in Roman/Latin script). This is very common for Indian hotel guests. Understand naturally.",
        "en":       "The guest is writing in English.",
        "other":    "The guest may be writing in a non-English/Hindi language. Do your best.",
    }.get(language, "")

    return f"""You are an intent classification system for Innhance, an AI hotel booking assistant.

Your ONLY job is to call exactly ONE tool that matches the guest's intent and extract any slot values they have provided.

{lang_note}

Rules:
- Call exactly one tool. Never output free text.
- Extract only slots the guest has explicitly stated. Do not invent or assume slot values.
- Dates must be YYYY-MM-DD format. If the guest says "tomorrow" or a relative date, you may convert it to absolute date if the conversation context makes it clear, otherwise leave as null.
- If a guest message contains both a greeting AND a booking request, classify as "booking".
- Be generous with booking/availability classification — if a guest sounds like they want to stay, it's a booking or check_availability intent.
- Confidence should reflect how certain you are of the intent, not the slot completeness."""


async def classify_intent(req: ClassifyRequest) -> ClassifyResponse:
    """
    Classify a guest message into an intent with extracted slot values.

    The classifier is the first call in every message pipeline.
    It must be fast — we use Haiku 3.5 with prompt caching.
    """
    system = _build_system_prompt(req.language)

    # Build message list: history + current message
    messages = [
        {"role": m.role, "content": m.content}
        for m in req.history
    ]
    messages.append({"role": "user", "content": req.message})

    result = await llm.classify(
        messages=messages,
        tools=CLASSIFY_TOOLS,
        system=system,
        use_cache=True,
    )

    intent_name = result["tool"]
    tool_input  = result["input"]
    provider    = result.get("provider", "anthropic")

    # Build BookingSlots from whatever the LLM extracted
    slots = BookingSlots(
        room_type=tool_input.get("room_type"),
        check_in=tool_input.get("check_in"),
        check_out=tool_input.get("check_out"),
        guest_count=tool_input.get("guest_count"),
        guest_name=tool_input.get("guest_name"),
        guest_phone=tool_input.get("guest_phone"),
    )

    confidence = float(tool_input.get("confidence", 0.8))

    logger.info(
        "classify | venue=%s intent=%s confidence=%.2f provider=%s",
        req.venue_id, intent_name, confidence, provider,
    )

    return ClassifyResponse(
        intent=intent_name,
        slots=slots,
        confidence=confidence,
        provider=provider,
        raw_message=req.message,
    )
