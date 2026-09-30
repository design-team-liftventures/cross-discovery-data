#!/usr/bin/env python3
"""Leak check for the published outputs (data/ and mirror/).

Counts — never prints — emails, phone numbers, long digit runs and person full
names (taken from the raw structured name fields) that survived scrubbing.
Run after ingest; a non-zero email count should block publishing.

    python pipeline/check_pii.py
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from anonymize import EMAIL_RE, PHONE_RE, Anonymizer  # noqa: E402
from ingest import ADAPTERS, REPO, Run, discover, load_cfg, resolve, salt_path  # noqa: E402
from classify import Classifier  # noqa: E402

# Addresses that are not personal (company/system senders) are allowed.
ALLOWED_EMAIL = re.compile(r"@(supersummary\.com|liftventures\.com|paypal\.com|braintreepayments\.com)$", re.I)


def main() -> int:
    cfg = load_cfg()
    raw_root = resolve(os.environ.get("CROSS_DISCOVERY_RAW", cfg["raw_root"]))
    anon = Anonymizer(salt_path(cfg).read_text().strip())
    run = Run(cfg, anon, Classifier(REPO / "config" / "taxonomy.yaml"), raw_root, dry=True)
    _, plan, _ = discover(cfg, raw_root)
    for month, by_source, _ in plan:
        for src, files in by_source.items():
            if ADAPTERS[src][0]:
                ADAPTERS[src][0](run, month, files)
    names = {n for n in anon.full_names if len(n) >= 7 and " " in n}
    name_rx = re.compile(r"\b[A-Z][a-zA-Z'\-]+[ \t]+[A-Z][a-zA-Z'\-]+\b")

    counts = Counter()
    def scan(text: str, where: str):
        if not text:
            return
        for e in EMAIL_RE.findall(text):
            if not ALLOWED_EMAIL.search(e):
                counts[(where, "email")] += 1
        counts[(where, "phone")] += len(PHONE_RE.findall(text))
        for m in name_rx.findall(text):
            if m.lower() in names:
                counts[(where, "full_name")] += 1

    for p in sorted((REPO / "data").glob("*.parquet")):
        df = pd.read_parquet(p)
        for col in df.columns:
            if df[col].dtype == object:
                for v in df[col].dropna():
                    if isinstance(v, str):
                        scan(v, f"data/{p.stem}.{col}")
    for p in sorted((REPO / "mirror").rglob("*")):
        if p.is_file():
            scan(p.read_text(encoding="utf-8", errors="replace"), "mirror")

    total_email = sum(n for (w, k), n in counts.items() if k == "email")
    for (where, kind), n in sorted(counts.items()):
        if n:
            print(f"{kind:10s} {n:6d}  {where}")
    print(f"known full names checked: {len(names)}")
    if total_email:
        print("FAIL: personal emails found in outputs", file=sys.stderr)
        return 1
    print("OK: no personal emails in outputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
