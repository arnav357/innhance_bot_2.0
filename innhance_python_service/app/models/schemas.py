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
    rooms_count: Optional[int] = None
    plan_name:   Optional[str] = None


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
        "banquet",          # Guest asking about banquet/event hall
        "command",           # Guest confirming/proceeding (yes/haan/ok)
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

# ── Booking session state (owned by Node/MongoDB, passed in on each call) ─────
class BookingSessionData(BaseModel):
    """
    Current state of the guest's booking flow.
    Node.js populates this from chat.bookingFlow.data in MongoDB.
    Python never writes to this directly — it returns updated state
    for Node to persist.
 
    Field names use snake_case here; Node maps from its camelCase
    (roomType → room_type etc.) before calling this endpoint.
    """
    room_type:      Optional[str] = None
    plan_name:      Optional[str] = None   # EP / CP / MAP etc.
    check_in:       Optional[str] = None   # YYYY-MM-DD
    check_out:      Optional[str] = None   # YYYY-MM-DD
    rooms_count:    Optional[int] = None
    guests:         Optional[int] = None   # total guest count
    adults_count:   Optional[int] = None
    children_count: Optional[int] = None
    guest_name:     Optional[str] = None
    guest_phone:    Optional[str] = None
 
 
# ── RAG context chunk (passed from Node after calling /retrieve) ──────────────
 
class RetrievedContext(BaseModel):
    """
    A single chunk retrieved by /retrieve.
    Node calls /retrieve, gets chunks, then passes them here.
    Python never calls /retrieve internally.
    """
    text:        str
    similarity:  float
    source_type: str
    image_url:   Optional[str] = None
 
 
# ── /reply request ────────────────────────────────────────────────────────────
 
class ClassifyResult(BaseModel):
    """
    The result of a prior /classify call, passed through by Node.
    Python does NOT re-classify — this is the contract.
    """
    intent:     str
    confidence: float
    slots:      "BookingSlots"   # forward ref — BookingSlots defined above in schemas.py
    provider:   str = "anthropic"
 
 
class ReplyRequest(BaseModel):
    """
    Everything Python needs to generate the right reply.
 
    Node.js is responsible for:
    - Calling /detect-language and /classify first
    - Merging new slots from classify_result.slots into session_data
    - Calling /retrieve if intent == 'hotel_question' and passing chunks here
    - Passing the last 6 messages as history
    """
    venue_id:    str  = Field(..., description="Hotel/venue identifier")
    message:     str  = Field(..., description="Original guest message text")
    language:    str  = Field(default="en", description="From /detect-language")
    hotel_name:  str  = Field(..., description="Hotel display name for Inna's replies")
 
    # Classification result from the prior /classify call
    classify_result: ClassifyResult
 
    # Current booking slot state (after Node has merged new slots in)
    session_data: Optional[BookingSessionData] = Field(
        default=None,
        description="Current bookingFlow.data from MongoDB — null if no active booking flow",
    )
 
    # Whether the selected room type has multiple meal plans
    # Node checks hotel.rooms to determine this after room_type slot is filled
    room_has_multiple_plans: bool = Field(
        default=False,
        description="Set to True if the chosen room has >1 plan (EP/CP/MAP etc.) — triggers plan_name slot",
    )
 
    # RAG context — Node calls /retrieve for hotel_question intent and passes chunks here
    # For all other intents, pass null or empty list
    rag_context: Optional[list[RetrievedContext]] = Field(
        default=None,
        description="Top-K chunks from /retrieve. Only needed for hotel_question intent.",
    )
 
    # Conversation history — last 6 turns, for RAG reply context
    history: Optional[list["Message"]] = Field(   # Message defined in schemas.py
        default=None,
        max_length=6,
        description="Last N conversation turns. Used for RAG reply generation only.",
    )
 
 
# ── /reply response ───────────────────────────────────────────────────────────
 
class ReplyResponse(BaseModel):
    """
    What Python tells Node to do next.
 
    action values and what Node should do:
      "send_reply"       → send reply_text to guest via WhatsApp
      "ask_slot"         → send reply_text (the slot question) to guest,
                           update chat status to 'booking_in_progress'
      "booking_complete" → all slots collected; Node should show booking
                           summary + confirm button to guest
                           (reply_text is empty — Node generates the summary)
      "passthrough"      → Node handles this intent entirely with its own
                           UI (room list menus, QR code etc.)
                           (reply_text is empty)
      "escalate_human"   → send reply_text, then set chat.mode = 'human'
    """
    reply_text:   str = Field(..., description="Text to send to guest. Empty string for passthrough/booking_complete.")
    intent:       str
    action:       Literal[
        "send_reply",
        "ask_slot",
        "booking_complete",
        "passthrough",
        "escalate_human",
    ]
    missing_slot: Optional[str] = Field(
        default=None,
        description="Which slot is still needed. Only set when action=ask_slot.",
    )
    session_data: Optional[BookingSessionData] = Field(
        default=None,
        description="Updated session state for Node to persist to chat.bookingFlow.data.",
    )