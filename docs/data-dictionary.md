# Data dictionary

All tables live in `data/*.parquet` and are rebuilt from every month folder on each run. Load them with `sql/views.sql`.

Every row that came from a raw file carries `source_file` (path under the raw root, e.g. `2026-08/Chargebee Form/…csv`) and `row_number` (1-based data record after the header rows). Together they point to the exact record in `mirror/` (anonymized copy) or the raw export (Drive).

## Keys

| Key | What it is | Where |
| --- | --- | --- |
| `user_key` | Salted hash of the email (`u_` + 16 hex). Same person → same key across sources. Not reversible without the salt. | every user-level table |
| `user_id` | SuperSummary internal user id = Amplitude `user_id`. Only numeric ids are kept. Filled directly (Chargebee, Sprig) or through `identity_map` (Freshdesk, MBG). | evidence, cancellations, sprig_responses, tickets, refunds, users |
| `period` | Month folder the export came from (`YYYY-MM`). | all |

## evidence — one row per piece of feedback, any source

The table to start with.

| Column | Meaning |
| --- | --- |
| `evidence_id` | Stable id (`ev_…`) |
| `source` | `chargebee` · `sprig` · `freshdesk` · `mbg` · `lyssna` · `interviews` |
| `record_id`, `sub_id` | Id of the source record (session, response, ticket…) and question number / column where relevant |
| `occurred_at` | When the user said it (timestamp) |
| `population` | `user` (real users) or `panel` (Lyssna participants). **Never mix them in one number.** |
| `user_key`, `user_id` | See Keys |
| `instrument` | Survey / test / form name |
| `question` | Question asked, when there is one |
| `text` | What the person said, scrubbed of personal data. For Chargebee: free text + competitor; for MBG: all answers joined with labels; for Freshdesk: subject + body |
| `category` | Source category: Chargebee cancel reason, NPS category, MBG "why cancel", Freshdesk sender type, PMF answer |
| `score`, `score_type` | `nps_0_10`, `return_likelihood_0_10`, `refund_amount_usd`, `pmf_1_5` (Sean Ellis question, 5 = very disappointed; `category` = very_disappointed / somewhat_disappointed / not_disappointed), `choice_value`, `scale` |
| `source_theme` | The source's own theme labels (Sprig AI themes) |
| `area` / `areas` | Primary shared-taxonomy area / all matching areas (see `config/taxonomy.yaml`) |
| `theme` | Finer theme: Chargebee reason slug, Sprig theme, or the chosen option for multiple choice |
| `theme_method` | How `area` was set: `source_map` (exact category) · `source_theme` · `text_rule` (keywords in the text) · `question_rule` (keywords in the question; answer itself matched nothing) · `none` |
| `answer_type` | `text` (open text) · `choice` (selected option) · `score` (number only) |
| `segment` | `BCM` / `Non-BCM` (Sprig file name or audience; Chargebee audience) |
| `audience` | `book_club_member`, `student`, `teacher`, `parent_of_student`, `librarian`, `avid_reader`, `other` |
| `channel` | `web` / `app` (Sprig); device type (Lyssna) |
| `plan` | Plan id |
| `initiative` | Book Hub · Growth Experimentation · PIN / Book Clubs · PMF · NPS · CX · Funnel Revamp |

## Source tables

**cancellations** (Chargebee / Brightback cancel flow, one row per cancel session): `session_id`, `cancel_at`, `reason`, `reason_category`, `reason_other`, `details`, `competitor`, `return_likelihood`, `accepted_offers`, `plan_id`, `plan_interval`, `billing_interval`, `mrr_usd`, `billing_price_usd`, `age_days`, `grade_level`, `page_attributed`, `coupon_ids`, `winbacks`, `validation_status`, `subscription_status`, `first_purchase_at`, `last_active_at`, `billing_customer_ref` (hashed Chargebee customer id when there is no numeric user id), `raw` (JSON with every other original column, names/emails removed — use `json_extract_string(raw, '$.Column Name')`).

**sprig_responses** (one row per survey response): `response_id`, `survey_id`, `survey_name`, `survey_family` (NPS · PMF · Growth Experimentation · PIN / Book Clubs · Book Hub), `initiative`, `created_at`, `completed_at`, `visitor_id`, `segment`, `audience`, `subscriber_status`, `plan`, `tenure`, `grade_level`, `channel`, `os`, `browser`, `device_type`, `href`, `triggering_event`, `attributes` (JSON of all Sprig attributes except email and names).

**sprig_answers** (one row per response × question): `response_id`, `question_no`, `question`, `skipped` (answer was "[skipped by user]"), `response`, `response_other`, `value`, `nps_category`, `primary_theme`, `themes` (list), `choices` (list).

**tickets** (Freshdesk, customer-facing mail only): `ticket_id`, `created_at`, `sender_type` (`customer` · `payment_dispute` · `billing_advocate` · `marketplace`), `sender_domain`, `subject`, `body`, `body_chars`. Internal and automated mail is in `rejects`.

**refunds** (Money-Back Guarantee form): `request_id`, `requested_at`, `status`, `refund_outcome`, `amount_usd`, `why_cancel`, `would_have_stayed_if`, `not_pleased_because`, `title_and_author`, `content_opinion`, `expected_to_find`, `technical_issue`, `dont_need_because`, `dropdown`, `notes_sent_email`.

**lyssna_participants** (one row per panel participant per test): `study_id`, `response_id`, `responded_at`, `duration_ms`, `country`, `age`, `gender`, `device_type`, `device_platform`, `demographics` (JSON).

**lyssna_answers** (long format, one row per participant × column): `study_id`, `response_id`, `column_index`, `column` (original header), `section`, `question`, `field` (Answer, Duration (ms), task fields…), `answer`.

**interviews** (interview tracker): `interview_id`, `user_key`, `segment`, `interview_date`, `lead_interviewer`, `outcome`, `plan`, `snapshot`, `transcript`, `notes`, `raw`. Recording and transcript links are removed.

**documents** (reports and syntheses: docx, pdf, md): `doc_id`, `folder`, `file_name`, `title`, `doc_type`, `initiative`, `chars`, `text` (full extracted text, scrubbed).

## Catalog and support tables

- **studies** — one row per Sprig survey (per month), Lyssna test, report or interview tracker: `study_id`, `kind`, `name`, `initiative`, `period`, `n`, `source_file`. Use it to answer "what has already been researched about X".
- **users** — one row per `user_key`: `user_id`, `sources` (list), `n_sources`, `evidence_items`, `first_seen`, `last_seen`, `audience`, `plan`.
- **identity_map** — `user_key` → `user_id`, `observations`, `is_primary`, `ambiguous` (one email seen with more than one user id).
- **rejects** — rows not loaded, with `excluded_reason` (`duplicate`, `empty_row`, `staff_response`, `sender_internal`, `sender_automated`, `unreadable`).
- **reconciliation** — per file: `rows_read`, `rows_loaded`, `rows_rejected`, `ok`.

## manifest.json

Written each run: months covered, reconciliation status, row counts per source and month, rejects by reason, table sizes, Amplitude link rate per source (`with_user_id`), area distribution, alerts (unreadable files, schema changes, volume swings, stale outputs). Read it first to know how fresh the base is.
