import assert from "node:assert/strict";
import test from "node:test";
import { dashboardState, filterGames, groupSharedEvents, loadSnapshot, validateSnapshot } from "../src/snapshot.js";

const now = Date.parse("2026-11-19T00:00:00Z");
const game = {
  title: "Falcons vs. Foxes", sport: "HOCKEY", starts_at: "2026-11-19T02:00:00Z",
  outcomes: [{ name: "Falcons", probability: 0.58 }, { name: "Foxes", probability: 0.42 }],
};
const quote = { valid_until: "2026-11-19T00:01:00Z" };
const snapshot = { source: "live", generated_at: new Date(now).toISOString(), odds: [game], opportunities: [quote] };

test("several contracts for one event use a single shared-event group", () => {
  const first = { event_id: "office", event_title: "Next press secretary", kalshi_id: "K-1" };
  const movie = { event_id: "rating", event_title: "Film rating", kalshi_id: "K-2" };
  const second = { ...first, kalshi_id: "K-3" };
  assert.deepEqual(groupSharedEvents([first, movie, second]), [
    { id: "office", title: "Next press secretary", pairs: [first, second] },
    { id: "rating", title: "Film rating", pairs: [movie] },
  ]);
});

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
  assert.deepEqual(await loadSnapshot(signal, now, request, "../snapshot.json"), newer);
  assert.deepEqual(calls, [
    ["snapshot.json", { signal, cache: "no-store" }],
    ["snapshot.json?refresh=" + now, { signal, cache: "no-store" }],
    ["../snapshot.json?refresh=" + now, { signal, cache: "no-store" }],
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

test("far-future filtering applies to all cross-venue sections and daily ROI sorts numerically", () => {
  const soon = { ...quote, closes_at: "2026-11-21T00:00:00Z", daily_roi_pct: "10", net_return_pct: "20" };
  const later = { ...quote, closes_at: "2027-12-31T00:00:00Z", daily_roi_pct: "2", net_return_pct: "80" };
  const far = { ...later, closes_at: "2027-06-01T00:00:00Z", capital_until: "2028-01-20T00:00:00Z" };
  const data = validateSnapshot({ ...snapshot, opportunities: [later, soon], matched_pairs: [soon, far],
    cancellation_only: [soon], shared_events: [far] });
  assert.equal(dashboardState(data, now).opportunities[0].daily_roi_pct, "10");
  assert.equal(dashboardState(data, now, 0, "net_return_pct").opportunities[0].net_return_pct, "80");
  const future = dashboardState(data, now, 365);
  assert.equal(future.opportunities.length, 1);
  assert.deepEqual(future.matchedPairs, [far]);
  assert.deepEqual(future.sharedEvents, [far]);
  assert.deepEqual(future.cancellationOnly, []);
  assert.deepEqual(dashboardState(data, Date.parse(far.closes_at)).sharedEvents, []);
});
