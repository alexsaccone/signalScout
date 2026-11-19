from collections import Counter, defaultdict
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
    common = {
        "a", "an", "at", "be", "between", "by", "for", "game", "in", "is", "match",
        "of", "on", "the", "this", "to", "versus", "vs", "will", "win", "winner", "wins",
    }
    return frozenset(re.findall(r"\w+(?:\.\d+)?", market["title"].casefold())) - common


def review_candidates(kalshi, polymarket):
    markets = [(market, title_words(market)) for market in polymarket if market["rules"].strip()]
    by_title = defaultdict(list)
    by_word = defaultdict(list)
    for index, (_, words) in enumerate(markets):
        by_title[words].append(index)
        for word in words:
            by_word[word].append(index)

    candidates = []
    max_postings = max(50, len(markets) // 10)
    for left in kalshi:
        words = title_words(left)
        if not words or not left["rules"].strip():
            continue
        hits = Counter(index for word in words if len(by_word[word]) <= max_postings for index in by_word[word])
        shortlist = set(by_title[words]) | {index for index, count in hits.items() if count >= 2}
        scores = []
        for index in shortlist:
            right_words = markets[index][1]
            score = len(words & right_words) / len(words | right_words)
            if score >= 0.5:
                scores.append((score, index))
        scores.sort(key=lambda item: (-item[0], markets[item[1]][0]["id"]))
        for _, index in scores[:3]:
            candidates.append({"kalshi": market_terms(left), "polymarket": market_terms(markets[index][0])})
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
