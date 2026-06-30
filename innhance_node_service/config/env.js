require("dotenv").config();

const env = {
  PORT: process.env.PORT || 8080,

  // Python AI service
  AI_SERVICE_URL: process.env.AI_SERVICE_URL || "http://localhost:8000",
  AI_SERVICE_TIMEOUT_MS: parseInt(process.env.AI_SERVICE_TIMEOUT_MS || "20000", 10),

  // WhatsApp
  WHATSAPP_TOKEN: process.env.WHATSAPP_TOKEN,
  WHATSAPP_VERIFY_TOKEN: process.env.WHATSAPP_VERIFY_TOKEN,
  WHATSAPP_API_VERSION: process.env.WHATSAPP_API_VERSION || "v21.0",

  // Image hosting (needed because Python /verify-payment wants a public URL)
  IMGBB_API_KEY: process.env.IMGBB_API_KEY,

  MONGO_URI: process.env.MONGODB_URI,
};

const required = ["AI_SERVICE_URL", "WHATSAPP_VERIFY_TOKEN", "MONGO_URI"];
for (const key of required) {
  if (!env[key]) console.warn(`⚠️  Missing required env var: ${key}`);
}

module.exports = env;
