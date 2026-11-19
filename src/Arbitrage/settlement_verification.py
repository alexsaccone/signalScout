from datetime import datetime, timezone
from functools import lru_cache
import re

import requests

if __package__:
    from .api import KALSHI_URL, ScanError, fetch_json
    from .searcher import CONTRACT_REFERENCE, review_candidates, rule_matches, settlement_key
    from .settlement_documents import KALSHI_BOOK, book_cancellation_difference, equivalent_rulebooks, load_rulebook
else:
    from api import KALSHI_URL, ScanError, fetch_json
    from searcher import CONTRACT_REFERENCE, review_candidates, rule_matches, settlement_key
    from settlement_documents import KALSHI_BOOK, book_cancellation_difference, equivalent_rulebooks, load_rulebook


CANCELLATION = re.compile(
    r'^(?P<trigger>If the (?:game|match|fight|event) is cancell?ed,) '
    r'(?:settle at |(?:the|this) market (?:will resolve|resolves)(?: to)? )'
    r'(?P<quote>")?(?P<payout>Yes|No|50-50|(?:the )?last fair price|a fair price)'
    r'(?(quote)(?:"\.|\.")|\.)[ \t]*\r?$',
    re.M | re.I,
)
UNBOUND_TERM = re.compile(
    r"\b(?:specified|listed|stated|shown) (?:in|on) (?:the |this )?(?:market )?(?:title|subtitle|question)\b", re.I,
)
DISCRETIONARY = re.compile(r"\b(?:fair (?:market )?price|refund|exchange discretion)\b", re.I)
PAYOUT_MARKER = "\u241e"
# Page numbers for the full Kalshi versions that were checked for the
# before-play cancellation rule. A revised PDF needs a fresh review.
FAIR_PRICE_CANCELLATION = {
    "03bfbad61dc5eb23caa715ed131af206a867f83462955544dbc0b87704ede4df": 4,  # SOCCER1H
    "3f1d6cc1765afa3eb44d809107f24b939dcc68f71718dc38ffe13d354c3f4ce2": 4,  # SOCCERGAMEWIN
    "f34c2e955eff1fac177ea529e223037a0ae7b40fb3ebdedba2d942c56190b4ec": 2,  # SOCCERWHOSTAT
    "8a6dfb6eab4a6c7efea4a19889b440d3422ff8affcc516edbe1a63bb3406079d": 2,  # SOCCERENTITYSTAT
    "5aeb2ccabe65f871b5e069b9d05091ae584521bfdb030b6523551ecc7d6aa7b2": 2,  # SOCCERSPREADS
}
KALSHI_CANCELLATION_SUMMARY = (
    "If the game is cancelled or rescheduled to over 48 hours away, "
    "the market will resolve to a fair price in accordance with the rules."
)
POLY_FIXED_CANCELLATION = re.compile(
    r'(?:^|(?<=\. ))If the game is cancell?ed'
    r'(?:, does not start by [^.]+? or is abandoned with no official result by that time)?'
    r', this market will resolve(?: to)? (?:"(No|50-50)(?:\."|"\.)|(No|50-50)\.)(?= |$)'
)


def rulebook_url(series):
    if not re.fullmatch(r"[A-Z0-9]+", series):
        return None
    doc, _ = fetch_json(f"{KALSHI_URL}/series/{series}")
    url = doc["series"].get("contract_terms_url")
    return url if isinstance(url, str) and re.fullmatch(KALSHI_BOOK, url) else None


def cancellation_mismatch(left, right, book):
    page = FAIR_PRICE_CANCELLATION.get(book.sha256)
    if page is None or CONTRACT_REFERENCE.search(right["rules"]):
        return None
    kalshi_text = " ".join(f"{left['rules']} {left['secondary_rules']}".split())
    extra = kalshi_text.replace(KALSHI_CANCELLATION_SUMMARY, "")
    if re.search(r"\b(?:cancel\w*|abandon\w*|no result|void|refund)\b", extra, re.I):
        return None
    polymarket_text = " ".join(right["rules"].split())
    matches = list(rule_matches(POLY_FIXED_CANCELLATION, polymarket_text).values())
    if len(matches) != 1:
        return None
    match = matches[0]
    return {"scenario": "Canceled before play starts", "kalshi_payout": "last fair price",
            "polymarket_payout": match[1] or match[2], "kalshi_rulebook_page": page,
            "polymarket_clause": match[0]}


def comparable_terms(market):
    # Structured thresholds can carry details outside the operative prose.
    metadata = market["resolution"]
    if isinstance(metadata, dict) and {"floor_strike", "cap_strike", "functional_strike"} & metadata.keys():
        return None
    rules, secondary = market["rules"], market["secondary_rules"]
    references = rule_matches(CONTRACT_REFERENCE, rules)
    book = [match[1] for match in references.values()]
    if len(book) > 1 or PAYOUT_MARKER in rules + secondary:
        return None
    if "tokens" in market and not book:
        return None
    rules = CONTRACT_REFERENCE.sub(lambda m: "" if m.start() in references else m[0], rules).strip()

    primary_cancellation, secondary_cancellation = (rule_matches(CANCELLATION, text) for text in (rules, secondary))
    payouts = [*primary_cancellation.values(), *secondary_cancellation.values()]
    if len(payouts) > 1:
        return None
    payout = None
    if payouts:
        payout = payouts[0]["payout"].casefold()

        def mask(match):
            trigger = match["trigger"].casefold().replace("cancelled", "canceled")
            return f"{trigger} this market resolves to {PAYOUT_MARKER}."

        rules = CANCELLATION.sub(lambda m: mask(m) if m.start() in primary_cancellation else m[0], rules)
        secondary = CANCELLATION.sub(lambda m: mask(m) if m.start() in secondary_cancellation else m[0], secondary)
    key = settlement_key(dict(market, rules=rules, secondary_rules=secondary))
    if not key or not key[2]:
        return None
    prose = f"{key[0]} {key[1]}"
    if UNBOUND_TERM.search(prose) or DISCRETIONARY.search(prose):
        return None
    return key, book[0] if book else None, payout


def document_lookup():
    @lru_cache(maxsize=None)
    def series_book(ticker):
        try:
            return rulebook_url(ticker)
        except (ScanError, AttributeError, KeyError, TypeError, ValueError):
            return None

    @lru_cache(maxsize=None)
    def document(url):
        try:
            return load_rulebook(url) if url else None
        except requests.RequestException:
            return None

    return series_book, document


def assessment_report(kalshi, polymarket, candidates, leads, now=None):
    report = {"generated_at": (now or datetime.now(timezone.utc)).isoformat(),
              "verified": [], "cancellation_only": [], "different_rules": [], "manual_review": []}
    markets = {market["id"]: market for market in kalshi + polymarket}
    explicit_books = [market for market in polymarket if CONTRACT_REFERENCE.search(market["rules"])]
    series_book, document = document_lookup()

    @lru_cache(maxsize=None)
    def comparison(market_id):
        return comparable_terms(markets[market_id])

    def key(market):
        parsed = comparison(market["id"])
        return parsed[0] if parsed else None

    matches = review_candidates(kalshi, explicit_books, key=key) if explicit_books else []
    seen = set()
    for candidate in matches + candidates + leads:
        left, right = candidate["kalshi"], candidate["polymarket"]
        ids = left["id"], right["id"]
        if ids in seen:
            continue
        seen.add(ids)
        series = left["id"].split("-", 1)[0]
        url = series_book(series)
        kalshi_book = document(url)
        k_terms, p_terms = map(comparison, ids)
        references = list(rule_matches(CONTRACT_REFERENCE, right["rules"]).values())
        poly_url = references[0][1] if len(references) == 1 else None
        poly_book = document(poly_url)
        evidence = {"kalshi_rulebook": url, "kalshi_sha256": kalshi_book.sha256 if kalshi_book else None,
                    "polymarket_rulebook": poly_url, "polymarket_sha256": poly_book.sha256 if poly_book else None}
        row = {"pair": {"kalshi": left, "polymarket": right}, "evidence": evidence}
        book_difference = book_cancellation_difference(kalshi_book, poly_book) if kalshi_book and poly_book else None
        if not kalshi_book:
            reason = "The full Kalshi contract terms could not be retrieved."
        elif difference := cancellation_mismatch(left, right, kalshi_book):
            row["difference"] = difference
            evidence["polymarket_source"] = "inline_rules"
            report["different_rules"].append(row)
            continue
        elif not p_terms or not poly_book:
            reason = "The full criteria could not be established from the published Polymarket rules."
        elif not k_terms or k_terms[0] != p_terms[0]:
            reason = "The published settlement conditions or exceptions could not be shown to match."
        elif not book_difference and not equivalent_rulebooks(kalshi_book, poly_book):
            reason = "The complete governing documents could not be shown to be equivalent."
        elif k_terms[1] and document(k_terms[1]) != kalshi_book:
            reason = "The Kalshi market and series reference different governing terms."
        elif book_difference and any(re.search(r"\b(?:cancel\w*|abandon\w*|refund|void)\b",
                                              f"{leg['rules']} {leg['secondary_rules']}", re.I)
                                     for leg in (left, right)):
            reason = "Market-level cancellation clauses may override the governing documents."
        else:
            left_payout, right_payout = book_difference or (k_terms[2], p_terms[2])
            if (left_payout and right_payout and left_payout != right_payout
                    and not all(DISCRETIONARY.search(payout) for payout in (left_payout, right_payout))):
                row["kalshi_cancellation"] = left_payout
                row["polymarket_cancellation"] = right_payout
                report["cancellation_only"].append(row)
                continue
            if left_payout == right_payout and (not left_payout or not DISCRETIONARY.search(left_payout)):
                report["verified"].append(row)
                continue
            reason = "The cancellation payouts could not be compared without interpreting venue-specific fair-price rules."
        row["reason"] = reason
        if "reason" in candidate:
            row["lead_reason"] = candidate["reason"]
        report["manual_review"].append(row)
    return report


def current_assessment_rows(rows):
    series_book, document = document_lookup()
    for row in rows:
        evidence = row["evidence"]
        fingerprint = evidence.get("kalshi_sha256")
        series = row["pair"]["kalshi"]["id"].split("-", 1)[0]
        official_url = series_book(series)
        if not fingerprint or official_url != evidence.get("kalshi_rulebook"):
            continue
        kalshi_book = document(official_url)
        if not kalshi_book or kalshi_book.sha256 != fingerprint:
            continue
        if evidence.get("polymarket_source") == "inline_rules":
            yield row
            continue
        poly_book = document(evidence.get("polymarket_rulebook"))
        if poly_book and poly_book.sha256 == evidence.get("polymarket_sha256", fingerprint):
            yield row
