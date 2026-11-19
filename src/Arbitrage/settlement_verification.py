from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
import re

import requests

if __package__:
    from .api import KALSHI_URL, ScanError, fetch_json
    from .searcher import QUOTED, review_candidates, settlement_key
else:
    from api import KALSHI_URL, ScanError, fetch_json
    from searcher import QUOTED, review_candidates, settlement_key


# Only an explicit incorporation clause makes a linked document governing.
CONTRACT_REFERENCE = re.compile(r"^Governing contract terms: (https://[^\s]+?\.pdf)\.?[ \t]*\r?$", re.M)
OFFICIAL_RULEBOOK = re.compile(
    r"https://(?:assets\.kalshi\.com|kalshi-public-docs\.s3\.amazonaws\.com)/contract_terms/[\w-]+\.pdf"
)
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
MAX_RULEBOOK_BYTES = 2_000_000


def rulebook_url(series):
    if not re.fullmatch(r"[A-Z0-9]+", series):
        return None
    doc, _ = fetch_json(f"{KALSHI_URL}/series/{series}")
    return doc["series"].get("contract_terms_url") or ""


def rulebook_digest(url):
    if not OFFICIAL_RULEBOOK.fullmatch(url):
        return None
    with requests.get(url, stream=True, allow_redirects=False, timeout=(5, 15)) as response:
        if response.status_code != 200:
            return None
        body = bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > MAX_RULEBOOK_BYTES:
                return None
    if not body.startswith(b"%PDF-") or not body.rstrip().endswith(b"%%EOF"):
        return None
    return sha256(body).hexdigest()


def rule_matches(pattern, text):
    quoted = list(QUOTED.finditer(text))
    return {match.start(): match for match in pattern.finditer(text)
            if not any(span.start() < match.start() < span.end() for span in quoted)}


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
    def digest(url):
        try:
            return rulebook_digest(url) if url else None
        except requests.RequestException:
            return None

    return series_book, digest


def assessment_report(kalshi, polymarket, candidates, leads, now=None):
    report = {"generated_at": (now or datetime.now(timezone.utc)).isoformat(),
              "verified": [], "cancellation_only": [], "manual_review": []}
    markets = {market["id"]: market for market in kalshi + polymarket}
    explicit_books = [market for market in polymarket if CONTRACT_REFERENCE.search(market["rules"])]
    series_book, digest = document_lookup()

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
        fingerprint = digest(url)
        k_terms, p_terms = map(comparison, ids)
        evidence = {"kalshi_rulebook": url, "kalshi_sha256": fingerprint}
        row = {"pair": {"kalshi": left, "polymarket": right}, "evidence": evidence}
        if not fingerprint:
            reason = "The full Kalshi contract terms could not be retrieved."
        elif not p_terms:
            reason = "Polymarket did not supply comparable complete terms with an explicit governing document."
        elif not k_terms or k_terms[0] != p_terms[0]:
            reason = "The published settlement conditions or exceptions could not be shown to match."
        elif digest(p_terms[1]) != fingerprint or (k_terms[1] and digest(k_terms[1]) != fingerprint):
            reason = "The governing documents could not be shown to match."
        else:
            evidence["polymarket_rulebook"] = p_terms[1]
            left_payout, right_payout = k_terms[2], p_terms[2]
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
        report["manual_review"].append(row)
    return report


def current_assessment_rows(rows):
    series_book, digest = document_lookup()
    for row in rows:
        evidence = row["evidence"]
        fingerprint = evidence.get("kalshi_sha256")
        series = row["pair"]["kalshi"]["id"].split("-", 1)[0]
        official_url = series_book(series)
        if (fingerprint and official_url == evidence.get("kalshi_rulebook")
                and digest(official_url) == fingerprint
                and digest(evidence.get("polymarket_rulebook")) == fingerprint):
            yield row
