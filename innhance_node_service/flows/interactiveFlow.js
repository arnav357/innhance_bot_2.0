// src/flows/interactiveFlow.js
const Chat = require("../models/Chat");
const Booking = require("../models/Booking");
const Payment = require("../models/Payment");
const { CHAT_STATUS, BOOKING_STATUS, PAYMENT_STATUS } = require("../config/constants");
const { sendText, sendButtons } = require("../services/whatsappService");
const { sendRoomMenu, sendRoomPhotos } = require("../services/menuService");
const { sendPaymentQR } = require("../services/paymentService");
const { saveMessage } = require("../services/chatService");
const { handleBooking } = require("./bookingFlow");
const { slotsToData } = require("../services/bookingService");

/**
 * Deterministic router for WhatsApp button/list replies.
 * Returns true  → fully handled, webhook should stop.
 * Returns false → not a recognized button id, let text logic take over.
 *
 * interactiveId values mirror the ids emitted across the flows:
 *   menu_book, menu_rooms, ask_question        (main menu)
 *   room_<name>, plan_<name>                   (dynamic menu selections)
 *   confirm_booking, ask_question              (summary gate)
 *   pay_qr, pay_desk                           (payment method)
 *   talk_human, continue_bot                   (fallback)
 *   back_to_bot                                (exit human mode)
 *   menu_book / View Rooks alt ids from availability buttons
 */
async function handleInteractive(ctx) {
  const { interactiveId, userMessage, hotel, customer, customerPhone, phoneNumberId, token } = ctx;

  switch (interactiveId) {
    // ── Main menu ─────────────────────────────────────────
    case "menu_book":
      return startBooking(ctx);

    case "menu_rooms":
      await sendRoomPhotos(customerPhone, phoneNumberId, token, hotel);
      await sendButtons(
        customerPhone,
        "Would you like to book one of these rooms?",
        [{ id: "menu_book", title: "Book a Room" }, { id: "ask_question", title: "Ask a Question" }],
        phoneNumberId, token
      );
      return true;

    case "ask_question":
      await sendText(
        customerPhone,
        "Sure — what would you like to know? You can ask about amenities, check-in times, location, food, and more.",
        phoneNumberId, token
      );
      await Chat.findOneAndUpdate(
        { phone: customerPhone, hotelId: hotel._id },
        { status: CHAT_STATUS.INQUIRY }
      );
      return true;

    // ── Confirmation gate (from bookingFlow showSummary) ──
    case "confirm_booking":
      return confirmBooking(ctx);

    // ── Payment method selection ──────────────────────────
    case "pay_qr":
      return payByQR(ctx);

    case "pay_desk":
      return payAtDesk(ctx);

    // ── Fallback buttons ──────────────────────────────────
    case "talk_human":
      await Chat.findOneAndUpdate(
        { phone: customerPhone, hotelId: hotel._id },
        { mode: "human", status: CHAT_STATUS.HUMAN_SUPPORT }
      );
      await sendText(
        customerPhone,
        "Connecting you with our team — someone will reply here shortly.",
        phoneNumberId, token
      );
      return true;

    case "continue_bot":
      await sendButtons(
        customerPhone,
        "No problem! How can I help?",
        [{ id: "menu_book", title: "Book a Room" }, { id: "menu_rooms", title: "View Rooms" }, { id: "ask_question", title: "Ask a Question" }],
        phoneNumberId, token
      );
      return true;

    case "back_to_bot":
      await Chat.findOneAndUpdate(
        { phone: customerPhone, hotelId: hotel._id },
        { mode: "bot", status: CHAT_STATUS.INQUIRY }
      );
      await sendButtons(
        customerPhone,
        "You're back with Inna, your virtual assistant. How can I help?",
        [{ id: "menu_book", title: "Book a Room" }, { id: "menu_rooms", title: "View Rooms" }, { id: "ask_question", title: "Ask a Question" }],
        phoneNumberId, token
      );
      return true;

    // ── Dynamic selections (room_<name> / plan_<name>) ────
    default:
      if (interactiveId?.startsWith("room_")) {
        return selectRoom(ctx, interactiveId.replace("room_", ""));
      }
      if (interactiveId?.startsWith("plan_")) {
        return selectPlan(ctx, interactiveId.replace("plan_", ""));
      }
      // Unknown id → let the text/intent pipeline handle it
      return false;
  }
}

// ── Handlers ────────────────────────────────────────────

async function startBooking(ctx) {
  const { hotel, customerPhone, phoneNumberId, token } = ctx;
  await Chat.findOneAndUpdate(
    { phone: customerPhone, hotelId: hotel._id },
    { "bookingFlow.active": true, status: CHAT_STATUS.BOOKING_IN_PROGRESS }
  );
  await sendRoomMenu(customerPhone, phoneNumberId, token, hotel);
  return true;
}

async function selectRoom(ctx, rawName) {
  const { hotel, customerPhone, phoneNumberId, token } = ctx;
  const room = hotel.rooms?.find(
    (r) => r.name.toLowerCase() === rawName.toLowerCase() ||
           r._id?.toString() === rawName
  );
  if (!room) {
    await sendText(customerPhone, "That room isn't available — please pick again.", phoneNumberId, token);
    await sendRoomMenu(customerPhone, phoneNumberId, token, hotel);
    return true;
  }

  await Chat.findOneAndUpdate(
    { phone: customerPhone, hotelId: hotel._id },
    { "bookingFlow.active": true, "bookingFlow.data.roomType": room.name, status: CHAT_STATUS.BOOKING_IN_PROGRESS }
  );

  // Re-enter the booking state machine so it asks for the next missing field
  await handleBooking({
    classification: { intent: "booking", slots: {}, confidence: 1 },
    userMessage: room.name,
    chat: await Chat.findOne({ phone: customerPhone, hotelId: hotel._id }),
    hotel, customer: ctx.customer, customerPhone, phoneNumberId, token,
  });
  return true;
}

async function selectPlan(ctx, rawName) {
  const { hotel, customerPhone, phoneNumberId, token } = ctx;
  await Chat.findOneAndUpdate(
    { phone: customerPhone, hotelId: hotel._id },
    { "bookingFlow.data.planName": rawName }
  );
  await handleBooking({
    classification: { intent: "booking", slots: {}, confidence: 1 },
    userMessage: rawName,
    chat: await Chat.findOne({ phone: customerPhone, hotelId: hotel._id }),
    hotel, customer: ctx.customer, customerPhone, phoneNumberId, token,
  });
  return true;
}

async function confirmBooking(ctx) {
  const { hotel, customerPhone, phoneNumberId, token } = ctx;
  const chat = await Chat.findOne({ phone: customerPhone, hotelId: hotel._id });

  if (!chat?.bookingFlow?.awaitingBookingConfirmation) {
    await sendText(customerPhone, "There's no booking awaiting confirmation. Tap 'Book a Room' to start.", phoneNumberId, token);
    return true;
  }

  // Mark confirmed and re-run booking flow → it will finalize + offer payment
  await Chat.findOneAndUpdate(
    { phone: customerPhone, hotelId: hotel._id },
    { "bookingFlow.bookingConfirmed": true }
  );

  await handleBooking({
    classification: { intent: "booking", slots: {}, confidence: 1 },
    userMessage: "confirm",
    chat: await Chat.findOne({ phone: customerPhone, hotelId: hotel._id }),
    hotel, customer: ctx.customer, customerPhone, phoneNumberId, token,
  });
  return true;
}

async function payByQR(ctx) {
  const { hotel, customer, customerPhone, phoneNumberId, token } = ctx;

  const booking = await Booking.findOne({
    customerId: customer._id,
    hotelId: hotel._id,
    status: BOOKING_STATUS.CONFIRMED,
  }).sort({ createdAt: -1 });

  if (!booking) {
    await sendText(customerPhone, "I couldn't find a booking to pay for. Please start a new booking.", phoneNumberId, token);
    return true;
  }

  if (!hotel.upiId) {
    await sendText(customerPhone, "Online payment isn't set up for this property. Please pay at the front desk.", phoneNumberId, token);
    return true;
  }

  await sendPaymentQR(customerPhone, phoneNumberId, token, booking, hotel);
  await Chat.findOneAndUpdate(
    { phone: customerPhone, hotelId: hotel._id },
    { status: CHAT_STATUS.PAYMENT_PENDING }
  );
  await saveMessage(customerPhone, hotel._id, customer._id, "assistant", "[Sent payment QR]", hotel.timezone);
  return true;
}

async function payAtDesk(ctx) {
  const { hotel, customer, customerPhone, phoneNumberId, token } = ctx;

  const booking = await Booking.findOne({
    customerId: customer._id,
    hotelId: hotel._id,
    status: BOOKING_STATUS.CONFIRMED,
  }).sort({ createdAt: -1 });

  if (booking) {
    await Payment.findOneAndUpdate(
      { bookingId: booking._id },
      { status: PAYMENT_STATUS.PENDING, method: "desk" }
    );
  }

  await Chat.findOneAndUpdate(
    { phone: customerPhone, hotelId: hotel._id },
    { status: CHAT_STATUS.BOOKED }
  );

  const ref = booking ? `#${booking._id.toString().slice(-6).toUpperCase()}` : "";
  const msg =
    `✅ *Booking Confirmed — Pay at Desk*\n\n` +
    (booking
      ? `${booking.guestName}\n${booking.roomType}\n${booking.checkIn} → ${booking.checkOut}\n` +
        `Amount due at check-in: ₹${booking.totalAmount?.toLocaleString()}\n\n`
      : "") +
    `Please pay at the front desk during check-in. We look forward to hosting you at *${hotel.name}*!\n` +
    (ref ? `_Booking ID: ${ref}_` : "");

  await sendText(customerPhone, msg, phoneNumberId, token);
  await saveMessage(customerPhone, hotel._id, customer._id, "assistant", msg, hotel.timezone);
  return true;
}

module.exports = { handleInteractive };
