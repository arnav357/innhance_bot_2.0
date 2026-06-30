const mongoose = require('mongoose');

const customerSchema = new mongoose.Schema({
  phone: { type: String, required: true },      // WhatsApp number
  hotelId: { type: mongoose.Schema.Types.ObjectId, ref: 'Hotel', required: true },

  name: { type: String },
  totalBookings: { type: Number, default: 0 },
  lastSeen: { type: Date, default: Date.now },

}, { timestamps: true });

// One customer per hotel (same phone can talk to multiple hotels)
customerSchema.index({ phone: 1, hotelId: 1 }, { unique: true });

module.exports = mongoose.model('Customer', customerSchema);