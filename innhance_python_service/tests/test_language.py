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
