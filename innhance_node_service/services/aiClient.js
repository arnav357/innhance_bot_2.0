/**
 * aiService.js
 * 
 * Node.js client for the Innhance Python AI service (V2).
 * Harsh plugs this into webhook.js to replace inline GPT-4o calls.
 * 
 * Full pipeline (mirrors the Python service flow exactly):
 *   detectLanguage → classifyIntent → [retrieveContext] → generateReply
 * 
 * Usage in webhook.js:
 *   const ai = require('../services/aiService');
 *   const lang   = await ai.detectLanguage(message);
 *   const cls    = await ai.classifyIntent(venueId, message, history, lang);
 *   const chunks = cls.intent === 'hotel_question'
 *                    ? await ai.retrieveContext(venueId, message, lang) : null;
 *   const reply  = await ai.generateReply({
 *     venueId, message, lang, hotelName,
 *     classifyResult: cls,
 *     sessionData: chat.bookingFlow.data,
 *     roomHasMultiplePlans,
 *     ragContext: chunks,
 *     history,
 *   });
 */

const axios = require('axios');

const { AI_SERVICE_URL, AI_SERVICE_TIMEOUT_MS } = require("../config/env");

const client = axios.create({
  baseURL: AI_SERVICE_URL,
  timeout: AI_SERVICE_TIMEOUT_MS,
  headers: { "Content-Type": "application/json" },
});


// ── Language Detection ────────────────────────────────────────────────────────

/**
 * Detect the language of a guest message.
 * Returns: "en" | "hi" | "hinglish" | "other"
 */
async function detectLanguage(text) {
  try {
    const { data } = await client.post('/detect-language', { text });
    return data.language;
  } catch (err) {
    console.error('❌ aiClient.detectLanguage error:', err.message);
    return 'en'; // safe fallback
  }
}


// ── Intent Classification ─────────────────────────────────────────────────────

/**
 * Classify the guest's intent and extract booking slots.
 * 
 * @param {string}   venueId - Hotel venue ID
 * @param {string}   message - Current guest message
 * @param {Array}    history - Last 6 messages [{role, content}] — REQUIRED, fixes slot misclassification bug
 * @param {string}   language - From detectLanguage()
 * @returns ClassifyResponse: { intent, slots, confidence, provider, raw_message }
 */
async function classify(venueId, message, history = [], language = 'en') {
  try {
    console.log(
  "Classifier history:",
  history.slice(-6).map((m) => `${m.role}: ${m.content}`)
);
    const { data } = await client.post('/classify', {
      venue_id: venueId,
      message,
      history: history.slice(-6), // max 6, always enforce on caller side too
      language,
    });
    return data;
  } catch (err) {
    console.error('❌ aiClient.classifyt error:', err.message);
    // Fallback — treat as unknown so bot doesn't crash
    return {
      intent: 'unknown',
      slots: {},
      confidence: 0,
      provider: 'error-fallback',
      raw_message: message,
    };
  }
}


// ── RAG Retrieval ─────────────────────────────────────────────────────────────

/**
 * Retrieve relevant knowledge chunks for a hotel question.
 * Only call this when intent === 'hotel_question'.
 * 
 * @returns Array of { text, similarity, source_type, image_url }
 *          Empty array if nothing above similarity threshold.
 */
async function retrieve(venueId, query, language = 'en', topK = 3) {
  try {
    const { data } = await client.post('/retrieve', {
      venue_id: venueId,
      query,
      language,
      top_k: topK,
    });
    return data.below_threshold ? [] : (data.chunks || []);
  } catch (err) {
    console.error('❌ aiClient.retrieve error:', err.message);
    return [];
  }
}


// ── Reply Generation ──────────────────────────────────────────────────────────

/**
 * Generate the final reply and action for a guest message.
 * Call this after classifyIntent (and retrieveContext if needed).
 *
 * @param {Object} params
 * @param {string}  params.venueId
 * @param {string}  params.message              - Original guest message
 * @param {string}  params.language             - From detectLanguage()
 * @param {string}  params.hotelName            - Hotel display name
 * @param {Object}  params.classifyResult       - Full response from classifyIntent()
 * @param {Object}  params.sessionData          - chat.bookingFlow.data from MongoDB (camelCase → snake_case mapped here)
 * @param {boolean} params.roomHasMultiplePlans - True if chosen room has >1 meal plan
 * @param {Array}   params.ragContext           - Chunks from retrieveContext() (null for non-hotel_question)
 * @param {Array}   params.history              - Last 6 messages for RAG reply context
 *
 * @returns ReplyResponse: {
 *   reply_text,   // send this to WhatsApp (empty for passthrough/booking_complete)
 *   intent,
 *   action,       // "send_reply" | "ask_slot" | "booking_complete" | "passthrough" | "escalate_human"
 *   missing_slot, // which slot to collect next (only when action=ask_slot)
 *   session_data, // updated booking state — persist to chat.bookingFlow.data
 * }
 */
async function generateReply({
  venueId,
  message,
  language = 'en',
  hotelName,
  classifyResult,
  sessionData = null,
  roomHasMultiplePlans = false,
  ragContext = null,
  history = [],
}) {
  // Map Node camelCase bookingFlow.data → Python snake_case BookingSessionData
  const session = sessionData ? {
    room_type:      sessionData.roomType      ?? null,
    plan_name:      sessionData.planName      ?? null,
    check_in:       sessionData.checkIn       ?? null,
    check_out:      sessionData.checkOut      ?? null,
    rooms_count:    sessionData.roomsCount    ?? null,
    guests:         sessionData.guests        ?? null,
    adults_count:   sessionData.adultsCount   ?? null,
    children_count: sessionData.childrenCount ?? null,
    guest_name:     sessionData.name          ?? null,   // V1 uses .name, V2 uses guest_name
    guest_phone:    sessionData.guestPhone    ?? null,
  } : null;

  // Map Python snake_case ClassifyResponse slots → request shape
  const classifyResultMapped = {
    intent:     classifyResult.intent,
    confidence: classifyResult.confidence,
    provider:   classifyResult.provider || 'anthropic',
    slots: {
      room_type:    classifyResult.slots?.room_type    ?? classifyResult.slots?.roomType    ?? null,
      plan_name:    classifyResult.slots?.plan_name    ?? classifyResult.slots?.planName    ?? null,
      check_in:     classifyResult.slots?.check_in     ?? classifyResult.slots?.checkIn     ?? null,
      check_out:    classifyResult.slots?.check_out    ?? classifyResult.slots?.checkOut    ?? null,
      rooms_count:  classifyResult.slots?.rooms_count  ?? classifyResult.slots?.roomsCount  ?? null,
      guests:       classifyResult.slots?.guests       ?? null,
      guest_count:  classifyResult.slots?.guest_count  ?? classifyResult.slots?.guestCount  ?? null,
      guest_name:   classifyResult.slots?.guest_name   ?? classifyResult.slots?.guestName   ?? null,
      guest_phone:  classifyResult.slots?.guest_phone  ?? classifyResult.slots?.guestPhone  ?? null,
    },
  };

  try {
    const { data } = await client.post('/reply', {
      venue_id:                 venueId,
      message,
      language,
      hotel_name:               hotelName,
      classify_result:          classifyResultMapped,
      session_data:             session,
      room_has_multiple_plans:  roomHasMultiplePlans,
      rag_context:              ragContext,
      history:                  history.slice(-6),
    });

    // Map session_data back from snake_case → camelCase for Node/MongoDB
    const updatedSession = data.session_data ? {
      roomType:      data.session_data.room_type,
      planName:      data.session_data.plan_name,
      checkIn:       data.session_data.check_in,
      checkOut:      data.session_data.check_out,
      roomsCount:    data.session_data.rooms_count,
      guests:        data.session_data.guests,
      adultsCount:   data.session_data.adults_count,
      childrenCount: data.session_data.children_count,
      name:          data.session_data.guest_name,    // V1 key
      guestPhone:    data.session_data.guest_phone,
    } : null;

    return {
      replyText:   data.reply_text,
      intent:      data.intent,
      action:      data.action,
      missingSlot: data.missing_slot,
      sessionData: updatedSession,
    };

  } catch (err) {
    console.error('❌ aiClient.generateReply error:', err.message);
    // Safe fallback — Node can handle this gracefully
    return {
      replyText:   "I'm having a little trouble right now 😊 Please try again in a moment.",
      intent:      'unknown',
      action:      'send_reply',
      missingSlot: null,
      sessionData: sessionData,
    };
  }
}


// ── Full pipeline convenience wrapper ─────────────────────────────────────────

/**
 * Run the full detect → classify → [retrieve] → reply pipeline.
 * Use this in webhook.js instead of calling each step manually.
 *
 * @param {Object} params
 * @param {string}  params.venueId
 * @param {string}  params.message
 * @param {string}  params.hotelName
 * @param {Object}  params.sessionData          - chat.bookingFlow.data
 * @param {boolean} params.roomHasMultiplePlans
 * @param {Array}   params.history              - Last 6 messages
 *
 * @returns { language, classifyResult, replyText, action, missingSlot, sessionData }
 */
async function processMessage({
  venueId,
  message,
  hotelName,
  sessionData = null,
  roomHasMultiplePlans = false,
  history = [],
}) {
  // Step 1: language
  const language = await detectLanguage(message);

  // Step 2: classify
  const classifyResult = await classify(venueId, message, history, language);

  // Step 3: retrieve (only for hotel questions)
  let ragContext = null;
  if (classifyResult.intent === 'hotel_question') {
    ragContext = await retrieve(venueId, message, language);
  }

  // Step 4: reply
  const reply = await generateReply({
    venueId,
    message,
    language,
    hotelName,
    classifyResult,
    sessionData,
    roomHasMultiplePlans,
    ragContext,
    history,
  });

  return { language, classifyResult, ...reply };
}

/**
 * POST /verify-payment
 * NOTE: Python wants a PUBLIC image_url, not base64. We must upload the
 * WhatsApp media to imgbb (or any host) first — see paymentService.
 * @returns VerifyPaymentResponse { status, confidence, amount_match, name_match, ... }
 */
async function verifyPayment({ venueId, imageUrl, expectedAmount, expectedName, bookingRef }) {
  try {
    const { data } = await client.post("/verify-payment", {
      venue_id: venueId,
      image_url: imageUrl,
      expected_amount: expectedAmount,
      expected_name: expectedName,
      booking_ref: bookingRef,
    });
    return data;
  } catch (err) {
    console.error("AI verifyPayment error:", err.message);
    // On error → needs_review, never auto-verify
    return {
      status: "needs_review",
      confidence: 0,
      amount_match: false,
      name_match: false,
      reason: "AI service error",
    };
  }
}


module.exports = {
  detectLanguage,
  classify,
  retrieve,
  generateReply,
  processMessage,  // convenience: runs all 4 steps
  verifyPayment,
};
