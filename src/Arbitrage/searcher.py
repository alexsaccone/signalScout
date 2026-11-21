from collections import Counter, defaultdict
from datetime import date, timedelta
from heapq import nsmallest
import re
from unicodedata import normalize

if __package__:
    from .api import POLY_US, lookup_markets, more_kalshi, more_poly, more_poly_us, ScanError, SCAN_WINDOW
else:
    from api import POLY_US, lookup_markets, more_kalshi, more_poly, more_poly_us, ScanError, SCAN_WINDOW


def filter_kalshi_events(now, window=SCAN_WINDOW):
    return more_kalshi(2000, now, window)


def filter_polymarket_events(now, window=SCAN_WINDOW):
    return more_poly(2000, now, window)


def filter_polymarket_us_events(now, window=SCAN_WINDOW):
    return more_poly_us(1000, now, window)


def market_terms(market):
    terms = {key: market[key] for key in ("id", "title", "subtitle", "rules", "secondary_rules", "resolution")}
    terms["close_time"] = market["close_time"].isoformat()
    if "tokens" in market:
        terms["tokens"] = market["tokens"]
    if market.get("venue") == POLY_US:
        terms["venue"] = POLY_US
        if "url" in market:
            terms["url"] = market["url"]
    return terms


MAX_SUGGESTIONS = 3
DATED = r"\b\d{4}-\d{2}-\d{2}\b"
IF_YES = re.compile(
    r'^If (.+?), (?:then )?(?:the|this) market (?:will resolve|resolves) to "?Yes"?\.(?: |$)', re.I,
)
YES_IF = r'^This market (?:will resolve|resolves|will settle|settles) to "?Yes"? if ('
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

# Only an explicit incorporation clause makes a linked document governing.
CONTRACT_REFERENCE = re.compile(r"^(?:Governing contract terms|For full rules, see): (https://[^\s]+?\.pdf)\.?[ \t]*\r?$", re.M)

CLOCK = re.compile(r"\bat (0?[1-9]|1[0-2])(?::([0-5]\d))? ([ap])\.?m\.? (ET|CT|MT|PT|UTC)\b", re.I)
CUTOFF_TIME = re.compile(r"11:59|12(?::00)? a\.?m|00:00|midnight", re.I)
CUTOFF_ZONE = r"(?P<zone>ET|CT|MT|PT|UTC)"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
CUTOFF_DAY = rf"(?:(?P<weekday>{'|'.join(WEEKDAYS)}), )?(?P<day>{DATED})"
LAST_MINUTE = rf"11:59 p\.?m\.? {CUTOFF_ZONE}"
MIDNIGHT_CLOCK = rf"(?:12(?::00)? a\.?m\.?|00:00) {CUTOFF_ZONE}"
ENTIRE_MINUTE = r", including the entire (?:final|11:59 p\.?m\.?) minute\b"
FULL_MINUTE_CUTOFFS = (
    re.compile(rf"\bthrough the end of the {LAST_MINUTE} minute on {CUTOFF_DAY}", re.I),
    re.compile(rf"\bthrough {CUTOFF_DAY}(?: at |, ){LAST_MINUTE}{ENTIRE_MINUTE}", re.I),
    re.compile(rf"\bthrough {LAST_MINUTE} on {CUTOFF_DAY}{ENTIRE_MINUTE}", re.I),
)
NEXT_MIDNIGHT_CUTOFFS = (
    re.compile(rf"\bbefore {CUTOFF_DAY} at {MIDNIGHT_CLOCK}\b", re.I),
    re.compile(rf"\bbefore {MIDNIGHT_CLOCK} on {CUTOFF_DAY}", re.I),
    re.compile(rf"\bbefore midnight {CUTOFF_ZONE} at the start of {CUTOFF_DAY}", re.I),
    re.compile(rf"\bbefore midnight at the start of {CUTOFF_DAY} (?P<paren>\()?{CUTOFF_ZONE}\b(?(paren)\))", re.I),
)
AMBIGUOUS_FINAL_MINUTE = (
    re.compile(rf"\b(?:by|through|until) {CUTOFF_DAY}(?: at |, ){LAST_MINUTE}\b", re.I),
    re.compile(rf"\b(?:by|through|until) {LAST_MINUTE} on {CUTOFF_DAY}", re.I),
)
AMBIGUOUS_MIDNIGHT = (
    re.compile(rf"\b(?:by|through|until) {CUTOFF_DAY}(?: at |, ){MIDNIGHT_CLOCK}\b", re.I),
    re.compile(rf"\b(?:by|before|through|until) midnight {CUTOFF_ZONE} on {CUTOFF_DAY}", re.I),
    re.compile(rf"\b(?:by|through|until) {MIDNIGHT_CLOCK} on {CUTOFF_DAY}", re.I),
)
QUOTED = re.compile(r'("[^"]*"|“[^”]*”)')
STAT_THRESHOLD = re.compile(
    r'^([^"“”]+?) (?:scores|records) '
    r'(?:(at least|no fewer than|greater than|more than|at most|no more than|less than|exactly) (\d+)'
    r'|(\d+)(\+| or more| or fewer)) (points|assists|rebounds|goals|touchdowns)(?= in the )'
)
STAT_COMPARISON = {
    "at least": "at least", "no fewer than": "at least", "or more": "at least", "+": "at least",
    "greater than": "more than", "more than": "more than",
    "at most": "at most", "no more than": "at most", "or fewer": "at most",
    "less than": "less than", "exactly": "exactly",
}
SENTENCE_START = r'(?:^|(?<=\. )|(?<=\." ))'
SETTLEMENT_CLAUSE = re.compile(
    rf'(?P<literal>{QUOTED.pattern})|{SENTENCE_START}(?:'
    rf'Use (?P<use_source>{SOURCE_URL.pattern}) as the official source\.'
    rf'|The resolution source for this market (?:is|will be) (?P<is_source>{SOURCE_URL.pattern})\.'
    rf'|Outcome sourced from [^()\n.]+ \((?P<outcome_source>{SOURCE_URL.pattern})\)\.'
    r'|If the (?P<event>game|match|fight) is cancell?ed, '
    r'(?:settle at |(?:the|this) market (?:resolves|will resolve)(?: to)? )'
    r'(?P<cancel_quote>")?(?P<cancel_payout>50-50|Yes|No)(?(cancel_quote)(?:"\.|\.")|\.)'
    r'|(?P<default>Otherwise, (?:the|this) market (?:resolves|will resolve) to (?:"No\."|"No"\.|No\.))'
    r')(?= |$)'
)


def iso_date(match):
    month, day, year = match.groups()
    return date(int(year), MONTH_NUMBER[month.lower()], int(day)).isoformat()


def normalize_cutoffs(text, review_cutoffs):
    if not CUTOFF_TIME.search(text):
        return text

    def boundary(match, shift):
        try:
            stated_day = date.fromisoformat(match["day"])
            if match["weekday"] and WEEKDAYS[stated_day.weekday()] != match["weekday"].casefold():
                return match[0]
            day = stated_day + timedelta(days=shift)
        except (OverflowError, ValueError):
            return match[0]
        return f'before {day.isoformat()} at 12:00 AM {match["zone"].upper()}'

    for pattern in FULL_MINUTE_CUTOFFS:
        text = pattern.sub(lambda match: boundary(match, 1), text)
    for pattern in NEXT_MIDNIGHT_CUTOFFS:
        text = pattern.sub(lambda match: boundary(match, 0), text)
    if review_cutoffs:
        for pattern in AMBIGUOUS_FINAL_MINUTE:
            text = pattern.sub(lambda match: boundary(match, 1), text)
        for pattern in AMBIGUOUS_MIDNIGHT:
            text = pattern.sub(lambda match: boundary(match, 0), text)
    return text


def normalize_rule_text(text, *, review_cutoffs=False):
    parts = QUOTED.split(text)
    for index in range(0, len(parts), 2):
        part = re.sub(r"\s+", " ", parts[index])
        part = EVENT_DATE.sub(iso_date, part)
        part = CLOCK.sub(
            lambda m: f"at {int(m[1])}:{m[2] or '00'} {m[3].upper()}M {m[4].upper()}", part,
        )
        parts[index] = normalize_cutoffs(part, review_cutoffs)
    return "".join(parts).strip()


def normalize_condition(condition):
    stat = STAT_THRESHOLD.match(condition)
    if stat:
        player, prefix, prefixed_number, suffixed_number, suffix, unit = stat.groups()
        comparison = STAT_COMPARISON[prefix or suffix.strip()]
        condition = f"{player} records {comparison} {prefixed_number or suffixed_number} {unit}" + condition[stat.end():]

    parts = QUOTED.split(condition)
    for index in range(0, len(parts), 2):
        parts[index] = MATCHUP.sub(lambda m: re.sub(r" (?:vs\.?|versus) ", " vs ", m[0]), parts[index])
    return "".join(parts)


def normalize_settlement_terms(remaining):
    sources = set()

    def normalize_clause(match):
        if match["literal"]:
            return match[0]
        if match["event"]:
            return f'If the {match["event"]} is canceled, settle at {match["cancel_payout"]}.'
        if match["default"]:
            return "Otherwise, this market will resolve to No."
        sources.add(match["use_source"] or match["is_source"] or match["outcome_source"])
        return ""

    # Only a standalone source declaration can move without changing precedence.
    remaining = SETTLEMENT_CLAUSE.sub(normalize_clause, remaining)
    return normalize_rule_text(remaining), frozenset(sources)


def published_condition(market):
    try:
        rules = normalize_rule_text(market["rules"])
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
    return condition, rules[payout.end():]


def settlement_key(market):
    parsed = published_condition(market)
    if not parsed:
        return None
    condition, remaining = parsed
    if not re.search(DATED, condition) or UNNAMED.search(condition):
        return None
    if SPORT.search(condition) and not (MATCHUP.search(condition) and SPORTS_SESSION.search(condition)):
        return None

    try:
        remaining = normalize_rule_text(f"{remaining} {market['secondary_rules']}")
        remaining, declared_sources = normalize_settlement_terms(remaining)
    except ValueError:
        return None
    sources = declared_sources or {url.rstrip(".,;!?") for url in SOURCE_URL.findall(remaining)}
    resolution = market["resolution"]
    if len(declared_sources) > 1 or not sources:
        return None
    if isinstance(resolution, str) and resolution and resolution.strip() not in sources:
        return None

    # shortcut: Unrecognized terms must still match as written. Add rules for observed paraphrases.
    return normalize_condition(condition), remaining, declared_sources


def review_candidates(kalshi, polymarket, key=settlement_key):
    by_settlement = defaultdict(lambda: defaultdict(list))
    for market in sorted(polymarket, key=lambda market: market["id"]):
        terms = key(market)
        if terms is not None:
            venue_matches = by_settlement[terms][market.get("venue")]
            if len(venue_matches) < MAX_SUGGESTIONS:
                venue_matches.append(market)

    candidates = []
    for left in kalshi:
        candidates.extend(
            {"kalshi": market_terms(left), "polymarket": market_terms(right)}
            for venue_matches in by_settlement.get(key(left), {}).values()
            for right in venue_matches
        )
    return candidates


LEAD_STOP_WORDS = frozenset("""
    the of and or a an to at for in is be will by on originally scheduled after
    including does not include between professional soccer game match vs versus fc afc
    am pm et est edt ct cst cdt time each during
""".split())
LEAD_WORD = re.compile(r"[^\W_]+")
MAX_LEADS = 80
MAX_POSTINGS = 120
LEAD_TYPES = {
    "score": re.compile(r"\bfinal score\b"),
    "both teams score": re.compile(r"\bboth teams (?:to )?score\b"),
    "margin": re.compile(r"\bwins? by (?:more than|at least)\b"),
    "player goals": re.compile(r": \d+\+ goals?\??$"),
    "winner": re.compile(r"\bwins?(?: (?:1st|2nd) half)?\??$|\bleading at halftime\b"),
}


def lead_type(title):
    title = title.casefold()
    kind = next((kind for kind, pattern in LEAD_TYPES.items() if pattern.search(title)), None)
    if kind is None:
        return None
    if re.search(r"\b(?:1st half|first half|halftime)\b", title):
        period = "first half"
    elif re.search(r"\b(?:2nd half|second half)\b", title):
        period = "second half"
    else:
        period = "full match"
    return kind, period


def lead_terms(market):
    parsed = published_condition(market)
    if not parsed:
        return None
    condition, _ = parsed
    dates = set(re.findall(DATED, condition))
    words = frozenset(LEAD_WORD.findall(re.sub(DATED, "", condition).casefold())) - LEAD_STOP_WORDS
    if len(dates) == 1 and len(words) >= 3:
        return dates.pop(), words


def rule_matches(pattern, text):
    quoted = list(QUOTED.finditer(text))
    return {match.start(): match for match in pattern.finditer(text)
            if not any(span.start() < match.start() < span.end() for span in quoted)}


def cutoff_review_key(market):
    if not CUTOFF_TIME.search(market["rules"] + " " + market["secondary_rules"]):
        return None
    try:
        rules = market["rules"]
        references = rule_matches(CONTRACT_REFERENCE, rules)
        rules = CONTRACT_REFERENCE.sub(lambda match: "" if match.start() in references else match[0], rules)
        fields = {"rules": normalize_rule_text(rules, review_cutoffs=True),
                  "secondary_rules": normalize_rule_text(market["secondary_rules"], review_cutoffs=True)}
    except ValueError:
        return None
    if " at 12:00 AM " in fields["rules"] + " " + fields["secondary_rules"]:
        return settlement_key(dict(market, **fields))


def review_leads(kalshi, polymarket):
    by_word = defaultdict(list)
    poly_terms = []
    venues = dict.fromkeys(market.get("venue") for market in polymarket)
    for market in polymarket:
        info = lead_terms(market)
        if not info:
            continue
        day, words = info
        index = len(poly_terms)
        poly_terms.append((market, words, lead_type(market['title'])))
        venue = market.get("venue")
        for word in words:
            posting = by_word[venue, day, word]
            if len(posting) <= MAX_POSTINGS:
                posting.append(index)

    by_event = defaultdict(list)
    for left in kalshi:
        info = lead_terms(left)
        if not info:
            continue
        day, words = info
        postings = (by_word.get((venue, day, word), ()) for venue in venues for word in words)
        overlaps = Counter(i for posting in postings if len(posting) <= MAX_POSTINGS for i in posting)
        left_type = lead_type(left["title"])
        groups = set()
        for i, common in overlaps.items():
            if common < 3:
                continue
            right, right_words, right_type = poly_terms[i]
            if left_type and right_type and left_type != right_type:
                continue
            score = len(words & right_words) / len(words | right_words)
            if score >= 0.5:
                group = right.get("venue"), left["event_id"]
                by_event[group].append((-score, left["id"], right["id"], day, left, right))
                groups.add(group)
        for group in groups:
            by_event[group] = nsmallest(2, by_event[group], key=lambda lead: lead[:3])

    by_venue = defaultdict(list)
    for (venue, _), group in by_event.items():
        by_venue[venue].extend(group)
    cutoff_leads = review_candidates(kalshi, polymarket, key=cutoff_review_key)
    candidates = []
    for lead in cutoff_leads:
        left_key = settlement_key(lead["kalshi"])
        if left_key is None or left_key != settlement_key(lead["polymarket"]):
            candidates.append({"reason": "Compare the end-of-day cutoff wording", **lead})
    for venue_leads in by_venue.values():
        ranked = nsmallest(MAX_LEADS, venue_leads, key=lambda lead: lead[:3])
        candidates.extend({"event_date": day, "kalshi": market_terms(left), "polymarket": market_terms(right)}
                          for _, _, _, day, left, right in ranked)
    events = {market["id"]: market["event_id"] for market in kalshi}
    seen_events = Counter()
    seen_venues = Counter()
    unique = {}
    for lead in candidates:
        ids = lead["kalshi"]["id"], lead["polymarket"]["id"]
        venue = lead["polymarket"].get("venue")
        group = venue, events[ids[0]]
        if ids in unique or seen_events[group] >= 2 or seen_venues[venue] >= MAX_LEADS:
            continue
        unique[ids] = lead
        seen_events[group] += 1
        seen_venues[venue] += 1
    return list(unique.values())


NEXT_ROLE_RULES = (
    re.compile(rf"^If (.+?) formally holds the position of (.+?) before ({DATED}), and is the first such subject\b", re.I),
    re.compile(rf'^This market will settle to "?Yes"? if (.+?) is the next person to assume the position of (.+?) by ({DATED})\b', re.I),
)


def next_role(market):
    rules = normalize_rule_text(market["rules"])
    for pattern in NEXT_ROLE_RULES:
        if match := pattern.match(rules):
            person, role, day = match.groups()
            return (person.casefold(), role.casefold()), date.fromisoformat(day)
    return None


def shared_role_leads(kalshi, polymarket):
    right_sides = defaultdict(list)
    for market in polymarket:
        if not market["rules"].startswith("This market will settle to"):
            continue
        try:
            info = next_role(market)
        except ValueError:
            continue
        if info:
            right_sides[info[0]].append(market)
    for market in kalshi:
        if "formally holds the position of" not in market["rules"]:
            continue
        try:
            info = next_role(market)
        except ValueError:
            continue
        if info:
            for right in right_sides.get(info[0], ()):
                yield {"kalshi": market_terms(market), "polymarket": market_terms(right)}


def same_scheduled_fixture(left, right):
    try:
        fixture = SCHEDULED_FIXTURE.match(normalize_rule_text(right["rules"]))
        left_rule = normalize_rule_text(left["rules"])
    except ValueError:
        return False
    if not fixture:
        return False
    _, _, first, second, day, _ = fixture.groups()
    marker = f" originally scheduled for {day}"
    if marker not in left_rule:
        return False
    matchup = left_rule.split(marker)[0]
    sides = re.split(r" \b(?:vs\.?|versus) ", matchup, flags=re.I)
    if len(sides) != 2:
        return False

    def words(text):
        ascii_text = normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
        return [word for word in LEAD_WORD.findall(ascii_text) if word not in {"fc", "afc", "ac"}]

    before, after = map(words, sides)
    for home, away in ((words(first), words(second)), (words(second), words(first))):
        if home and away and before[-len(home):] == home and after[:len(away)] == away:
            return True
    return False


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
    market_ids = defaultdict(set)
    for review in reviews:
        for venue, leg in (("kalshi", review["kalshi"]), (review["polymarket"].get("venue", "polymarket"),
                                                        review["polymarket"])):
            if venue not in {"kalshi", "polymarket", POLY_US}:
                raise ScanError("Unsupported review venue")
            market_id = leg["id"]
            if not isinstance(market_id, str) or not market_id.strip():
                raise ScanError(f"Invalid reviewed {venue} market ID")
            market_ids[venue].add(market_id)
    kalshi = lookup_markets(market_ids["kalshi"], "kalshi", now)
    poly = lookup_markets(market_ids["polymarket"], "polymarket", now)
    if market_ids[POLY_US]:
        poly += lookup_markets(market_ids[POLY_US], POLY_US, now)
    return verified_pairs(kalshi, poly, reviews)
