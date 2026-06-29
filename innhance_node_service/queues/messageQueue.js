const { Queue } = require("bullmq");
const IORedis = require("ioredis");

const connection = new IORedis(
  process.env.UPSTASH_REDIS_URL,
  {
    maxRetriesPerRequest: null,
  }
);

const messageQueue = new Queue("incoming-messages", {
  connection,
  defaultJobOptions: {
    removeOnComplete: 100,
    removeOnFail: 100,
    attempts: 3,
    backoff: {
      type: "exponential",
      delay: 2000,
    },
  },
});

module.exports = {
  messageQueue,
  connection,
};