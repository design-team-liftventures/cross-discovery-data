#!/usr/bin/env python3
"""Cross Discovery ingest — turns monthly raw exports into an anonymized, queryable base.

Usage (from the repo root):
    python pipeline/ingest.py --init-salt      # once, creates the salt file outside the repo
    python pipeline/ingest.py                  # rebuild data/, mirror/, manifest.json
    python pipeline/ingest.py --dry-run        # parse + reconcile, write nothing

The run rebuilds everything from all month folders under raw_root. It refuses to
publish when any file fails reconciliation (rows read != loaded + rejected).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adapters import ADAPTERS, documents  # noqa: E402
from anonymize import Anonymizer  # noqa: E402
from classify import Classifier  # noqa: E402
from common import short_hash, slug, write_csv  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOC_EXT = {".docx", ".pdf", ".md", ".txt"}


class Run:
    def __init__(self, cfg: dict, anon: Anonymizer, clf: Classifier, raw_root: Path, dry: bool):
        self.cfg, self.anon, self.clf, self.raw_root, self.dry = cfg, anon, clf, raw_root, dry
        self.tables: dict[str, list[dict]] = defaultdict(list)
        self.evidence: list[dict] = []
        self.rejects: list[dict] = []
        self.recons: list[dict] = []
        self.identities: list[tuple] = []
        self.studies: list[dict] = []
        self.schemas: dict[str, dict[str, list[str]]] = defaultdict(dict)
        self.alerts: list[str] = []
        self._seen: dict[str, set] = defaultdict(set)
        self.mirror_root = REPO / "mirror"

    # --- bookkeeping --------------------------------------------------------
    def rel(self, f: Path) -> str:
        try:
            return str(f.relative_to(self.raw_root))
        except ValueError:
            return str(f)

    def seen(self, source: str, rid: str) -> bool:
        if rid in self._seen[source]:
            return True
        self._seen[source].add(rid)
        return False

    def add(self, table: str, row: dict) -> None:
        self.tables[table].append(row)

    def add_study(self, row: dict) -> None:
        self.studies.append(row)

    def reject(self, source, month, f, n, rid, reason) -> None:
        self.rejects.append({"source": source, "period": month, "source_file": self.rel(f),
                             "row_number": n, "record_id": rid, "excluded_reason": reason})

    def recon(self, source, month, f, read, loaded, rejected) -> None:
        self.recons.append({"source": source, "period": month, "file": self.rel(f), "rows_read": read,
                            "rows_loaded": loaded, "rows_rejected": rejected,
                            "ok": read == loaded + rejected})

    def identity(self, user_key, user_id, source) -> None:
        if user_key and user_id and str(user_id).isdigit():
            self.identities.append((user_key, str(user_id), source))

    def schema(self, source, f, header) -> None:
        self.schemas[source][self.rel(f)] = list(header)

    def alert(self, msg: str) -> None:
        self.alerts.append(msg)

    def add_evidence(self, *, source, record_id, period, occurred_at, user_key, user_id, instrument, question,
                     text, category=None, score=None, score_type=None, source_theme=None, mapping=None,
                     segment=None, audience=None, channel=None, plan=None, initiative=None,
                     population="user", sub_id="", source_file=None, row_number=None, choice=False) -> None:
        blob = " ".join(x for x in (text or "", category or "") if x)
        area, areas, theme, method = self.clf.classify(blob, source_theme or "", mapping, question or "")
        if choice and not theme and text:
            theme = text[:120]
        self.evidence.append({
            "evidence_id": "ev_" + short_hash(source, str(record_id), str(sub_id)),
            "source": source, "record_id": str(record_id), "sub_id": str(sub_id) or None,
            "period": period, "occurred_at": occurred_at, "population": population,
            "user_key": user_key, "user_id": str(user_id) if user_id else None,
            "instrument": instrument, "question": question, "text": text,
            "text_chars": len(text or ""), "category": category, "score": score, "score_type": score_type,
            "source_theme": source_theme or None, "area": area, "areas": areas, "theme": theme,
            "theme_method": method, "answer_type": "choice" if choice else ("score" if score_type and not (text or "").strip(" 0123456789.") else "text"),
            "segment": segment, "audience": audience, "channel": channel,
            "plan": plan, "initiative": initiative, "source_file": source_file, "row_number": row_number,
        })

    # --- mirror -----------------------------------------------------------------
    def write_mirror(self, month, f: Path, rows) -> None:
        if self.dry:
            return
        write_csv(self.mirror_root / self.rel(f), rows)

    def write_mirror_text(self, month, f: Path, text: str) -> None:
        if self.dry:
            return
        out = self.mirror_root / (self.rel(f) + ".txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------------------
def load_cfg() -> dict:
    return yaml.safe_load((REPO / "config" / "pipeline.yaml").read_text(encoding="utf-8"))


def resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (REPO / path).resolve()


def salt_path(cfg) -> Path:
    return resolve(os.environ.get("CROSS_DISCOVERY_SALT_FILE", cfg["salt_file"]))


def discover(cfg, raw_root: Path):
    """Yield (month, source, [files]) and documents per month; report unhandled files."""
    mrx = re.compile(cfg["month_pattern"])
    folder_to_source = {name.lower(): src for src, names in cfg["sources"].items() for name in names}
    plan, unhandled = [], []
    months = sorted(d.name for d in raw_root.iterdir() if d.is_dir() and mrx.match(d.name))
    for month in months:
        by_source = defaultdict(list)
        docs = []
        for f in sorted((raw_root / month).rglob("*")):
            if not f.is_file() or any(part.startswith(".") for part in f.relative_to(raw_root).parts):
                continue
            ext = f.suffix.lower()
            top = f.relative_to(raw_root / month).parts
            src = folder_to_source.get(top[0].lower()) if len(top) > 1 else None
            if ext in DOC_EXT:
                docs.append(f)
            elif ext == ".csv" and src:
                by_source[src].append(f)
            else:
                unhandled.append(str(f.relative_to(raw_root)))
        plan.append((month, dict(by_source), docs))
    return months, plan, unhandled


def to_frame(rows: list[dict]) -> pd.DataFrame:
    """Stable column types: *_at / *_date / first_seen / last_seen as timestamps,
    all-empty columns as strings (so a column never flips type between runs)."""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in df.columns:
        if col.endswith(("_at", "_date")) or col in ("first_seen", "last_seen"):
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif df[col].isna().all():
            df[col] = df[col].astype("string")
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--init-salt", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_cfg()
    started = datetime.now().timestamp() - 1

    sp = salt_path(cfg)
    if args.init_salt:
        if sp.exists():
            print(f"Salt already exists at {sp}; not overwriting (that would change every user_key).")
            return 0
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(secrets.token_hex(32), encoding="utf-8")
        print(f"Created salt at {sp}. Keep it out of Git and back it up in the team vault.")
        return 0
    if not sp.exists():
        print(f"No salt at {sp}. Run: python pipeline/ingest.py --init-salt", file=sys.stderr)
        return 1

    raw_root = resolve(os.environ.get("CROSS_DISCOVERY_RAW", cfg["raw_root"]))
    anon = Anonymizer(sp.read_text(encoding="utf-8").strip())
    clf = Classifier(REPO / "config" / "taxonomy.yaml")
    run = Run(cfg, anon, clf, raw_root, args.dry_run)

    months, plan, unhandled = discover(cfg, raw_root)
    if not months:
        print(f"No month folders (YYYY-MM) under {raw_root}", file=sys.stderr)
        return 1
    for u in unhandled:
        run.alert(f"unhandled file (not ingested): {u}")

    before = set()
    if not args.dry_run:
        for d in (run.mirror_root, REPO / "data"):
            if d.exists():
                before |= {p for p in d.rglob("*") if p.is_file()}

    # pass 1: collect person names so scrubbing can mask them anywhere
    for month, by_source, _ in plan:
        for src, files in by_source.items():
            pre = ADAPTERS[src][0]
            if pre:
                pre(run, month, files)
    # pass 2: parse
    for month, by_source, docs in plan:
        for src, files in sorted(by_source.items()):
            ADAPTERS[src][1](run, month, files)
        documents(run, month, docs)

    # ---- identity map + user ids -------------------------------------------------
    idmap = defaultdict(Counter)
    for uk, uid, src in run.identities:
        idmap[uk][uid] += 1
    identity_rows = []
    for uk, c in idmap.items():
        for uid, n in c.items():
            identity_rows.append({"user_key": uk, "user_id": uid, "observations": n,
                                  "is_primary": uid == c.most_common(1)[0][0], "ambiguous": len(c) > 1})
    primary = {uk: c.most_common(1)[0][0] for uk, c in idmap.items()}
    for table in ("tickets", "refunds", "interviews"):
        for r in run.tables.get(table, []):
            r["user_id"] = primary.get(r.get("user_key"))
    for e in run.evidence:
        if not e["user_id"] and e["user_key"]:
            e["user_id"] = primary.get(e["user_key"])

    # ---- sprig studies ------------------------------------------------------------
    sp_counts = Counter((r["survey_id"], r["survey_name"], r["survey_family"], r["initiative"], r["period"], r["source_file"])
                        for r in run.tables.get("sprig_responses", []))
    for (sid, name, fam, ini, period, sf), n in sp_counts.items():
        run.add_study({"study_id": f"sprig_{sid}_{period}", "kind": "sprig_" + slug(fam),
                       "name": name, "initiative": ini, "period": period, "n": n, "source_file": sf})

    # ---- users ----------------------------------------------------------------------
    users = {}
    for e in run.evidence:
        uk = e["user_key"]
        if not uk:
            continue
        u = users.setdefault(uk, {"user_key": uk, "user_id": primary.get(uk), "sources": set(), "evidence_items": 0,
                                  "first_seen": None, "last_seen": None, "audience": None, "plan": None})
        u["sources"].add(e["source"]); u["evidence_items"] += 1
        t = e["occurred_at"]
        if t:
            u["first_seen"] = min(filter(None, [u["first_seen"], t]))
            u["last_seen"] = max(filter(None, [u["last_seen"], t]))
        u["audience"] = u["audience"] or e["audience"]
        u["plan"] = e["plan"] or u["plan"]
    user_rows = [{**u, "sources": sorted(u["sources"]), "n_sources": len(u["sources"])} for u in users.values()]

    # ---- checks -------------------------------------------------------------------
    bad = [r for r in run.recons if not r["ok"]]
    prev_manifest = {}
    mpath = REPO / "manifest.json"
    if mpath.exists():
        try:
            prev_manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    snap_path = REPO / "schema_snapshot.json"
    prev_snap = json.loads(snap_path.read_text(encoding="utf-8")) if snap_path.exists() else {}
    for src, files in run.schemas.items():
        cols_now = set().union(*[set(c) for c in files.values()]) if files else set()
        cols_prev = set(prev_snap.get(src, []))
        if cols_prev:
            new, gone = sorted(cols_now - cols_prev), sorted(cols_prev - cols_now)
            if src == "sprig":  # question/attribute columns vary by survey by design
                new = [c for c in new if not re.match(r"^(Q\d+_|Attribute_)", c)]
                gone = [c for c in gone if not re.match(r"^(Q\d+_|Attribute_)", c)]
            if src == "lyssna":
                new, gone = [], []
            if new:
                run.alert(f"schema: {src} has new columns {new[:10]}")
            if gone:
                run.alert(f"schema: {src} lost columns {gone[:10]}")
    prev_vol = {(r["source"], r["period"]): r["rows_read"] for r in prev_manifest.get("by_source_month", [])}
    by_sm = defaultdict(lambda: {"rows_read": 0, "rows_loaded": 0, "rows_rejected": 0, "files": 0})
    for r in run.recons:
        k = (r["source"], r["period"])
        for f in ("rows_read", "rows_loaded", "rows_rejected"):
            by_sm[k][f] += r[f]
        by_sm[k]["files"] += 1
    ratio = cfg.get("volume_alert_ratio", 0.5)
    for (src, period), v in by_sm.items():
        pv = prev_vol.get((src, period))
        if pv and abs(v["rows_read"] - pv) / pv > ratio:
            run.alert(f"volume: {src} {period} rows {pv} -> {v['rows_read']}")

    ev_users = [e for e in run.evidence if e["population"] == "user"]
    def rate(items, key):
        return round(sum(1 for x in items if x.get(key)) / len(items), 4) if items else None
    match_by_source = {}
    for src in sorted({e["source"] for e in ev_users}):
        items = [e for e in ev_users if e["source"] == src]
        match_by_source[src] = {"evidence_items": len(items), "with_user_key": rate(items, "user_key"),
                                "with_user_id": rate(items, "user_id")}

    rejects_by_reason = Counter((r["source"], r["excluded_reason"]) for r in run.rejects)
    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "months": months,
        "taxonomy_version": clf.version, "taxonomy_hash": clf.version_hash,
        "reconciliation_ok": not bad,
        "files": len(run.recons),
        "by_source_month": [{"source": s, "period": p, **v} for (s, p), v in sorted(by_sm.items())],
        "rejects_by_reason": [{"source": s, "reason": r, "rows": n} for (s, r), n in sorted(rejects_by_reason.items())],
        "tables": {t: len(v) for t, v in sorted(run.tables.items())} | {
            "evidence": len(run.evidence), "identity_map": len(identity_rows), "users": len(user_rows),
            "studies": len(run.studies), "rejects": len(run.rejects)},
        "amplitude_link": match_by_source,
        "areas": Counter(e["area"] for e in ev_users).most_common(),
        "theme_methods": Counter(e["theme_method"] for e in run.evidence).most_common(),
        "alerts": run.alerts,
        "reconciliation_failures": bad,
    }

    print(json.dumps({k: manifest[k] for k in ("months", "reconciliation_ok", "files", "tables", "amplitude_link")}, indent=1))
    print(f"alerts: {len(run.alerts)}")
    for a in run.alerts[:40]:
        print("  -", a)
    if bad:
        print("RECONCILIATION FAILED — nothing published:", file=sys.stderr)
        for r in bad:
            print("  ", r, file=sys.stderr)
        return 2
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    out = REPO / "data"
    out.mkdir(exist_ok=True)
    frames = dict(run.tables)
    frames.update({"evidence": run.evidence, "identity_map": identity_rows, "users": user_rows,
                   "studies": run.studies, "rejects": run.rejects, "reconciliation": run.recons})
    for name, rows in frames.items():
        df = to_frame(rows)
        df.to_parquet(out / f"{name}.parquet", index=False)
    # Outputs are overwritten in place (no deletes). Anything left from an earlier
    # run that this run did not produce is reported so a person can remove it.
    written = {p for d in (run.mirror_root, out) if d.exists() for p in d.rglob("*") if p.is_file()
               and p.stat().st_mtime >= started}
    stale = sorted(str(p.relative_to(REPO)) for p in before - written)
    for s_ in stale:
        run.alert(f"stale output from an earlier run (safe to delete): {s_}")
    manifest["alerts"] = run.alerts
    manifest["stale_outputs"] = stale
    mpath.write_text(json.dumps(manifest, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    snap = {src: sorted(set().union(*[set(c) for c in files.values()])) for src, files in run.schemas.items()}
    snap_path.write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"published {len(frames)} tables to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
