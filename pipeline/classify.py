"""Rule-based classification against config/taxonomy.yaml."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml


class Classifier:
    def __init__(self, path: Path):
        raw = path.read_text(encoding="utf-8")
        self.version_hash = hashlib.sha256(raw.encode()).hexdigest()[:10]
        cfg = yaml.safe_load(raw)
        self.version = cfg.get("version")
        self.areas = []
        for a in cfg["areas"]:
            kws = sorted({k.lower() for k in a.get("keywords", [])}, key=len, reverse=True)
            rx = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in kws) + r")(?![a-z0-9])", re.I)
            self.areas.append((a["id"], a.get("label", a["id"]), rx))
        self.labels = {a[0]: a[1] for a in self.areas}
        self.source_map = cfg.get("source_map", {})

    def _hits(self, text: str) -> dict[str, int]:
        out = {}
        if not text:
            return out
        for aid, _, rx in self.areas:
            n = len(rx.findall(text))
            if n:
                out[aid] = n
        return out

    def _best(self, hits: dict[str, int]) -> str | None:
        if not hits:
            return None
        order = [a[0] for a in self.areas]
        return max(hits, key=lambda k: (hits[k], -order.index(k)))

    def classify(self, text: str = "", source_theme: str = "", mapping: tuple[str, str] | None = None,
                 context: str = ""):
        """Return (area, areas, theme, method).

        mapping: (map_name, key) looked up in source_map, e.g. ("chargebee_reason", reason).
        context: the question asked; used only when the answer itself matches nothing.
        """
        text_hits = self._hits(text)
        theme_hits = self._hits(source_theme)
        all_areas = sorted(set(text_hits) | set(theme_hits))

        if mapping:
            m = self.source_map.get(mapping[0], {}).get((mapping[1] or "").strip())
            if m:
                areas = sorted(set(all_areas) | {m["area"]})
                return m["area"], areas, m.get("theme"), "source_map"
        if theme_hits:
            return self._best(theme_hits), all_areas, source_theme or None, "source_theme"
        if text_hits:
            return self._best(text_hits), all_areas, source_theme or None, "text_rule"
        ctx_hits = self._hits(context)
        if ctx_hits and text:
            return self._best(ctx_hits), sorted(ctx_hits), source_theme or None, "question_rule"
        return "other", [], source_theme or None, "none"
