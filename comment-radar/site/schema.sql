CREATE TABLE IF NOT EXISTS comment_run(
  day TEXT PRIMARY KEY, checked INTEGER, posted_profiles INTEGER, spent_usd REAL, note TEXT);
CREATE TABLE IF NOT EXISTS comment_draft(
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, bucket TEXT, author TEXT, headline TEXT, profile_url TEXT,
  post_url TEXT NOT NULL UNIQUE, age_min INTEGER, why TEXT, about TEXT, ctype TEXT, comment TEXT,
  post_text TEXT, reactions INTEGER, comments_n INTEGER,
  state TEXT NOT NULL DEFAULT 'new', final_comment TEXT, skip_reason TEXT, state_by TEXT, state_at TEXT);
CREATE INDEX IF NOT EXISTS comment_draft_day ON comment_draft(day);
CREATE TABLE IF NOT EXISTS engager(
  slug TEXT PRIMARY KEY, name TEXT, headline TEXT, company TEXT, profile_url TEXT, grp TEXT, status TEXT,
  reactions INTEGER, comments INTEGER, posts INTEGER, own_n INTEGER, competitors TEXT, score INTEGER, level TEXT,
  last_at TEXT, updated TEXT);
