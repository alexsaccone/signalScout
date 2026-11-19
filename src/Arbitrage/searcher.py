from collections import Counter, defaultdict
from functools import lru_cache
from heapq import nsmallest
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


COMMON_WORDS = frozenset({
    "a", "an", "at", "be", "between", "by", "for", "game", "in", "is", "match",
    "of", "on", "the", "this", "to", "versus", "vs", "will", "win", "winner", "wins",
})
TITLE_WORD = re.compile(r"\w+(?:\.\d+)?")
MAX_SUGGESTIONS = 3


def title_words(market):
    return frozenset(TITLE_WORD.findall(market["title"].casefold())) - COMMON_WORDS


def review_candidates(kalshi, polymarket):
    markets = [(market, title_words(market)) for market in sorted(polymarket, key=lambda market: market["id"])
               if market["rules"].strip()]
    by_title = defaultdict(list)
    by_word = defaultdict(list)
    max_postings = max(50, len(markets) // 10)
    for index, (_, words) in enumerate(markets):
        day = markets[index][0]["close_time"].date().toordinal()
        exact = by_title[day, words]
        if len(exact) < MAX_SUGGESTIONS:
            exact.append(index)
        for word in words:
            posting = by_word[word]
            if len(posting) <= max_postings:
                posting.append(index)

    @lru_cache(maxsize=1024)
    def shortlist(day, words):
        days = range(day - 1, day + 2)
        exact = sorted(index for nearby in days for index in by_title.get((nearby, words), ()))
        if len(exact) >= MAX_SUGGESTIONS:
            return exact[:MAX_SUGGESTIONS]
        hits = Counter(index for word in words if len(by_word.get(word, ())) <= max_postings
                       for index in by_word.get(word, ()))

        def fuzzy_scores():
            for index, overlap in hits.items():
                right, right_words = markets[index]
                if overlap >= 2 and right_words != words and right["close_time"].date().toordinal() in days:
                    score = len(words & right_words) / len(words | right_words)
                    if score >= 0.5:
                        yield -score, index

        return exact + [index for _, index in nsmallest(MAX_SUGGESTIONS - len(exact), fuzzy_scores())]

    candidates = []
    for left in kalshi:
        words = title_words(left)
        if words and left["rules"].strip():
            day = left["close_time"].date().toordinal()
            candidates.extend(
                {"kalshi": market_terms(left), "polymarket": market_terms(markets[index][0])}
                for index in shortlist(day, words)
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
