"""SQLite storage: schema, connections, transactions, FTS5 fallback."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  field TEXT NOT NULL DEFAULT '',
  question TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'paper',
  content_md TEXT NOT NULL DEFAULT '',
  word_count INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  content_md TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doi TEXT UNIQUE,
  title TEXT NOT NULL,
  authors TEXT NOT NULL DEFAULT '[]',
  year INTEGER,
  venue TEXT NOT NULL DEFAULT '',
  volume TEXT NOT NULL DEFAULT '',
  issue TEXT NOT NULL DEFAULT '',
  pages TEXT NOT NULL DEFAULT '',
  type TEXT NOT NULL DEFAULT 'journal-article',
  language TEXT NOT NULL DEFAULT '',
  abstract TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  source_id TEXT NOT NULL DEFAULT '',
  bibkey TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'inbox',
  pdf_path TEXT,
  fulltext_path TEXT,
  fulltext TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_refs (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  ref_id INTEGER NOT NULL REFERENCES refs(id) ON DELETE CASCADE,
  relevance REAL NOT NULL DEFAULT 0,
  added_at TEXT NOT NULL,
  PRIMARY KEY (project_id, ref_id)
);

CREATE TABLE IF NOT EXISTS searches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  source TEXT NOT NULL,
  query TEXT NOT NULL,
  filters TEXT NOT NULL DEFAULT '{}',
  count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS style_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  text_hash TEXT NOT NULL DEFAULT '',
  score REAL NOT NULL DEFAULT 0,
  level TEXT NOT NULL DEFAULT 'low',
  findings TEXT NOT NULL DEFAULT '[]',
  baseline TEXT NOT NULL DEFAULT '{}',
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rewrites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  mode TEXT NOT NULL,
  source_text TEXT NOT NULL,
  result_text TEXT NOT NULL,
  ops TEXT NOT NULL DEFAULT '[]',
  gaps TEXT NOT NULL DEFAULT '[]',
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'proposed',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS method_rows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  ref_id INTEGER REFERENCES refs(id) ON DELETE CASCADE,
  method TEXT NOT NULL DEFAULT '',
  data TEXT NOT NULL DEFAULT '',
  sample TEXT NOT NULL DEFAULT '',
  theory TEXT NOT NULL DEFAULT '',
  finding TEXT NOT NULL DEFAULT '',
  limitation TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  stage TEXT NOT NULL DEFAULT 'todo',
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'todo',
  due TEXT,
  notes TEXT NOT NULL DEFAULT '',
  sort INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citation_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ref_id INTEGER NOT NULL REFERENCES refs(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '{}',
  checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER,
  task TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  ms INTEGER NOT NULL DEFAULT 0,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  ok INTEGER NOT NULL DEFAULT 1,
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS direction_cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
  topic TEXT NOT NULL DEFAULT '',
  question TEXT NOT NULL,
  gap TEXT NOT NULL DEFAULT '',
  materials TEXT NOT NULL DEFAULT '',
  method TEXT NOT NULL DEFAULT '',
  risk TEXT NOT NULL DEFAULT '',
  difficulty TEXT NOT NULL DEFAULT '',
  novelty TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_project_refs_project ON project_refs(project_id);
CREATE INDEX IF NOT EXISTS idx_refs_year ON refs(year);
CREATE INDEX IF NOT EXISTS idx_refs_doi ON refs(doi);
CREATE INDEX IF NOT EXISTS idx_method_rows_project ON method_rows(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS refs_fts USING fts5(
  title, abstract, note, fulltext,
  content='refs', content_rowid='id', tokenize='{tokenizer}'
);
CREATE TRIGGER IF NOT EXISTS refs_ai AFTER INSERT ON refs BEGIN
  INSERT INTO refs_fts(rowid, title, abstract, note, fulltext)
  VALUES (new.id, new.title, new.abstract, new.note, new.fulltext);
END;
CREATE TRIGGER IF NOT EXISTS refs_ad AFTER DELETE ON refs BEGIN
  INSERT INTO refs_fts(refs_fts, rowid, title, abstract, note, fulltext)
  VALUES ('delete', old.id, old.title, old.abstract, old.note, old.fulltext);
END;
CREATE TRIGGER IF NOT EXISTS refs_au AFTER UPDATE ON refs BEGIN
  INSERT INTO refs_fts(refs_fts, rowid, title, abstract, note, fulltext)
  VALUES ('delete', old.id, old.title, old.abstract, old.note, old.fulltext);
  INSERT INTO refs_fts(rowid, title, abstract, note, fulltext)
  VALUES (new.id, new.title, new.abstract, new.note, new.fulltext);
END;
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.fts_tokenizer: str | None = None

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=5000")
        return con

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = self.connect()
        try:
            con.executescript(SCHEMA)
            con.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._init_fts(con)
            con.commit()
        finally:
            con.close()

    def _init_fts(self, con: sqlite3.Connection) -> None:
        existing = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='refs_fts'"
        ).fetchone()
        if existing:
            row = con.execute(
                "SELECT sql FROM sqlite_master WHERE name='refs_fts'"
            ).fetchone()
            sql = (row["sql"] if row else "") or ""
            self.fts_tokenizer = "trigram" if "trigram" in sql else "unicode61"
            con.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('fts_tokenizer', ?)",
                (self.fts_tokenizer,),
            )
            return
        for tokenizer in ("trigram", "unicode61"):
            try:
                con.executescript(FTS_SQL.format(tokenizer=tokenizer))
                self.fts_tokenizer = tokenizer
                con.execute(
                    "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('fts_tokenizer', ?)",
                    (tokenizer,),
                )
                return
            except sqlite3.OperationalError:
                con.execute("DROP TABLE IF EXISTS refs_fts")
                continue
        self.fts_tokenizer = None

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        con = self.connect()
        try:
            return con.execute(sql, tuple(params)).fetchall()
        finally:
            con.close()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        con = self.connect()
        try:
            cur = con.execute(sql, tuple(params))
            con.commit()
            return int(cur.lastrowid or 0)
        finally:
            con.close()

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        rows = self.query(sql, params)
        return rows[0][0] if rows else None

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        con = self.connect()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def table_names(self) -> list[str]:
        return [r["name"] for r in self.query("SELECT name FROM sqlite_master WHERE type='table'")]

    def health(self) -> dict[str, Any]:
        return {
            "fts_tokenizer": self.fts_tokenizer,
            "integrity": self.scalar("PRAGMA integrity_check") or "unknown",
        }


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Sequence[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
