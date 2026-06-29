// services/redis.js

const IORedis = require("ioredis");

const redis = new IORedis(process.env.UPSTASH_REDIS_URL, {
    maxRetriesPerRequest: null,
});

module.exports = redis;