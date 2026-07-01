const mongoose = require("mongoose");

async function connectDB() {
  if (mongoose.connection.readyState === 1) {
    return;
  }

  await mongoose.connect(process.env.MONGODB_URI);

  console.log("✅ MongoDB Connected");

  try {
    await mongoose.connection.syncIndexes();
    console.log("✅ MongoDB indexes synced");
  } catch (err) {
    console.log("⚠️ MongoDB index sync skipped:", err.message);
  }
}

module.exports = connectDB;