const { slotsToData, mergeBooking, getMissing } = require("../services/bookingService");

describe("slotsToData", () => {
  test("maps each slot field individually", () => {
    expect(slotsToData({ room_type: "Deluxe" })).toEqual({ roomType: "Deluxe" });
    expect(slotsToData({ check_in: "01-07-2026" })).toEqual({ checkIn: "01-07-2026" });
    expect(slotsToData({ check_out: "03-07-2026" })).toEqual({ checkOut: "03-07-2026" });
    expect(slotsToData({ guest_count: 2 })).toEqual({ guests: 2 });
    expect(slotsToData({ guest_name: "Hey There" })).toEqual({ name: "Hey There" });
    expect(slotsToData({ guest_phone: "9999999999" })).toEqual({ phone: "9999999999" });
    expect(slotsToData({ rooms_count: 3 })).toEqual({ roomsCount: 3 });
    expect(slotsToData({ plan_name: "Breakfast Included" })).toEqual({ planName: "Breakfast Included" });
  });

  test("maps multiple slots at once", () => {
    const slots = {
      room_type: "Suite",
      guest_count: 4,
      rooms_count: 2,
      plan_name: "All Inclusive",
    };
    expect(slotsToData(slots)).toEqual({
      roomType: "Suite",
      guests: 4,
      roomsCount: 2,
      planName: "All Inclusive",
    });
  });

  test("skips null, undefined, and empty string values", () => {
    const slots = {
      room_type: null,
      check_in: undefined,
      check_out: "",
      guest_name: null,
      rooms_count: undefined,
      plan_name: "",
    };
    expect(slotsToData(slots)).toEqual({});
  });

  test("handles a full classifier-shaped payload", () => {
    const slots = {
      room_type: "Deluxe",
      check_in: "01-07-2026",
      check_out: "05-07-2026",
      guest_count: 2,
      guest_name: "Hey There",
      guest_phone: "9876543210",
      rooms_count: 1,
      plan_name: "Room Only",
    };
    expect(slotsToData(slots)).toEqual({
      roomType: "Deluxe",
      checkIn: "01-07-2026",
      checkOut: "05-07-2026",
      guests: 2,
      name: "Hey There",
      phone: "9876543210",
      roomsCount: 1,
      planName: "Room Only",
    });
  });
});

describe("mergeBooking — multi-turn persistence with slotsToData", () => {
  test("roomsCount set in turn 1 survives into turn 2 merge", () => {
    const turn1 = mergeBooking({}, slotsToData({ rooms_count: 2 }));
    expect(turn1).toEqual({ roomsCount: 2 });

    const turn2 = mergeBooking(turn1, slotsToData({ room_type: "Deluxe" }));
    expect(turn2).toEqual({ roomsCount: 2, roomType: "Deluxe" });
  });

  test("roomsCount in turn 1, planName in turn 2 — both survive in final merge", () => {
    let data = {};
    data = mergeBooking(data, slotsToData({ rooms_count: 3 }));
    data = mergeBooking(data, slotsToData({ plan_name: "Breakfast Included" }));

    expect(data).toEqual({
      roomsCount: 3,
      planName: "Breakfast Included",
    });
  });

  test("three-turn conversation: roomsCount, then planName, then unrelated field — all persist", () => {
    let data = {};
    data = mergeBooking(data, slotsToData({ rooms_count: 1, room_type: "Suite" }));
    data = mergeBooking(data, slotsToData({ plan_name: "All Inclusive" }));
    data = mergeBooking(data, slotsToData({ guest_name: "Hey There" }));

    expect(data).toEqual({
      roomsCount: 1,
      roomType: "Suite",
      planName: "All Inclusive",
      name: "Hey There",
    });
  });
});

describe("getMissing", () => {
  const hotelWithPlans = {
    rooms: [
      { name: "Deluxe", price: 5000, plans: [{ name: "Breakfast Included", price: 5500 }] },
    ],
  };

  test('returns "roomsCount" when all earlier slots are filled but roomsCount is missing', () => {
    const data = {
      roomType: "Deluxe",
      name: "Hey There",
      checkIn: "01-07-2026",
      checkOut: "03-07-2026",
      guests: 2,
    };
    expect(getMissing(data, hotelWithPlans)).toBe("roomsCount");
  });

  test('returns "planName" (not "roomsCount") once roomsCount is set, for a hotel where the room has plans', () => {
    const data = {
      roomType: "Deluxe",
      name: "Hey There",
      checkIn: "01-07-2026",
      checkOut: "03-07-2026",
      guests: 2,
      roomsCount: 1,
    };
    expect(getMissing(data, hotelWithPlans)).toBe("planName");
  });

  test("returns null only once every slot including roomsCount is present", () => {
    const data = {
      roomType: "Deluxe",
      name: "Hey There",
      checkIn: "01-07-2026",
      checkOut: "03-07-2026",
      guests: 2,
      roomsCount: 1,
      planName: "Breakfast Included",
    };
    expect(getMissing(data, hotelWithPlans)).toBeNull();
  });
});