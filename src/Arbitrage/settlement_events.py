"""Match observed event formats whose operative terms don't share a sentence shape."""
from collections import defaultdict
from datetime import date
import re

if __package__:
    from .searcher import MONTHS, POLY_US, market_terms, normalize_rule_text
else:
    from searcher import MONTHS, POLY_US, market_terms, normalize_rule_text


WEATHER_BOOKS = ("7d0bc031326bf6adcf0e5b50757a9f56c4e30bf21d84e331906869d39411c5a7",
                 "e79cd6f91384d0ee2ccd25ef2405ec8f7fa2bd36ce7f79476073148d4717239f")
FED_BOOKS = ("3a8851179be6e53dbdaa7228179375996a1267412b26af923b7349c35297e198",
             "f88b1722fae0be4232b378371f43d6652d25601c9483523956fdf524dfcf6c12")
# Match the documented station, not just the city.
STATIONS = {"CLINYC": "KNYC", "CLILAX": "KLAX", "CLIMIA": "KMIA", "CLIMDW": "KMDW", "CLISFO": "KSFO"}
K_WEATHER = re.compile(
    r"If the (maximum|minimum) temperature recorded at [^(]+ \((\w+)\) for (\d{4}-\d{2}-\d{2}), "
    r"is (less than|greater than|between) (-?\d+)(?:-(-?\d+))?° fahrenheit according to "
    r"The Weather Company, then the market resolves to Yes\."
)
P_WEATHER = re.compile(
    r"Will the (highest|lowest) temperature recorded at [^(]+ \((\w+)\) [^?]+? for (\d{4}-\d{2}-\d{2}) "
    r"as reported by the National Weather Service's Climatological Report \(Daily\) be "
    r"(less than or equal to|greater than or equal to|between) (-?\d+)F(?: and (-?\d+)F)?\? "
    r"Outcome verified from NWS Climatological Report\."
)
K_FED = re.compile(
    r"If the Federal Reserve does a (Cut|Hike) of (> ?)?(0|25) ?bps on (\d{4}-\d{2}-\d{2}), "
    r"then the market resolves to Yes\."
)
P_FED = re.compile(r"rdc-usfed-fomc-(\d{4}-\d{2}-\d{2})-(hike25|hike50|cut25|cut50|nochng)")
FED_ROUNDING = (
    "If the change in the specified rate does not precisely match the displayed options, changes smaller than "
    "the smallest option of the same direction (increase/decrease) will be rounded to that smallest option, "
    "and changes greater than the smallest option of the same direction will be rounded to the nearest "
    "displayed option, with values exactly halfway between options being rounded away from zero."
)


def weather_option(market):
    is_us = market.get("venue") == POLY_US
    if not market["id"].startswith("tc-temp-" if is_us else ("KXHIGH", "KXLOW")):
        return None
    try:
        rules = normalize_rule_text(market["rules"])
    except ValueError:
        return None
    match = (P_WEATHER if is_us else K_WEATHER).fullmatch(rules)
    if not match:
        return None
    measure, station, day, operator, first, last = match.groups()
    station = station if is_us else STATIONS.get(station)
    if not station:
        return None
    first = int(first)
    if operator == "between":
        if last is None or int(last) < first:
            return None
        bounds = first, int(last)
    elif last is not None:
        return None
    elif operator.startswith("less"):
        bounds = None, first - (not is_us)
    else:
        bounds = first + (not is_us), None
    measure = "high" if measure in {"maximum", "highest"} else "low"
    return ("temperature", station, measure, day), bounds


def fed_option(market):
    if market["id"].startswith("KXFEDDECISION-"):
        try:
            rules = normalize_rule_text(market["rules"])
        except ValueError:
            return None
        if match := K_FED.fullmatch(rules):
            direction, larger, amount, day = match.groups()
            subtitle = market["subtitle"]
            if amount == "25":
                # The API sometimes strips the > sign from the prose but preserves it in the outcome label.
                if subtitle == f"{direction} >25bps":
                    return ("fed", day), direction.casefold() + "50"
                if not larger and subtitle == f"{direction} 25bps":
                    return ("fed", day), direction.casefold() + "25"
            if amount == "0" and direction == "Hike" and not larger and subtitle == "Fed maintains rate":
                return ("fed", day), "nochng"
    if market.get("venue") != POLY_US or not (match := P_FED.fullmatch(market["id"])):
        return None
    day, option = match.groups()
    try:
        meeting = date.fromisoformat(day)
    except ValueError:
        return None
    action = "does not change the upper bound of the target federal funds rate"
    if option != "nochng":
        verb = "increases" if option.startswith("hike") else "decreases"
        minimum = " or more" if option.endswith("50") else ""
        action = f"{verb} the upper bound of the target federal funds rate by {option[-2:]} basis points{minimum}"
    month = MONTHS[meeting.month - 1]
    rules = (
        f"This market will settle to Yes if the Federal Reserve {action} at the {month} {meeting.year} "
        f"Federal Open Market Committee (FOMC) meeting, currently scheduled for {month} "
        f"{meeting.day - 1}-{meeting.day}. Outcome sourced from the Federal Reserve."
    )
    if " ".join(market["rules"].split()) in (rules, f"{rules} {FED_ROUNDING}"):
        return ("fed", day), option


def within(value, bounds):
    low, high = bounds
    return (low is None or low <= value) and (high is None or value <= high)


def event_leads(kalshi, polymarket):
    by_event = defaultdict(list)
    for market in polymarket:
        if result := weather_option(market) or fed_option(market):
            identity, option = result
            by_event[identity].append((option, market))
    for left in kalshi:
        if not (result := weather_option(left) or fed_option(left)):
            continue
        identity, left_option = result
        for right_option, right in by_event[identity]:
            if identity[0] == "fed":
                if left_option != right_option:
                    continue
            else:
                l_low, l_high = left_option
                r_low, r_high = right_option
                if (l_low is None) != (r_low is None) or (l_high is None) != (r_high is None):
                    continue
                if None not in (l_low, l_high, r_low, r_high) and max(l_low, r_low) > min(l_high, r_high):
                    continue
            yield {"kalshi": market_terms(left), "polymarket": market_terms(right),
                   "event_terms": (identity, left_option, right_option)}


def event_difference(terms, left_book, right_book):
    if not (terms and left_book and right_book):
        return None
    identity, left, right = terms
    books = left_book.sha256, right_book.sha256
    if identity[0] == "fed" and books == FED_BOOKS and left != "nochng":
        action = "raises" if left.startswith("hike") else "cuts"
        payouts = ("No", "Yes") if left.endswith("25") else ("Yes", "No")
        return f"The Fed {action} rates by 30 basis points", *payouts
    if identity[0] == "temperature" and books == WEATHER_BOOKS:
        edges = {edge + step for bounds in (left, right) for edge in bounds
                 if edge is not None for step in (-1, 0, 1)}
        for reading in sorted(edges):
            if within(reading, left) != within(reading, right):
                return (f"Both sources report {reading}°F", "Yes" if within(reading, left) else "No",
                        "Yes" if within(reading, right) else "No")
        boundary = left[0] if left[0] is not None else left[1]
        other = boundary - 1 if left[0] is not None else boundary + 1
        return f"The Weather Company reports {boundary}°F and the NWS reports {other}°F", "Yes", "No"
