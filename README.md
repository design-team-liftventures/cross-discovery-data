# Cross Discovery Data

One anonymized, queryable base of SuperSummary user evidence: Chargebee cancellations, Sprig surveys, Freshdesk tickets, Money-Back Guarantee requests, Lyssna tests, interviews and research reports — linked to Amplitude through the shared user id.

Teams query it through Claude with the **cross-discovery-data** skill (`skill/SKILL.md`). Research owns the pipeline, the taxonomy and the monthly run.

## Layout

```
cross-discovery-data/          ← this repository (private GitHub)
  config/pipeline.yaml         where raw lives, source folders, Freshdesk sender rules
  config/taxonomy.yaml         shared areas + keywords + exact source mappings (Research)
  pipeline/ingest.py           monthly build
  pipeline/check_pii.py        leak check on the outputs
  data/*.parquet               normalized base (published)
  mirror/YYYY-MM/<source>/     every raw file, same rows and columns, personal data masked
  manifest.json                run report: reconciliation, volumes, alerts, Amplitude link rate
  schema_snapshot.json         columns seen per source (for schema-change alerts)
  sql/views.sql                DuckDB views
  docs/data-dictionary.md      tables and columns
  skill/                       the query skill

<raw root>/                    ← Google Drive "Cross Discovery Data", NOT in Git
  YYYY-MM/Chargebee Form/  Freshdesk Tickets/  MBG Form/  Surveys/{NPS,PMF}/  Lyssna Tests/  Interviews/  *.pdf
_secrets/cross_discovery_salt.txt   ← outside the repo; back it up in the team vault
```

## Monthly run (≈20 min, around the 17th)

1. Save the month's exports in a new `YYYY-MM/` folder under the raw root, using the same subfolder names.
2. From the repo root:
   ```bash
   pip install -r requirements.txt
   python pipeline/ingest.py --dry-run     # parse + reconcile, writes nothing
   python pipeline/ingest.py               # publishes data/, mirror/, manifest.json
   python pipeline/check_pii.py            # must print OK
   ```
3. Read the alerts in `manifest.json` (unreadable files, new/lost columns, volume swings).
4. Commit and push: `git add -A && git commit -m "Ingest YYYY-MM" && git tag YYYY-MM && git push --tags origin main`.

First time only: `python pipeline/ingest.py --init-salt` creates the salt. **Never regenerate it** — every `user_key` would change.

If raw lives somewhere else (e.g. the Drive for desktop path), set `CROSS_DISCOVERY_RAW=/path/to/raw` before running.

## Guarantees

- `raw/` is never modified; every run rebuilds from it.
- Every file must reconcile: rows read = rows loaded + rows rejected. Otherwise the run fails and publishes nothing.
- Nothing is silently dropped: excluded rows are in `data/rejects.parquet` with a reason; source tables keep all original columns (`raw` JSON where not curated).
- Outputs are overwritten in place; files from earlier runs that were not rebuilt are listed as `stale_outputs` in the manifest.

## Privacy

- Emails become `user_key` (salted SHA-256). Names are removed from structured fields.
- Free text is scrubbed of emails, phone numbers, long digit runs, the record's own names, any full name seen in the exports, greeting/sign-off names and payment-processor name templates. Scrubbing is good, not perfect — keep this repository restricted to company members.
- Interview recording and transcript links are removed.
- `user_id` (Amplitude id) is kept to join with Amplitude; answers never display it.

## Amplitude

`user_id` is the Amplitude `user_id` (verified on samples from Chargebee, Sprig, Freshdesk and MBG in project Production 284674). Non-numeric Chargebee ids are Chargebee customer ids and do not exist in Amplitude; they are kept hashed as `billing_customer_ref`. Link rates per source are in `manifest.json → amplitude_link`.

## Changing the taxonomy

Edit `config/taxonomy.yaml` (keywords, areas, exact mappings), bump `version` if an area's meaning changes, rerun ingest. The manifest records the taxonomy hash used.
