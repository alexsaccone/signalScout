from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import re

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
POLYMARKET_BOOK = r"https://(?:docs\.)?polymarket\.com/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_-]+\.pdf"
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
            if any(operator not in TEXT_OPERATORS for _, operator in contents.operations):
                return None
            page_text = page.extract_text().strip()
            if not page_text:
                return None
            text.append(page_text)
        rules = " ".join(text)
        if VENUE_DEPENDENT.search(rules):
            return None
        return normalize_settlement_terms(" ".join(rules.split()))
    except (PdfReadError, AttributeError, KeyError, TypeError, ValueError, OSError):
        return None


def load_rulebook(url):
    if not isinstance(url, str) or not OFFICIAL_RULEBOOK.fullmatch(url):
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
    return Rulebook(sha256(body).hexdigest(), text_policy(body))


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
