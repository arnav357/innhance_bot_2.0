const IORedis = require("ioredis");

console.log("Redis URL:", process.env.UPSTASH_REDIS_URL);

const redis = new IORedis(process.env.UPSTASH_REDIS_URL, {
  maxRetriesPerRequest: null,
});

redis.on("connect", () => {
  console.log("✅ Redis CONNECT");
});

redis.on("ready", () => {
  console.log("✅ Redis READY");
});

redis.on("error", (err) => {
  console.error("❌ Redis ERROR:", err);
});

redis.on("close", () => {
  console.log("❌ Redis CLOSED");
});

module.exports = redis;