require("dotenv").config();
const connectDB = require("../config/database");

const { Worker } = require("bullmq");

const { connection } = require("../queues/messageQueue");

const { processIncomingMessage } = require("../services/messageProcessor");
console.log("Redis URL:", process.env.UPSTASH_REDIS_URL);
const worker = new Worker(
  "incoming-messages",

  async (job) => {
    await connectDB();
    console.log(
      `Processing message from ${job.data.value.messages?.[0]?.from}`,
    );

    try {
      await processIncomingMessage({
        value: job.data.value,
      });
    } catch (err) {
      console.error(err);
      throw err; // BullMQ will retry
    }

    console.log("Finished processing message.");
  },

  {
    connection,
  },
);

worker.on("completed", (job) => {
  console.log(`Job ${job.id} completed`);
});

worker.on("failed", (job, err) => {
  console.error(`Job ${job?.id} failed`, err);
});
