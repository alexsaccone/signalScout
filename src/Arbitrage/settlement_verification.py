from datetime import datetime, timedelta, timezone
from functools import lru_cache
from hashlib import sha256
import re

import requests

if __package__:
    from .api import GAMMA_URL, KALSHI_URL, POLY_US, ScanError, fetch_json
    from .settlement_events import event_difference, event_leads
    from .searcher import CONTRACT_REFERENCE, next_role, published_condition, review_candidates, rule_matches, same_scheduled_fixture, settlement_key, shared_role_leads, stat_cutoff
    from .settlement_documents import (
        KALSHI_BOOK, Rulebook, book_cancellation_difference, equivalent_rulebooks, filing_url,
        load_filing_catalog, load_rulebook, rule_policy,
    )
else:
    from api import GAMMA_URL, KALSHI_URL, POLY_US, ScanError, fetch_json
    from settlement_events import event_difference, event_leads
    from searcher import CONTRACT_REFERENCE, next_role, published_condition, review_candidates, rule_matches, same_scheduled_fixture, settlement_key, shared_role_leads, stat_cutoff
    from settlement_documents import (
        KALSHI_BOOK, Rulebook, book_cancellation_difference, equivalent_rulebooks, filing_url,
        load_filing_catalog, load_rulebook, rule_policy,
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
EXTERNAL_TERMS = re.compile(
    r"\.pdf\b|\brulebook\b|\b(?:full|complete|governing) (?:market |contract )?(?:rules|terms)\b", re.I,
)
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
RATING_CONDITION = re.compile(
    r"(.+?) has a (?:Rotten Tomatoes )?Tomatometer score of (above )?(\d{1,3})( or more)? "
    r"on (\d{4}-\d{2}-\d{2} at \d{1,2}:\d{2} [AP]M ET)"
)
# Reviewed versions of Kalshi RT and Polymarket US ROTC.
RATING_BOOKS = ("871c9d51b9e908ec3653bf71f6e1fb9f5f50ef7180cea9fc7c52a87753e08f2f",
                "65f81b4acc4c9e10f88e86e7dc8d953c08758e556806a507f4e3784dc852b482")
RATING_KALSHI_SECONDARY = "06615583780b946abfba8ff2de17f62c07d812c699740217dae5b08b1e061bea"
NETFLIX_BOOKS = ("e053f0ff7aa757f872c436f1ac18aad410353443f6a847b4221a37c27162ec34",
                 "5f4ed4e824174a5045df453670dbd2736e7cd008bc68c7bc6013a9d1a32d5b16")
NETFLIX_RANK = (
    re.compile(r"(.+?) is #([1-9][0-9]*) on the Netflix Top 10 (Global|US) (Movie|Show) "
               r"on the chart published on (\d{4}-\d{2}-\d{2})"),
    re.compile(r"(.+?) is #([1-9][0-9]*) on the Netflix (Global) Top 10 (Movie|Show)s \(English\) "
               r"chart published on (\d{4}-\d{2}-\d{2})"),
    re.compile(r"(.+?) is #([1-9][0-9]*) on the Netflix Top 10 (Movie|Show)s in (United States) "
               r"chart published on (\d{4}-\d{2}-\d{2})"),
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
    if UNBOUND_TERM.search(prose) or DISCRETIONARY.search(prose) or EXTERNAL_TERMS.search(prose):
        return None
    return key, book[0] if book else None, payout


def inline_rulebook(market):
    rules = f"{market['rules']}\n{market['secondary_rules']}"
    if not EXTERNAL_TERMS.search(rules) and (policy := rule_policy(rules)):
        return Rulebook(sha256(rules.encode("utf-8")).hexdigest(), policy)


def market_clarifications(market_id, event_id):
    if not all(isinstance(value, (int, str)) and re.fullmatch(r"[0-9]+", str(value))
               for value in (market_id, event_id)):
        return None
    try:
        for key, identifier in (("market_id", market_id), ("event_id", event_id)):
            rows, _ = fetch_json(f"{GAMMA_URL}/market-clarifications", {key: identifier, "limit": 1})
            if not isinstance(rows, list):
                return None
            if rows:
                return True
    except ScanError:
        return None
    return False


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

    @lru_cache(maxsize=1)
    def catalog():
        try:
            return load_filing_catalog()
        except (requests.RequestException, KeyError, TypeError, ValueError):
            return {}

    return series_book, document, catalog, lru_cache(maxsize=None)(market_clarifications)


def role_deadline_difference(left, right):
    if "formally holds the position of" not in left["rules"] or "next person to assume the position of" not in right["rules"]:
        return None
    try:
        kalshi, poly = next_role(left), next_role(right)
    except ValueError:
        return None
    # Dates alone cannot establish an interval between adjacent civil days.
    if not kalshi or not poly or kalshi[0] != poly[0] or abs(kalshi[1] - poly[1]) < timedelta(days=2):
        return None
    k_day, p_day = kalshi[1], poly[1]
    k_payout, p_payout = ("Yes", "No") if k_day > p_day else ("No", "Yes")
    return {"scenario": "The named candidate first takes office between the two deadlines",
            "kalshi_cutoff": k_day.isoformat(), "polymarket_cutoff": p_day.isoformat(),
            "kalshi_cutoff_inclusive": False, "polymarket_cutoff_inclusive": True,
            "kalshi_payout": k_payout, "polymarket_payout": p_payout}


def film_rating_key(market):
    is_kalshi = market["id"].startswith("KXRT-")
    if not is_kalshi and not (market.get("venue") == POLY_US and market["id"].startswith("rotc-")):
        return None
    parsed = published_condition(market)
    if not parsed or not (match := RATING_CONDITION.fullmatch(parsed[0])):
        return None
    film, above, threshold, inclusive, cutoff = match.groups()
    if is_kalshi:
        strike = market["resolution"]
        if (not above or inclusive or parsed[1] or not isinstance(strike, dict) or strike.get("strike_type") != "greater"
                or strike.get("floor_strike") != int(threshold)):
            return None
    elif above or not inclusive or parsed[1] != "Outcome sourced from Rotten Tomatoes." or market["secondary_rules"]:
        return None
    return film.casefold(), int(threshold), cutoff


def stat_payout_difference(k_terms, p_terms, kalshi_book, poly_book):
    # Only the exact same fixed source and unconditional No default support this proof.
    default = "Otherwise, this market will resolve to No."
    if not (k_terms and p_terms and kalshi_book and poly_book):
        return None
    k_key, k_reference, k_cancel = k_terms
    p_key, _, p_cancel = p_terms
    if (k_reference or k_cancel or p_cancel or k_key[1:] != p_key[1:] or k_key[1] != default
            or kalshi_book.policy != (default, k_key[2]) or poly_book.policy != kalshi_book.policy):
        return None
    lhs, rhs = stat_cutoff(k_key[0]), stat_cutoff(p_key[0])
    if not lhs or not rhs or lhs[0] != rhs[0] or lhs[1] == rhs[1]:
        return None
    payouts = ("yes", "no") if lhs[1] < rhs[1] else ("no", "yes")
    scenario = f"{lhs[0][0]} records exactly {min(lhs[1], rhs[1])} {lhs[0][1]}"
    return {"scenario": scenario, "kalshi_payout": payouts[0].title(), "polymarket_payout": payouts[1].title()}, payouts


def netflix_rank(market):
    if not market["id"].startswith(("KXNETFLIXRANK", "ccrc-ntflx-")):
        return None
    parsed = published_condition(market)
    if not parsed:
        return None
    condition, _ = parsed
    for pattern in NETFLIX_RANK:
        if match := pattern.fullmatch(condition):
            entry, rank, region, kind, day = match.groups()
            if kind == "United States":
                region, kind = "US", region
            return (entry.casefold(), region, kind, day), int(rank)
    return None


def assessment_report(kalshi, polymarket, candidates, leads, now=None):
    now = now or datetime.now(timezone.utc)
    report = {"generated_at": now.isoformat(),
              "verified": [], "cancellation_only": [], "different_rules": [], "manual_review": []}
    markets = {market["id"]: market for market in kalshi + polymarket}
    comparable = [market for market in polymarket if CONTRACT_REFERENCE.search(market["rules"])
                  or any(phrase in market["rules"] for phrase in ("https://", "http://"))]
    series_book, document, catalog, clarifications = document_lookup()

    @lru_cache(maxsize=None)
    def comparison(market_id):
        return comparable_terms(markets[market_id])

    def key(market):
        parsed = comparison(market["id"])
        return parsed[0] if parsed else None

    matches = review_candidates(kalshi, comparable, key=key, all_matches=True) if comparable else []
    rating_markets = [market for market in polymarket if market["id"].startswith("rotc-")]
    rating_leads = review_candidates(kalshi, rating_markets, key=film_rating_key, all_matches=True) if rating_markets else []
    rank_markets = [market for market in polymarket if market["id"].startswith("ccrc-ntflx-")]

    def chart_key(market):
        rank = netflix_rank(market)
        return rank[0] if rank else None

    rank_leads = review_candidates(kalshi, rank_markets, key=chart_key, all_matches=True) if rank_markets else []
    structured_leads = list(event_leads(kalshi, polymarket))
    seen = set()
    for candidate in structured_leads + matches + rating_leads + rank_leads + list(shared_role_leads(kalshi, polymarket)) + candidates + leads:
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
        source = "linked_rulebook"
        if not references:
            if right.get("venue") == POLY_US:
                source = "regulatory_filing"
                poly_url = filing_url(right["id"], markets[right["id"]].get("listed_at"), catalog(), now.date())
            elif not EXTERNAL_TERMS.search(f"{right['rules']} {right['secondary_rules']}"):
                source = "inline_rules"
        poly_book = inline_rulebook(right) if source == "inline_rules" else document(poly_url)
        evidence = {"kalshi_rulebook": url, "kalshi_sha256": kalshi_book.sha256 if kalshi_book else None,
                    "polymarket_source": source, "polymarket_rulebook": poly_url,
                    "polymarket_sha256": poly_book.sha256 if poly_book else None}
        if source == "regulatory_filing":
            evidence["polymarket_listed_at"] = markets[right["id"]].get("listed_at")
        elif source == "inline_rules":
            evidence["polymarket_market_id"] = markets[right["id"]].get("market_id")
            evidence["polymarket_event_id"] = markets[right["id"]].get("market_event_id")
        event_title = markets[right["id"]].get("event_title")
        row = {"pair": {"kalshi": left, "polymarket": right}, "evidence": evidence,
               "event_id": markets[left["id"]]["event_id"],
               "kalshi_event_id": markets[left["id"]]["event_id"],
               "polymarket_event_query": event_title,
               "polymarket_event_url": markets[right["id"]].get("url"),
               "event_title": event_title.strip() if isinstance(event_title, str) and event_title.strip() else left["title"]}
        if difference := event_difference(candidate.get("event_terms"), kalshi_book, poly_book):
            scenario, kalshi_payout, polymarket_payout = difference
            row["difference"] = {"scenario": scenario, "kalshi_payout": kalshi_payout, "polymarket_payout": polymarket_payout}
            row["shared_event"] = True
            report["different_rules"].append(row)
            continue
        book_difference = book_cancellation_difference(kalshi_book, poly_book) if kalshi_book and poly_book else None
        cutoff_difference = role_deadline_difference(left, right) if kalshi_book and poly_book and poly_url else None
        if cutoff_difference:
            row["difference"] = cutoff_difference
            row["shared_event"] = True
            report["different_rules"].append(row)
            continue
        if (kalshi_book and poly_book and (kalshi_book.sha256, poly_book.sha256) == RATING_BOOKS
                and sha256(" ".join(left["secondary_rules"].split()).encode("utf-8")).hexdigest() == RATING_KALSHI_SECONDARY):
            rating = film_rating_key(left)
            if rating and rating == film_rating_key(right):
                row["difference"] = {"scenario": f"The Tomatometer score is exactly {rating[1]}%",
                                     "kalshi_payout": "No", "polymarket_payout": "Yes"}
                row["shared_event"] = True
                report["different_rules"].append(row)
                continue
        if kalshi_book and poly_book and (kalshi_book.sha256, poly_book.sha256) == NETFLIX_BOOKS:
            lhs, rhs = netflix_rank(left), netflix_rank(right)
            if lhs and rhs and lhs[0] == rhs[0] and lhs[1] != rhs[1]:
                _, region, kind, day = lhs[0]
                row["event_id"] = f"netflix-{region}-{kind}-{day}"
                row["event_title"] = f"Netflix {region} {kind.lower()} chart · {day}"
                row["difference"] = {"scenario": f"Netflix ranks the named title #{lhs[1]} on that chart",
                                     "kalshi_payout": "Yes", "polymarket_payout": "No"}
                row["shared_event"] = True
                report["different_rules"].append(row)
                continue
        if not left["resolution"] and (stat_difference := stat_payout_difference(k_terms, p_terms, kalshi_book, poly_book)):
            row["difference"], payouts = stat_difference
            row["shared_event"] = True
            row["payout_scenarios"] = [("no", "no"), ("yes", "yes"), payouts]
            row["rule_difference"] = "The venues use different thresholds for the same statistic."
            report["different_rules"].append(row)
            continue
        if not kalshi_book:
            reason = "The full Kalshi contract terms could not be retrieved."
        elif source == "inline_rules" and (difference := cancellation_mismatch(left, right, kalshi_book)):
            row["difference"] = difference
            row["shared_event"] = same_scheduled_fixture(left, right)
            report["different_rules"].append(row)
            continue
        elif not poly_book and source == "regulatory_filing":
            reason = "An applicable full Polymarket US product certification could not be established."
        elif not poly_book and source == "linked_rulebook":
            reason = "The linked governing Polymarket PDF could not be established."
        elif not poly_book or not p_terms:
            reason = "The published Polymarket settlement criteria could not be parsed completely."
        elif not k_terms or k_terms[0] != p_terms[0]:
            reason = "The published settlement conditions or exceptions could not be shown to match."
        elif not book_difference and not equivalent_rulebooks(kalshi_book, poly_book):
            reason = "The complete governing documents could not be shown to be equivalent."
        elif k_terms[1] and document(k_terms[1]) != kalshi_book:
            reason = "The Kalshi market and series reference different governing terms."
        elif source == "inline_rules" and clarifications(evidence["polymarket_market_id"],
                                                         evidence["polymarket_event_id"]) is not False:
            reason = "Polymarket clarifications exist or could not be ruled out."
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
                if (kalshi_book.policy and poly_book.policy
                        and {left_payout, right_payout} <= {"yes", "no", "50-50"}):
                    # Each state records the payout on YES. Outside cancellation the rules agree.
                    row["payout_scenarios"] = [("no", "no"), ("yes", "yes"), (left_payout, right_payout)]
                    row["rule_difference"] = "The venues pay differently if the event is canceled."
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
    report["candidate_pairs_assessed"] = len(seen)
    report["structured_event_candidates"] = len(structured_leads)
    return report


def current_assessment_rows(rows, now=None):
    now = now or datetime.now(timezone.utc)
    series_book, document, catalog, clarifications = document_lookup()
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
        source = evidence.get("polymarket_source")
        if source == "inline_rules" and "difference" in row and "payout_scenarios" not in row:
            yield row
            continue
        right = row["pair"]["polymarket"]
        poly_url = evidence.get("polymarket_rulebook")
        if source == "regulatory_filing" and poly_url != filing_url(
            right["id"], evidence.get("polymarket_listed_at"), catalog(), now.date()
        ):
            continue
        if source == "inline_rules":
            if clarifications(evidence.get("polymarket_market_id"), evidence.get("polymarket_event_id")) is not False:
                continue
            poly_book = inline_rulebook(right)
        else:
            poly_book = document(poly_url)
        if poly_book and poly_book.sha256 == evidence.get("polymarket_sha256", fingerprint):
            yield row
