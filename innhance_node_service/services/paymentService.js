const axios = require("axios");
const FormData = require("form-data");
const QRCode = require("qrcode");

const Payment = require("../models/Payment");
const { IMGBB_API_KEY } = require("../config/env");
const { PAYMENT_EXPIRY_MS } = require("../config/constants");
const { sendImage, sendText } = require("./whatsappService");
const aiClient = require("./aiClient");

/** Upload a base64 image to imgbb → returns public URL (Python needs a URL). */
async function uploadToImgbb(base64) {
  if (!IMGBB_API_KEY) throw new Error("IMGBB_API_KEY not configured");
  const form = new FormData();
  form.append("image", base64);
  const { data } = await axios.post(
    `https://api.imgbb.com/1/upload?key=${IMGBB_API_KEY}`,
    form,
    { headers: form.getHeaders() }
  );
  return data?.data?.url;
}

function buildUpiLink({ upiId, upiName, amount, note }) {
  const params = new URLSearchParams({
    pa: upiId,
    pn: upiName,
    am: String(amount),
    cu: "INR",
    tn: note,
  });
  return `upi://pay?${params.toString()}`;
}

/** Create (or reuse) a pending payment and send the QR image. */
async function sendPaymentQR(customerPhone, phoneNumberId, token, booking, hotel) {
  const bookingRef = booking._id.toString().slice(-6).toUpperCase();
  const note = `HOTEL-${hotel.shortCode}-BOOK-${bookingRef}`;

  await Payment.findOneAndUpdate(
    { bookingId: booking._id },
    {
      hotelId: hotel._id,
      hotelName: hotel.name,
      bookingId: booking._id,
      bookingRef,
      customerPhone,
      guestName: booking.guestName,
      amount: booking.totalAmount,
      transactionNote: note,
      status: "pending",
      expiresAt: new Date(Date.now() + PAYMENT_EXPIRY_MS),
    },
    { upsert: true }
  );

  const upiLink = buildUpiLink({
    upiId: hotel.upiId,
    upiName: hotel.upiName,
    amount: booking.totalAmount,
    note,
  });

  // Render QR → base64 → imgbb → send as image
  const qrDataUrl = await QRCode.toDataURL(upiLink, { width: 600 });
  const qrBase64 = qrDataUrl.replace(/^data:image\/png;base64,/, "");
  const publicUrl = await uploadToImgbb(qrBase64);

  await sendImage(
    customerPhone,
    publicUrl,
    `Scan to pay ₹${booking.totalAmount?.toLocaleString()} to ${hotel.upiName}\n` +
      `After paying, send the payment screenshot here for instant verification.`,
    phoneNumberId,
    token
  );
}

/**
 * Full screenshot verification: WhatsApp media → imgbb → Python /verify-payment.
 * Returns the Python VerifyPaymentResponse.
 */
async function verifyScreenshot({ media, payment, hotel }) {
  const imageUrl = await uploadToImgbb(media.base64);
  return aiClient.verifyPayment({
    venueId: hotel._id.toString(),
    imageUrl,
    expectedAmount: payment.amount,
    expectedName: hotel.upiName,
    bookingRef: payment.bookingRef,
  });
}

module.exports = { sendPaymentQR, verifyScreenshot, uploadToImgbb, buildUpiLink };
