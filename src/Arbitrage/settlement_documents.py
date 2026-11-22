from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import re
from urllib.parse import quote

from pypdf import PdfReader
from pypdf.errors import PdfReadError
import requests

if __package__:
    from .searcher import QUOTED, normalize_settlement_terms
else:
    from searcher import QUOTED, normalize_settlement_terms


KALSHI_BOOK = (
    r"https://(?:assets\.kalshi\.com|kalshi-public-docs\.s3\.amazonaws\.com)/contract_terms/[\w-]+\.pdf"
)
POLY_FILINGS = "https://www.polymarketexchange.com/files/products/"
FILING_NAME = r"PMUS - ([A-Z0-9]+) - \((\d{4}\.\d{2}\.\d{2})\)\.pdf"
POLYMARKET_BOOK = (
    r"https://(?:docs\.)?polymarket\.com/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_-]+\.pdf"
    r"|https://polymarketexchange\.com/files/product-terms/[a-zA-Z0-9_-]+\.pdf"
    r"|https://polymarket-upload\.s3\.us-east-2\.amazonaws\.com/market_products/"
    r"(?:[a-zA-Z0-9_+-]+/)*[a-zA-Z0-9_+-]+\.pdf"
    rf"|{re.escape(POLY_FILINGS)}PMUS%20-%20[A-Z0-9]+%20-%20%28\d{{4}}\.\d{{2}}\.\d{{2}}%29\.pdf"
)
OFFICIAL_RULEBOOK = re.compile(rf"(?:{KALSHI_BOOK}|{POLYMARKET_BOOK})")
MAX_RULEBOOK_BYTES = 2_000_000
TEXT_OPERATORS = set(b"BT ET Tf Tj TJ Tm Td TD T* ' \" Tc Tw Tz TL Ts Tr q Q cm rg RG g G k K BMC BDC EMC".split())
VENUE_DEPENDENT = re.compile(
    r"\b(?:fair (?:market )?price|sole discretion|exchange rulebook|approved source agencies|"
    r"in its discretion|rules of (?:the|this) (?:exchange|venue))\b",
    re.I,
)

CANCELLATION_CLAUSE = re.compile(
    r'(?:(?<=\. )|^)If the (?P<event>game|match|fight|event) is cancell?ed, '
    r'(?:settle at |(?:the|this) market (?:will resolve|resolves)(?: to)? )'
    r'(?P<quote>")?(?P<payout>Yes|No|50-50)(?(quote)(?:"\.|\.")|\.)'
    r'(?= |$)'
)


@dataclass(frozen=True)
class Rulebook:
    sha256: str
    policy: tuple | None = None


def rule_policy(rules):
    if VENUE_DEPENDENT.search(rules):
        return None
    try:
        terms, sources = normalize_settlement_terms(" ".join(rules.split()))
    except ValueError:
        return None
    if terms and len(sources) <= 1:
        return terms, sources


def text_policy(body):
    try:
        reader = PdfReader(BytesIO(body), strict=True)
        if reader.is_encrypted or not 0 < len(reader.pages) <= 40:
            return None
        root = reader.root_object
        if any(key in root for key in ("/AcroForm", "/Names", "/OpenAction", "/AA")):
            return None
        text = []
        for page in reader.pages:
            contents = page.get_contents()
            if contents is None or "/Annots" in page or "/AA" in page:
                return None
            if any(operator not in TEXT_OPERATORS or (operator == b"Tr" and operands != [0])
                   for operands, operator in contents.operations):
                return None
            page_text = page.extract_text().strip()
            if not page_text:
                return None
            text.append(page_text)
        return rule_policy(" ".join(text))
    except (PdfReadError, AttributeError, KeyError, TypeError, ValueError, OSError):
        return None


def download_rules(url):
    with requests.get(url, stream=True, allow_redirects=False, timeout=(5, 15)) as response:
        if response.status_code != 200:
            return None
        body = bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > MAX_RULEBOOK_BYTES:
                return None
    return body


def rulebook_body(url):
    if not isinstance(url, str) or not OFFICIAL_RULEBOOK.fullmatch(url):
        return None
    body = download_rules(url)
    if not body or not body.startswith(b"%PDF-") or not body.rstrip().endswith(b"%%EOF"):
        return None
    return body


def load_rulebook(url):
    if body := rulebook_body(url):
        return Rulebook(sha256(body).hexdigest(), text_policy(body))


def load_filing_catalog():
    page = download_rules("https://www.polymarketexchange.com/notices.html")
    if page:
        script = re.search(rb'<script type="application/json" id="productCertificationsData">(.+?)</script>', page, re.S)
        if script:
            return json.loads(script[1])["products"]
    return {}


def filing_url(slug, listed_at, catalog, today):
    code, sep, _ = slug.upper().partition("-")
    if not sep or not re.fullmatch(r"[A-Z0-9]+", code) or not isinstance(listed_at, str):
        return None
    try:
        timestamp = datetime.fromisoformat(listed_at)
        if timestamp.tzinfo is None:
            return None
        listed = timestamp.astimezone(timezone.utc).date()
        versions = [(date.fromisoformat(record["effective"]), date.fromisoformat(filed), record)
                    for filed, record in catalog[code]["versions"].items() if not record.get("withdrawn")]
        effective, filed, record = max((v for v in versions if v[0] <= today), key=lambda v: v[:2])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    # The April RDC amendment was checked for markets first listed after it took effect.
    reviewed_amendment = code == "RDC" and filed == date(2026, 4, 6) and record.get("rule") == "40.6"
    if (not filed <= effective < listed <= today or (record.get("rule") != "40.2" and not reviewed_amendment)
            or sum(day == effective for day, _, _ in versions) != 1):
        return None
    stamp = filed.isoformat().replace("-", ".")
    name = record.get("file", f"PMUS - {code} - ({stamp}).pdf")
    match = re.fullmatch(FILING_NAME, name) if isinstance(name, str) else None
    if match and match.groups() == (code, stamp):
        return POLY_FILINGS + quote(name)


def equivalent_rulebooks(left, right):
    return (left.sha256 == right.sha256 or
            (left.policy is not None and right.policy is not None and left.policy == right.policy))


def book_cancellation_difference(left, right):
    def split(policy):
        if not policy:
            return None
        text, sources = policy
        quotes = list(QUOTED.finditer(text))
        clauses = [m for m in CANCELLATION_CLAUSE.finditer(text)
                   if not any(q.start() < m.start() < q.end() for q in quotes)]
        if len(clauses) != 1:
            return None
        clause, = clauses
        masked = f"{text[:clause.start()]}[canceled {clause['event']}]{text[clause.end():]}"
        return (masked, sources), clause["payout"].casefold()

    lhs, rhs = split(left.policy), split(right.policy)
    if lhs and rhs and lhs[0] == rhs[0] and lhs[1] != rhs[1]:
        return lhs[1], rhs[1]
