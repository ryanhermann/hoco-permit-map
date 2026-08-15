"use strict";
const test = require("node:test");
const assert = require("node:assert");
const Filters = require("./filter.js");

const permit = (over) => Object.assign({
  id: "B26000127", type: "Commercial Addition Permit",
  category: "Commercial", contractor: "COMPLETE SVS",
  description: "EXTERIOR STAIRCASE", address: "10335 GUILFORD RD, JESSUP, MD 20794",
  issued: "2026-06-11",
}, over);

const EMPTY = { q: "", from: "", to: "", cat: "All", types: [] };

test("empty state matches everything", () => {
  assert.ok(Filters.matches(permit(), EMPTY));
});

test("query matches across fields, case-insensitive", () => {
  assert.ok(Filters.matches(permit(), { ...EMPTY, q: "staircase" }));
  assert.ok(Filters.matches(permit(), { ...EMPTY, q: "guilford" }));
  assert.ok(Filters.matches(permit(), { ...EMPTY, q: "b26000127" }));
  assert.ok(!Filters.matches(permit(), { ...EMPTY, q: "zebra" }));
});

test("date range is inclusive by day", () => {
  assert.ok(Filters.matches(permit(), { ...EMPTY, from: "2026-06-11", to: "2026-06-11" }));
  assert.ok(!Filters.matches(permit(), { ...EMPTY, to: "2026-06-10" }));
  assert.ok(!Filters.matches(permit(), { ...EMPTY, from: "2026-06-12" }));
});

test("legacy month ranges still include the whole month", () => {
  assert.ok(Filters.matches(permit(), { ...EMPTY, from: "2026-06", to: "2026-06" }));
  assert.deepStrictEqual(Filters.normalizeRange("2026-02", "2026-02"), {
    from: "2026-02-01", to: "2026-02-28",
  });
});

test("last-month shortcuts use complete calendar months through the newest date", () => {
  assert.deepStrictEqual(Filters.lastMonths("2026-07-31", 1), {
    from: "2026-07-01", to: "2026-07-31",
  });
  assert.deepStrictEqual(Filters.lastMonths("2026-01-15", 3), {
    from: "2025-11-01", to: "2026-01-15",
  });
  assert.deepStrictEqual(Filters.lastMonths("2026-07-31", 12, "2026-01-02"), {
    from: "2026-01-02", to: "2026-07-31",
  });
});

test("category and type filters", () => {
  assert.ok(!Filters.matches(permit(), { ...EMPTY, cat: "Residential" }));
  assert.ok(Filters.matches(permit(), { ...EMPTY, types: ["Commercial Addition Permit"] }));
  assert.ok(!Filters.matches(permit(), { ...EMPTY, types: ["Porch Permit"] }));
});

test("apply filters a list", () => {
  const list = [permit(), permit({ id: "X", category: "Residential" })];
  assert.strictEqual(Filters.apply(list, { ...EMPTY, cat: "Residential" }).length, 1);
});

test("hash round-trips state", () => {
  const state = { q: "solar panels", from: "2026-01", to: "2026-06",
                  cat: "Residential", types: ["Porch Permit", "Deck"] };
  assert.deepStrictEqual(Filters.fromHash(Filters.toHash(state)), state);
});

test("empty state serializes to empty hash", () => {
  assert.strictEqual(Filters.toHash(EMPTY), "");
  assert.deepStrictEqual(Filters.fromHash(""), EMPTY);
});

test("fromHash tolerates garbage without throwing", () => {
  assert.deepStrictEqual(Filters.fromHash("#%GG"), EMPTY);
  assert.deepStrictEqual(Filters.fromHash("#q=%GG"), { ...EMPTY, q: "%GG" });
  assert.deepStrictEqual(Filters.fromHash("#types="), EMPTY);
});
