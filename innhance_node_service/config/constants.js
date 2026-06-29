// Chat statuses — must match the enum in models/Chat.js
const CHAT_STATUS = {
  INQUIRY: "inquiry",
  BOOKING_IN_PROGRESS: "booking_in_progress",
  AWAITING_CONFIRMATION: "awaiting_confirmation",
  PAYMENT_PENDING: "payment_pending",
  PAYMENT_EXPIRED: "payment_expired",
  BOOKED: "booked",
  CANCELLED: "cancelled",
  HUMAN_SUPPORT: "human_support",
};

const BOOKING_STATUS = {
  PENDING: "pending",
  CONFIRMED: "confirmed",
  CANCELLED: "cancelled",
  COMPLETED: "completed",
};

const PAYMENT_STATUS = {
  PENDING: "pending",
  VERIFIED: "verified",
  FAILED: "failed",
  SETTLED: "settled",
  EXPIRED: "expired",
};

// Intents — must match ClassifyResponse.intent in your Python models
const INTENT = {
  BOOKING: "booking",
  CHECK_AVAILABILITY: "check_availability",
  HOTEL_QUESTION: "hotel_question",
  SHOW_ROOMS: "show_rooms",
  EXISTING_BOOKING: "existing_booking",
  PAYMENT: "payment",
  HUMAN: "human",
  GREETING: "greeting",
  CHITCHAT: "chitchat",
  CANCEL: "cancel",
  UNKNOWN: "unknown",
};

const STALE_MESSAGE_MS = 180_000; // 3 min
const PAYMENT_EXPIRY_MS = 15 * 60 * 1000; // 15 min
const VERIFY_CONFIDENCE_FLOOR = 0.95; // Python uses this; mirror for clarity

module.exports = {
  CHAT_STATUS,
  BOOKING_STATUS,
  PAYMENT_STATUS,
  INTENT,
  STALE_MESSAGE_MS,
  PAYMENT_EXPIRY_MS,
  VERIFY_CONFIDENCE_FLOOR,
};
