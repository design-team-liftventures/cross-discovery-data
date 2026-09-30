-- Cross Discovery Data — DuckDB views over the published Parquet tables.
-- Usage from the repo root:  duckdb -init sql/views.sql
--                    or in Python: duckdb.sql(open('sql/views.sql').read())
CREATE OR REPLACE VIEW evidence            AS SELECT * FROM 'data/evidence.parquet';
CREATE OR REPLACE VIEW cancellations       AS SELECT * FROM 'data/cancellations.parquet';
CREATE OR REPLACE VIEW sprig_responses     AS SELECT * FROM 'data/sprig_responses.parquet';
CREATE OR REPLACE VIEW sprig_answers       AS SELECT * FROM 'data/sprig_answers.parquet';
CREATE OR REPLACE VIEW tickets             AS SELECT * FROM 'data/tickets.parquet';
CREATE OR REPLACE VIEW refunds             AS SELECT * FROM 'data/refunds.parquet';
CREATE OR REPLACE VIEW lyssna_participants AS SELECT * FROM 'data/lyssna_participants.parquet';
CREATE OR REPLACE VIEW lyssna_answers      AS SELECT * FROM 'data/lyssna_answers.parquet';
CREATE OR REPLACE VIEW interviews          AS SELECT * FROM 'data/interviews.parquet';
CREATE OR REPLACE VIEW documents           AS SELECT * FROM 'data/documents.parquet';
CREATE OR REPLACE VIEW studies             AS SELECT * FROM 'data/studies.parquet';
CREATE OR REPLACE VIEW users               AS SELECT * FROM 'data/users.parquet';
CREATE OR REPLACE VIEW identity_map        AS SELECT * FROM 'data/identity_map.parquet';
CREATE OR REPLACE VIEW rejects             AS SELECT * FROM 'data/rejects.parquet';
CREATE OR REPLACE VIEW reconciliation      AS SELECT * FROM 'data/reconciliation.parquet';
