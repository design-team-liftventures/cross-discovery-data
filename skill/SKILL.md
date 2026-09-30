---
name: cross-discovery-data
description: Query SuperSummary's Cross Discovery base of user evidence — Chargebee cancellations, Sprig NPS/PMF/surveys, Freshdesk tickets, Money-Back Guarantee refunds, Lyssna tests, interviews and research reports — and join it with Amplitude. Use whenever someone asks what users say, why they cancel or ask for refunds, NPS/PMF results, support themes, conversion barriers, what research already exists on a topic, or wants user quotes and counts, in any language ("o que os usuários dizem", "por que cancelam").
---

# Cross Discovery Data

A monthly-built, anonymized base of user evidence. You answer questions with counts, sources, period and representative quotes — never with guesses.

## 1. Get the data

Try in order, stop at the first that works:

1. **Connected folder** — look for `cross-discovery-data/data/evidence.parquet` in the user's connected folders (on their computer: `ls $HOME/mnt/*/cross-discovery-data/data` via the device shell). Work there.
2. **GitHub** — `git clone --depth 1 https://github.com/design-team-liftventures/cross-discovery-data` (private; needs the user's credentials or a token available in the session).
3. Otherwise tell the user you can't reach the base and ask them to connect the folder that holds `cross-discovery-data`.

Then:

```python
import duckdb, json            # pip install duckdb pyarrow  (if missing)
con = duckdb.connect()
con.execute(open("sql/views.sql").read())   # run from the repo root
m = json.load(open("manifest.json"))
```

Read `manifest.json` first: `months` (coverage), `run_at` (freshness), `alerts`, `amplitude_link`. Mention the period covered in every answer.

## 2. What is in it

Start with **`evidence`** — one row per piece of feedback from any source.

Key columns: `source` (chargebee · sprig · freshdesk · mbg · lyssna · interviews), `period` (YYYY-MM), `occurred_at`, `population` (**user** or **panel**), `user_key` (hashed email), `user_id` (= Amplitude user_id), `instrument`, `question`, `text` (scrubbed), `category` (cancel reason / NPS category / MBG reason / sender type), `score` + `score_type` (nps_0_10, return_likelihood_0_10, refund_amount_usd, pmf_1_5 — 5 = very disappointed, choice_value, scale), `area` / `areas` (shared taxonomy), `theme`, `theme_method`, `answer_type` (text · choice · score), `segment` (BCM / Non-BCM), `audience`, `channel` (web/app), `plan`, `initiative`, `source_file`, `row_number`.

Taxonomy areas: billing_charges, pricing_value, cancellation_request, short_term_need, content_coverage, content_quality, navigation_ux, technical_bugs, account_access, book_clubs, book_hub_discovery, ai_features, engagement_features, format_access, praise_value, other.

Source tables with every field: `cancellations`, `sprig_responses` + `sprig_answers`, `tickets`, `refunds`, `lyssna_participants` + `lyssna_answers`, `interviews`, `documents` (full text of reports). Catalog: `studies`. People: `users`, `identity_map`. Audit: `rejects`, `reconciliation`. Full column list: `docs/data-dictionary.md`. Columns not curated are in the `raw` JSON (`json_extract_string(raw, '$.Coupon Codes')`) or `attributes` JSON (Sprig).

## 3. Rules (always)

- State **n, source(s) and period** with every number. Flag **n < 30** as directional.
- **Never mix** `population = 'panel'` (Lyssna) with real users in one figure.
- Keyword areas are approximate. For a precise count on a theme, also search `text` directly (`ILIKE`) and say which method you used. `theme_method = 'source_map'` (exact Chargebee reasons) is the most reliable.
- Quotes: 3–5 short, representative quotes, each with its source and `record_id`. Keep `[name]`, `[email]` masks as they are.
- **Never try to re-identify anyone** or display `user_id` / `user_key` in answers. Use them only to join.
- Distinct people: count `DISTINCT user_key`, not rows (one user can cancel, write tickets and answer surveys).
- Show the SQL when asked, or when a number will drive a decision.
- If a source or month is missing from the manifest, say so instead of extrapolating.

## 4. Going deeper (raw fallback)

When the base is not enough — a column not curated, a full ticket thread, all answers of one Lyssna participant, verifying a surprising number, a table inside a PDF:

1. Use `source_file` + `row_number` to open the same record in `mirror/<source_file>` (anonymized, every column). For documents: `mirror/<source_file>.txt`.
2. Only if the person has access to the raw Drive folder and needs something the mirror masks, read the raw file — and still never quote personal data.
3. Say in the answer that the figure came from the mirror/raw, not from the standard base.
4. Note the field/reason you needed in your answer so Research can promote it into the pipeline.

## 5. Amplitude

`user_id` resolves in Amplitude project **Production (284674)**. Coverage (see `manifest.amplitude_link`): Chargebee ~50% (non-numeric ids are Chargebee customer ids, not in Amplitude), Sprig ~65%, MBG ~40%, Freshdesk ~12%, Lyssna 0%. Three patterns:

1. **Few users in depth** — take `user_id`s from the base, read each profile/timeline with the Amplitude user tool.
2. **Amplitude → base (large groups)** — build or reuse a behavioral cohort in Amplitude, export its members, join on `user_id` in DuckDB to read what they said.
3. **Base → Amplitude (aggregates)** — filter an Amplitude query by a list of `user_id`s (works for a few hundred; for more, use pattern 2).

Report the match rate of the group you joined ("312 of 540 cancelled users have an Amplitude id").

## 6. Recipes

```sql
-- Top cancel reasons by plan interval, one month
SELECT reason, plan_interval, count(*) n, round(avg(return_likelihood),1) avg_return
FROM cancellations WHERE period = '2026-08' GROUP BY ALL ORDER BY n DESC;

-- Everything about an area across sources, real users only
SELECT source, count(*) n, count(DISTINCT user_key) people
FROM evidence WHERE population = 'user' AND list_contains(areas, 'billing_charges')
GROUP BY source ORDER BY n DESC;

-- Open-text search (precise), with quotes
SELECT source, period, left(text, 240) AS excerpt, record_id
FROM evidence WHERE population = 'user' AND answer_type = 'text'
  AND text ILIKE '%audiobook%' ORDER BY occurred_at DESC LIMIT 20;

-- NPS by segment and channel
SELECT a.nps_category, r.segment, r.channel, count(*) n
FROM sprig_answers a JOIN sprig_responses r USING (response_id)
WHERE a.nps_category IS NOT NULL GROUP BY ALL ORDER BY r.segment, n DESC;
-- NPS score = %Promoter − %Detractor per group

-- PMF (Sean Ellis top box): share "very disappointed" per surface and month
SELECT period, instrument, count(*) n,
       round(100.0 * count(*) FILTER (WHERE category = 'very_disappointed') / count(*), 1) pct_very
FROM evidence WHERE score_type = 'pmf_1_5' GROUP BY ALL ORDER BY period, pct_very DESC;

-- Journey: what August cancellers said before cancelling
SELECT e.source, e.area, count(DISTINCT c.user_key) people
FROM cancellations c JOIN evidence e USING (user_key)
WHERE c.period = '2026-08' AND e.source <> 'chargebee' AND e.occurred_at < c.cancel_at
GROUP BY ALL ORDER BY people DESC;

-- Refund requests that also opened a ticket
SELECT count(DISTINCT r.user_key) FROM refunds r JOIN tickets t USING (user_key);

-- What research already exists on a topic
SELECT kind, name, period, n, source_file FROM studies
WHERE name ILIKE '%book club%' OR initiative = 'PIN / Book Clubs' ORDER BY period DESC;
SELECT title, period, left(text, 400) FROM documents WHERE text ILIKE '%book brief%';

-- Lyssna: answers to one question in one test (panel)
SELECT a.answer FROM lyssna_answers a JOIN studies s ON s.study_id = a.study_id
WHERE s.name ILIKE '%Tab vs. ToC%' AND a.field = 'Answer' AND a.question ILIKE '%easy%';

-- Users seen in several sources (for triangulation)
SELECT n_sources, count(*) FROM users GROUP BY 1 ORDER BY 1;
```

## 7. Answer format

1. The answer in one or two sentences, with the key number, n and period.
2. A small table if it helps (counts by source/segment/month).
3. 3–5 quotes with source and id.
4. Caveats in one line (small n, keyword classification, missing months, match rate).
5. Offer the SQL or a CSV export if they want to keep digging.
