import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { dashboardState, filterGames, loadSnapshot } from "./snapshot.js";
import "./style.css";

const fixtureLabel = "Fixture preview";
const gamesPage = document.body.dataset.page === "games";
const marketHome = gamesPage ? "../" : "./";
const shortDate = new Intl.DateTimeFormat(undefined, {
  month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
});
const checkTime = new Intl.DateTimeFormat(undefined, {
  hour: "numeric", minute: "2-digit", second: "2-digit",
});
const closeDate = new Intl.DateTimeFormat(undefined, {
  year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
});
const ruleDate = new Intl.DateTimeFormat(undefined, {
  year: "numeric", month: "short", day: "numeric", timeZone: "UTC",
});
const percent = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 });
const roi = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 4 });
const currency = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" });

function formatDate(value) {
  return shortDate.format(new Date(value));
}

function polymarketLabel(venue) {
  return venue === "polymarket_us" ? "Polymarket US" : "Polymarket International";
}

function CloseTime({ value }) {
  return <time dateTime={value}>{closeDate.format(new Date(value))}</time>;
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

function Opportunities({ rows, sort, setSort }) {
  return (
    <section id="opportunities" aria-labelledby="opportunities-heading">
      <h2 id="opportunities-heading">Reviewed opportunities</h2>
      <p className="muted">Daily ROI divides estimated net return after fees by the days until the later listed close.</p>
      <div className="market-control">
        <label htmlFor="opportunity-sort">Sort opportunities</label>
        <select id="opportunity-sort" value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="daily_roi_pct">Daily ROI</option>
          <option value="net_return_pct">Total ROI</option>
        </select>
      </div>
      {rows.length === 0 ? (
        <div className="message">
          <p className="message-title">No opportunities in this snapshot</p>
          <p>Open pairs appear here when their estimated net return is positive.</p>
        </div>
      ) : (
        <ul className="opportunity-list">
          {rows.map((row) => (
            <li key={row.kalshi_id + ":" + row.polymarket_id + ":" + row.kalshi_side}>
              <div className="quote-heading">
                <p className="opportunity-name">{row.kalshi_name}</p>
                {row.expired && <span className="tag warning">Expired quote</span>}
              </div>
              <p className="legs">Kalshi {row.kalshi_side.toUpperCase()} · {polymarketLabel(row.polymarket_venue)} {row.polymarket_side.toUpperCase()}</p>
              <dl className="quote-stats">
                {row.daily_roi_pct != null && <div><dt>Daily ROI</dt><dd>{roi.format(Number(row.daily_roi_pct) / 100)}</dd></div>}
                <div><dt>Total ROI</dt><dd>{roi.format(Number(row.net_return_pct) / 100)}</dd></div>
                <div><dt>Net profit</dt><dd>{currency.format(Number(row.estimated_net_profit))}</dd></div>
                <div><dt>Contracts</dt><dd>{row.max_contracts}</dd></div>
              </dl>
              {row.capital_until && <p className="quote-time">Later close <CloseTime value={row.capital_until} /></p>}
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
                <div><dt>{polymarketLabel(row.polymarket_venue)}</dt><dd>{row.polymarket_url ? <a href={row.polymarket_url}>{row.polymarket_title}</a> : row.polymarket_title}</dd></div>
              </dl>
              <p className="quote-time">First close <CloseTime value={row.closes_at} /></p>
              {row.capital_until && row.capital_until !== row.closes_at &&
                <p className="quote-time">Later close <CloseTime value={row.capital_until} /></p>}
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
                <div><dt>{polymarketLabel(row.polymarket_venue)}</dt><dd>{payouts[row.polymarket_cancellation] ?? row.polymarket_cancellation}</dd></div>
              </dl>
              <a className="quote-time" href={row.rulebook}>Governing rules</a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SharedEvents({ rows, loading }) {
  return (
    <section id="shared-events" aria-labelledby="shared-events-heading">
      <h2 id="shared-events-heading">Shared events, different rules</h2>
      <p className="muted">Contracts on the same event with a documented scenario where payouts differ.</p>
      {rows?.length ? (
        <ul className="opportunity-list">
          {rows.map((row) => (
            <li key={row.kalshi_id + ":" + row.polymarket_id}>
              <h3 className="opportunity-name">{row.kalshi_title}</h3>
              {row.polymarket_title !== row.kalshi_title && <p className="muted">{row.polymarket_title}</p>}
              <p className="rule-scenario">{row.difference.scenario}</p>
              <dl className="rule-comparison">
                {[
                  { label: "Kalshi", close: row.kalshi_close, book: row.kalshi_rulebook, payout: row.difference.kalshi_payout,
                    cutoff: row.difference.kalshi_cutoff, inclusive: row.difference.kalshi_cutoff_inclusive },
                  { label: polymarketLabel(row.polymarket_venue), url: row.polymarket_url, close: row.polymarket_close, book: row.polymarket_rulebook,
                    payout: row.difference.polymarket_payout, cutoff: row.difference.polymarket_cutoff, inclusive: row.difference.polymarket_cutoff_inclusive },
                ].map(({ label, url, close, book, payout, cutoff, inclusive }) => (
                  <div key={label}>
                    <dt>{url ? <a href={url}>{label}</a> : label}</dt>
                    <dd>{payout}{payout === "Yes" || payout === "No" ? " pays $1" : ""}</dd>
                    {cutoff && <dd className="quote-time">Rule deadline {inclusive ? "by" : "before"} <time dateTime={cutoff}>{ruleDate.format(new Date(cutoff))}</time></dd>}
                    <dd className="quote-time">Trading closes <CloseTime value={close} /></dd>
                    {book && <dd><a className="quote-time" href={book} aria-label={label + " governing rules"}>Governing rules</a></dd>}
                  </div>
                ))}
              </dl>
            </li>
          ))}
        </ul>
      ) : <div className="message">{loading ? "Loading shared events…" : rows ? "No shared events with documented rule differences in this window." : "Waiting for a snapshot."}</div>}
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
  const [minimumDays, setMinimumDays] = useState(0);
  const [sort, setSort] = useState("daily_roi_pct");

  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    let active = true;
    async function load() {
      setLoading(true);
      setError(false);
      try {
        const next = await loadSnapshot(controller.signal, request ? Date.now() : null, undefined, marketHome + "snapshot.json");
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

  const state = snapshot && dashboardState(snapshot, now, minimumDays, sort);
  const sports = state ? [...new Set(state.games.map((game) => game.sport))].sort() : [];
  const filtered = state ? filterGames(state.games, query, sport) : [];
  const update = () => setRequest((count) => count + 1);

  return (
    <>
      <a className="skip" href="#content">Skip to dashboard</a>
      <header className="masthead">
        <div className="frame masthead-inner">
          <div className="masthead-top">
            <a className="wordmark" href={marketHome}><span className="mark" aria-hidden="true"><i></i><i></i><i></i></span>SignalScout</a>
            <nav className="page-nav" aria-label="Main navigation">
              <a href={marketHome} aria-current={gamesPage ? undefined : "page"}>Markets</a>
              <a href={gamesPage ? "./" : "./games/"} aria-current={gamesPage ? "page" : undefined}>Games</a>
            </nav>
          </div>
          <div className="masthead-main">
            <div>
              <h1>{gamesPage ? "Upcoming games" : "Markets"}</h1>
              <p>{gamesPage ? "Polymarket moneyline prices, shown as implied probabilities." :
                "Verified contract pairs, settlement differences, and cross-venue returns."}</p>
            </div>
            <div className="snapshot-status">
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
              <button className="refresh" onClick={update} disabled={loading}>{loading ? "Refreshing…" : "Refresh data"}</button>
            </div>
          </div>
        </div>
      </header>
      <main className="frame workspace" id="content">
        {error && <div className="notice" role="alert"><span>{state ? "Couldn’t refresh. Showing the last loaded snapshot." : "The dashboard snapshot couldn’t be loaded."}</span><button disabled={loading} onClick={update}>Retry</button></div>}
        {state?.stale && <div className="notice">This snapshot is over three hours old. Prices may have changed.</div>}
        {gamesPage ? (
          <section aria-label="Game odds" id="games" className="games">
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
        ) : (
          <>
            <nav className="section-links" aria-label="Market sections">
              <a href="#opportunities">Opportunities</a>
              <a href="#matched-pairs">Matched pairs</a>
              <a href="#shared-events">Shared events</a>
              <a href="#cancellation-rules">Cancellation rules</a>
            </nav>
            <div className="market-control market-window">
              <label htmlFor="market-window">Cross-venue closing window</label>
              <select id="market-window" value={minimumDays} onChange={(event) => setMinimumDays(Number(event.target.value))}>
                <option value="0">All open pairs</option>
                <option value="4">Later close more than 4 days away</option>
                <option value="30">Later close more than 30 days away</option>
                <option value="365">Later close more than 1 year away</option>
              </select>
            </div>
            <div className="market-grid">
              {state
                ? <Opportunities rows={state.opportunities} sort={sort} setSort={setSort} />
                : <section id="opportunities"><h2>Reviewed opportunities</h2><p className="muted">{loading ? "Loading snapshot…" : "Waiting for a snapshot."}</p></section>}
              <MatchedPairs rows={state?.matchedPairs} loading={!state && loading} />
              <SharedEvents rows={state?.sharedEvents} loading={!state && loading} />
              <CancellationDifferences rows={state?.cancellationOnly ?? []} />
            </div>
          </>
        )}
      </main>
      <footer className="frame"><a href="https://github.com/alexsaccone/signalScout">SignalScout on GitHub</a></footer>
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
