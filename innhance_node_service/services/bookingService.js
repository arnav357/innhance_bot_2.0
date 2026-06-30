const { parseDDMMYYYY } = require("../utils/date");

/**
 * Map Python BookingSlots (snake_case) → internal bookingFlow.data shape.
 */
function slotsToData(slots = {}) {
  const out = {};
  if (slots.room_type) out.roomType = slots.room_type;
  if (slots.check_in) out.checkIn = slots.check_in;
  if (slots.check_out) out.checkOut = slots.check_out;
  if (slots.guest_count != null) out.guests = slots.guest_count;
  if (slots.guest_name) out.name = slots.guest_name;
  if (slots.guest_phone) out.phone = slots.guest_phone;
  if (slots.rooms_count != null) out.roomsCount = slots.rooms_count;
  if (slots.plan_name) out.planName = slots.plan_name;
  return out;
}

function mergeBooking(oldData = {}, newData = {}) {
  const merged = { ...oldData };
  for (const [k, v] of Object.entries(newData)) {
    if (v !== null && v !== undefined && v !== "") merged[k] = v;
  }
  return merged;
}

/**
 * Returns the next missing field name, or null if complete.
 * Order defines the question sequence.
 */
function getMissing(data = {}, hotel) {
  if (!data.roomType) return "roomType";
  if (!data.name) return "name";
  if (!data.checkIn) return "checkIn";
  if (!data.checkOut) return "checkOut";
  if (!data.guests) return "guests";
  if (!data.roomsCount) return "roomsCount";

  const room = hotel.rooms?.find(
    (r) => r.name.toLowerCase() === String(data.roomType).toLowerCase()
  );

  if (room?.plans?.length && !data.planName) return "planName";

  return null;
}

function calcNights(checkIn, checkOut) {
  const ci = new Date(parseDDMMYYYY(checkIn) || checkIn);
  const co = new Date(parseDDMMYYYY(checkOut) || checkOut);
  return Math.max(1, Math.ceil((co - ci) / (1000 * 60 * 60 * 24)));
}

function calcTotal(hotel, data) {
  const room = hotel.rooms?.find(
    (r) => r.name.toLowerCase() === String(data.roomType).toLowerCase()
  );
  let pricePerNight = room?.price || 0;
  if (room?.plans?.length && data.planName) {
    const plan = room.plans.find(
      (p) => p.name.toLowerCase() === String(data.planName).toLowerCase()
    );
    if (plan?.price) pricePerNight = plan.price;
  }
  const nights = calcNights(data.checkIn, data.checkOut);
  return pricePerNight * nights * (data.roomsCount || 1);
}

module.exports = { slotsToData, mergeBooking, getMissing, calcNights, calcTotal };
