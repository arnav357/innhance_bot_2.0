"""
All request and response models for the Innhance AI service.

These are the API contract. Harsh builds the Node.js caller against these.
Archana builds dashboard UI against these. Never change a field name without
updating both the Node.js caller and the Notion API contract doc.
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Literal, Optional
from enum import Enum


# ── Language detection ────────────────────────────────────────────────────────

class DetectLanguageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class DetectLanguageResponse(BaseModel):
    language: Literal["en", "hi", "hinglish", "other"]
    script: Literal["latin", "devanagari", "mixed"]
    confidence: float = Field(..., ge=0.0, le=1.0)


# ── Intent classification ─────────────────────────────────────────────────────

class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ClassifyRequest(BaseModel):
    venue_id: str = Field(..., description="Unique hotel/venue identifier")
    message: str  = Field(..., description="Latest guest message to classify")
    history: list[Message] = Field(
        default=[],
        max_length=6,
        description="Last N conversation turns for context. Max 6.",
    )
    language: str = Field(default="en", description="From /detect-language output")


class BookingSlots(BaseModel):
    """Extracted booking slot values. None means the guest hasn't provided it yet."""
    room_type:   Optional[str] = None
    check_in:    Optional[str] = None   # ISO date string YYYY-MM-DD
    check_out:   Optional[str] = None
    guest_count: Optional[int] = None
    guest_name:  Optional[str] = None
    guest_phone: Optional[str] = None


class ClassifyResponse(BaseModel):
    intent: Literal[
        "booking",          # Guest wants to make a booking
        "check_availability",# Guest asking if dates/rooms are available
        "hotel_question",   # Question about the hotel (answered by RAG)
        "show_rooms",       # Guest wants to see room options + images
        "existing_booking", # Asking about an existing reservation
        "payment",          # Sending or asking about payment
        "human",            # Wants to speak to a human
        "greeting",         # Hi / hello / start of conversation
        "chitchat",         # Off-topic, weather, jokes etc
        "cancel",           # Wants to cancel a booking
        "unknown",          # Could not determine intent
    ]
    slots: BookingSlots
    confidence: float = Field(..., ge=0.0, le=1.0)
    provider: str = Field(default="anthropic", description="Which LLM provider was used")
    raw_message: str


# ── RAG retrieval ─────────────────────────────────────────────────────────────

class RetrieveRequest(BaseModel):
    venue_id: str
    query:    str = Field(..., min_length=1, max_length=500)
    language: str = Field(default="en")
    top_k:    int = Field(default=3, ge=1, le=5)


class Chunk(BaseModel):
    text:       str
    similarity: float
    source_type:str          # "policy_pdf" | "room_description" | "faq" | "local_area"
    image_url:  Optional[str] = None


class RetrieveResponse(BaseModel):
    chunks:      list[Chunk]
    venue_id:    str
    retrieved:   int          # how many chunks returned
    below_threshold: bool     # True if no chunks met min similarity — bot should NOT hallucinate


# ── Document ingestion ────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    venue_id:    str
    source_type: Literal["policy_pdf", "room_description", "faq", "local_area"]
    # Provide either file_base64 (PDF) or url (webpage)
    file_base64: Optional[str] = Field(None, description="Base64-encoded PDF content")
    url:         Optional[str] = Field(None, description="Public URL to ingest")
    language:    str = Field(default="en")
    source_name: str = Field(..., description="Human-readable name e.g. 'Hotel Policy 2024'")

    def model_post_init(self, __context):
        if not self.file_base64 and not self.url:
            raise ValueError("Provide either file_base64 or url")


class IngestResponse(BaseModel):
    status:      Literal["queued"]
    venue_id:    str
    source_name: str
    message:     str = "Ingestion started in background. Poll /ingest/status for updates."


class IngestStatusResponse(BaseModel):
    venue_id:    str
    source_name: str
    status:      Literal["processing", "ready", "failed"]
    chunk_count: Optional[int] = None
    error:       Optional[str] = None


# ── Payment verification ──────────────────────────────────────────────────────

class VerifyPaymentRequest(BaseModel):
    venue_id:        str
    image_url:       str = Field(..., description="Public URL of the payment screenshot")
    expected_amount: float
    expected_name:   str  = Field(..., description="UPI recipient name on the venue config")
    booking_ref:     str


class VerifyPaymentResponse(BaseModel):
    status:     Literal["verified", "failed", "needs_review"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    extracted_amount:  Optional[float] = None
    extracted_name:    Optional[str]   = None
    amount_match:      bool = False
    name_match:        bool = False
    reason:            str  = ""
    # If confidence < 0.95 or any mismatch → needs_review, never auto-verified
