const MAX_AGE = 3 * 60 * 60 * 1000;
const DAY = 24 * 60 * 60 * 1000;

export function validateSnapshot(snapshot) {
  if (!snapshot || !["live", "fixture"].includes(snapshot.source) ||
      !Number.isFinite(Date.parse(snapshot.generated_at)) ||
      !Array.isArray(snapshot.odds) || !Array.isArray(snapshot.opportunities) ||
      (snapshot.cancellation_only !== undefined && !Array.isArray(snapshot.cancellation_only)) ||
      (snapshot.shared_events !== undefined && !Array.isArray(snapshot.shared_events)) ||
      (snapshot.matched_pairs !== undefined && !Array.isArray(snapshot.matched_pairs))) {
    throw new Error("Invalid dashboard snapshot");
  }
  return snapshot;
}

export async function loadSnapshot(signal, refreshAt, request = globalThis.fetch, path = "snapshot.json") {
  const url = refreshAt === null ? path : path + "?refresh=" + refreshAt;
  const response = await request(url, { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Snapshot unavailable");
  return validateSnapshot(await response.json());
}

export function dashboardState(snapshot, now, minimumDays = 0, sort = "daily_roi_pct") {
  const generated = Date.parse(snapshot.generated_at);
  const fixture = snapshot.source === "fixture";
  const asOf = fixture ? generated : now;
  const stale = !fixture && now - generated >= MAX_AGE;
  const games = snapshot.odds.filter((game) => Date.parse(game.starts_at) > asOf);
  const inWindow = (row) => !minimumDays ||
    Date.parse(row.capital_until ?? row.closes_at) > asOf + minimumDays * DAY;
  const open = (row) => Date.parse(row.closes_at) > asOf && inWindow(row);
  const opportunities = snapshot.opportunities.filter((row) =>
    (!row.closes_at || Date.parse(row.closes_at) > asOf) && inWindow(row)).map((row) => ({
    ...row,
    expired: stale || !(Date.parse(row.valid_until) > asOf),
  })).sort((a, b) => Number(b[sort] ?? -Infinity) - Number(a[sort] ?? -Infinity));
  const cancellationOnly = (snapshot.cancellation_only ?? []).filter(open);
  const matchedPairs = (snapshot.matched_pairs ?? []).filter(open);
  const sharedEvents = (snapshot.shared_events ?? []).filter(open);
  return { fixture, stale, games, opportunities, cancellationOnly, matchedPairs, sharedEvents };
}

export function filterGames(games, query, sport) {
  const needle = query.trim().toLocaleLowerCase();
  return games.filter((game) => (!sport || game.sport === sport) &&
    [game.title, game.sport, ...game.outcomes.map((outcome) => outcome.name)]
      .some((value) => value.toLocaleLowerCase().includes(needle)));
}
