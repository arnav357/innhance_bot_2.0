"""
Payment screenshot verification service.
Uses GPT-4o vision to read UPI payment screenshots and verify:
  - Payment amount matches expected
  - Recipient name matches hotel UPI name
  - Transaction appears genuine

IMPORTANT: This service NEVER auto-verifies payments.
If confidence < 0.95 or any field mismatches → status = "needs_review"
A human (hotel staff) must approve in the dashboard.
"""

import re
import json
import logging
from app.core import llm
from app.models.schemas import VerifyPaymentRequest, VerifyPaymentResponse

logger = logging.getLogger(__name__)

VERIFY_PROMPT_TEMPLATE = """You are verifying a UPI payment screenshot for a hotel booking system.

Expected payment details:
- Amount: ₹{expected_amount}
- Recipient name: {expected_name}
- Booking reference: {booking_ref}

Look at this payment screenshot and extract:
1. The amount paid (numbers only, no ₹ symbol)
2. The recipient/UPI name shown
3. Whether this looks like a genuine UPI payment confirmation (not a fake, edited, or pending transaction)

Respond ONLY with a valid JSON object — no other text:
{{
  "extracted_amount": <number or null>,
  "extracted_name": <string or null>,
  "looks_genuine": <true or false>,
  "confidence": <0.0 to 1.0>,
  "notes": "<brief explanation>"
}}"""


def _amounts_match(expected: float, extracted: float | None, tolerance: float = 1.0) -> bool:
    """
    Allow ±₹1 tolerance for rounding differences in UPI apps.
    Larger discrepancies always go to human review.
    """
    if extracted is None:
        return False
    return abs(expected - extracted) <= tolerance


def _names_match(expected: str, extracted: str | None) -> bool:
    """
    Fuzzy name match — UPI apps sometimes truncate or capitalise differently.
    """
    if not extracted:
        return False
    e = expected.lower().strip()
    x = extracted.lower().strip()
    # Direct match
    if e == x:
        return True
    # One contains the other (handles truncation)
    if e in x or x in e:
        return True
    # First word match (enough for most UPI names)
    if e.split()[0] == x.split()[0]:
        return True
    return False


async def verify_payment(req: VerifyPaymentRequest) -> VerifyPaymentResponse:
    """
    Run GPT-4o vision on a payment screenshot URL.
    Always returns a structured result — never raises on LLM errors.
    """
    prompt = VERIFY_PROMPT_TEMPLATE.format(
        expected_amount=req.expected_amount,
        expected_name=req.expected_name,
        booking_ref=req.booking_ref,
    )

    try:
        raw = await llm.vision_verify(image_url=req.image_url, prompt=prompt)
        raw_text = raw.get("raw", "")

        # Parse JSON from LLM response
        # Strip any accidental markdown fences
        clean = re.sub(r"```json|```", "", raw_text).strip()
        parsed = json.loads(clean)

    except Exception as exc:
        logger.error("vision_verify parse error: %s", exc)
        return VerifyPaymentResponse(
            status="needs_review",
            confidence=0.0,
            reason=f"Could not parse verification response: {exc}",
        )

    extracted_amount = parsed.get("extracted_amount")
    extracted_name   = parsed.get("extracted_name")
    looks_genuine    = parsed.get("looks_genuine", False)
    confidence       = float(parsed.get("confidence", 0.0))
    notes            = parsed.get("notes", "")

    amount_ok = _amounts_match(req.expected_amount, extracted_amount)
    name_ok   = _names_match(req.expected_name, extracted_name)

    # Verification logic — human review required for any uncertainty
    all_good = amount_ok and name_ok and looks_genuine and confidence >= 0.95

    if all_good:
        status = "verified"
        reason = f"Amount ₹{extracted_amount} matches, name '{extracted_name}' matches, transaction appears genuine."
    elif not looks_genuine:
        status = "failed"
        reason = f"Transaction does not appear genuine. Notes: {notes}"
    else:
        status = "needs_review"
        issues = []
        if not amount_ok:
            issues.append(f"amount mismatch (expected ₹{req.expected_amount}, got ₹{extracted_amount})")
        if not name_ok:
            issues.append(f"name mismatch (expected '{req.expected_name}', got '{extracted_name}')")
        if confidence < 0.95:
            issues.append(f"low confidence ({confidence:.0%})")
        reason = "Requires human review: " + "; ".join(issues)

    logger.info(
        "verify_payment | venue=%s booking=%s status=%s confidence=%.2f",
        req.venue_id, req.booking_ref, status, confidence,
    )

    return VerifyPaymentResponse(
        status=status,
        confidence=confidence,
        extracted_amount=extracted_amount,
        extracted_name=extracted_name,
        amount_match=amount_ok,
        name_match=name_ok,
        reason=reason,
    )
