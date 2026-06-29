const express = require("express");
const router = express.Router();

const Hotel = require("../models/Hotel");
const Customer = require("../models/Customer");
const Chat = require("../models/Chat");

const { WHATSAPP_VERIFY_TOKEN, WHATSAPP_TOKEN } = require("../config/env");
const { STALE_MESSAGE_MS } = require("../config/constants");
// const { normalizePhone } = require("../utils/phone");
const {
  saveMessage,
  getHistory,
  isFirstMessage,
} = require("../services/chatService");
const aiClient = require("../services/aiClient");
const { sendText } = require("../services/whatsappService");
const { handleImage } = require("../flows/imageFlow");
const { handleInteractive } = require("../flows/interactiveFlow");
const { handleText } = require("../flows/textFlow");

// ── Verify ──────────────────────────────────────────────
router.get("/", (req, res) => {
  if (
    req.query["hub.mode"] === "subscribe" &&
    req.query["hub.verify_token"] === WHATSAPP_VERIFY_TOKEN
  ) {
    return res.status(200).send(req.query["hub.challenge"]);
  }
  return res.sendStatus(403);
});

// ── Receive ─────────────────────────────────────────────
router.post("/", async (req, res) => {
  res.sendStatus(200); // ACK immediately

  try {
    const value = req.body.entry?.[0]?.changes?.[0]?.value;
    if (value?.statuses || !value?.messages) return;

    const message = value.messages[0];
    const messageId = message.id;
    const phoneNumberId = value.metadata?.phone_number_id;
    const customerPhone = message.from;
    if (customerPhone === phoneNumberId) return;

    // Drop stale messages
    if (Date.now() - parseInt(message.timestamp) * 1000 > STALE_MESSAGE_MS)
      return;

    const hotel = await Hotel.findOne({ whatsappPhoneNumberId: phoneNumberId });
    if (!hotel) return;
    const token = hotel.whatsappToken || WHATSAPP_TOKEN;
    if (!token) return;

    const customer = await Customer.findOneAndUpdate(
      { phone: customerPhone, hotelId: hotel._id },
      { lastSeen: new Date() },
      { upsert: true, new: true },
    );
    const chat = await Chat.findOne({
      phone: customerPhone,
      hotelId: hotel._id,
    });

    const ctx = {
      message,
      hotel,
      customer,
      chat,
      customerPhone,
      phoneNumberId,
      token,
    };

    // 1. Image (payment screenshot)
    if (message.type === "image") return handleImage(ctx);

    // 2. Only text/interactive beyond here
    if (!["text", "interactive"].includes(message.type)) {
      return sendText(
        customerPhone,
        "I can process text, images, and the menu buttons.",
        phoneNumberId,
        token,
      );
    }

    // Extract message content + interactive id
    let userMessage = "";
    let interactiveId = "";
    if (message.type === "text") {
      userMessage = message.text.body.trim();
    } else {
      const i = message.interactive;
      const reply = i.button_reply || i.list_reply;
      interactiveId = reply.id;
      userMessage = reply.title;
    }

    // Live dashboard refresh
    req.app
      .get("io")
      ?.to(hotel._id.toString())
      .emit("refreshChats", { hotelId: hotel._id, phone: customerPhone });

    // If a human is handling this chat, don't let the bot interfere (except 'back_to_bot')
    if (chat?.mode === "human" && interactiveId !== "back_to_bot") {
      await saveMessage(
        customerPhone,
        hotel._id,
        customer._id,
        "user",
        userMessage,
        hotel.timezone,
      );
      return;
    }

    // Save the inbound user message
    await saveMessage(
      customerPhone,
      hotel._id,
      customer._id,
      "user",
      interactiveId
        ? `[Interactive:${interactiveId}] ${userMessage}`
        : userMessage,
      hotel.timezone,
    );

    // 3. Interactive button/list → deterministic routing
    if (message.type === "interactive") {
      const handled = await handleInteractive({
        ...ctx,
        interactiveId,
        userMessage,
      });
      if (handled) return; // if not handled, fall through to text logic
    }

    if (!userMessage) return;

    // 4. Detect language + classify intent via Python service
    const history = await getHistory(customerPhone, hotel._id);

    const ai = await aiClient.processMessage({
      venueId: hotel._id.toString(),
      hotelName: hotel.name,
      message: userMessage,
      history,
      sessionData: chat?.bookingFlow?.data || {},
      roomHasMultiplePlans: hotel.rooms.some((room) => room.plans?.length > 1),
    });
    console.log("========== AI RESULT ==========");
    console.dir(ai, { depth: null });
    console.log("===============================");

    // 5. Route by intent
    console.log("Action:", ai.action);
    console.log("Intent:", ai.classifyResult?.intent);
    console.log("Reply:", ai.replyText);
    console.log("Missing Slot:", ai.missingSlot);
    return handleText({
      ai,
      chat,
      hotel,
      customer,
      customerPhone,
      phoneNumberId,
      token,
    });
  } catch (err) {
    console.error("Webhook error:", err.message, err.stack);
  }
});

module.exports = router;
