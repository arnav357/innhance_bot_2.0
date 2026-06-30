"""
/reply router

Called by Node.js AFTER /classify (and optionally /retrieve).
Generates the final reply text and tells Node what action to take.

Node.js pipeline:
  WhatsApp → /detect-language → /classify → [/retrieve if hotel_question]
  → POST /reply → send to WhatsApp
"""

import logging
from fastapi import APIRouter
from app.models.schemas import ReplyRequest, ReplyResponse
from app.services.reply import generate_reply

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reply"])


@router.post("/reply", response_model=ReplyResponse)
async def reply(req: ReplyRequest) -> ReplyResponse:
    """
    Generate a guest reply based on classified intent and current session state.

    Expects Node.js to have already:
    - Called /detect-language and /classify
    - Merged new slots from classify_result.slots into session_data
    - Called /retrieve if intent == hotel_question and populated rag_context

    Returns:
    - reply_text: text to send to WhatsApp (empty for passthrough/booking_complete)
    - action: what Node should do next
    - missing_slot: which slot to collect next (only when action=ask_slot)
    - session_data: updated state for Node to persist to MongoDB
    """
    return await generate_reply(req)