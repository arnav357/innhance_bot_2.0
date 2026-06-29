const { Worker } = require("bullmq");

const {
  connection,
} = require("../queues/messageQueue");

const {
  classifyIntent,
} = require("../services/aiService");

const worker = new Worker(
  "incoming-messages",

  async (job) => {
    console.log(
      "Processing:",
      job.data.message
    );

    const intent = await classifyIntent({
      venueId: job.data.hotelId,
      message: job.data.message,
      history: job.data.history || [],
      language: "en",
    });

    console.log(
      "Intent:",
      JSON.stringify(intent, null, 2)
    );

    return intent;
  },

  {
    connection,
  }
);

worker.on("completed", (job) => {
  console.log(
    `Job ${job.id} completed`
  );
});

worker.on("failed", (job, err) => {
  console.error(
    `Job ${job?.id} failed`,
    err
  );
});