const { INTENT } = require("../config/constants");
const aiClient = require("../services/aiClient");
const { sendText, sendButtons } = require("../services/whatsappService");
const { sendRoomPhotos } = require("../services/menuService");
const { saveMessage, getHistory } = require("../services/chatService");
const { handleBooking } = require("./bookingFlow");
const Chat = require("../models/Chat");

async function handleText({
  ai,
  chat,
  hotel,
  customer,
  customerPhone,
  phoneNumberId,
  token,
}) {
  const {
    classifyResult,
    language,
    replyText,
    action,
    missingSlot,
    sessionData,
  } = ai;

  const { intent } = classifyResult;

  console.log("intent =", intent);
  switch (intent) {
    case INTENT.BOOKING:
    case INTENT.CHECK_AVAILABILITY:
      return handleBooking({
        classification: classifyResult,
        userMessage: ai.message ?? null,
        chat,
        hotel,
        customer,
        customerPhone,
        phoneNumberId,
        token,
      });

    case INTENT.SHOW_ROOMS:
      await sendRoomPhotos(customerPhone, phoneNumberId, token, hotel);
      await saveMessage(
        customerPhone,
        hotel._id,
        customer._id,
        "assistant",
        "Would you like to book one of these rooms?",
        hotel.timezone,
      );
      return;

    case INTENT.HOTEL_QUESTION:
      await sendText(customerPhone, replyText, phoneNumberId, token);
      await saveMessage(
        customerPhone,
        hotel._id,
        customer._id,
        "assistant",
        replyText,
        hotel.timezone,
      );
      return;

    case INTENT.HUMAN:
      await Chat.findOneAndUpdate(
        { phone: customerPhone, hotelId: hotel._id },
        { mode: "human" },
      );
      await sendText(
        customerPhone,
        "Connecting you with our team — someone will reply shortly.",
        phoneNumberId,
        token,
      );
      await saveMessage(
        customerPhone,
        hotel._id,
        customer._id,
        "Connecting you with our team — someone will reply shortly.",
        text,
        hotel.timezone,
      );
      return;

    case INTENT.GREETING:
      // console.log("Entered greeting case");
      try {
        const text = `Hello! I'm Inna, your assistant at ${hotel.name}. How can I help?`;
        await sendButtons(
          customerPhone,
          `Hello! I'm Inna, your assistant at ${hotel.name}. How can I help?`,
          [
            { id: "menu_book", title: "Book a Room" },
            { id: "menu_rooms", title: "View Rooms" },
            { id: "ask_question", title: "Ask a Question" },
          ],
          phoneNumberId,
          token,
        );
        await saveMessage(
          customerPhone,
          hotel._id,
          customer._id,
          "assistant",
          text,
          hotel.timezone,
        );
        return;

        // console.log("Buttons sent");
      } catch (err) {
        console.error("sendButtons error:", err.response?.data || err);
      }

      return;

    case INTENT.CHITCHAT:
      const text =
        "Happy to chat! I can help you book a room, view rooms, or answer questions about the hotel. What would you like?";

      await sendText(customerPhone, text, phoneNumberId, token);

      await saveMessage(
        customerPhone,
        hotel._id,
        customer._id,
        "assistant",
        text,
        hotel.timezone,
      );

      return;

    case INTENT.UNKNOWN:
    default:
      await sendButtons(
        customerPhone,
        "Sorry, I didn't quite catch that. Would you like to talk to our team?",
        [
          { id: "talk_human", title: "Talk to Human" },
          { id: "continue_bot", title: "Continue with Bot" },
        ],
        phoneNumberId,
        token,
      );
      await saveMessage(
        customerPhone,
        hotel._id,
        customer._id,
        "assistant",
        "Sorry, I didn't quite catch that. Would you like to talk to our team?(Unknown intent)",
        hotel.timezone,
      );
      return;
  }
}

/** RAG-powered hotel Q&A via Python /retrieve. Never hallucinate below threshold. */
async function handleHotelQuestion({
  userMessage,
  language,
  hotel,
  customer,
  customerPhone,
  phoneNumberId,
  token,
}) {
  const result = await aiClient.retrieve({
    venueId: hotel._id.toString(),
    query: userMessage,
    language: language?.language || "en",
  });

  if (result.below_threshold || !result.chunks.length) {
    return sendButtons(
      customerPhone,
      "I'm not certain about that one. Would you like to talk to our team?",
      [
        { id: "talk_human", title: "Talk to Human" },
        { id: "menu_book", title: "Book Room" },
      ],
      phoneNumberId,
      token,
    );
  }

  // Use the top chunk(s) as the grounded answer. (You can add an LLM "compose"
  // step here later, but grounded chunk text is safe and avoids hallucination.)
  const answer = result.chunks.map((c) => c.text).join("\n\n");
  await sendText(customerPhone, answer, phoneNumberId, token);
  await saveMessage(
    customerPhone,
    hotel._id,
    customer._id,
    "assistant",
    answer,
    hotel.timezone,
  );

  // If the top chunk has an image (e.g. room), send it too
  const withImage = result.chunks.find((c) => c.image_url);
  if (withImage?.image_url) {
    const { sendImage } = require("../services/whatsappService");
    await sendImage(
      customerPhone,
      withImage.image_url,
      "",
      phoneNumberId,
      token,
    );
  }
}

module.exports = { handleText };
