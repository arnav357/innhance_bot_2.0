const { STALE_MESSAGE_MS } = require("../config/constants");
const { WHATSAPP_TOKEN } = require("../config/env");
const aiClient = require("./aiClient");
const { sendText } = require("./whatsappService");
const { saveMessage, getHistory } = require("./chatService");

const { handleImage } = require("../flows/imageFlow");
const { handleInteractive } = require("../flows/interactiveFlow");
const { handleText } = require("../flows/textFlow");

const Hotel = require("../models/Hotel");
const Customer = require("../models/Customer");
const Chat = require("../models/Chat");

async function processIncomingMessage({ value }) {
//     console.log(
//   `Processing message from ${job.data.value.messages?.[0]?.from}`
// );
console.log("Entering processIncomingMessage");
  const message = value.messages?.[0];
  if (!message) return;

  const phoneNumberId = value.metadata?.phone_number_id;
  const customerPhone = message.from;
  if (customerPhone === phoneNumberId) return;

  // Drop stale messages
  if (Date.now() - parseInt(message.timestamp) * 1000 > STALE_MESSAGE_MS){
    console.log("Dropping stale message");
    return;}

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
  if (ai.sessionData) {
    await Chat.findOneAndUpdate(
      {
        phone: customerPhone,
        hotelId: hotel._id,
      },
      {
        "bookingFlow.data": ai.sessionData,
      },
    );
  }

  console.log("========== AI RESULT ==========");
  console.dir(ai, { depth: null });
  console.log("===============================");

  // 5. Route by intent
  console.log("Action:", ai.action);
  console.log("Intent:", ai.classifyResult?.intent);
  console.log("Reply:", ai.replyText);
  console.log("Missing Slot:", ai.missingSlot);

  const freshChat = await Chat.findOne({
    phone: customerPhone,
    hotelId: hotel._id,
  });

  return handleText({
    ai,
    chat: freshChat,
    hotel,
    customer,
    customerPhone,
    phoneNumberId,
    token,
  });
}

module.exports = {
  processIncomingMessage,
};
