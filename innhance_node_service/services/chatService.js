const Chat = require("../models/Chat");
const { DateTime } = require("luxon");

async function saveMessage(phone, hotelId, customerId, role, content, timezone = "Asia/Kolkata") {
  const now = DateTime.now().setZone(timezone);
  await Chat.findOneAndUpdate(
    { phone, hotelId },
    {
      $set: {
        customerId,
        time: now.toFormat("hh:mm a"),
        lastMessageDate: now.toFormat("dd LLL yyyy"),
        lastMessageTimestamp: new Date(),
      },
      $push: {
        messages: {
          role,
          content,
          time: now.toFormat("hh:mm a"),
          date: now.toFormat("dd LLL yyyy"),
          timestamp: new Date(),
        },
      },
    },
    { upsert: true }
  );
}

/** Returns [{ role, content }] for the AI history param */
async function getHistory(phone, hotelId, limit = 12) {
  const chat = await Chat.findOne({ phone, hotelId }).lean();
  if (!chat?.messages?.length) return [];
  return chat.messages.slice(-limit).map((m) => ({ role: m.role, content: m.content }));
}

async function isFirstMessage(phone, hotelId) {
  const chat = await Chat.findOne({ phone, hotelId }).lean();
  return !chat || !chat.messages || chat.messages.length === 0;
}

module.exports = { saveMessage, getHistory, isFirstMessage };
