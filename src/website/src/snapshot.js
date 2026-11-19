const MAX_AGE = 3 * 60 * 60 * 1000;

export function validateSnapshot(snapshot) {
  if (!snapshot || !["live", "fixture"].includes(snapshot.source) ||
      !Number.isFinite(Date.parse(snapshot.generated_at)) ||
      !Array.isArray(snapshot.odds) || !Array.isArray(snapshot.opportunities) ||
      (snapshot.cancellation_only !== undefined && !Array.isArray(snapshot.cancellation_only))) {
    throw new Error("Invalid dashboard snapshot");
  }
  return snapshot;
}

export async function loadSnapshot(signal, refreshAt, request = globalThis.fetch) {
  const url = refreshAt === null ? "snapshot.json" : "snapshot.json?refresh=" + refreshAt;
  const response = await request(url, { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Snapshot unavailable");
  return validateSnapshot(await response.json());
}

export function dashboardState(snapshot, now) {
  const generated = Date.parse(snapshot.generated_at);
  const fixture = snapshot.source === "fixture";
  const asOf = fixture ? generated : now;
  const stale = !fixture && now - generated >= MAX_AGE;
  const games = snapshot.odds.filter((game) => Date.parse(game.starts_at) > asOf);
  const opportunities = snapshot.opportunities.map((row) => ({
    ...row,
    expired: stale || !(Date.parse(row.valid_until) > asOf),
  }));
  const cancellationOnly = (snapshot.cancellation_only ?? []).filter((row) => Date.parse(row.closes_at) > asOf);
  return { fixture, stale, games, opportunities, cancellationOnly };
}

export function filterGames(games, query, sport) {
  const needle = query.trim().toLocaleLowerCase();
  return games.filter((game) => (!sport || game.sport === sport) &&
    [game.title, game.sport, ...game.outcomes.map((outcome) => outcome.name)]
      .some((value) => value.toLocaleLowerCase().includes(needle)));
}
