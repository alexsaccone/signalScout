from collections import defaultdict
from datetime import datetime, timezone
import re

if __package__:
    from .api import more_kalshi, more_poly
    from .formulas import arbitrage_pct, get_stakes, has_arbitrage, pct_return_per_day, profit_pct
else:
    from api import more_kalshi, more_poly
    from formulas import arbitrage_pct, get_stakes, has_arbitrage, pct_return_per_day, profit_pct


def filter_kalshi_events(now):
    return more_kalshi(1000, now)


def filter_polymarket_events(now):
    return more_poly(50, now)


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


OUTPUT_FIELDS = (
    "kalshi_id", "polymarket_id", "kalshi_name", "polymarket_name", "kalshi_side", "polymarket_side",
    "arbitrage_pct", "profit_pct", "kalshi_stake", "polymarket_stake", "daily_pct_return",
)


def arbitrage_analysis(pairs, now):
    opportunities = []
    for kalshi, poly in pairs:
        for k_side, p_side in (("yes", "no"), ("no", "yes")):
            k_price = kalshi[f"{k_side}_ask"]
            p_price = poly[f"{p_side}_ask"]
            if not all(price.is_finite() and 0 < price < 1 for price in (k_price, p_price)):
                continue
            odds = 1 / float(k_price), 1 / float(p_price)
            cost = arbitrage_pct(*odds)
            if not has_arbitrage(cost):
                continue
            kalshi_stake, poly_stake = get_stakes(*odds)
            days = (max(kalshi["close_time"], poly["close_time"]).date() - now.date()).days
            opportunities.append({
                "kalshi_id": kalshi["id"], "polymarket_id": poly["id"],
                "kalshi_name": kalshi["title"], "polymarket_name": poly["title"],
                "kalshi_side": k_side, "polymarket_side": p_side,
                "arbitrage_pct": cost, "profit_pct": profit_pct(cost),
                "kalshi_stake": kalshi_stake, "polymarket_stake": poly_stake,
                "daily_pct_return": pct_return_per_day(cost, days),
            })
    return sorted(opportunities, key=lambda opportunity: opportunity["daily_pct_return"], reverse=True)
