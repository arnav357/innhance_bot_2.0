"""
Reply generation service.

Receives the classify result + current booking session state from Node.js.
Decides what to do next and generates the reply text.

This service is intentionally STATELESS — all session state (booking slots,
conversation history) is owned by Node/MongoDB and passed in on every call.

Flow (called after /classify):
  Node calls /classify → gets intent + slots
  Node merges new slots into its bookingFlow.data
  Node calls /reply with merged state + classify result
  /reply decides: ask_slot | rag_answer | booking_complete | passthrough
  Node sends reply_text to WhatsApp, persists session_data to MongoDB

Slot collection order (mirrors V1 bookEngine.js getMissing exactly):
  roomType → planName (only if room has multiple plans) → checkIn →
  checkOut → roomsCount → guests → guest_name

The planName step is skipped when the hotel has only one plan per room
(Node passes room_has_multiple_plans=True to trigger it).
"""

import logging
from typing import Optional

from app.core import llm
from app.models.schemas import (
    ReplyRequest,
    ReplyResponse,
    BookingSessionData,
    RetrievedContext,
)

logger = logging.getLogger(__name__)


# ── Slot question templates ────────────────────────────────────────────────────
# Mirrors V1 webhook.js handleSmartBooking() ask messages exactly so the
# guest experience doesn't change during V1→V2 transition.

_SLOT_QUESTIONS: dict[str, dict[str, str]] = {
    "room_type": {
        "en":       "Which type of room would you like? 😊",
        "hi":       "आप कौन सा कमरा लेना चाहते हैं? 😊",
        "hinglish": "Aap kaun sa room lena chahte hain? 😊",
    },
    "plan_name": {
        "en":       "Which meal plan would you prefer? 😊",
        "hi":       "आप कौन सा मील प्लान लेना चाहते हैं? 😊",
        "hinglish": "Aap kaun sa meal plan lena chahenge? 😊",
    },
    "check_in": {
        "en":       "📅 What is your check-in date? Please use DD/MM/YYYY format — for example 31/12/2026 😊",
        "hi":       "📅 आपकी चेक-इन तारीख क्या है? कृपया DD/MM/YYYY फॉर्मेट में बताएं 😊",
        "hinglish": "📅 Aapka check-in date kya hai? DD/MM/YYYY format mein batayein — jaise 31/12/2026 😊",
    },
    "check_out": {
        "en":       "📅 What is your check-out date? Please use DD/MM/YYYY format — for example 31/12/2026 😊",
        "hi":       "📅 आपकी चेक-आउट तारीख क्या है? कृपया DD/MM/YYYY फॉर्मेट में बताएं 😊",
        "hinglish": "📅 Aapka check-out date kya hai? DD/MM/YYYY format mein batayein — jaise 31/12/2026 😊",
    },
    "rooms_count": {
        "en":       "🏨 How many rooms would you like? 😊",
        "hi":       "🏨 आपको कितने कमरे चाहिए? 😊",
        "hinglish": "🏨 Aapko kitne rooms chahiye? 😊",
    },
    "guests": {
        "en":       (
            "👥 How many guests will be staying? 😊\n\n"
            "You can reply like:\n• 2\n• 2 adults\n• 2 adults 1 child\n• 4 adults 2 kids"
        ),
        "hi":       "👥 कितने मेहमान रुकेंगे? 😊",
        "hinglish": (
            "👥 Kitne guests rahenge? 😊\n\n"
            "Aap reply kar sakte hain:\n• 2\n• 2 adults\n• 2 adults 1 child"
        ),
    },
    "guest_name": {
        "en":       "😊 May I know your full name?",
        "hi":       "😊 क्या मैं आपका पूरा नाम जान सकती हूँ?",
        "hinglish": "😊 Aapka poora naam bata sakte hain?",
    },
}

# Slot collection order — must match V1 getMissing() in bookEngine.js
_SLOT_ORDER = [
    "room_type",
    "plan_name",    # only checked when room_has_multiple_plans=True
    "check_in",
    "check_out",
    "rooms_count",
    "guests",
    "guest_name",
]


def get_missing_slot(
    session: BookingSessionData,
    room_has_multiple_plans: bool = False,
) -> Optional[str]:
    """
    Return the next slot that needs to be collected, or None if all complete.

    Mirrors V1 bookEngine.js getMissing() exactly, including the planName
    conditional and slot order.
    """
    if not session.room_type:
        return "room_type"
    if room_has_multiple_plans and not session.plan_name:
        return "plan_name"
    if not session.check_in:
        return "check_in"
    if not session.check_out:
        return "check_out"
    if not session.rooms_count:
        return "rooms_count"
    # guests = total; accept either guests or adultsCount as proof it was collected
    total_guests = session.guests or (
        (session.adults_count or 0) + (session.children_count or 0)
    )
    if not total_guests:
        return "guests"
    if not session.guest_name:
        return "guest_name"
    return None


def _slot_question(slot: str, language: str) -> str:
    """Return the localised question for a slot."""
    lang_key = language if language in ("hi", "hinglish") else "en"
    return _SLOT_QUESTIONS[slot][lang_key]


# ── System prompt builders ─────────────────────────────────────────────────────

def _booking_system_prompt(language: str, hotel_name: str) -> str:
    lang_note = {
        "hi":       "Reply in Hindi (Devanagari script).",
        "hinglish": "Reply in Hinglish (Hindi words in Roman/Latin script). This is natural for Indian guests.",
        "en":       "Reply in English.",
    }.get(language, "Reply in English.")

    return f"""You are Inna, the AI receptionist for {hotel_name}.
You are speaking TO the guest via WhatsApp. Every message you write is FROM you TO them.

{lang_note}

Rules:
- Be warm, friendly, and concise — max 3-4 lines.
- Use emojis naturally but not excessively.
- NEVER claim a booking is confirmed unless explicitly told so.
- NEVER make up room prices, availability, or policies.
- NEVER produce a reply that sounds like the guest is speaking."""


def _rag_system_prompt(language: str, hotel_name: str, context_chunks: list[str]) -> str:
    lang_note = {
        "hi":       "Reply in Hindi (Devanagari script).",
        "hinglish": "Reply in Hinglish (Hindi words in Roman/Latin script).",
        "en":       "Reply in English.",
    }.get(language, "Reply in English.")

    context = "\n\n---\n\n".join(context_chunks) if context_chunks else ""

    return f"""You are Inna, the AI receptionist for {hotel_name}.
You are speaking TO the guest via WhatsApp.

{lang_note}

HOTEL KNOWLEDGE (answer ONLY from this — do not guess):
{context if context else "No specific information available for this question."}

Rules:
- Answer the guest's question directly and warmly.
- If the answer is not in the hotel knowledge above, say:
  "I'm not able to confirm that right now — please contact the hotel directly 😊"
- Be concise — max 3-4 lines.
- After answering, gently ask if they'd like to continue with a booking.
- NEVER make up facts not present in the hotel knowledge above.
- NEVER claim a booking is confirmed unless explicitly told so."""


# ── Greeting + chitchat ────────────────────────────────────────────────────────

_GREETING_REPLIES = {
    "en":       "Hello! 👋 Welcome to {hotel_name}. I'm Inna, your AI receptionist. How can I help you today? 😊",
    "hi":       "नमस्ते! 👋 {hotel_name} में आपका स्वागत है। मैं Inna हूँ, आपकी AI receptionist। आज मैं आपकी कैसे मदद कर सकती हूँ? 😊",
    "hinglish": "Hello! 👋 {hotel_name} mein aapka swagat hai. Main Inna hoon, aapki AI receptionist. Aaj main aapki kaise help kar sakti hoon? 😊",
}

_CHITCHAT_REPLIES = {
    "en":       "I'm here to help you with hotel bookings and information 😊 Would you like to book a room or learn about our hotel?",
    "hi":       "मैं होटल बुकिंग और जानकारी में मदद करने के लिए हूँ 😊 क्या आप कमरा बुक करना चाहते हैं?",
    "hinglish": "Main hotel booking aur information mein help kar sakti hoon 😊 Kya aap room book karna chahte hain?",
}

_HUMAN_REPLIES = {
    "en":       "Of course! 🙋 I'm connecting you with our team right away. They'll be with you shortly.",
    "hi":       "बिल्कुल! 🙋 मैं आपको अभी हमारी टीम से जोड़ रही हूँ। वे जल्द ही आपके पास आएंगे।",
    "hinglish": "Bilkul! 🙋 Main aapko abhi humari team se connect kar rahi hoon. Wo jald aapke paas aayenge.",
}

_EXISTING_BOOKING_REPLIES = {
    "en":       "I'll connect you with our team to help with your existing booking 😊 They'll be with you shortly.",
    "hi":       "मैं आपकी मौजूदा बुकिंग के लिए हमारी टीम से जोड़ रही हूँ 😊",
    "hinglish": "Main aapki existing booking ke liye humari team se connect kar rahi hoon 😊",
}

_CANCEL_REPLIES = {
    "en":       "I'll connect you with our team to help with the cancellation 😊 They'll be with you shortly.",
    "hi":       "मैं रद्दीकरण के लिए हमारी टीम से जोड़ रही हूँ 😊",
    "hinglish": "Main cancellation ke liye humari team se connect kar rahi hoon 😊",
}

_UNKNOWN_REPLIES = {
    "en":       "I didn't quite understand that 😊 I can help you with room bookings, availability, hotel information, or payments. What would you like?",
    "hi":       "मुझे समझ नहीं आया 😊 मैं कमरे की बुकिंग, उपलब्धता, होटल की जानकारी या भुगतान में मदद कर सकती हूँ।",
    "hinglish": "Mujhe samajh nahi aaya 😊 Main room booking, availability, hotel information ya payment mein help kar sakti hoon.",
}


def _localised(template_dict: dict, language: str, **kwargs) -> str:
    lang_key = language if language in ("hi", "hinglish") else "en"
    text = template_dict[lang_key]
    return text.format(**kwargs) if kwargs else text


# ── Main reply function ────────────────────────────────────────────────────────

async def generate_reply(req: "ReplyRequest") -> "ReplyResponse":
    """
    Generate a reply based on the classified intent and current session state.

    Decision tree:
    1. greeting / chitchat / human / existing_booking / cancel / unknown
       → return a canned/templated reply (no LLM call needed)
    2. booking / check_availability
       → get_missing_slot → if slot missing, return slot question (no LLM call)
       → if all slots complete, return action=booking_complete (Node creates booking)
    3. hotel_question
       → use RAG context chunks passed in by Node → LLM generates grounded answer
    4. show_rooms / payment
       → passthrough action (Node handles these with its own UI — list menus, QR etc.)
    """
    intent  = req.classify_result.intent
    lang    = req.language
    session = req.session_data or BookingSessionData()
    hotel   = req.hotel_name

    logger.info(
        "reply | venue=%s intent=%s lang=%s",
        req.venue_id, intent, lang,
    )

    # ── 1. Intents that don't need LLM ────────────────────────────────────────

    if intent == "greeting":
        return ReplyResponse(
            reply_text=_localised(_GREETING_REPLIES, lang, hotel_name=hotel),
            intent=intent,
            action="send_reply",
            session_data=session,
        )

    if intent == "chitchat":
        return ReplyResponse(
            reply_text=_localised(_CHITCHAT_REPLIES, lang),
            intent=intent,
            action="send_reply",
            session_data=session,
        )

    if intent == "human":
        return ReplyResponse(
            reply_text=_localised(_HUMAN_REPLIES, lang),
            intent=intent,
            action="escalate_human",   # Node switches chat.mode = 'human'
            session_data=session,
        )

    if intent == "existing_booking":
        return ReplyResponse(
            reply_text=_localised(_EXISTING_BOOKING_REPLIES, lang),
            intent=intent,
            action="escalate_human",
            session_data=session,
        )

    if intent == "cancel":
        return ReplyResponse(
            reply_text=_localised(_CANCEL_REPLIES, lang),
            intent=intent,
            action="escalate_human",
            session_data=session,
        )

    if intent == "unknown":
        return ReplyResponse(
            reply_text=_localised(_UNKNOWN_REPLIES, lang),
            intent=intent,
            action="send_reply",
            session_data=session,
        )

    # ── 2. show_rooms / payment — passthrough to Node ─────────────────────────
    # Node owns the WhatsApp list menus and QR generation.
    # Python just confirms the intent so Node knows what to do.

    if intent in ("show_rooms", "payment"):
        return ReplyResponse(
            reply_text="",          # Node generates this reply itself
            intent=intent,
            action="passthrough",   # Node handles entirely
            session_data=session,
        )

    # ── 3. booking / check_availability — slot filling ────────────────────────

    if intent in ("booking", "check_availability"):
        missing = get_missing_slot(session, req.room_has_multiple_plans)

        if missing:
            question = _slot_question(missing, lang)
            logger.info(
                "reply | slot_needed=%s venue=%s",
                missing, req.venue_id,
            )
            return ReplyResponse(
                reply_text=question,
                intent=intent,
                action="ask_slot",
                missing_slot=missing,
                session_data=session,
            )

        # All slots collected — tell Node to create the booking
        logger.info("reply | all slots complete | venue=%s", req.venue_id)
        return ReplyResponse(
            reply_text="",          # Node sends the booking summary + confirm button
            intent=intent,
            action="booking_complete",
            missing_slot=None,
            session_data=session,
        )

    # ── 4. hotel_question — RAG-grounded LLM reply ────────────────────────────

    if intent == "hotel_question":
        context_chunks = [c.text for c in (req.rag_context or [])]

        # If no RAG context was provided (Node skipped /retrieve), tell guest
        if not context_chunks:
            fallback = {
                "en":       "I'm not able to confirm that right now — please contact the hotel directly 😊",
                "hi":       "मैं अभी यह पुष्टि नहीं कर सकती — कृपया सीधे होटल से संपर्क करें 😊",
                "hinglish": "Main abhi confirm nahi kar sakti — please hotel se directly contact karein 😊",
            }
            return ReplyResponse(
                reply_text=_localised(fallback, lang),
                intent=intent,
                action="send_reply",
                session_data=session,
            )

        system = _rag_system_prompt(lang, hotel, context_chunks)
        messages = [
            *[{"role": m.role, "content": m.content} for m in (req.history or [])],
            {"role": "user", "content": req.message},
        ]

        reply_text = await llm.complete(
            messages=messages,
            system=system,
            max_tokens=300,
            use_cache=True,
        )

        logger.info("reply | rag_answer generated | venue=%s", req.venue_id)
        return ReplyResponse(
            reply_text=reply_text,
            intent=intent,
            action="send_reply",
            session_data=session,
        )

    # ── Fallback (should never reach here given exhaustive intent list) ────────
    logger.warning("reply | unhandled intent=%s | venue=%s", intent, req.venue_id)
    return ReplyResponse(
        reply_text=_localised(_UNKNOWN_REPLIES, lang),
        intent=intent,
        action="send_reply",
        session_data=session,
    )