"""
Language detection service.
Owner: Riddhima (reviewed by co-lead before merge)

Detects whether a WhatsApp message is English, Hindi, Hinglish, or other.
Uses langdetect + Unicode range analysis — zero LLM cost, near-zero latency.

Devanagari Unicode range: U+0900–U+097F
Latin range: basic ASCII + extended Latin
Hinglish: Latin script but contains Hindi words written in Roman script
"""

import re
import logging
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

# Make langdetect deterministic (it uses random seeds internally)
DetectorFactory.seed = 42

logger = logging.getLogger(__name__)

# Common Hinglish words written in Roman script
# These appear in English-script text but are Hindi words
HINGLISH_MARKERS = {
    "kya", "hai", "hain", "mujhe", "aapko", "kyun", "kab", "kaise",
    "nahi", "nahin", "hoga", "chahiye", "milega", "batao", "theek",
    "achha", "accha", "bilkul", "zaroor", "shukriya", "dhanyawad",
    "kal", "aaj", "parso", "raat", "subah", "dopahar", "shaam",
    "kamra", "room", "booking", "kitna", "kitne", "paisa", "rupees",
    "bhai", "yaar", "bhen", "didi", "bhaiya", "ji", "haan", "hna",
    "aur", "lekin", "toh", "par", "mein", "se", "ko", "ka", "ki",
    "kar", "karo", "karna", "sakte", "sakta", "sakti",
    "din", "liye", "wala", "wali", "ho", "gaya", "gayi", "bhejo", "bhej", "garam", "paani", "raha", "do", "aa",
}


def _contains_devanagari(text: str) -> bool:
    """True if text has any Devanagari Unicode characters."""
    return bool(re.search(r"[\u0900-\u097F]", text))


def _devanagari_ratio(text: str) -> float:
    """Fraction of characters that are Devanagari."""
    if not text:
        return 0.0
    devanagari = len(re.findall(r"[\u0900-\u097F]", text))
    letters    = len(re.findall(r"[A-Za-z\u0900-\u097F]", text))
    return devanagari / letters if letters > 0 else 0.0


def _hinglish_score(text: str) -> float:
    """
    Score 0–1 for how Hinglish the text is.
    Based on fraction of words that are known Hindi words in Roman script.
    """
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return 0.0
    matches = sum(1 for w in words if w in HINGLISH_MARKERS)
    return matches / len(words)


def detect_language(text: str) -> dict:
    """
    Main detection function.

    Returns:
        language: "en" | "hi" | "hinglish" | "other"
        script:   "latin" | "devanagari" | "mixed"
        confidence: 0.0–1.0
    """
    text = text.strip()
    if not text:
        return {"language": "en", "script": "latin", "confidence": 0.5}

    deva_ratio    = _devanagari_ratio(text)
    has_devanagari = _contains_devanagari(text)
    has_latin      = bool(re.search(r"[A-Za-z]", text))

    # ── Script detection ──────────────────────────────────────────────────────
    if deva_ratio > 0.7:
        script = "devanagari"
    elif has_devanagari and has_latin:
        script = "mixed"
    else:
        script = "latin"

    # ── Pure Devanagari → Hindi ───────────────────────────────────────────────
    if script == "devanagari":
        return {"language": "hi", "script": "devanagari", "confidence": 0.95}

    # ── Mixed script → treat as Hinglish ─────────────────────────────────────
    if script == "mixed":
        return {"language": "hinglish", "script": "mixed", "confidence": 0.85}

    # ── Latin script — could be EN or Hinglish ───────────────────────────────
    hinglish_score = _hinglish_score(text)
    if hinglish_score >= 0.25:
        # 25%+ of words are Hindi-origin → Hinglish
        confidence = min(0.95, 0.60 + hinglish_score)
        return {"language": "hinglish", "script": "latin", "confidence": round(confidence, 2)}

    # Try langdetect for the remaining cases
    try:
        detected = detect(text)
        if detected == "hi":
            # langdetect thinks Hindi but in Latin script — Hinglish
            return {"language": "hinglish", "script": "latin", "confidence": 0.80}
        elif detected == "en":
            confidence = 0.90 if len(text.split()) >= 3 else 0.70
            return {"language": "en", "script": "latin", "confidence": confidence}
        else:
            return {"language": "other", "script": "latin", "confidence": 0.65}

    except LangDetectException:
        # Very short text — default to English
        logger.debug("langdetect failed on short text: %r", text)
        return {"language": "en", "script": "latin", "confidence": 0.50}
