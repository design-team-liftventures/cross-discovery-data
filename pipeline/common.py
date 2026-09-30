"""Shared helpers: CSV reading, dates, ids."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(10**9)


def read_csv(path: Path) -> list[list[str]]:
    """Read a CSV exactly as exported. Keeps every line, including blank ones."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        return list(csv.reader(fh))


def write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def is_blank(row: list[str]) -> bool:
    return not any((v or "").strip() for v in row)


def short_hash(*parts: str, n: int = 12) -> str:
    h = hashlib.sha256("\x1f".join(p or "" for p in parts).encode()).hexdigest()
    return h[:n]


_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%B %d, %Y %I:%M %p",
    "%B %d, %Y",
]


def parse_dt(value: str) -> datetime | None:
    """Parse the date formats found in the exports. Returns naive UTC-ish datetime or None."""
    v = (value or "").strip()
    if not v:
        return None
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(v, fmt)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            continue
    return None


def to_float(value: str) -> float | None:
    v = (value or "").strip().replace(",", "")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


INITIATIVE_PATTERNS = [
    (re.compile(r"book[\s_]*hub|\bbhb\b|book brief|books? like", re.I), "Book Hub"),
    (re.compile(r"growth[\s_]*exp", re.I), "Growth Experimentation"),
    (re.compile(r"\bpin\b|book clubs?", re.I), "PIN / Book Clubs"),
    (re.compile(r"\bpmf\b", re.I), "PMF"),
    (re.compile(r"\bnps\b", re.I), "NPS"),
    (re.compile(r"funnel", re.I), "Funnel Revamp"),
    (re.compile(r"jtbd|payoff", re.I), "Growth Experimentation"),
    (re.compile(r"\bcx\b|bug analysis|freshdesk", re.I), "CX"),
]


def initiative_of(*texts: str) -> str | None:
    blob = " ".join(t or "" for t in texts)
    for rx, name in INITIATIVE_PATTERNS:
        if rx.search(blob):
            return name
    return None
