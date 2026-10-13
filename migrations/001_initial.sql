CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 username TEXT NOT NULL, ff_uid TEXT NOT NULL DEFAULT '',
 role TEXT NOT NULL DEFAULT 'PENDENTE' CHECK(role IN ('FUNDADOR','ADMIN_MEMBROS','ADMIN_OPERACIONAL','CAPITAO','MEMBRO','PENDENTE')),
 status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','ACTIVE','SUSPENDED','REJECTED')),
 avatar_url TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, approved_at TEXT,
 last_seen TEXT, bio TEXT NOT NULL DEFAULT '', privacy_public INTEGER NOT NULL DEFAULT 1,
 CHECK(length(username) BETWEEN 2 AND 40)
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf_token TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS reset_tokens (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at TEXT NOT NULL, consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS login_attempts (key TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(key,created_at);
CREATE TABLE IF NOT EXISTS teams (
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, captain_id TEXT REFERENCES users(id),
 created_at TEXT NOT NULL, adaptation_end_at TEXT, extension_used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS team_members (
 team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
 joined_at TEXT NOT NULL, PRIMARY KEY(team_id,user_id)
);
CREATE TABLE IF NOT EXISTS wars (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, opponent TEXT NOT NULL, starts_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PLANNED' CHECK(status IN ('PLANNED','LIVE','DONE','CANCELLED')),
 result TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
 created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS war_lineups (
 war_id TEXT NOT NULL REFERENCES wars(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 confirmed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(war_id,user_id)
);
CREATE TABLE IF NOT EXISTS ranking_entries (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), week_start TEXT NOT NULL,
 points INTEGER NOT NULL CHECK(points BETWEEN -100000 AND 100000),
 reason TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ranking_week ON ranking_entries(week_start);
CREATE TABLE IF NOT EXISTS posts (
 id TEXT PRIMARY KEY, author_id TEXT NOT NULL REFERENCES users(id), body TEXT NOT NULL,
 pinned INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT,
 hidden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS comments (
 id TEXT PRIMARY KEY, post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 author_id TEXT NOT NULL REFERENCES users(id), body TEXT NOT NULL,
 created_at TEXT NOT NULL, parent_id TEXT REFERENCES comments(id)
);
CREATE TABLE IF NOT EXISTS reactions (
 post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 PRIMARY KEY(post_id,user_id)
);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, author_id TEXT NOT NULL REFERENCES users(id),
 channel TEXT NOT NULL CHECK(channel IN ('general','admin','team','war','private')),
 target_id TEXT NOT NULL DEFAULT '', body TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel,target_id,created_at);
CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',
 starts_at TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 kind TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id,read_at);
CREATE TABLE IF NOT EXISTS proposals (
 id TEXT PRIMARY KEY, action TEXT NOT NULL, payload TEXT NOT NULL,
 proposed_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','EXECUTED','REJECTED')),
 executed_at TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
 proposal_id TEXT NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
 founder_id TEXT NOT NULL REFERENCES users(id), approved_at TEXT NOT NULL,
 PRIMARY KEY(proposal_id,founder_id)
);
CREATE TABLE IF NOT EXISTS discipline (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), actor_id TEXT NOT NULL REFERENCES users(id),
 action TEXT NOT NULL CHECK(action IN ('WARNING','SUSPENSION','REINSTATEMENT','APPEAL')),
 reason TEXT NOT NULL, ends_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
 id TEXT PRIMARY KEY, actor_id TEXT, action TEXT NOT NULL,
 entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
