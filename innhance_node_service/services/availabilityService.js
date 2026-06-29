const Booking = require("../models/Booking");
const { parseDDMMYYYY } = require("../utils/date");

async function checkRoomAvailability({ hotel, roomType, checkIn, checkOut, requestedRooms = 1 }) {
  const room = hotel.rooms.find((r) => r.name.toLowerCase() === roomType.toLowerCase());
  if (!room) return { available: false, remainingRooms: 0 };

  const ci = new Date(parseDDMMYYYY(checkIn) || checkIn);
  const co = new Date(parseDDMMYYYY(checkOut) || checkOut);

  const bookings = await Booking.find({
    hotelId: hotel._id,
    roomType: new RegExp(`^${roomType}$`, "i"),
    status: "confirmed",
  }).lean();

  const overlapping = bookings.filter((b) => {
    return new Date(b.checkIn) < co && new Date(b.checkOut) > ci;
  });

  const alreadyBooked = overlapping.reduce((sum, b) => sum + (b.numberOfRooms || 1), 0);
  const remainingRooms = (room.totalRooms || 0) - alreadyBooked;

  return { available: remainingRooms >= requestedRooms, remainingRooms };
}

module.exports = { checkRoomAvailability };
