import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { dashboardState, filterGames, loadSnapshot } from "./snapshot.js";
import "./style.css";

const fixtureLabel = "Fixture preview";
const shortDate = new Intl.DateTimeFormat(undefined, {
  month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
});
const checkTime = new Intl.DateTimeFormat(undefined, {
  hour: "numeric", minute: "2-digit", second: "2-digit",
});
const percent = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 });
const currency = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" });

function formatDate(value) {
  return shortDate.format(new Date(value));
}

function Matchup({ game }) {
  const [first, second] = game.outcomes;
  const share = 100 * first.probability / (first.probability + second.probability);
  return (
    <article className="matchup">
      <div className="matchup-name">
        <span className="league">{game.sport}</span>
        <h3><a href={game.url}>{game.title}</a></h3>
        <time dateTime={game.starts_at}>{formatDate(game.starts_at)}</time>
      </div>
      <div className="probabilities">
        <div className="probability-labels">
          <span><strong>{percent.format(first.probability)}</strong> {first.name}</span>
          <span>{second.name} <strong>{percent.format(second.probability)}</strong></span>
        </div>
        <div className="odds-rail" aria-hidden="true" style={{ "--share": share + "%" }}></div>
      </div>
    </article>
  );
}

function Opportunities({ rows }) {
  return (
    <section id="opportunities" aria-labelledby="opportunities-heading">
      <h2 id="opportunities-heading">Reviewed opportunities</h2>
      <p className="muted">Estimated net return after venue fees.</p>
      {rows.length === 0 ? (
        <div className="message">
          <p className="message-title">No opportunities in this snapshot</p>
          <p>Only reviewed contract pairs with positive estimated net returns appear here.</p>
        </div>
      ) : (
        <ul className="opportunity-list">
          {rows.map((row) => (
            <li key={row.kalshi_id + ":" + row.polymarket_id + ":" + row.kalshi_side}>
              <div className="quote-heading">
                <p className="opportunity-name">{row.kalshi_name}</p>
                {row.expired && <span className="tag warning">Expired quote</span>}
              </div>
              <p className="legs">Kalshi {row.kalshi_side.toUpperCase()} · Polymarket {row.polymarket_side.toUpperCase()}</p>
              <dl className="quote-stats">
                <div><dt>Net return</dt><dd>{percent.format(Number(row.net_return_pct) / 100)}</dd></div>
                <div><dt>Net profit</dt><dd>{currency.format(Number(row.estimated_net_profit))}</dd></div>
                <div><dt>Contracts</dt><dd>{row.max_contracts}</dd></div>
              </dl>
              <p className="quote-time">Quoted <time dateTime={row.quote_at}>{formatDate(row.quote_at)}</time></p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function MatchedPairs({ rows, loading }) {
  return (
    <section id="matched-pairs" aria-labelledby="matches-heading">
      <h2 id="matches-heading">Matched pairs</h2>
      <p className="muted">All open pairs with matching settlement rules.</p>
      {rows?.length ? (
        <ul className="opportunity-list">
          {rows.map((row) => (
            <li key={row.kalshi_id + ":" + row.polymarket_id}>
              <dl className="pair-venues">
                <div><dt>Kalshi</dt><dd>{row.kalshi_title}</dd></div>
                <div><dt>Polymarket</dt><dd>{row.polymarket_title}</dd></div>
              </dl>
              <p className="quote-time">Trading closes <time dateTime={row.closes_at}>{formatDate(row.closes_at)}</time></p>
            </li>
          ))}
        </ul>
      ) : (
        <div className="message">{loading ? "Loading matches…" : rows ? "No matched pairs in this snapshot." : "Waiting for a snapshot."}</div>
      )}
    </section>
  );
}

function CancellationDifferences({ rows }) {
  const payouts = { yes: "Yes pays $1", no: "No pays $1", "50-50": "Pays $0.50 per side" };
  return (
    <section id="cancellation-rules" aria-labelledby="cancellation-heading">
      <h2 id="cancellation-heading">Cancellation differences</h2>
      <p className="muted">These pairs have different payouts if the event is canceled.</p>
      {rows.length === 0 ? (
        <div className="message">No cancellation-only pairs in this snapshot.</div>
      ) : (
        <ul className="opportunity-list">
          {rows.map((row) => (
            <li key={row.kalshi_id + ":" + row.polymarket_id}>
              <h3 className="opportunity-name">{row.title}</h3>
              {row.polymarket_title !== row.title && <p className="muted">{row.polymarket_title}</p>}
              <dl className="quote-stats cancellation-payouts">
                <div><dt>Kalshi</dt><dd>{payouts[row.kalshi_cancellation] ?? row.kalshi_cancellation}</dd></div>
                <div><dt>Polymarket</dt><dd>{payouts[row.polymarket_cancellation] ?? row.polymarket_cancellation}</dd></div>
              </dl>
              <a className="quote-time" href={row.rulebook}>Governing rules</a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [request, setRequest] = useState(0);
  const [checkedAt, setCheckedAt] = useState(null);
  const [now, setNow] = useState(Date.now);
  const [query, setQuery] = useState("");
  const [sport, setSport] = useState("");
  const [limit, setLimit] = useState(12);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    let active = true;
    async function load() {
      setLoading(true);
      setError(false);
      try {
        const next = await loadSnapshot(controller.signal, request ? Date.now() : null);
        if (!active) return;
        const loadedAt = Date.now();
        setSnapshot(next);
        setNow(loadedAt);
        if (request) setCheckedAt(loadedAt);
      } catch {
        if (active) setError(true);
      } finally {
        clearTimeout(timeout);
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [request]);

  useEffect(() => {
    const ticker = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(ticker);
  }, []);

  const state = snapshot && dashboardState(snapshot, now);
  const sports = state ? [...new Set(state.games.map((game) => game.sport))].sort() : [];
  const filtered = state ? filterGames(state.games, query, sport) : [];
  const update = () => setRequest((count) => count + 1);

  return (
    <>
      <a className="skip" href="#content">Skip to dashboard</a>
      <header className="masthead">
        <div className="frame masthead-inner">
          <div className="masthead-top">
            <a className="wordmark" href="./"><span className="mark" aria-hidden="true"><i></i><i></i><i></i></span>SignalScout</a>
            <nav aria-label="Dashboard sections">
              <a href="#games">Upcoming games</a>
              <a href="#opportunities">Opportunities</a>
              <a href="#matched-pairs">Matched pairs</a>
              <a href="#cancellation-rules">Cancellation rules</a>
            </nav>
          </div>
          <div className="masthead-main">
            <div>
              <h1>Market monitor</h1>
              <p>Upcoming game odds and reviewed cross-venue estimates.</p>
            </div>
            <div className="freshness" aria-live="polite">
              {state && (
                <>
                  <span className={"tag " + (state.stale || error ? "warning" : "current")}>
                    {state.fixture ? fixtureLabel : state.stale ? "Stale snapshot" : "Snapshot"}
                  </span>
                  <div>
                    <div>Updated <time dateTime={snapshot.generated_at}>{formatDate(snapshot.generated_at)}</time></div>
                    {checkedAt !== null && !loading && !error && (
                      <div>Checked <time dateTime={new Date(checkedAt).toISOString()}>{checkTime.format(checkedAt)}</time></div>
                    )}
                  </div>
                </>
              )}
              {!state && <span>{loading ? "Loading snapshot" : "Snapshot unavailable"}</span>}
            </div>
          </div>
        </div>
      </header>
      <main className="frame workspace" id="content">
        {error && <div className="notice" role="alert"><span>{state ? "Couldn’t refresh. Showing the last loaded snapshot." : "The dashboard snapshot couldn’t be loaded."}</span><button disabled={loading} onClick={update}>Retry</button></div>}
        {state?.stale && <div className="notice">This snapshot is over three hours old. Upcoming odds may have changed.</div>}
        <div className="columns">
          <section aria-labelledby="games-heading" id="games" className="games">
            <div className="section-heading">
              <div>
                <h2 id="games-heading">Upcoming games</h2>
                <p className="muted">Polymarket moneyline prices, shown as implied probabilities.</p>
              </div>
              <button className="refresh" onClick={update} disabled={loading}>{loading ? "Refreshing…" : "Refresh data"}</button>
            </div>
            {state && (
              <>
                <div className="filters">
                  <div>
                    <label htmlFor="search">Find a matchup</label>
                    <input id="search" type="search" placeholder="Search by team or league" value={query} onChange={(event) => { setQuery(event.target.value); setLimit(12); }} />
                  </div>
                  <div>
                    <label htmlFor="sport">League</label>
                    <select id="sport" value={sport} onChange={(event) => { setSport(event.target.value); setLimit(12); }}>
                      <option value="">All leagues</option>
                      {sports.map((label) => <option key={label}>{label}</option>)}
                    </select>
                  </div>
                </div>
                <div className="matchups" aria-live="polite">
                  {filtered.length
                    ? filtered.slice(0, limit).map((game) => <Matchup key={game.id} game={game} />)
                    : <div className="message"><p className="message-title">{state.games.length ? "No matching games" : "No upcoming games in this snapshot"}</p>
                      {state.games.length > 0 && <button onClick={() => { setQuery(""); setSport(""); }}>Clear filters</button>}</div>}
                </div>
                {filtered.length > limit && <button className="more" onClick={() => setLimit(limit + 12)}>Show more games</button>}
              </>
            )}
            {!state && loading && <div className="skeleton" aria-label="Loading game odds"><span></span><span></span><span></span></div>}
            {!state && !loading && <div className="message">Game odds will appear when a snapshot is available.</div>}
          </section>
          <aside className="opportunities">
            {state
              ? <Opportunities rows={state.opportunities} />
              : <section id="opportunities"><h2>Reviewed opportunities</h2><p className="muted">{loading ? "Loading snapshot…" : "Waiting for a snapshot."}</p></section>}
            <MatchedPairs rows={state?.matchedPairs} loading={!state && loading} />
            <CancellationDifferences rows={state?.cancellationOnly ?? []} />
          </aside>
        </div>
      </main>
      <footer className="frame"><a href="https://github.com/alexsaccone/signalScout">SignalScout on GitHub</a></footer>
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
