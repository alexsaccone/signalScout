from collections import defaultdict
from datetime import date
import re

if __package__:
    from .api import lookup_markets, more_kalshi, more_poly, ScanError, SCAN_WINDOW
else:
    from api import lookup_markets, more_kalshi, more_poly, ScanError, SCAN_WINDOW


def filter_kalshi_events(now, window=SCAN_WINDOW):
    return more_kalshi(1000, now, window)


def filter_polymarket_events(now, window=SCAN_WINDOW):
    return more_poly(1000, now, window)


def market_terms(market):
    terms = {key: market[key] for key in ("id", "title", "subtitle", "rules", "secondary_rules", "resolution")}
    terms["close_time"] = market["close_time"].isoformat()
    if "tokens" in market:
        terms["tokens"] = market["tokens"]
    return terms


MAX_SUGGESTIONS = 3
DATED = r"\b\d{4}-\d{2}-\d{2}\b"
IF_YES = re.compile(
    r'^If (.+?), (?:then )?(?:the|this) market (?:will resolve|resolves) to "?Yes"?\.(?: |$)', re.I,
)
YES_IF = r'^This market (?:will resolve|resolves) to "?Yes"? if ('
INLINE_YES = re.compile(rf'{YES_IF}.*?{DATED}.*?)\.(?: |$)', re.I)
FIXTURE_YES = re.compile(rf'{YES_IF}.+?)\.(?: |$)', re.I)
SCHEDULED_FIXTURE = re.compile(
    rf"^In the upcoming (.+?) (game|match) between (.+?) and (.+?), "
    rf"(?:originally )?scheduled for (?:[A-Za-z]+day, )?({DATED}) at "
    rf"(\d{{1,2}}(?::\d{{2}})? [AP]M [A-Z]{{2,4}})"
    rf"(?: \(as of creation of the first market related to the event\))?: ",
)
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
MONTH_NUMBER = {name.lower(): index for index, month in enumerate(MONTHS, 1) for name in (month, month[:3])}
EVENT_DATE = re.compile(rf"\b({'|'.join(MONTH_NUMBER)})\.? (\d{{1,2}}),? (\d{{4}})\b", re.I)
SPORT = re.compile(r"\b(?:game|match|teams?|player|touchdowns?|goals?|innings?)\b", re.I)
MATCHUP = re.compile(r"\b[A-Z][\w'’-]*(?: [A-Z][\w'’-]*)* (?:vs\.?|versus) [A-Z][\w'’-]*")
SPORTS_SESSION = re.compile(r"\b(?:\d{1,2}(?::\d{2})? [ap]m [A-Z]{2,4}|(?:game|leg) \d+)\b", re.I)
UNNAMED = re.compile(r"\b(?:listed|selected|specified) (?:player|team)\b|\bthe (?:home team|away team|player)\b", re.I)
SOURCE_URL = re.compile(r'https?://[^\s<>()"]+')


def iso_date(match):
    month, day, year = match.groups()
    return date(int(year), MONTH_NUMBER[month.lower()], int(day)).isoformat()


def settlement_key(market):
    try:
        rules = EVENT_DATE.sub(iso_date, " ".join(market["rules"].split()))
        secondary = EVENT_DATE.sub(iso_date, " ".join(market["secondary_rules"].split()))
    except ValueError:
        return None
    fixture = SCHEDULED_FIXTURE.match(rules)
    if fixture:
        league, event_type, first, second, day, starts_at = fixture.groups()
        rules = rules[fixture.end():]
        payout = IF_YES.match(rules) or FIXTURE_YES.match(rules)
    else:
        payout = IF_YES.match(rules) or INLINE_YES.match(rules)
    if not payout:
        return None

    condition = payout[1]
    if fixture:
        condition += f" in the {first} vs {second} {league} {event_type} on {day} at {starts_at}"
    if not re.search(DATED, condition) or UNNAMED.search(condition):
        return None
    if SPORT.search(condition) and not (MATCHUP.search(condition) and SPORTS_SESSION.search(condition)):
        return None

    remaining = " ".join((rules[payout.end():], secondary)).strip()
    sources = {url.rstrip(".,;!?") for url in SOURCE_URL.findall(remaining)}
    resolution = market["resolution"]
    if not sources or (isinstance(resolution, str) and resolution and resolution.strip() not in sources):
        return None

    # Reconcile common venue wrappers and date formats. Compare the complete
    # condition and all subsequent clauses, including any exception or deadline.
    return condition, remaining


def review_candidates(kalshi, polymarket):
    by_settlement = defaultdict(list)
    for market in sorted(polymarket, key=lambda market: market["id"]):
        key = settlement_key(market)
        if key is not None and len(by_settlement[key]) < MAX_SUGGESTIONS:
            by_settlement[key].append(market)

    candidates = []
    for left in kalshi:
        candidates.extend(
            {"kalshi": market_terms(left), "polymarket": market_terms(right)}
            for right in by_settlement.get(settlement_key(left), ())
        )
    return candidates


def verified_pairs(kalshi, polymarket, reviewed):
    by_kalshi_id = {market["id"]: market for market in kalshi}
    by_poly_id = {market["id"]: market for market in polymarket}
    seen = set()
    for review in reviewed:
        left = by_kalshi_id.get(review["kalshi"]["id"])
        right = by_poly_id.get(review["polymarket"]["id"])
        if not left or not right or not left["rules"].strip() or not right["rules"].strip():
            continue
        if review != {"kalshi": market_terms(left), "polymarket": market_terms(right)}:
            continue
        # A review binds both displayed rules and the exact outcome tokens.
        ids = left["id"], right["id"]
        if ids not in seen:
            seen.add(ids)
            yield left, right


def refresh_reviewed_pairs(reviews, now):
    markets = []
    for venue in ("kalshi", "polymarket"):
        ids = {review[venue]["id"] for review in reviews}
        if any(not isinstance(market_id, str) or not market_id.strip() for market_id in ids):
            raise ScanError(f"Invalid reviewed {venue} market ID")
        markets.append(lookup_markets(ids, venue, now))
    return verified_pairs(*markets, reviews)
