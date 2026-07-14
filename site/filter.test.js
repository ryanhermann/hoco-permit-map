"use strict";
const test = require("node:test");
const assert = require("node:assert");
const Filters = require("./filter.js");

const permit = (over) => Object.assign({
  id: "B26000127", type: "Commercial Addition Permit",
  category: "Commercial", owner: "HOCK/BAVAR", contractor: "COMPLETE SVS",
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

test("date range is inclusive by month", () => {
  assert.ok(Filters.matches(permit(), { ...EMPTY, from: "2026-06", to: "2026-06" }));
  assert.ok(!Filters.matches(permit(), { ...EMPTY, to: "2026-05" }));
  assert.ok(!Filters.matches(permit(), { ...EMPTY, from: "2026-07" }));
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
