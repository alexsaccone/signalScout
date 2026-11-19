import assert from "node:assert/strict";
import test from "node:test";
import { dashboardState, filterGames, loadSnapshot, validateSnapshot } from "../src/snapshot.js";

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

test("manual refresh bypasses browser and CDN caches and uses the new snapshot", async () => {
  const { signal } = new AbortController();
  const newer = { ...snapshot, generated_at: new Date(now + 60000).toISOString(), odds: [] };
  const calls = [];
  const request = async (url, options) => {
    calls.push([url, options]);
    return { ok: true, json: async () => calls.length === 1 ? snapshot : newer };
  };
  assert.deepEqual(await loadSnapshot(signal, null, request), snapshot);
  assert.deepEqual(await loadSnapshot(signal, now, request), newer);
  assert.deepEqual(calls, [
    ["snapshot.json", { signal, cache: "no-store" }],
    ["snapshot.json?refresh=" + now, { signal, cache: "no-store" }],
  ]);
});

test("refresh rejects missing and malformed snapshots", async () => {
  const { signal } = new AbortController();
  await assert.rejects(loadSnapshot(signal, now, async () => ({ ok: false })), /unavailable/);
  await assert.rejects(loadSnapshot(signal, now, async () => ({ ok: true, json: async () => ({}) })), /Invalid/);
});

test("shows cancellation differences separately while both contracts are open", () => {
  const row = { closes_at: "2026-11-19T00:01:00Z" };
  const withCancellation = validateSnapshot({ ...snapshot, cancellation_only: [row] });
  assert.deepEqual(dashboardState(withCancellation, now).cancellationOnly, [row]);
  assert.deepEqual(dashboardState(withCancellation, now + 60000).cancellationOnly, []);
  assert.deepEqual(dashboardState(snapshot, now).cancellationOnly, []);
});

test("matched pairs appear without quotes and expire at their trading cutoff", () => {
  const row = { kalshi_id: "K-1", polymarket_id: "P-1", closes_at: "2026-11-19T00:01:00Z" };
  const withMatches = validateSnapshot({ ...snapshot, opportunities: [], matched_pairs: [row] });
  assert.deepEqual(dashboardState(withMatches, now).matchedPairs, [row]);
  assert.deepEqual(dashboardState(withMatches, now + 60000).matchedPairs, []);
  assert.deepEqual(dashboardState(snapshot, now).matchedPairs, []);
});
