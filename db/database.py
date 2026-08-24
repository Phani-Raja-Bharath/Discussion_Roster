import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


BASE_DIR = Path(__file__).resolve().parent.parent
SQLITE_PATH = BASE_DIR / "nominations.db"
INPUTS_DIR = BASE_DIR / "inputs"
STUDENTS_JSON = INPUTS_DIR / "students.json"
SCHEDULE_JSON = INPUTS_DIR / "discussion_schedule.json"
PAPERS_JSON = INPUTS_DIR / "papers.json"


def get_secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except StreamlitSecretNotFoundError:
        return default


def admin_password():
    return get_secret("ADMIN_PASSWORD", "change-me")


def database_url():
    return get_secret("DATABASE_URL") or os.getenv("DATABASE_URL")


def is_postgres():
    url = database_url()
    return bool(url and url.startswith(("postgresql://", "postgres://")))


def placeholder(sql):
    return sql.replace("?", "%s") if is_postgres() else sql


def normalize_postgres_url(url):
    if url and url.startswith("postgres://"):
        return "postgresql://" + url.removeprefix("postgres://")
    return url


_schema_ready = False
_pool = None


class _PooledConnection:
    """A psycopg connection checked out from the pool.

    Behaves like a plain connection for callers (attribute access delegates
    through), but close()/__exit__ return the connection to the pool instead
    of tearing down the TCP/TLS session — that round trip is what made every
    rows()/one()/execute() call slow.
    """

    def __init__(self, pool, connection):
        self._pool = pool
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        self.close()
        return False

    def close(self):
        if self._connection is not None:
            self._pool.putconn(self._connection)
            self._connection = None


def _get_pool():
    global _pool
    if _pool is None:
        try:
            from psycopg_pool import ConnectionPool
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "DATABASE_URL is set, but psycopg[pool] is not installed. "
                "Run pip install -r requirements.txt."
            ) from exc
        _pool = ConnectionPool(
            normalize_postgres_url(database_url()),
            min_size=1,
            max_size=5,
            open=True,
        )
    return _pool


def connect():
    global _schema_ready
    if is_postgres():
        pool = _get_pool()
        connection = _PooledConnection(pool, pool.getconn())
    else:
        connection = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
        connection.execute("PRAGMA journal_mode=WAL")
    # init_db() runs CREATE TABLE / ALTER TABLE checks. Every rows()/one()/execute()
    # call opens its own connection, so without this guard those checks (and their
    # round trips to Postgres) would re-run on every single query in the app.
    if not _schema_ready:
        init_db(connection)
        _schema_ready = True
    return connection


def init_db(connection):
    if is_postgres():
        statements = [
            """CREATE TABLE IF NOT EXISTS students (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                active BOOLEAN DEFAULT TRUE
            )""",
            """CREATE TABLE IF NOT EXISTS papers (
                id SERIAL PRIMARY KEY,
                week INTEGER NOT NULL,
                paper_number INTEGER NOT NULL,
                paper_title TEXT NOT NULL,
                paper_link TEXT,
                active BOOLEAN DEFAULT TRUE,
                UNIQUE(week, paper_number)
            )""",
            """CREATE TABLE IF NOT EXISTS nominations (
                id SERIAL PRIMARY KEY,
                student_id INTEGER NOT NULL REFERENCES students(id),
                paper_id INTEGER NOT NULL REFERENCES papers(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id),
                UNIQUE(paper_id)
            )""",
        ]
    else:
        statements = [
            """CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                active BOOLEAN DEFAULT TRUE
            )""",
            """CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week INTEGER NOT NULL,
                paper_number INTEGER NOT NULL,
                paper_title TEXT NOT NULL,
                paper_link TEXT,
                active BOOLEAN DEFAULT TRUE,
                UNIQUE(week, paper_number)
            )""",
            """CREATE TABLE IF NOT EXISTS nominations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id),
                paper_id INTEGER NOT NULL REFERENCES papers(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id),
                UNIQUE(paper_id)
            )""",
        ]
    for statement in statements:
        connection.execute(statement)
    migrate_sqlite(connection)
    migrate_postgres(connection)
    connection.commit()


def migrate_sqlite(connection):
    if is_postgres():
        return
    paper_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(papers)").fetchall()
    }
    student_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(students)").fetchall()
    }
    if "paper_number" not in paper_columns:
        connection.execute("ALTER TABLE papers ADD COLUMN paper_number INTEGER")
        connection.execute("UPDATE papers SET paper_number = id WHERE paper_number IS NULL")
    if "active" not in paper_columns:
        connection.execute("ALTER TABLE papers ADD COLUMN active BOOLEAN DEFAULT TRUE")
    if "active" not in student_columns:
        connection.execute("ALTER TABLE students ADD COLUMN active BOOLEAN DEFAULT TRUE")
    # file_data/file_name/file_mime backed a PDF-in-the-database download feature that
    # has been removed (every paper now links to its source instead) — drop the columns
    # from any database that still has them from before.
    for column in ("file_data", "file_name", "file_mime"):
        if column in paper_columns:
            connection.execute(f"ALTER TABLE papers DROP COLUMN {column}")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_week_number ON papers(week, paper_number)"
    )


def migrate_postgres(connection):
    if not is_postgres():
        return
    for column in ("file_data", "file_name", "file_mime"):
        connection.execute(f"ALTER TABLE papers DROP COLUMN IF EXISTS {column}")


@contextmanager
def transaction():
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def rows(sql, params=()):
    with connect() as connection:
        cursor = connection.execute(placeholder(sql), params)
        return cursor.fetchall()


def one(sql, params=()):
    result = rows(sql, params)
    return result[0] if result else None


def execute(sql, params=()):
    with transaction() as connection:
        connection.execute(placeholder(sql), params)


def read_dataframe(sql, params=()):
    with connect() as connection:
        prepared_sql = placeholder(sql)
        if is_postgres():
            cursor = connection.execute(prepared_sql, params)
            columns = [
                column.name if hasattr(column, "name") else column[0]
                for column in cursor.description
            ]
            return pd.DataFrame(cursor.fetchall(), columns=columns)
        return pd.read_sql_query(prepared_sql, connection, params=params)


def read_upload(upload):
    if upload.name.lower().endswith(".csv"):
        return pd.read_csv(upload)
    return pd.read_excel(upload)


def dataframe_from_json(path):
    return pd.read_json(path)


def schedule_papers_dataframe(path):
    """Flatten discussion_schedule.json's per-week embedded papers into a
    week/paper_number/title/link table, the shape import_papers_df() expects.
    This is the single source of truth for both the schedule (date/topic) and
    the paper list, so there's nothing to keep in sync with a second file."""
    import json

    with open(path, encoding="utf-8") as handle:
        schedule = json.load(handle)

    rows_out = []
    for week in schedule:
        for paper in week.get("papers", []):
            rows_out.append(
                {
                    "week": week["week"],
                    "paper_number": paper.get("paper_number"),
                    "title": paper.get("title"),
                    "link": paper.get("link", ""),
                }
            )
    return pd.DataFrame(rows_out)


def extract_url(value):
    match = re.search(r"https?://\S+", str(value))
    return match.group(0).rstrip(".,)") if match else ""


def parse_week(value):
    match = re.search(r"\d+", str(value))
    if not match:
        raise ValueError(f"Could not read a week number from {value!r}.")
    return int(match.group())


def import_students_df(df):
    columns = {str(column).strip().lower(): column for column in df.columns}
    name_column = columns.get("name") or columns.get("student") or columns.get("student name")
    if not name_column:
        raise ValueError("Student file needs a Name, Student, or Student Name column.")

    with transaction() as connection:
        for value in df[name_column].dropna():
            name = str(value).strip()
            if name:
                connection.execute(
                    placeholder(
                        "INSERT INTO students(name, active) VALUES(?, TRUE) "
                        "ON CONFLICT(name) DO UPDATE SET active = TRUE"
                    ),
                    (name,),
                )


def import_papers_df(df):
    columns = {str(column).strip().lower(): column for column in df.columns}
    week_column = columns.get("week")
    number_column = columns.get("paper number") or columns.get("paper_number") or columns.get("number")
    title_column = (
        columns.get("paper title")
        or columns.get("paper")
        or columns.get("title")
        or columns.get("paper_title")
    )
    link_column = columns.get("link") or columns.get("paper link") or columns.get("url") or columns.get("paper_link")

    if not week_column or not title_column:
        raise ValueError("Paper file needs Week and Paper Title, Paper, or Title columns.")

    with transaction() as connection:
        week_counters = {}
        for index, row in df.iterrows():
            if pd.isna(row[week_column]) or pd.isna(row[title_column]):
                continue
            title = str(row[title_column]).strip()
            week = parse_week(row[week_column])
            if number_column and not pd.isna(row[number_column]):
                paper_number = int(row[number_column])
            else:
                week_counters[week] = week_counters.get(week, 0) + 1
                paper_number = week_counters[week]
            link = (
                str(row[link_column]).strip()
                if link_column and not pd.isna(row[link_column])
                else extract_url(title)
            )
            connection.execute(
                placeholder(
                    "INSERT INTO papers(week, paper_number, paper_title, paper_link, active) "
                    "VALUES(?, ?, ?, ?, TRUE) "
                    "ON CONFLICT(week, paper_number) DO UPDATE SET "
                    "paper_title = excluded.paper_title, paper_link = excluded.paper_link, active = TRUE"
                ),
                (week, paper_number, title, link),
            )


def paper_schedule_warning():
    df = read_dataframe(
        'SELECT week AS "week", COUNT(*) AS "papers" FROM papers WHERE active = TRUE GROUP BY week ORDER BY CAST(week AS INTEGER)'
    )
    total = int(df["papers"].sum()) if not df.empty else 0
    bad_weeks = df[df["papers"] != 4]["week"].tolist() if not df.empty else []
    if total == 40 and len(df) == 10 and not bad_weeks:
        return None
    return f"Schedule currently has {total} papers across {len(df)} weeks. Expected 40 papers across 10 weeks with 4 papers per week."


def create_nomination(student_id, paper_id):
    with transaction() as connection:
        connection.execute(
            placeholder("INSERT INTO nominations(student_id, paper_id) VALUES(?, ?)"),
            (student_id, paper_id),
        )


def is_integrity_error(exc):
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    return exc.__class__.__name__ in {"IntegrityError", "UniqueViolation"}


def seed_from_inputs_if_empty():
    with connect() as connection:
        student_count = connection.execute(
            "SELECT COUNT(*) FROM students WHERE active = TRUE"
        ).fetchone()[0]
        paper_count = connection.execute(
            "SELECT COUNT(*) FROM papers WHERE active = TRUE"
        ).fetchone()[0]

    seeded = []
    if student_count == 0 and STUDENTS_JSON.exists():
        import_students_df(dataframe_from_json(STUDENTS_JSON))
        seeded.append("students")
    if paper_count == 0:
        if SCHEDULE_JSON.exists():
            import_papers_df(schedule_papers_dataframe(SCHEDULE_JSON))
            seeded.append("papers")
        elif PAPERS_JSON.exists():
            import_papers_df(dataframe_from_json(PAPERS_JSON))
            seeded.append("papers")
    return seeded
