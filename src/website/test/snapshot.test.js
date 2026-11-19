import assert from "node:assert/strict";
import test from "node:test";
import { dashboardState, filterGames, validateSnapshot } from "../src/snapshot.js";

const now = Date.parse("2026-11-19T00:00:00Z");
const game = {
  title: "Falcons vs. Foxes", sport: "HOCKEY", starts_at: "2026-11-19T02:00:00Z",
  outcomes: [{ name: "Falcons", probability: 0.58 }, { name: "Foxes", probability: 0.42 }],
};
const quote = { valid_until: "2026-11-19T00:01:00Z" };
const snapshot = { source: "live", generated_at: new Date(now).toISOString(), odds: [game], opportunities: [quote] };

test("shows populated data and expires individual quotes", () => {
  assert.deepEqual(dashboardState(validateSnapshot(snapshot), now).games, [game]);
  assert.equal(dashboardState(snapshot, now).opportunities[0].expired, false);
  assert.equal(dashboardState(snapshot, now + 60000).opportunities[0].expired, true);
});

test("stale snapshots and empty collections have separate states", () => {
  const stale = dashboardState(snapshot, now + 3 * 60 * 60 * 1000);
  assert.equal(stale.stale, true);
  assert.equal(stale.opportunities[0].expired, true);
  assert.deepEqual(stale.games, []);
  assert.equal(dashboardState({ ...snapshot, odds: [], opportunities: [] }, now).stale, false);
});

test("fixture time is frozen and explicitly identified", () => {
  const fixture = dashboardState({ ...snapshot, source: "fixture" }, now + 86400000);
  assert.equal(fixture.fixture, true);
  assert.equal(fixture.stale, false);
  assert.equal(fixture.opportunities[0].expired, false);
  assert.deepEqual(fixture.games, [game]);
});

test("search and league filters combine and malformed snapshots are rejected", () => {
  assert.deepEqual(filterGames([game], "  FOXES ", "HOCKEY"), [game]);
  assert.deepEqual(filterGames([game], "Falcons", "NFL"), []);
  assert.throws(() => validateSnapshot({ ...snapshot, generated_at: "invalid" }), /Invalid/);
});
