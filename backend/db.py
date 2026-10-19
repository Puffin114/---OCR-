"""SQLite 初始化与连接。表：dataset/document/label/eval_task/metric/eval_criteria/review_override。"""
import os
import sqlite3
from contextlib import contextmanager

from config import get_config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dataset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    doc_total INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS label (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    label_id TEXT NOT NULL,
    label_name TEXT NOT NULL,
    label_color TEXT,
    display_order INTEGER DEFAULT 0,
    label_extend TEXT
);
CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    key TEXT NOT NULL,            -- 文件名前缀 row{N}_...
    doc_file TEXT,                -- doc/ 原始文件名
    has_annotation INTEGER DEFAULT 0,
    has_parser INTEGER DEFAULT 0,
    has_doc INTEGER DEFAULT 0,
    complete INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS eval_task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'created',   -- created/running/success/failed
    version TEXT DEFAULT 'V1',
    doc_keys TEXT,                   -- JSON: 本次评测的文档key列表
    message TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS prediction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    doc_key TEXT NOT NULL,
    raw_json TEXT,                   -- 公有云原始返回
    parsed_json TEXT                 -- {field:[values]}
);
CREATE TABLE IF NOT EXISTS metric (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    review INTEGER DEFAULT 0,        -- 0=原始 1=人工复核后
    scope TEXT NOT NULL,             -- 'overall' 或字段名
    data_count INTEGER DEFAULT 0,
    tp INTEGER DEFAULT 0,
    fp INTEGER DEFAULT 0,
    fn INTEGER DEFAULT 0,
    precision REAL DEFAULT 0,
    recall REAL DEFAULT 0,
    f1 REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS eval_criteria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    field TEXT NOT NULL,             -- 字段名；'*' 表示全局
    modes TEXT NOT NULL,             -- JSON 数组，如 ["trim_punct","date_normalize"]
    regex TEXT,
    UNIQUE(task_id, field)
);
CREATE TABLE IF NOT EXISTS review_override (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    doc_key TEXT NOT NULL,
    field TEXT NOT NULL,
    verdict TEXT NOT NULL,           -- success/fail
    old_verdict TEXT,
    operator TEXT DEFAULT 'user',
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(task_id, doc_key, field)
);
CREATE TABLE IF NOT EXISTS model_service (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    model TEXT,
    model_type TEXT,                 -- 文本生成-非思考 / 视觉理解-思考 等
    api_key TEXT,
    api_url TEXT,
    context_len TEXT,
    max_input TEXT,
    max_output TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


def _db_path() -> str:
    cfg = get_config()
    return os.path.join(cfg.storage_dir, "app.sqlite")


# 幂等迁移：对已存在的旧库补充新列
_MIGRATIONS = [
    ("prediction", "elapsed_ms", "REAL DEFAULT 0"),
    ("prediction", "slice_count", "INTEGER DEFAULT 0"),
    ("dataset", "base_dir", "TEXT"),
    ("eval_task", "engine", "TEXT"),
    ("eval_task", "started_at", "TEXT"),
    ("eval_task", "finished_at", "TEXT"),
    ("label", "parent_id", "TEXT"),
    ("label", "eval_modes", "TEXT"),
    ("eval_task", "fields", "TEXT"),
    ("eval_task", "field_defs", "TEXT"),
    ("dataset", "source", "TEXT"),
]


def _migrate(conn):
    for table, column, decl in _MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _dedup_names(conn, table):
    """历史重名去重：按 id 升序保留先出现者，后出现的同名追加 ' (2)'、' (3)'…；
    同时把名称 strip 规整，确保后续唯一索引可建立。幂等。"""
    rows = conn.execute(f"SELECT id, name FROM {table} ORDER BY id").fetchall()
    used = set()
    for r in rows:
        nm = (r["name"] or "").strip()
        candidate = nm
        i = 1
        while candidate in used:
            i += 1
            candidate = f"{nm} ({i})"
        used.add(candidate)
        if candidate != (r["name"] or ""):
            conn.execute(f"UPDATE {table} SET name=? WHERE id=?", (candidate, r["id"]))


def _migrate_unique_names(conn):
    """数据集/评测任务名称全局唯一：先清历史重名，再建唯一索引。幂等可重复执行。"""
    _dedup_names(conn, "dataset")
    _dedup_names(conn, "eval_task")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_dataset_name ON dataset(name)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_eval_task_name ON eval_task(name)")


def init_db():
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        _migrate_unique_names(conn)
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
