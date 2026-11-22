import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { dashboardState, filterGames, groupSharedEvents, loadSnapshot } from "./snapshot.js";
import "./style.css";

const fixtureLabel = "Fixture preview";
const gamesPage = document.body.dataset.page === "games";
const marketHome = gamesPage ? "../" : "./";
const marketTabs = [
  ["opportunities", "Opportunities"],
  ["matched-pairs", "Matched pairs"],
  ["shared-events", "Shared events"],
  ["cancellation-rules", "Cancellation rules"],
  ["ai-reviewed", "AI-reviewed"],
];
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

function EventLink({ url, children }) {
  return url ? <a href={url}>{children}</a> : children;
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
    <section aria-labelledby="opportunities-heading">
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
          <p>Open pairs appear here when their minimum payout exceeds the cost of both legs after fees.</p>
        </div>
      ) : (
        <ul className="opportunity-list">
          {rows.map((row) => (
            <li key={row.kalshi_id + ":" + row.polymarket_id + ":" + row.kalshi_side + ":" + row.polymarket_side}>
              <div className="quote-heading">
                <p className="opportunity-name">{row.kalshi_name}</p>
                <div className="quote-tags">
                  {row.rule_difference && <span className="tag rule-variance">Different rules</span>}
                  {row.expired && <span className="tag warning">Expired quote</span>}
                </div>
              </div>
              {row.rule_difference && <p className="muted">{row.polymarket_name}</p>}
              <p className="legs">
                <EventLink url={row.kalshi_url}>Kalshi</EventLink> {row.kalshi_side.toUpperCase()} ·{" "}
                <EventLink url={row.polymarket_url}>{polymarketLabel(row.polymarket_venue)}</EventLink> {row.polymarket_side.toUpperCase()}
              </p>
              <dl className="quote-stats">
                {row.daily_roi_pct != null && <div><dt>Daily ROI</dt><dd>{roi.format(Number(row.daily_roi_pct) / 100)}</dd></div>}
                <div><dt>Total ROI</dt><dd>{roi.format(Number(row.net_return_pct) / 100)}</dd></div>
                <div><dt>{row.rule_difference ? "Minimum net profit" : "Net profit"}</dt><dd>{currency.format(Number(row.estimated_net_profit))}</dd></div>
                <div><dt>Contracts</dt><dd>{row.max_contracts}</dd></div>
                {row.rule_difference && <div><dt>Minimum payout</dt><dd>{currency.format(Number(row.minimum_payout))}</dd></div>}
              </dl>
              {row.rule_difference && <p className="quote-time">{row.rule_difference}</p>}
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
    <section aria-labelledby="matches-heading">
      <h2 id="matches-heading">Matched pairs</h2>
      <p className="muted">All open pairs with matching settlement rules.</p>
      {rows?.length ? (
        <ul className="opportunity-list">
          {rows.map((row) => (
            <li key={row.kalshi_id + ":" + row.polymarket_id}>
              <dl className="pair-venues">
                <div><dt>Kalshi</dt><dd><EventLink url={row.kalshi_url}>{row.kalshi_title}</EventLink></dd></div>
                <div><dt>{polymarketLabel(row.polymarket_venue)}</dt><dd><EventLink url={row.polymarket_url}>{row.polymarket_title}</EventLink></dd></div>
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
    <section aria-labelledby="cancellation-heading">
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
                <div><dt><EventLink url={row.kalshi_url}>Kalshi</EventLink></dt><dd>{payouts[row.kalshi_cancellation] ?? row.kalshi_cancellation}</dd></div>
                <div><dt><EventLink url={row.polymarket_url}>{polymarketLabel(row.polymarket_venue)}</EventLink></dt><dd>{payouts[row.polymarket_cancellation] ?? row.polymarket_cancellation}</dd></div>
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
  const groups = groupSharedEvents(rows);
  return (
    <section aria-labelledby="shared-events-heading">
      <h2 id="shared-events-heading">Shared events, different rules</h2>
      <p className="muted">Contracts on the same event with a documented scenario where payouts differ.</p>
      {groups.length ? (
        <div className="shared-event-groups">
          {groups.map(({ id, title, pairs }) => (
            <details key={id}>
              <summary>
                <span>{title}</span>
                <span className="shared-event-count">{pairs.length} {pairs.length === 1 ? "pair" : "pairs"}</span>
              </summary>
              <ul className="opportunity-list">
                {pairs.map((row) => <SharedEventPair key={row.kalshi_id + ":" + row.polymarket_id} row={row} />)}
              </ul>
            </details>
          ))}
        </div>
      ) : <div className="message">{loading ? "Loading shared events…" : rows ? "No shared events with documented rule differences in this window." : "Waiting for a snapshot."}</div>}
    </section>
  );
}

function SharedEventPair({ row }) {
  return (
    <li>
      <h3 className="opportunity-name">{row.kalshi_title}</h3>
      {row.polymarket_title !== row.kalshi_title && <p className="muted">{row.polymarket_title}</p>}
      <p className="rule-scenario">{row.difference.scenario}</p>
      <dl className="rule-comparison">
        {[
          { label: "Kalshi", url: row.kalshi_url, close: row.kalshi_close, book: row.kalshi_rulebook, payout: row.difference.kalshi_payout,
            cutoff: row.difference.kalshi_cutoff, inclusive: row.difference.kalshi_cutoff_inclusive },
          { label: polymarketLabel(row.polymarket_venue), url: row.polymarket_url, close: row.polymarket_close, book: row.polymarket_rulebook,
            payout: row.difference.polymarket_payout, cutoff: row.difference.polymarket_cutoff, inclusive: row.difference.polymarket_cutoff_inclusive },
        ].map(({ label, url, close, book, payout, cutoff, inclusive }) => (
          <div key={label}>
            <dt><EventLink url={url}>{label}</EventLink></dt>
            <dd>{payout}{payout === "Yes" || payout === "No" ? " pays $1" : ""}</dd>
            {cutoff && <dd className="quote-time">Rule deadline {inclusive ? "by" : "before"} <time dateTime={cutoff}>{ruleDate.format(new Date(cutoff))}</time></dd>}
            <dd className="quote-time">Trading closes <CloseTime value={close} /></dd>
            {book && <dd><a className="quote-time" href={book} aria-label={label + " governing rules"}>Governing rules</a></dd>}
          </div>
        ))}
      </dl>
    </li>
  );
}

const aiVerdicts = {
  likely_equivalent: "Likely equivalent",
  cancellation_only: "Cancellation difference only",
  different_rules: "Different rules",
  insufficient_evidence: "Insufficient evidence",
};

function AIReviewedPairs({ rows, loading }) {
  return (
    <section aria-labelledby="ai-reviewed-heading">
      <h2 id="ai-reviewed-heading">AI-reviewed pairs</h2>
      <p className="muted">Gemini’s rule comparisons. Each suggestion still needs human review before it can be used for pricing.</p>
      {rows?.length ? (
        <ul className="opportunity-list">
          {rows.map((row) => (
            <li key={row.kalshi_id + ":" + row.polymarket_id}>
              <h3 className="opportunity-name">{aiVerdicts[row.verdict]}</h3>
              <dl className="pair-venues">
                <div><dt>Kalshi</dt><dd><EventLink url={row.kalshi_url}>{row.kalshi_title}</EventLink></dd></div>
                <div><dt>{polymarketLabel(row.polymarket_venue)}</dt><dd><EventLink url={row.polymarket_url}>{row.polymarket_title}</EventLink></dd></div>
              </dl>
              <p className="rule-scenario">{row.summary}</p>
              <p className="quote-time">First close <CloseTime value={row.closes_at} /></p>
              {row.quotes.length > 0 && (
                <details className="ai-evidence">
                  <summary>Supporting quotes</summary>
                  {row.quotes.map(({ venue, page, quote }, index) => {
                    const label = venue === "kalshi" ? "Kalshi" : polymarketLabel(row.polymarket_venue);
                    return (
                      <blockquote key={index}>
                        <p>{quote}</p>
                        <p className="quote-time">
                          {label} · {page ? <EventLink url={row[venue + "_rulebook"]}>Governing rules, page {page}</EventLink> : "Market rules"}
                        </p>
                      </blockquote>
                    );
                  })}
                </details>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className="message">{loading ? "Loading AI-reviewed pairs…" : rows ? "No AI-reviewed pairs in this closing window." : "Waiting for a snapshot."}</div>
      )}
    </section>
  );
}

function marketTabFromHash() {
  const hash = window.location.hash.slice(1);
  return marketTabs.find(([id]) => id === hash)?.[0];
}

function MarketTabs({ panels, children }) {
  const [selected, setSelected] = useState(() => marketTabFromHash() ?? marketTabs[0][0]);

  useEffect(() => {
    function followLocation() {
      const tab = marketTabFromHash();
      if (tab || !window.location.hash) setSelected(tab ?? marketTabs[0][0]);
    }
    window.addEventListener("popstate", followLocation);
    window.addEventListener("hashchange", followLocation);
    return () => {
      window.removeEventListener("popstate", followLocation);
      window.removeEventListener("hashchange", followLocation);
    };
  }, []);

  function selectTab(id) {
    if (id === selected) return;
    window.history.pushState(null, "", "#" + id);
    setSelected(id);
  }

  function handleTabKey(event, index) {
    const last = marketTabs.length - 1;
    let next;
    switch (event.key) {
      case "ArrowRight": next = index === last ? 0 : index + 1; break;
      case "ArrowLeft": next = index === 0 ? last : index - 1; break;
      case "Home": next = 0; break;
      case "End": next = last; break;
      default: return;
    }
    event.preventDefault();
    const [id] = marketTabs[next];
    document.getElementById("tab-" + id).focus();
    selectTab(id);
  }

  return (
    <>
      <div className="market-tabs" role="tablist" aria-label="Market sections">
        {marketTabs.map(([id, label], index) => (
          <button key={id} type="button" role="tab" id={"tab-" + id} aria-controls={id}
            aria-selected={id === selected} tabIndex={id === selected ? 0 : -1}
            onClick={() => selectTab(id)} onKeyDown={(event) => handleTabKey(event, index)}>
            {label}
          </button>
        ))}
      </div>
      {children}
      {marketTabs.map(([id]) => (
        <div key={id} className="market-panel" id={id} role="tabpanel" aria-labelledby={"tab-" + id}
          tabIndex={0} hidden={id !== selected}>
          {id === selected && panels[id]}
        </div>
      ))}
    </>
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
          <MarketTabs panels={{
            opportunities: state
              ? <Opportunities rows={state.opportunities} sort={sort} setSort={setSort} />
              : <section><h2>Reviewed opportunities</h2><p className="muted">{loading ? "Loading snapshot…" : "Waiting for a snapshot."}</p></section>,
            "matched-pairs": <MatchedPairs rows={state?.matchedPairs} loading={!state && loading} />,
            "shared-events": <SharedEvents rows={state?.sharedEvents} loading={!state && loading} />,
            "cancellation-rules": <CancellationDifferences rows={state?.cancellationOnly ?? []} />,
            "ai-reviewed": <AIReviewedPairs rows={state?.aiReviews} loading={!state && loading} />,
          }}>
            <div className="market-control market-window">
              <label htmlFor="market-window">Cross-venue closing window</label>
              <select id="market-window" value={minimumDays} onChange={(event) => setMinimumDays(Number(event.target.value))}>
                <option value="0">All open pairs</option>
                <option value="4">Later close more than 4 days away</option>
                <option value="30">Later close more than 30 days away</option>
                <option value="365">Later close more than 1 year away</option>
              </select>
            </div>
          </MarketTabs>
        )}
      </main>
      <footer className="frame"><a href="https://github.com/alexsaccone/signalScout">SignalScout on GitHub</a></footer>
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
