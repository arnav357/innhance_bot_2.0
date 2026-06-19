"""
Tests for the language detection service.
Owner: Ridhimaa

Run with:  pytest tests/test_language.py -v
"""

import pytest
from app.services.language import detect_language


# ── English ───────────────────────────────────────────────────────────────────
class TestEnglish:
    def test_plain_english(self):
        r = detect_language("I want to book a room for 2 nights")
        assert r["language"] == "en"
        assert r["script"] == "latin"
        assert r["confidence"] >= 0.7

    def test_english_booking_query(self):
        r = detect_language("Do you have rooms available from December 20th to 25th?")
        assert r["language"] == "en"

    def test_english_greeting(self):
        r = detect_language("Hello, good morning!")
        assert r["language"] == "en"

    def test_english_payment(self):
        r = detect_language("I have made the payment. Please confirm my booking.")
        assert r["language"] == "en"


# ── Hindi (Devanagari script) ─────────────────────────────────────────────────
class TestHindi:
    def test_pure_devanagari(self):
        r = detect_language("मुझे एक कमरा चाहिए")
        assert r["language"] == "hi"
        assert r["script"] == "devanagari"
        assert r["confidence"] >= 0.9

    def test_hindi_booking(self):
        r = detect_language("क्या आपके पास कल के लिए कमरा उपलब्ध है?")
        assert r["language"] == "hi"

    def test_hindi_greeting(self):
        r = detect_language("नमस्ते, मुझे बुकिंग करनी है")
        assert r["language"] == "hi"


# ── Hinglish (Roman script) ───────────────────────────────────────────────────
class TestHinglish:
    def test_hinglish_basic(self):
        r = detect_language("bhai ek room chahiye mujhe")
        assert r["language"] == "hinglish"

    def test_hinglish_booking(self):
        r = detect_language("kya aapke paas room available hai kal ke liye")
        assert r["language"] == "hinglish"

    def test_hinglish_payment(self):
        r = detect_language("maine payment kar diya hai, booking confirm karo")
        assert r["language"] == "hinglish"

    def test_hinglish_question(self):
        r = detect_language("breakfast milega kya hotel mein")
        assert r["language"] == "hinglish"

    def test_hinglish_with_english_words(self):
        r = detect_language("kya aapka hotel pet friendly hai")
        assert r["language"] == "hinglish"

    def test_hinglish_greeting(self):
        r = detect_language("hello bhai room chahiye")
        assert r["language"] == "hinglish"



# ── Hinglish Extended ─────────────────────────────────────────────────────────
class TestHinglishExtended:
    def test_room_available(self):
        r = detect_language("bhai room available hai?")
        assert r["language"] == "hinglish"

    def test_kitna_charge(self):
        r = detect_language("kitna charge hoga ek raat ka")
        assert r["language"] == "hinglish"

    def test_checkout_kab(self):
        r = detect_language("checkout kab hai")
        assert r["language"] == "hinglish"

    def test_pool_hai_kya(self):
        r = detect_language("pool hai kya hotel mein")
        assert r["language"] == "hinglish"

    def test_ac_room_chahiye(self):
        r = detect_language("ac room chahiye")
        assert r["language"] == "hinglish"

    def test_late_checkout(self):
        r = detect_language("late checkout chahiye")
        assert r["language"] == "hinglish"

    def test_discount_milega(self):
        r = detect_language("koi discount milega")
        assert r["language"] == "hinglish"

    def test_online_payment(self):
        r = detect_language("online payment kar sakte hai")
        assert r["language"] == "hinglish"

    def test_parking_available(self):
        r = detect_language("parking available hai kya")
        assert r["language"] == "hinglish"

    def test_breakfast_milega(self):
        r = detect_language("subah breakfast milega kya")
        assert r["language"] == "hinglish"

    def test_booking_confirm(self):
        r = detect_language("booking confirm ho gayi kya")
        assert r["language"] == "hinglish"

    def test_cancel_karna(self):
        r = detect_language("booking cancel karna hai")
        assert r["language"] == "hinglish"

    def test_extra_bed(self):
        r = detect_language("extra bed milega kya")
        assert r["language"] == "hinglish"

    def test_do_din(self):
        r = detect_language("do din ke liye book karna hai")
        assert r["language"] == "hinglish"

    def test_price_batao(self):
        r = detect_language("bhai price batao na")
        assert r["language"] == "hinglish"

    def test_refund_kab(self):
        r = detect_language("refund kab aayega")
        assert r["language"] == "hinglish"

    def test_wifi_password(self):
        r = detect_language("wifi ka password kya hai")
        assert r["language"] == "hinglish"

    def test_room_change(self):
        r = detect_language("room change ho sakta hai")
        assert r["language"] == "hinglish"

    def test_geyser_hai(self):
        r = detect_language("geyser hai room mein")
        assert r["language"] == "hinglish"

    def test_aaj_ke_liye(self):
        r = detect_language("aaj ke liye room chahiye")
        assert r["language"] == "hinglish"

        

# ── Mixed script ──────────────────────────────────────────────────────────────
class TestMixedScript:
    def test_mixed_devanagari_and_latin(self):
        r = detect_language("मुझे room booking करनी है")
        assert r["script"] == "mixed"
        assert r["language"] == "hinglish"


# ── Edge cases ────────────────────────────────────────────────────────────────
class TestEdgeCases:
    def test_empty_string(self):
        r = detect_language("")
        assert r["language"] == "en"          # safe default
        assert r["confidence"] <= 0.6

    def test_single_word_hi(self):
        r = detect_language("hi")
        # "hi" is ambiguous — just check it doesn't crash
        assert r["language"] in ("en", "hinglish", "other")

    def test_numbers_only(self):
        r = detect_language("2 nights 5000 rupees")
        assert r["language"] in ("en", "hinglish")

    def test_very_short_hinglish(self):
        r = detect_language("haan ji")
        assert r["language"] in ("hinglish", "en")   # short — allow either

    def test_returns_all_fields(self):
        r = detect_language("book a room please")
        assert "language" in r
        assert "script" in r
        assert "confidence" in r
        assert 0.0 <= r["confidence"] <= 1.0



