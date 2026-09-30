"""Pseudonymization and free-text scrubbing.

- Emails become a salted, non-reversible `user_key` (u_ + 16 hex chars).
- Free text loses emails, phone numbers, long digit runs (cards, accounts),
  the record's own person names, any full name seen anywhere in the exports,
  and names after greetings / before sign-offs.

Scrubbing is good, not perfect: keep the repository restricted to company members.
"""
from __future__ import annotations

import hashlib
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)")
LONGNUM_RE = re.compile(r"(?<![\d:])\d(?:[ \-]?\d){11,18}(?![\d:])")
GREETING_RE = re.compile(r"\b(Hi|Hello|Hey|Dear|Hiya)(,?[ \t]+)([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)?)\b")
SIGNOFF_RE = re.compile(
    r"\b(Thanks|Thank you|Thank You|Best|Regards|Best regards|Kind regards|Warm regards|Sincerely|Cheers|Warmly|Respectfully|Thanks again|Many thanks)"
    r"([,!.]?[ \t]*\r?\n+[ \t]*(?:-|—)?[ \t]*)([A-Z][a-z]+(?:[ \t]+[A-Z][a-zA-Z'\-]+)?)"
)
CAP_BIGRAM_RE = re.compile(r"\b([A-Z][a-zA-Z'\-]+)[ \t]+([A-Z][a-zA-Z'\-]+)\b")

# Words that look like names after a greeting but are not.
_NOT_NAMES = {"There", "Team", "Support", "Supersummary", "SuperSummary", "Sir", "Madam", "All", "Everyone", "Again", "Customer", "Service"}
MASK = "[name]"

# Capitalized words that are never treated as a first name by the aggressive rule.
_STOP_FIRST = {"The", "This", "That", "These", "Those", "Thank", "Thanks", "Hello", "Dear", "Best", "Kind", "Warm",
               "Your", "Our", "My", "New", "Customer", "Support", "Team", "Super", "Study", "Book", "Books", "Case",
               "Money", "Back", "Guarantee", "Order", "Transaction", "Billing", "Please", "Sent", "From", "Subject",
               "Date", "Reply", "Account", "Payment", "Refund", "Cancel", "Monday", "Tuesday", "Wednesday", "Thursday",
               "Friday", "Saturday", "Sunday", "January", "February", "March", "April", "June", "July", "August",
               "September", "October", "November", "December", "Google", "Apple", "Amazon", "Chrome", "United", "States"}
_TOK = r"[A-Za-z][A-Za-z'\-]+"
_NAME3 = rf"({_TOK}(?:[ \t]+{_TOK}){{0,2}})"
POSSESSIVE_AGREEMENT_RE = re.compile(rf"(?<=change to ){_NAME3}(?='s[ \t]+billing agreement)", re.I)
BEFORE_EMAIL_RE = re.compile(r"\b([A-Z][a-zA-Z'\-]+(?:[ \t]+[A-Z][a-zA-Z'\-]+){0,2})(?=,?[ \t]*[<(]\[email\][>)])")
PAYPAL_NAME_RES = [
    re.compile(rf"(?<=The billing agreement for ){_NAME3}(?=[ \t]+was\b)", re.I),
    re.compile(rf"(?:(?<=agreement\. )|(?<=agreement )|^){_NAME3}(?=[ \t]+canceled this billing agreement)", re.I | re.M),
    re.compile(rf"(?<=canceled )({_TOK}(?:[ \t]+{_TOK})?)(?=[ \t]+\(\[email\]\))", re.I),
    re.compile(r"\b([A-Z][a-zA-Z'\-]+(?:[ \t]+[A-Z][a-zA-Z'\-]+){0,2})(?=, (?:a decision on your case|here are the details))"),
    re.compile(rf"(?<=notified you that ){_NAME3}(?=[ \t]+(?:filed|opened|has|asked))", re.I),
    re.compile(rf"(?<=Buyer's name[ \t]){_NAME3}(?=[ \t]+Buyer)", re.I),
    re.compile(rf"(?<=Buyer: ){_NAME3}", re.I),
    re.compile(rf"(?<=Buyer name: ){_NAME3}", re.I),
]
SAME_LINE_SIGNOFF_RE = re.compile(
    r"\b(Thanks|Thank you|Regards|Best regards|Kind regards|Sincerely|Cheers|Best)([,!.]?[ \t]+)([A-Z][a-z]+(?:[ \t]+[A-Z][a-zA-Z'\-]+)?)[ \t.]*$", re.M)
SIGNATURE_LINE_RE = re.compile(r"^[ \t]*(?:-|—)?[ \t]*[A-Z][a-z]+(?:[ \t]+[A-Z]\.?)?(?:[ \t]+[A-Z][a-zA-Z'\-]+)?[ \t]*$")


class Anonymizer:
    def __init__(self, salt: str):
        if not salt or len(salt) < 16:
            raise ValueError("Salt missing or too short; run `python pipeline/ingest.py --init-salt` once.")
        self.salt = salt
        self.full_names: set[str] = set()
        self.first_names: set[str] = set()

    # ---- keys -----------------------------------------------------------
    @staticmethod
    def norm_email(email: str) -> str | None:
        e = (email or "").strip().lower()
        m = EMAIL_RE.fullmatch(e)
        return e if m else None

    def user_key(self, email: str) -> str | None:
        e = self.norm_email(email)
        if not e:
            return None
        return "u_" + hashlib.sha256((self.salt + e).encode()).hexdigest()[:16]

    def hash_id(self, value: str, prefix: str = "h_") -> str | None:
        v = (value or "").strip()
        if not v:
            return None
        return prefix + hashlib.sha256((self.salt + "|id|" + v).encode()).hexdigest()[:16]

    # ---- names ----------------------------------------------------------
    def add_name(self, *parts: str) -> None:
        """Register a person's name seen in a structured field."""
        tokens = [t for p in parts for t in re.split(r"\s+", (p or "").strip()) if t]
        if tokens and len(tokens[0]) >= 3 and tokens[0].isalpha():
            self.first_names.add(tokens[0].capitalize())
        if len(tokens) >= 2:
            self.full_names.add(" ".join(tokens[:2]).lower())
            self.full_names.add(" ".join(tokens).lower())

    # ---- text -----------------------------------------------------------
    def scrub(self, text: str, own_names: tuple[str, ...] = (), aggressive: bool = False) -> str:
        """aggressive=True is for email-like text (support tickets, interviews): it also masks
        capitalized word pairs that start with any first name seen in the exports, names in
        payment-processor templates, same-line sign-offs and a trailing signature line."""
        if not text:
            return text
        t = EMAIL_RE.sub("[email]", text)
        t = PHONE_RE.sub("[phone]", t)
        t = LONGNUM_RE.sub("[number]", t)

        # The record's own names (first, last, full), whole words only.
        for n in sorted({x.strip() for x in own_names if x and len(x.strip()) >= 3}, key=len, reverse=True):
            t = re.sub(r"\b" + re.escape(n) + r"\b", MASK, t, flags=re.I)

        # Full names seen anywhere in the exports.
        if self.full_names:
            def _bigram(m: re.Match) -> str:
                return MASK if f"{m.group(1)} {m.group(2)}".lower() in self.full_names else m.group(0)
            t = CAP_BIGRAM_RE.sub(_bigram, t)

        def _greet(m: re.Match) -> str:
            first = m.group(3).split()[0]
            return m.group(0) if first in _NOT_NAMES else f"{m.group(1)}{m.group(2)}{MASK}"
        t = GREETING_RE.sub(_greet, t)

        def _sign(m: re.Match) -> str:
            first = m.group(3).split()[0]
            return m.group(0) if first in _NOT_NAMES else f"{m.group(1)}{m.group(2)}{MASK}"
        t = SIGNOFF_RE.sub(_sign, t)
        if aggressive:
            t = self._aggressive(t)
        return t

    def _aggressive(self, t: str) -> str:
        found: set[str] = set()
        def _tpl(m: re.Match) -> str:
            if m.group(1).split()[0].capitalize() in _STOP_FIRST:
                return m.group(0)
            found.add(m.group(1))
            return MASK
        for rx in [POSSESSIVE_AGREEMENT_RE, BEFORE_EMAIL_RE] + PAYPAL_NAME_RES:
            t = rx.sub(_tpl, t)
        # a name caught by a template is masked everywhere else in the same text too
        for n in sorted(found, key=len, reverse=True):
            if len(n) >= 4:
                t = re.sub(r"\b" + re.escape(n) + r"\b", MASK, t, flags=re.I)
        if self.first_names:
            def _fn(m: re.Match) -> str:
                a = m.group(1)
                return MASK if a in self.first_names and a not in _STOP_FIRST else m.group(0)
            t = CAP_BIGRAM_RE.sub(_fn, t)

        def _same(m: re.Match) -> str:
            first = m.group(3).split()[0]
            return m.group(0) if first in _NOT_NAMES or first in _STOP_FIRST else f"{m.group(1)}{m.group(2)}{MASK}"
        t = SAME_LINE_SIGNOFF_RE.sub(_same, t)
        lines = t.rstrip().split("\n")
        if sum(1 for ln in lines if ln.strip()) < 2:  # one-liners (subjects) have no signature
            return t
        # trailing signature: last non-empty line that is just a short name
        for i in range(len(lines) - 1, max(-1, len(lines) - 3), -1):
            line = lines[i].strip()
            if not line:
                continue
            if len(line) <= 40 and SIGNATURE_LINE_RE.match(line) and line.split()[0].lstrip("-— ") not in _STOP_FIRST | _NOT_NAMES:
                lines[i] = MASK
            break
        return "\n".join(lines)
