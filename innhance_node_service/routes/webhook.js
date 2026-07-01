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
const redis = require("../services/redis");
const { messageQueue } = require("../queues/messageQueue");

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
    console.log("📩 Webhook hit");
    const value = req.body.entry?.[0]?.changes?.[0]?.value;
    if (value?.statuses || !value?.messages) return;

    const message = value.messages[0];
    const messageId = message.id;
    console.log("📨 Message ID:", messageId);
    const key = `wa:msg:${messageId}`;
    console.log(key);
    const exists = await redis.get(key);

    console.log("4. Redis GET completed");

    if (exists) {
      console.log("Duplicate message ignored:", messageId);
      return;
    }

    console.log("5. Redis SET completed");

    await redis.set(key, "1", "EX", 300);
    console.log("Adding job to queue...");
    await messageQueue.add("incoming", {
      value,
    });
    console.log("Job queued:");
    return;
  } catch (err) {
    console.error("Webhook error:", err.message, err.stack);
  }
});

module.exports = router;
