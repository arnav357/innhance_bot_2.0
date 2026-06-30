const axios = require("axios");
const { WHATSAPP_API_VERSION } = require("../config/env");

function api(phoneNumberId, token) {
  return axios.create({
    baseURL: `https://graph.facebook.com/${WHATSAPP_API_VERSION}/${phoneNumberId}`,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  });
}

async function send(phoneNumberId, token, payload) {
  try {
    console.log("Sending payload:");
    console.dir(payload, { depth: null });

    const response = await api(phoneNumberId, token).post("/messages", {
      messaging_product: "whatsapp",
      ...payload,
    });

    console.log("WhatsApp Success:");
    console.dir(response.data, { depth: null });

    return response.data;
  } catch (err) {
    console.error("WhatsApp Error Status:", err.response?.status);
    console.error("WhatsApp Error Data:", err.response?.data);
    throw err;
  }
}

const sendText = (to, body, phoneNumberId, token) =>
  send(phoneNumberId, token, { to, type: "text", text: { body } });

const sendImage = (to, link, caption, phoneNumberId, token) =>
  send(phoneNumberId, token, { to, type: "image", image: { link, caption } });

const sendVideo = (to, link, caption, phoneNumberId, token) =>
  send(phoneNumberId, token, { to, type: "video", video: { link, caption } });

const sendButtons = (to, body, buttons, phoneNumberId, token) =>
  send(phoneNumberId, token, {
    to,
    type: "interactive",
    interactive: {
      type: "button",
      body: { text: body },
      action: {
        buttons: buttons.slice(0, 3).map((b) => ({
          type: "reply",
          reply: { id: b.id, title: b.title.slice(0, 20) },
        })),
      },
    },
  });

const sendList = (to, body, buttonText, sections, phoneNumberId, token) =>
  send(phoneNumberId, token, {
    to,
    type: "interactive",
    interactive: {
      type: "list",
      body: { text: body },
      action: { button: buttonText, sections },
    },
  });

/** Download WhatsApp media and return { base64, mimeType, buffer } */
async function fetchMedia(mediaId, token) {
  try {
    const meta = await axios.get(
      `https://graph.facebook.com/${WHATSAPP_API_VERSION}/${mediaId}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const bin = await axios.get(meta.data.url, {
      headers: { Authorization: `Bearer ${token}` },
      responseType: "arraybuffer",
    });
    const buffer = Buffer.from(bin.data);
    return {
      buffer,
      base64: buffer.toString("base64"),
      mimeType: meta.data.mime_type || "image/jpeg",
    };
  } catch (err) {
    console.error("fetchMedia error:", err.message);
    return null;
  }
}

module.exports = { sendText, sendImage, sendVideo, sendButtons, sendList, fetchMedia };
