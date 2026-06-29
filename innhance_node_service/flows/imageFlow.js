const Payment = require("../models/Payment");
const Booking = require("../models/Booking");
const Chat = require("../models/Chat");
const { PAYMENT_STATUS, CHAT_STATUS } = require("../config/constants");
const { sendText, fetchMedia } = require("../services/whatsappService");
const { verifyScreenshot } = require("../services/paymentService");
const { saveMessage } = require("../services/chatService");

async function handleImage({ message, hotel, customer, customerPhone, phoneNumberId, token }) {
  const mediaId = message.image?.id;
  if (!mediaId) {
    return sendText(customerPhone, "I couldn't read that image — please resend the screenshot.", phoneNumberId, token);
  }

  const payment = await Payment.findOne({
    customerPhone,
    hotelId: hotel._id,
    status: PAYMENT_STATUS.PENDING,
  }).sort({ createdAt: -1 });

  if (!payment) {
    return sendText(customerPhone, "No pending payment found. Please request a payment QR first.", phoneNumberId, token);
  }

  const booking = await Booking.findById(payment.bookingId);
  await sendText(customerPhone, "Verifying your payment screenshot, please wait…", phoneNumberId, token);

  const media = await fetchMedia(mediaId, token);
  if (!media) {
    return sendText(customerPhone, "Sorry, I couldn't download your screenshot. Please try again.", phoneNumberId, token);
  }

  const result = await verifyScreenshot({ media, payment, hotel });
  console.log("Verify result:", JSON.stringify(result));

  // Persist extracted data
  payment.transactionId = result.transaction_id || payment.transactionId;
  payment.screenshotVerified = result.status === "verified";

  if (result.status === "verified") {
    payment.status = PAYMENT_STATUS.VERIFIED;
    await payment.save();

    await Chat.findOneAndUpdate(
      { phone: customerPhone, hotelId: hotel._id },
      { status: CHAT_STATUS.BOOKED }
    );

    const nights = Math.ceil(
      (new Date(booking.checkOut) - new Date(booking.checkIn)) / (1000 * 60 * 60 * 24)
    );
    const msg =
      `✅ *Payment Verified & Booking Confirmed!*\n\n` +
      `Name: ${booking.guestName}\n` +
      `Room: ${booking.roomType}\n` +
      `Check-in: ${booking.checkIn}\n` +
      `Check-out: ${booking.checkOut}\n` +
      `Nights: ${nights}\n` +
      `Guests: ${booking.numberOfGuests}\n` +
      `Amount Paid: ₹${booking.totalAmount?.toLocaleString()}\n\n` +
      `Thank you for choosing *${hotel.name}*! See you soon.\n` +
      `_Booking ID: #${booking._id.toString().slice(-6).toUpperCase()}_`;

    await sendText(customerPhone, msg, phoneNumberId, token);
    await saveMessage(customerPhone, hotel._id, customer._id, "assistant", msg, hotel.timezone);
    return;
  }

  // needs_review or failed
  payment.status = result.status === "failed" ? PAYMENT_STATUS.FAILED : PAYMENT_STATUS.PENDING;
  await payment.save();

  let reason = result.reason || "I couldn't verify the payment.";
  if (!result.amount_match) reason = `Amount doesn't match the booking total (₹${payment.amount}). Please check and resend.`;
  else if (!result.name_match) reason = `Receiver name doesn't match. Please pay to *${hotel.upiName}* and resend the screenshot.`;
  else if (result.status === "needs_review") reason = "I need a clearer screenshot to confirm. Please resend, or tap 'Talk to Human'.";

  await sendText(customerPhone, reason, phoneNumberId, token);
  await saveMessage(customerPhone, hotel._id, customer._id, "assistant", reason, hotel.timezone);
}

module.exports = { handleImage };
