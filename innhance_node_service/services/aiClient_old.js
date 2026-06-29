const axios = require("axios");
const { AI_SERVICE_URL, AI_SERVICE_TIMEOUT_MS } = require("../config/env");

const client = axios.create({
  baseURL: AI_SERVICE_URL,
  timeout: AI_SERVICE_TIMEOUT_MS,
  headers: { "Content-Type": "application/json" },
});

/**
 * POST /detect-language
 * @returns { language, script, confidence }
 */
async function detectLanguage(text) {
  try {
    const { data } = await client.post("/detect-language", { text });
    return data;
  } catch (err) {
    console.error("AI detectLanguage error:", err.message);
    // Safe default — never block the conversation on language detection
    return { language: "en", script: "latin", confidence: 0 };
  }
}

/**
 * POST /classify
 * history must be [{ role, content }] (max 6) — matches Message model.
 * @returns ClassifyResponse { intent, slots, confidence, provider, raw_message }
 */
async function classify({ venueId, message, history = [], language = "en" }) {
  console.log(
  "Classifier history:",
  history.slice(-6).map((m) => `${m.role}: ${m.content}`)
);
  try {
    const { data } = await client.post("/classify", {
      venue_id: venueId,
      message,
      history: history.slice(-6),
      language,
    });
    console.log("\n========== CLASSIFIER RESPONSE ==========");
console.log(JSON.stringify(data, null, 2));
console.log("=========================================\n");
    return data;
  } catch (err) {
    console.error("AI classify error:", err.message);
    return {
      intent: "unknown",
      slots: {},
      confidence: 0,
      provider: "fallback",
      raw_message: message,
    };
  }
}

/**
 * POST /retrieve  (RAG for hotel questions)
 * @returns RetrieveResponse { chunks, retrieved, below_threshold, ... }
 */
async function retrieve({ venueId, query, language = "en", topK = 3 }) {
  try {
    const { data } = await client.post("/retrieve", {
      venue_id: venueId,
      query,
      language,
      top_k: topK,
    });
    return data;
  } catch (err) {
    console.error("AI retrieve error:", err.message);
    return { chunks: [], retrieved: 0, below_threshold: true, venue_id: venueId };
  }
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

async function processMessage({
    venueId,
    hotelName,
    message,
    history,
    sessionData,
    roomHasMultiplePlans,
}) {

    const language = await detectLanguage(message);

    const classification = await classify({
        venueId,
        message,
        history,
        language: language.language,
    });

    let rag = null;

    if (classification.intent === "hotel_question") {
        rag = await retrieve({
            venueId,
            query: message,
            language: language.language,
        });
    }

    // Call /reply endpoint
    const reply = await client.post("/reply", {
        venue_id: venueId,
        hotel_name: hotelName,
        language: language.language,
        classify_result: classification,
        session_data: sessionData,
        rag_result: rag,
        room_has_multiple_plans: roomHasMultiplePlans,
    });

    return {
        language,
        classification,
        rag,
        reply: reply.data,
    };
}

module.exports = { detectLanguage, classify, retrieve, verifyPayment, processMessage };
