"""
db.py — SQLite layer for SMVS OCR.

Single file DB (jobs/_data/smvs.db) — Coolify volume ni andar j rahe (jobs/ persistent chhe).
Tracks: jobs (lifecycle + cloud upload status), login_history, page_views.
Designed to be import-and-call: no ORM, plain sqlite3 + small helpers, thread-safe via
check_same_thread=False + a single module-level lock (writes are infrequent/small).
"""

import json
import os
import sqlite3
import threading
import time
import uuid

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "jobs", "_data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "smvs.db")

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL;")
_conn.execute("PRAGMA foreign_keys=ON;")


def _init():
    with _lock:
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id            TEXT PRIMARY KEY,
                username          TEXT NOT NULL,
                original_filename TEXT,
                output_filename   TEXT,
                pages             INTEGER DEFAULT 0,
                language          TEXT,
                mode              TEXT,
                status            TEXT NOT NULL DEFAULT 'queued',
                -- queued | processing | uploading | completed | upload_failed | error
                error_message     TEXT,
                created_at        REAL NOT NULL,
                start_time        REAL,
                end_time          REAL,
                duration_sec      REAL,
                cloud_provider    TEXT,
                cloud_folder_link TEXT,
                upload_attempts   INTEGER DEFAULT 0,
                ip                TEXT,
                location          TEXT,
                device            TEXT,
                mac               TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_username ON jobs(username);
            CREATE INDEX IF NOT EXISTS idx_jobs_status   ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_created  ON jobs(created_at);

            CREATE TABLE IF NOT EXISTS login_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT,
                ip          TEXT,
                device      TEXT,
                location    TEXT,
                success     INTEGER NOT NULL,
                timestamp   REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_login_ts ON login_history(timestamp);

            CREATE TABLE IF NOT EXISTS page_views (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT,
                page        TEXT,
                logged_in   INTEGER NOT NULL DEFAULT 0,
                ip          TEXT,
                timestamp   REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pv_ts ON page_views(timestamp);

            CREATE TABLE IF NOT EXISTS live_sessions (
                session_id  TEXT PRIMARY KEY,
                page        TEXT,
                logged_in   INTEGER NOT NULL DEFAULT 0,
                last_seen   REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_users (
                username      TEXT PRIMARY KEY,
                email         TEXT NOT NULL,
                first_name    TEXT NOT NULL,
                last_name     TEXT NOT NULL,
                salt          TEXT NOT NULL,
                hash          TEXT NOT NULL,
                token         TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                reject_reason TEXT,
                token_used    INTEGER NOT NULL DEFAULT 0,
                created_at    REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token       TEXT PRIMARY KEY,
                username    TEXT NOT NULL,
                expires_at  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                email       TEXT,
                username    TEXT,
                type        TEXT NOT NULL,
                message     TEXT NOT NULL,
                rating      INTEGER,
                status      TEXT NOT NULL DEFAULT 'new',
                action_done INTEGER NOT NULL DEFAULT 0,
                created_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fb_created ON feedback(created_at);

            CREATE TABLE IF NOT EXISTS roles (
                name        TEXT PRIMARY KEY,
                permissions TEXT NOT NULL DEFAULT '[]',
                created_at  REAL NOT NULL
            );

            -- Session invalidation: per-user + global cutoff timestamps.
            -- A token is valid only if its issued-at (iat) >= the applicable cutoff.
            CREATE TABLE IF NOT EXISTS session_control (
                scope       TEXT PRIMARY KEY,   -- 'global' or 'user:<username>'
                cutoff      REAL NOT NULL        -- tokens issued before this are invalid
            );
            """
        )
        _conn.commit()


_init()


def _migrate():
    """Add columns to existing tables that may predate them (safe idempotent)."""
    with _lock:
        cols = {r[1] for r in _conn.execute("PRAGMA table_info(feedback)").fetchall()}
        if "username" not in cols:
            _conn.execute("ALTER TABLE feedback ADD COLUMN username TEXT")
        if "action_done" not in cols:
            _conn.execute("ALTER TABLE feedback ADD COLUMN action_done INTEGER NOT NULL DEFAULT 0")
        jcols = {r[1] for r in _conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "failed_pages" not in jcols:
            _conn.execute("ALTER TABLE jobs ADD COLUMN failed_pages INTEGER DEFAULT 0")
        pcols = {r[1] for r in _conn.execute("PRAGMA table_info(pending_users)").fetchall()}
        if "status" not in pcols:
            _conn.execute("ALTER TABLE pending_users ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
        if "reject_reason" not in pcols:
            _conn.execute("ALTER TABLE pending_users ADD COLUMN reject_reason TEXT")
        if "token_used" not in pcols:
            _conn.execute("ALTER TABLE pending_users ADD COLUMN token_used INTEGER NOT NULL DEFAULT 0")
        _conn.commit()


_migrate()


# ------------------------------------------------------------------ JOBS

def job_create(job_id, username, original_filename, language=None, mode=None,
                ip=None, location=None, device=None, mac=None):
    now = time.time()
    with _lock:
        _conn.execute(
            """INSERT INTO jobs (job_id, username, original_filename, status,
                                  created_at, language, mode, ip, location, device, mac)
               VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, username, original_filename, now, language, mode, ip, location, device, mac),
        )
        _conn.commit()


def job_update(job_id, **fields):
    """Generic partial update. e.g. job_update(jid, status='processing', start_time=time.time())"""
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [job_id]
    with _lock:
        _conn.execute(f"UPDATE jobs SET {cols} WHERE job_id = ?", vals)
        _conn.commit()


def job_get(job_id):
    with _lock:
        row = _conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def jobs_pending_count():
    """Jobs ahead in queue (queued or processing) — for queue-position estimate."""
    with _lock:
        row = _conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE status IN ('queued', 'processing')"
        ).fetchone()
    return row["c"] if row else 0


def avg_seconds_per_page(limit=50):
    """Rolling average duration/page from last N completed jobs — for time estimates."""
    with _lock:
        rows = _conn.execute(
            """SELECT duration_sec, pages FROM jobs
               WHERE status = 'completed' AND duration_sec IS NOT NULL AND pages > 0
               ORDER BY end_time DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    if not rows:
        return 2.5  # fallback default guess (sec/page) until we have history
    total_sec = sum(r["duration_sec"] for r in rows)
    total_pages = sum(r["pages"] for r in rows)
    return (total_sec / total_pages) if total_pages else 2.5


def jobs_failed_uploads():
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM jobs WHERE status = 'upload_failed' ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def jobs_query(username=None, status=None, date_from=None, date_to=None,
                search=None, limit=200):
    q = "SELECT * FROM jobs WHERE 1=1"
    params = []
    if username:
        q += " AND username = ?"
        params.append(username)
    if status:
        q += " AND status = ?"
        params.append(status)
    if date_from:
        q += " AND created_at >= ?"
        params.append(date_from)
    if date_to:
        q += " AND created_at <= ?"
        params.append(date_to)
    if search:
        q += " AND (original_filename LIKE ? OR output_filename LIKE ? OR username LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _lock:
        rows = _conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def dashboard_summary(since_ts=None):
    """Top summary cards: totals + per-status counts, optionally since a timestamp."""
    where = "WHERE created_at >= ?" if since_ts else ""
    params = [since_ts] if since_ts else []
    with _lock:
        total = _conn.execute(f"SELECT COUNT(*) c FROM jobs {where}", params).fetchone()["c"]
        by_status = _conn.execute(
            f"SELECT status, COUNT(*) c FROM jobs {where} GROUP BY status", params
        ).fetchall()
        pages = _conn.execute(
            f"SELECT COALESCE(SUM(pages),0) p FROM jobs {where}", params
        ).fetchone()["p"]
        avg_dur = _conn.execute(
            f"SELECT AVG(duration_sec) d FROM jobs {where} AND status='completed'"
            if where else "SELECT AVG(duration_sec) d FROM jobs WHERE status='completed'",
            params,
        ).fetchone()["d"]
        users = _conn.execute(f"SELECT COUNT(DISTINCT username) c FROM jobs {where}", params).fetchone()["c"]
    status_map = {r["status"]: r["c"] for r in by_status}
    return {
        "total_jobs": total,
        "completed": status_map.get("completed", 0),
        "pending": status_map.get("queued", 0) + status_map.get("processing", 0)
                   + status_map.get("uploading", 0),
        "failed": status_map.get("error", 0) + status_map.get("upload_failed", 0),
        "total_users": users,
        "total_pages": pages,
        "avg_duration_sec": round(avg_dur, 1) if avg_dur else 0,
    }


def dashboard_timeseries(days=30):
    """Daily job counts for the last N days — for line/bar charts."""
    since = time.time() - days * 86400
    with _lock:
        rows = _conn.execute(
            """SELECT date(created_at, 'unixepoch') d, status, COUNT(*) c
               FROM jobs WHERE created_at >= ?
               GROUP BY d, status ORDER BY d ASC""",
            (since,),
        ).fetchall()
    return [dict(r) for r in rows]


def dashboard_userwise(since_ts=None):
    where = "WHERE j.created_at >= ?" if since_ts else ""
    params = [since_ts] if since_ts else []
    with _lock:
        rows = _conn.execute(
            f"""SELECT j.username,
                      COUNT(*) total,
                      SUM(CASE WHEN j.status='completed' THEN 1 ELSE 0 END) completed,
                      SUM(CASE WHEN j.status IN ('queued','processing','uploading') THEN 1 ELSE 0 END) pending,
                      SUM(CASE WHEN j.status IN ('error','upload_failed') THEN 1 ELSE 0 END) failed,
                      COALESCE(SUM(CASE WHEN j.status='completed' THEN j.pages ELSE 0 END),0) pages_done,
                      COALESCE(SUM(CASE WHEN j.status IN ('error','upload_failed') THEN j.pages ELSE 0 END),0) pages_failed,
                      (SELECT j2.ip FROM jobs j2 WHERE j2.username = j.username AND j2.ip IS NOT NULL
                       ORDER BY j2.created_at DESC LIMIT 1) ip,
                      (SELECT j3.location FROM jobs j3 WHERE j3.username = j.username AND j3.location IS NOT NULL
                       ORDER BY j3.created_at DESC LIMIT 1) location
               FROM jobs j {where} GROUP BY j.username ORDER BY total DESC""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------- LOGIN HISTORY

def login_record(username, ip, device, location, success):
    with _lock:
        _conn.execute(
            """INSERT INTO login_history (username, ip, device, location, success, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (username, ip, device, location, 1 if success else 0, time.time()),
        )
        _conn.commit()


def login_history_recent(limit=100, since_ts=None):
    with _lock:
        if since_ts:
            rows = _conn.execute(
                "SELECT * FROM login_history WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
                (since_ts, limit),
            ).fetchall()
        else:
            rows = _conn.execute(
                "SELECT * FROM login_history ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ PAGE VIEWS

def page_view_record(session_id, page, logged_in, ip, count_view=True):
    """count_view=True → records a page view (visit count). Always updates live presence.
    Refresh/ping ma count_view=False rakho jethi count na vadhe (point 10)."""
    now = time.time()
    with _lock:
        if count_view:
            _conn.execute(
                "INSERT INTO page_views (session_id, page, logged_in, ip, timestamp) VALUES (?, ?, ?, ?, ?)",
                (session_id, page, 1 if logged_in else 0, ip, now),
            )
        _conn.execute(
            """INSERT INTO live_sessions (session_id, page, logged_in, last_seen)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET page=?, logged_in=?, last_seen=?""",
            (session_id, page, 1 if logged_in else 0, now, page, 1 if logged_in else 0, now),
        )
        _conn.commit()


def live_touch(session_id, page, logged_in):
    """Only update live presence (no view count) — for heartbeat ping."""
    now = time.time()
    with _lock:
        _conn.execute(
            """INSERT INTO live_sessions (session_id, page, logged_in, last_seen)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET page=?, logged_in=?, last_seen=?""",
            (session_id, page, 1 if logged_in else 0, now, page, 1 if logged_in else 0, now),
        )
        _conn.commit()


def live_counts(active_window_sec=60):
    """Live visitor counts for dashboard / login page widget."""
    cutoff = time.time() - active_window_sec
    with _lock:
        _conn.execute("DELETE FROM live_sessions WHERE last_seen < ?", (cutoff,))
        _conn.commit()
        total = _conn.execute("SELECT COUNT(*) c FROM live_sessions").fetchone()["c"]
        logged_in = _conn.execute(
            "SELECT COUNT(*) c FROM live_sessions WHERE logged_in = 1"
        ).fetchone()["c"]
    return {"total_online": total, "logged_in_online": logged_in,
            "pre_login_online": max(total - logged_in, 0)}


# --------------------------------------------------------- SESSION INVALIDATION
def session_set_cutoff(scope, cutoff=None):
    """Set an invalidation cutoff. scope='global' logs everyone out;
    scope='user:<name>' logs out that one user. Tokens issued before cutoff are rejected."""
    if cutoff is None:
        cutoff = time.time()
    with _lock:
        _conn.execute(
            "INSERT INTO session_control (scope, cutoff) VALUES (?, ?) "
            "ON CONFLICT(scope) DO UPDATE SET cutoff=?",
            (scope, cutoff, cutoff),
        )
        _conn.commit()
    return cutoff


def session_get_cutoff(username):
    """Highest applicable cutoff for a user (max of global and user-specific)."""
    with _lock:
        rows = _conn.execute(
            "SELECT scope, cutoff FROM session_control WHERE scope IN ('global', ?)",
            (f"user:{username}",),
        ).fetchall()
    cutoff = 0.0
    for r in rows:
        if r["cutoff"] > cutoff:
            cutoff = r["cutoff"]
    return cutoff


def session_active_users(active_window_sec=120):
    """Distinct logged-in usernames currently active (from live_sessions).
    live_sessions doesn't store username, so we return count-based presence only.
    Actual username list comes from recent login_history cross-referenced with live activity."""
    cutoff = time.time() - active_window_sec
    with _lock:
        rows = _conn.execute(
            "SELECT DISTINCT username FROM login_history "
            "WHERE success=1 AND timestamp >= ? ORDER BY username",
            (time.time() - 86400,),  # logged in within last 24h as candidate pool
        ).fetchall()
    return [r["username"] for r in rows if r["username"]]
# ------------------------------------------------------ END SESSION INVALIDATION


def page_view_totals(since_ts=None):
    where = "WHERE timestamp >= ?" if since_ts else ""
    params = [since_ts] if since_ts else []
    with _lock:
        total = _conn.execute(f"SELECT COUNT(*) c FROM page_views {where}", params).fetchone()["c"]
        pre = _conn.execute(
            f"SELECT COUNT(*) c FROM page_views {where} {'AND' if where else 'WHERE'} logged_in = 0",
            params,
        ).fetchone()["c"]
        post = total - pre
    return {"total_views": total, "pre_login_views": pre, "post_login_views": post}

def batch_has_pending_upload(job_prefix):
    with _lock:
        row = _conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE job_id LIKE ? AND status = 'upload_failed'",
            (job_prefix + "_%",),
        ).fetchone()
    return row["c"] > 0 if row else False


def cloud_jobs_all(limit=200):
    """Cloud Management tab mate — badha j jobs jema cloud_provider ya upload_failed status hoy,
    plus nava jobs je abhi uploading/queued hoy. Server remove status = local folder exist kare ke nahi."""
    with _lock:
        rows = _conn.execute(
            """SELECT job_id, username, original_filename, output_filename,
                      status, cloud_provider, cloud_folder_link,
                      upload_attempts, error_message, created_at, end_time
               FROM jobs
               WHERE status IN ('completed','upload_failed','uploading','error')
                  OR cloud_provider IS NOT NULL
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]



# -------------------------------------------------------- PENDING USERS (signup)

def pending_user_create(username, email, first_name, last_name, salt, pw_hash, token):
    with _lock:
        _conn.execute(
            """INSERT OR REPLACE INTO pending_users
               (username,email,first_name,last_name,salt,hash,token,status,token_used,created_at)
               VALUES (?,?,?,?,?,?,?,'pending',0,?)""",
            (username, email, first_name, last_name, salt, pw_hash, token, time.time()),
        )
        _conn.commit()


def pending_user_get(token):
    with _lock:
        row = _conn.execute("SELECT * FROM pending_users WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def pending_user_get_by_name(username):
    with _lock:
        row = _conn.execute("SELECT * FROM pending_users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def pending_user_mark_token_used(username):
    """One-time token — mark used so link can't work again (point 5)."""
    with _lock:
        _conn.execute("UPDATE pending_users SET token_used=1 WHERE username=?", (username,))
        _conn.commit()


def pending_user_mark_rejected(username, reason):
    """Keep the record with status=rejected + reason, mark token used."""
    with _lock:
        _conn.execute(
            "UPDATE pending_users SET status='rejected', reject_reason=?, token_used=1 WHERE username=?",
            (reason or "", username),
        )
        _conn.commit()


def pending_user_get_all():
    with _lock:
        rows = _conn.execute("SELECT * FROM pending_users ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def pending_user_delete(username):
    with _lock:
        _conn.execute("DELETE FROM pending_users WHERE username=?", (username,))
        _conn.commit()


def username_taken(username, users_dict):
    if username in users_dict:
        return True
    with _lock:
        # rejected users don't block re-signup; only active-pending do
        row = _conn.execute(
            "SELECT 1 FROM pending_users WHERE username=? AND status='pending'", (username,)
        ).fetchone()
    return row is not None


# -------------------------------------------------- PASSWORD RESET TOKENS

def reset_token_create(username, expires_minutes=30):
    token = uuid.uuid4().hex + uuid.uuid4().hex
    expires = time.time() + expires_minutes * 60
    with _lock:
        _conn.execute("DELETE FROM password_reset_tokens WHERE username=?", (username,))
        _conn.execute(
            "INSERT INTO password_reset_tokens (token,username,expires_at) VALUES (?,?,?)",
            (token, username, expires),
        )
        _conn.commit()
    return token


def reset_token_consume(token):
    with _lock:
        row = _conn.execute(
            "SELECT username, expires_at FROM password_reset_tokens WHERE token=?", (token,)
        ).fetchone()
        if not row:
            return None
        if time.time() > row["expires_at"]:
            _conn.execute("DELETE FROM password_reset_tokens WHERE token=?", (token,))
            _conn.commit()
            return None
        _conn.execute("DELETE FROM password_reset_tokens WHERE token=?", (token,))
        _conn.commit()
    return row["username"]


# --------------------------------------------------------------- FEEDBACK

def feedback_create(name, email, fb_type, message, rating=None, username=None):
    with _lock:
        cur = _conn.execute(
            "INSERT INTO feedback (name,email,username,type,message,rating,created_at) VALUES (?,?,?,?,?,?,?)",
            (name, email or "", username or "", fb_type, message, rating, time.time()),
        )
        _conn.commit()
        return cur.lastrowid


def feedback_list(limit=200, fb_type=None):
    q = "SELECT * FROM feedback"
    params = []
    if fb_type:
        q += " WHERE type = ?"
        params.append(fb_type)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _lock:
        rows = _conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def feedback_types():
    with _lock:
        rows = _conn.execute("SELECT DISTINCT type FROM feedback ORDER BY type").fetchall()
    return [r["type"] for r in rows]


def feedback_mark_read(fb_id):
    with _lock:
        _conn.execute("UPDATE feedback SET status='read' WHERE id=?", (fb_id,))
        _conn.commit()


def feedback_toggle_action(fb_id):
    with _lock:
        row = _conn.execute("SELECT action_done FROM feedback WHERE id=?", (fb_id,)).fetchone()
        if not row:
            return None
        new_val = 0 if row["action_done"] else 1
        _conn.execute("UPDATE feedback SET action_done=? WHERE id=?", (new_val, fb_id))
        _conn.commit()
    return new_val


# --------------------------------------------------------------- ROLES
import json as _json


def role_upsert(name, permissions):
    with _lock:
        _conn.execute(
            """INSERT INTO roles (name, permissions, created_at) VALUES (?,?,?)
               ON CONFLICT(name) DO UPDATE SET permissions=?""",
            (name, _json.dumps(permissions), time.time(), _json.dumps(permissions)),
        )
        _conn.commit()


def role_get(name):
    with _lock:
        row = _conn.execute("SELECT * FROM roles WHERE name=?", (name,)).fetchone()
    if not row:
        return None
    return {"name": row["name"], "permissions": _json.loads(row["permissions"] or "[]")}


def role_list():
    with _lock:
        rows = _conn.execute("SELECT * FROM roles ORDER BY created_at ASC").fetchall()
    return [{"name": r["name"], "permissions": _json.loads(r["permissions"] or "[]")} for r in rows]


def role_delete(name):
    with _lock:
        _conn.execute("DELETE FROM roles WHERE name=?", (name,))
        _conn.commit()
def new_session_id():
    return uuid.uuid4().hex

