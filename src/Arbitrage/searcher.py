from collections import defaultdict
import re

if __package__:
    from .api import more_kalshi, more_poly, SCAN_WINDOW
else:
    from api import more_kalshi, more_poly, SCAN_WINDOW


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


def title_words(market):
    return tuple(re.findall(r"\w+", market["title"].casefold()))


def review_candidates(kalshi, polymarket):
    by_title = defaultdict(list)
    for market in polymarket:
        by_title[title_words(market)].append(market)
    return [
        {"kalshi": market_terms(left), "polymarket": market_terms(right)}
        for left in kalshi
        for right in by_title.get(title_words(left), ())
        if left["rules"].strip() and right["rules"].strip()
    ]


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
