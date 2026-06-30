"""
tests/test_reply.py

Tests for POST /reply endpoint and get_missing_slot() logic.

Run: pytest tests/test_reply.py -v
"""

import pytest
from app.models.schemas import (
    ReplyRequest, ReplyResponse, BookingSessionData,
    RetrievedContext, ClassifyResult, BookingSlots, Message,
)
from app.services.reply import get_missing_slot, generate_reply


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_classify(intent: str, slots: dict = None) -> ClassifyResult:
    return ClassifyResult(
        intent=intent,
        confidence=0.95,
        slots=BookingSlots(**(slots or {})),
        provider="test",
    )


def make_session(**kwargs) -> BookingSessionData:
    return BookingSessionData(**kwargs)


def make_request(intent: str, session: BookingSessionData = None, **kwargs) -> ReplyRequest:
    return ReplyRequest(
        venue_id="test_hotel_01",
        message="test message",
        language="en",
        hotel_name="Test Hotel",
        classify_result=make_classify(intent),
        session_data=session,
        **kwargs,
    )


# ── get_missing_slot() — slot order tests ─────────────────────────────────────

class TestGetMissingSlot:

    def test_empty_session_returns_room_type(self):
        session = make_session()
        assert get_missing_slot(session) == "room_type"

    def test_after_room_type_returns_check_in_when_single_plan(self):
        session = make_session(room_type="Deluxe")
        # room_has_multiple_plans=False (default) → skip plan_name
        assert get_missing_slot(session, room_has_multiple_plans=False) == "check_in"

    def test_after_room_type_returns_plan_name_when_multiple_plans(self):
        session = make_session(room_type="Deluxe")
        assert get_missing_slot(session, room_has_multiple_plans=True) == "plan_name"

    def test_after_plan_name_returns_check_in(self):
        session = make_session(room_type="Deluxe", plan_name="CP")
        assert get_missing_slot(session, room_has_multiple_plans=True) == "check_in"

    def test_after_check_in_returns_check_out(self):
        session = make_session(room_type="Deluxe", check_in="2026-08-01")
        assert get_missing_slot(session) == "check_out"

    def test_after_check_out_returns_rooms_count(self):
        session = make_session(room_type="Deluxe", check_in="2026-08-01", check_out="2026-08-03")
        assert get_missing_slot(session) == "rooms_count"

    def test_after_rooms_count_returns_guests(self):
        session = make_session(
            room_type="Deluxe", check_in="2026-08-01",
            check_out="2026-08-03", rooms_count=1,
        )
        assert get_missing_slot(session) == "guests"

    def test_guests_via_adults_count(self):
        """Should accept adults_count + children_count as proof guests were collected."""
        session = make_session(
            room_type="Deluxe", check_in="2026-08-01",
            check_out="2026-08-03", rooms_count=1,
            adults_count=2, children_count=0,
        )
        assert get_missing_slot(session) == "guest_name"

    def test_after_guests_returns_guest_name(self):
        session = make_session(
            room_type="Deluxe", check_in="2026-08-01",
            check_out="2026-08-03", rooms_count=1, guests=2,
        )
        assert get_missing_slot(session) == "guest_name"

    def test_all_slots_complete_returns_none(self):
        session = make_session(
            room_type="Deluxe", check_in="2026-08-01",
            check_out="2026-08-03", rooms_count=1,
            guests=2, guest_name="Rahul Sharma",
        )
        assert get_missing_slot(session) is None

    def test_all_slots_complete_with_plan_returns_none(self):
        session = make_session(
            room_type="Suite", plan_name="MAP",
            check_in="2026-08-01", check_out="2026-08-03",
            rooms_count=2, guests=4, guest_name="Priya Verma",
        )
        assert get_missing_slot(session, room_has_multiple_plans=True) is None


# ── generate_reply() — intent routing tests ───────────────────────────────────

@pytest.mark.asyncio
class TestGenerateReply:

    async def test_greeting_returns_send_reply(self):
        req = make_request("greeting")
        res = await generate_reply(req)
        assert res.action == "send_reply"
        assert "Inna" in res.reply_text or "Welcome" in res.reply_text or "welcome" in res.reply_text.lower()
        assert res.reply_text != ""

    async def test_greeting_hindi(self):
        req = make_request("greeting")
        req.language = "hi"
        res = await generate_reply(req)
        assert res.action == "send_reply"
        assert res.reply_text != ""

    async def test_greeting_hinglish(self):
        req = make_request("greeting")
        req.language = "hinglish"
        res = await generate_reply(req)
        assert res.action == "send_reply"
        assert "swagat" in res.reply_text.lower() or "Hello" in res.reply_text

    async def test_chitchat_returns_send_reply(self):
        req = make_request("chitchat")
        res = await generate_reply(req)
        assert res.action == "send_reply"
        assert res.reply_text != ""

    async def test_human_escalation(self):
        req = make_request("human")
        res = await generate_reply(req)
        assert res.action == "escalate_human"
        assert res.reply_text != ""

    async def test_existing_booking_escalates(self):
        req = make_request("existing_booking")
        res = await generate_reply(req)
        assert res.action == "escalate_human"

    async def test_cancel_escalates(self):
        req = make_request("cancel")
        res = await generate_reply(req)
        assert res.action == "escalate_human"

    async def test_unknown_returns_send_reply(self):
        req = make_request("unknown")
        res = await generate_reply(req)
        assert res.action == "send_reply"
        assert res.reply_text != ""

    async def test_show_rooms_is_passthrough(self):
        req = make_request("show_rooms")
        res = await generate_reply(req)
        assert res.action == "passthrough"
        assert res.reply_text == ""

    async def test_payment_is_passthrough(self):
        req = make_request("payment")
        res = await generate_reply(req)
        assert res.action == "passthrough"
        assert res.reply_text == ""

    # ── Booking flow ──────────────────────────────────────────────────────────

    async def test_booking_no_session_asks_room_type(self):
        req = make_request("booking", session=None)
        res = await generate_reply(req)
        assert res.action == "ask_slot"
        assert res.missing_slot == "room_type"

    async def test_booking_has_room_type_asks_check_in(self):
        session = make_session(room_type="Deluxe")
        req = make_request("booking", session=session)
        res = await generate_reply(req)
        assert res.action == "ask_slot"
        assert res.missing_slot == "check_in"

    async def test_booking_asks_plan_when_multiple_plans(self):
        session = make_session(room_type="Suite")
        req = make_request("booking", session=session, room_has_multiple_plans=True)
        res = await generate_reply(req)
        assert res.action == "ask_slot"
        assert res.missing_slot == "plan_name"

    async def test_booking_complete_when_all_slots_filled(self):
        session = make_session(
            room_type="Deluxe", check_in="2026-08-01",
            check_out="2026-08-03", rooms_count=1,
            guests=2, guest_name="Rahul Sharma",
        )
        req = make_request("booking", session=session)
        res = await generate_reply(req)
        assert res.action == "booking_complete"
        assert res.missing_slot is None
        assert res.reply_text == ""   # Node generates the booking summary

    async def test_check_availability_also_does_slot_filling(self):
        """check_availability follows same slot order as booking."""
        session = make_session(room_type="Deluxe", check_in="2026-08-01")
        req = make_request("check_availability", session=session)
        res = await generate_reply(req)
        assert res.action == "ask_slot"
        assert res.missing_slot == "check_out"

    async def test_slot_question_language_hindi(self):
        session = make_session(room_type="Deluxe", check_in="2026-08-01")
        req = make_request("booking", session=session)
        req.language = "hi"
        res = await generate_reply(req)
        assert res.action == "ask_slot"
        # Hindi check-out question should contain Hindi characters
        assert any(ord(c) > 127 for c in res.reply_text)

    async def test_slot_question_language_hinglish(self):
        session = make_session(room_type="Deluxe", check_in="2026-08-01")
        req = make_request("booking", session=session)
        req.language = "hinglish"
        res = await generate_reply(req)
        assert res.action == "ask_slot"
        # Hinglish check-out question should contain romanised Hindi
        assert "check-out" in res.reply_text.lower() or "checkout" in res.reply_text.lower()

    # ── hotel_question (RAG) ──────────────────────────────────────────────────

    async def test_hotel_question_no_context_returns_fallback(self):
        req = make_request("hotel_question", rag_context=[])
        res = await generate_reply(req)
        assert res.action == "send_reply"
        # Should tell guest to contact hotel
        assert "contact" in res.reply_text.lower() or "confirm" in res.reply_text.lower()

    async def test_hotel_question_none_context_returns_fallback(self):
        req = make_request("hotel_question", rag_context=None)
        res = await generate_reply(req)
        assert res.action == "send_reply"

    # NOTE: hotel_question WITH actual RAG context requires a live LLM call.
    # Those tests live in tests/test_reply_integration.py (marked slow).


# ── Session data pass-through ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSessionPassthrough:

    async def test_session_data_returned_unchanged_for_non_booking_intents(self):
        """Python should return session_data untouched for non-booking intents."""
        session = make_session(room_type="Deluxe", check_in="2026-08-01")
        req = make_request("greeting", session=session)
        res = await generate_reply(req)
        assert res.session_data.room_type == "Deluxe"
        assert res.session_data.check_in == "2026-08-01"

    async def test_null_session_handled_for_greeting(self):
        req = make_request("greeting", session=None)
        res = await generate_reply(req)
        assert res.action == "send_reply"
        # Should not crash on null session