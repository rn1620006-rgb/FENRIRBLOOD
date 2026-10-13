CREATE TABLE IF NOT EXISTS ranking_finalizations (
 week_start TEXT PRIMARY KEY,
 proposal_id TEXT NOT NULL REFERENCES proposals(id),
 finalized_at TEXT NOT NULL
);
