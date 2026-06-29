const Chat = require("../models/Chat");
const Booking = require("../models/Booking");
const {
  BOOKING_STATUS,
  CHAT_STATUS,
  PAYMENT_STATUS,
  PAYMENT_EXPIRY_MS,
} = require("../config/constants");
const Payment = require("../models/Payment");
const { sendText, sendButtons } = require("../services/whatsappService");
const { sendRoomMenu } = require("../services/menuService");
const { saveMessage } = require("../services/chatService");
const {
  slotsToData,
  mergeBooking,
  getMissing,
  calcTotal,
} = require("../services/bookingService");
const { checkRoomAvailability } = require("../services/availabilityService");

async function handleBooking({
  classification,
  userMessage,
  chat,
  hotel,
  customer,
  customerPhone,
  phoneNumberId,
  token,
}) {
  const latest = await Chat.findOne({
    phone: customerPhone,
    hotelId: hotel._id,
  });
  const flow = latest?.bookingFlow || {};
  const oldData = flow.data || {};

  // Merge Python-extracted slots into our flow data
  const newData = slotsToData(classification?.slots);
  const data = mergeBooking(oldData, newData);
  if (!data.roomsCount) {
    data.roomsCount = 1;
  }
  console.log("Old booking data:");
  console.dir(oldData, { depth: null });

  console.log("New slots:");
  console.dir(newData, { depth: null });

  console.log("Merged booking:");
  console.dir(data, { depth: null });

  console.log("Next missing:", getMissing(data, hotel));

  await Chat.findOneAndUpdate(
    { phone: customerPhone, hotelId: hotel._id },
    {
      "bookingFlow.active": true,
      "bookingFlow.data": data,
      status: CHAT_STATUS.BOOKING_IN_PROGRESS,
    },
  );

  // Validate date ordering
  if (
    data.checkIn &&
    data.checkOut &&
    new Date(data.checkOut) <= new Date(data.checkIn)
  ) {
    await Chat.findOneAndUpdate(
      { phone: customerPhone, hotelId: hotel._id },
      { "bookingFlow.data.checkOut": null },
    );
    return sendText(
      customerPhone,
      "Check-out must be after check-in. Please re-enter the check-out date.",
      phoneNumberId,
      token,
    );
  }

  const missing = getMissing(data, hotel);
  if (missing)
    return askForField(missing, {
      hotel,
      data,
      customer,
      customerPhone,
      phoneNumberId,
      token,
    });

  // All slots filled → confirmation gate
  if (!flow.awaitingBookingConfirmation && !flow.bookingConfirmed) {
    return await showSummary({
      data,
      hotel,
      customer,
      customerPhone,
      phoneNumberId,
      token,
    });
  }

  if (!flow.bookingConfirmed) return; // waiting on the Confirm button

  // Confirmed → create booking
  return await finalizeBooking({
    data,
    hotel,
    customer,
    customerPhone,
    phoneNumberId,
    token,
  });
}

async function askForField(
  field,
  { hotel, data, customer, customerPhone, phoneNumberId, token },
) {
  const prompts = {
    name: "May I know your full name?",
    checkIn:
      "What is your check-in date? Please use DD/MM/YYYY (e.g. 31/12/2026).",
    checkOut:
      "What is your check-out date? Please use DD/MM/YYYY (e.g. 31/12/2026).",
    roomsCount: "How many rooms would you like?",
    guests: "How many guests will be staying? (e.g. '2', '2 adults 1 child')",
  };
  console.log("Asking for field:", field);

  if (field === "roomType") {
    await sendRoomMenu(customerPhone, phoneNumberId, token, hotel);
    return;
  }
  if (field === "planName") {
    const room = hotel.rooms.find(
      (r) => r.name.toLowerCase() === data.roomType.toLowerCase(),
    );
    const text = room.plans
      .map(
        (p, i) => `${i + 1}. ${p.name} — ₹${p.price}\n${p.description || ""}`,
      )
      .join("\n\n");
    return sendText(
      customerPhone,
      `Available plans for *${room.name}*:\n\n${text}\n\nWhich plan would you like?`,
      phoneNumberId,
      token,
    );
  }

  await sendText(customerPhone, prompts[field], phoneNumberId, token);
  await saveMessage(
    customerPhone,
    hotel._id,
    customer._id,
    "assistant",
    prompts[field],
    hotel.timezone,
  );
}

async function showSummary({
  data,
  hotel,
  customer,
  customerPhone,
  phoneNumberId,
  token,
}) {
  // Availability check before showing summary
  const availability = await checkRoomAvailability({
    hotel,
    roomType: data.roomType,
    checkIn: data.checkIn,
    checkOut: data.checkOut,
    requestedRooms: data.roomsCount || 1,
  });
  if (!availability.available) {
    await Chat.findOneAndUpdate(
      { phone: customerPhone, hotelId: hotel._id },
      { status: CHAT_STATUS.INQUIRY, bookingFlow: { active: false, data: {} } },
    );
    return sendButtons(
      customerPhone,
      `Sorry, only ${Math.max(0, availability.remainingRooms)} room(s) are available for those dates. Try different dates?`,
      [
        { id: "menu_book", title: "Book Again" },
        { id: "menu_rooms", title: "View Rooms" },
      ],
      phoneNumberId,
      token,
    );
  }

  const total = calcTotal(hotel, data);
  const summary =
    `📋 *Booking Summary*\n\n` +
    `Room: ${data.roomType}\n` +
    (data.planName ? `Plan: ${data.planName}\n` : "") +
    `Check-in: ${data.checkIn}\nCheck-out: ${data.checkOut}\n` +
    `Rooms: ${data.roomsCount}\nGuests: ${data.guests}\nName: ${data.name}\n` +
    `Estimated Total: ₹${total.toLocaleString()}\n\n` +
    `Please review before we proceed.`;

  await sendButtons(
    customerPhone,
    summary,
    [
      { id: "confirm_booking", title: "✅ Confirm" },
      { id: "ask_question", title: "❓ Ask Question" },
    ],
    phoneNumberId,
    token,
  );
  await Chat.findOneAndUpdate(
    { phone: customerPhone, hotelId: hotel._id },
    { "bookingFlow.awaitingBookingConfirmation": true },
  );
  await saveMessage(
    customerPhone,
    hotel._id,
    customer._id,
    "assistant",
    summary,
    hotel.timezone,
  );
}

async function finalizeBooking({
  data,
  hotel,
  customer,
  customerPhone,
  phoneNumberId,
  token,
}) {
  const total = calcTotal(hotel, data);

  const booking = await Booking.create({
    hotelId: hotel._id,
    customerId: customer._id,
    guestName: data.name,
    phone: customerPhone,
    checkIn: data.checkIn,
    checkOut: data.checkOut,
    roomType: data.roomType,
    planName: data.planName || null,
    numberOfRooms: data.roomsCount,
    numberOfGuests: data.guests,
    totalAmount: total,
    status: BOOKING_STATUS.CONFIRMED,
    source: "whatsapp",
  });

  const bookingRef = booking._id.toString().slice(-6).toUpperCase();
  await Payment.findOneAndUpdate(
    { bookingId: booking._id },
    {
      hotelId: hotel._id,
      hotelName: hotel.name,
      bookingId: booking._id,
      bookingRef,
      customerPhone,
      guestName: data.name,
      amount: total,
      transactionNote: `HOTEL-${hotel.shortCode}-BOOK-${bookingRef}`,
      status: PAYMENT_STATUS.PENDING,
      expiresAt: new Date(Date.now() + PAYMENT_EXPIRY_MS),
    },
    { upsert: true },
  );

  await Chat.findOneAndUpdate(
    { phone: customerPhone, hotelId: hotel._id },
    {
      status: CHAT_STATUS.AWAITING_CONFIRMATION,
      bookingFlow: { active: false, data: {} },
    },
  );

  const msg =
    `🎉 *Booking Ready!*\n\n` +
    `${data.name}\n${data.roomType}\n${data.checkIn} → ${data.checkOut}\n` +
    `${data.roomsCount} room(s), ${data.guests} guest(s)\nTotal: ₹${total.toLocaleString()}\n\n` +
    `Choose a payment method below.`;
  await sendText(customerPhone, msg, phoneNumberId, token);
  await sendButtons(
    customerPhone,
    "How would you like to pay?",
    [
      { id: "pay_qr", title: "💳 Pay QR" },
      { id: "pay_desk", title: "🏨 Pay at Desk" },
    ],
    phoneNumberId,
    token,
  );
  await saveMessage(
    customerPhone,
    hotel._id,
    customer._id,
    "assistant",
    msg,
    hotel.timezone,
  );
}

module.exports = { handleBooking };
