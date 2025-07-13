import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import pytz

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, path: str = "bot_data.db"):
        self.path = path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            c.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    birthday DATE,
    last_name TEXT,
    daily_reports INTEGER DEFAULT 1,
    expiry_warnings INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS user_uuids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    uuid TEXT UNIQUE,
    name TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS usage_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid_id INTEGER,
    usage_gb REAL,
    taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(uuid_id) REFERENCES user_uuids(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS scheduled_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_type, chat_id)
);
    -- افزودن ایندکس‌ها برای افزایش سرعت کوئری‌ها
    CREATE INDEX IF NOT EXISTS idx_user_uuids_uuid ON user_uuids(uuid);
    CREATE INDEX IF NOT EXISTS idx_user_uuids_user_id ON user_uuids(user_id);
    CREATE INDEX IF NOT EXISTS idx_snapshots_uuid_id_taken_at ON usage_snapshots(uuid_id, taken_at);
    CREATE INDEX IF NOT EXISTS idx_scheduled_messages_job_type ON scheduled_messages(job_type);
""")
        logger.info("SQLite schema and indexes are ready.")

    def get_user_ids_by_uuids(self, uuids: List[str]) -> List[int]:
        """Fetches distinct Telegram user_ids for a given list of UUIDs."""
        if not uuids:
            return []
        
        placeholders = ','.join('?' for _ in uuids)
        query = f"SELECT DISTINCT user_id FROM user_uuids WHERE uuid IN ({placeholders})"
        
        with self._conn() as c:
            rows = c.execute(query, uuids).fetchall()
            return [row['user_id'] for row in rows]
        
    def window_usage(self, uuid_id: int, hours_ago: int) -> float:
        """Calculates the usage difference in a given time window (in hours)."""
        start_time_utc = datetime.now(pytz.utc) - timedelta(hours=hours_ago)
        
        with self._conn() as c:
            # Find the earliest and latest snapshots within the time window
            query = """
                SELECT MIN(usage_gb) as start_usage, MAX(usage_gb) as end_usage
                FROM usage_snapshots
                WHERE uuid_id = ? AND taken_at >= ?
            """
            row = c.execute(query, (uuid_id, start_time_utc)).fetchone()

            if row and row['start_usage'] is not None and row['end_usage'] is not None:
                # The usage is the difference between the last and first snapshot
                return max(0, row['end_usage'] - row['start_usage'])
            
            return 0.0

    def get_usage_since_midnight(self, uuid_id: int) -> float:
        """Calculates usage difference since midnight TEHRAN time correctly."""
        tehran_tz = pytz.timezone("Asia/Tehran")
        today_midnight_tehran = datetime.now(tehran_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today_midnight_utc = today_midnight_tehran.astimezone(pytz.utc)
        
        with self._conn() as c:
            query = """
                SELECT
                    (SELECT usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at ASC LIMIT 1) as start_usage,
                    (SELECT usage_gb FROM usage_snapshots WHERE uuid_id = ? AND taken_at >= ? ORDER BY taken_at DESC LIMIT 1) as end_usage
            """
            params = (uuid_id, today_midnight_utc, uuid_id, today_midnight_utc)
            row = c.execute(query, params).fetchone()

            if row and row['start_usage'] is not None and row['end_usage'] is not None:
                return max(0, row['end_usage'] - row['start_usage'])
            
            return 0.0

    def get_uuid_id_by_uuid(self, uuid_str: str) -> Optional[int]:
        with self._conn() as c:
            row = c.execute("SELECT id FROM user_uuids WHERE uuid = ?", (uuid_str,)).fetchone()
            return row['id'] if row else None

    def get_usage_since_midnight_by_uuid(self, uuid_str: str) -> float:
        uuid_id = self.get_uuid_id_by_uuid(uuid_str)
        return self.get_usage_since_midnight(uuid_id) if uuid_id else 0.0

    def add_or_update_scheduled_message(self, job_type: str, chat_id: int, message_id: int):
        with self._conn() as c:
            c.execute(
                "INSERT INTO scheduled_messages(job_type, chat_id, message_id) VALUES(?,?,?) "
                "ON CONFLICT(job_type, chat_id) DO UPDATE SET message_id=excluded.message_id, created_at=CURRENT_TIMESTAMP",
                (job_type, chat_id, message_id)
            )

    def get_scheduled_messages(self, job_type: str) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM scheduled_messages WHERE job_type=?", (job_type,)).fetchall()
            return [dict(r) for r in rows]

    def delete_scheduled_message(self, job_id: int):
        with self._conn() as c:
            c.execute("DELETE FROM scheduled_messages WHERE id=?", (job_id,))
            
    def user(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def add_or_update_user(self, user_id: int, username: Optional[str], first: Optional[str], last: Optional[str]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO users(user_id, username, first_name, last_name) VALUES(?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name",
                (user_id, username, first, last),
            )

    def get_user_settings(self, user_id: int) -> Dict[str, bool]:
        with self._conn() as c:
            row = c.execute("SELECT daily_reports, expiry_warnings FROM users WHERE user_id=?", (user_id,)).fetchone()
            if row:
                return {'daily_reports': bool(row['daily_reports']), 'expiry_warnings': bool(row['expiry_warnings'])}
            return {'daily_reports': True, 'expiry_warnings': True}

    def update_user_setting(self, user_id: int, setting: str, value: bool) -> None:
        if setting not in ['daily_reports', 'expiry_warnings']: return
        with self._conn() as c:
            c.execute(f"UPDATE users SET {setting}=? WHERE user_id=?", (int(value), user_id))

    def add_uuid(self, user_id: int, uuid_str: str, name: str) -> str:
        uuid_str = uuid_str.lower()
        with self._conn() as c:
            existing = c.execute("SELECT * FROM user_uuids WHERE uuid = ?", (uuid_str,)).fetchone()
            if existing:
                if existing['is_active']:
                    if existing['user_id'] == user_id:
                        return "این UUID در حال حاضر در لیست شما فعال است."
                    else:
                        return "این UUID قبلاً توسط کاربر دیگری ثبت شده است."
                else:
                    if existing['user_id'] == user_id:
                        c.execute("UPDATE user_uuids SET is_active = 1, name = ?, updated_at = CURRENT_TIMESTAMP WHERE uuid = ?", (name, uuid_str))
                        return "✅ اکانت شما که قبلاً حذف شده بود، با موفقیت دوباره فعال شد."
                    else:
                        return "این UUID متعلق به کاربر دیگری بوده و در حال حاضر غیرفعال است. امکان ثبت آن وجود ندارد."
            else:
                c.execute(
                    "INSERT INTO user_uuids (user_id, uuid, name) VALUES (?, ?, ?)",
                    (user_id, uuid_str, name)
                )
                return "✅ اکانت شما با موفقیت ثبت شد."

    def uuids(self, user_id: int) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM user_uuids WHERE user_id=? AND is_active=1 ORDER BY created_at", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def uuid_by_id(self, user_id: int, uuid_id: int) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM user_uuids WHERE user_id=? AND id=? AND is_active=1", (user_id, uuid_id)).fetchone()
            return dict(row) if row else None

    def deactivate_uuid(self, uuid_id: int) -> bool:
        """Deactivates a UUID, but does not delete it from the database."""
        with self._conn() as c:
            res = c.execute("UPDATE user_uuids SET is_active = 0 WHERE id = ?", (uuid_id,))
            return res.rowcount > 0

    def delete_user_by_uuid(self, uuid: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM user_uuids WHERE uuid=?", (uuid,))

    def all_active_uuids(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT id, user_id, uuid, created_at FROM user_uuids WHERE is_active=1").fetchall()
            return [dict(r) for r in rows]
            
    def get_all_user_ids(self) -> list[int]:
        with self._conn() as c:
            return [r['user_id'] for r in c.execute("SELECT user_id FROM users")]
        
    def get_all_bot_users(self) -> List[Dict[str, Any]]:
        """Retrieves all registered users from the 'users' table."""
        with self._conn() as c:
            rows = c.execute("SELECT user_id, username, first_name, last_name FROM users ORDER BY user_id").fetchall()
            return [dict(r) for r in rows]
        
    def add_usage_snapshot(self, uuid_id: int, usage_gb: float) -> None:
        """Adds a new usage snapshot for a given UUID."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO usage_snapshots (uuid_id, usage_gb, taken_at) VALUES (?, ?, ?)",
                (uuid_id, usage_gb, datetime.now(pytz.utc))
            )

    def update_user_birthday(self, user_id: int, birthday_date: datetime.date):
        """Updates the birthday for a given user."""
        with self._conn() as c:
            c.execute("UPDATE users SET birthday = ? WHERE user_id = ?", (birthday_date, user_id))

    def get_users_with_birthdays(self) -> List[Dict[str, Any]]:
        """Gets all users who have set their birthday, ordered by month and day."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT user_id, first_name, username, birthday FROM users
                WHERE birthday IS NOT NULL
                ORDER BY strftime('%m-%d', birthday)
            """).fetchall()
            return [dict(r) for r in rows]
        
    def get_user_id_by_uuid(self, uuid: str) -> Optional[int]:
        """Fetches a user_id from the user_uuids table based on a UUID."""
        with self._conn() as c:
            row = c.execute("SELECT user_id FROM user_uuids WHERE uuid = ?", (uuid,)).fetchone()
            return row['user_id'] if row else None

    def reset_user_birthday(self, user_id: int) -> None:
        """Resets the birthday for a given user by setting it to NULL."""
        with self._conn() as c:
            c.execute("UPDATE users SET birthday = NULL WHERE user_id = ?", (user_id,))

    def delete_user_snapshots(self, uuid_id: int) -> int:
        """
        تمام رکوردهای مصرف مربوط به یک اکانت خاص را حذف می‌کند.
        این تابع بعد از ارسال گزارش شبانه فراخوانی می‌شود.
        """
        with self._conn() as c:
            cursor = c.execute("DELETE FROM usage_snapshots WHERE uuid_id = ?", (uuid_id,))
            return cursor.rowcount
    
    def get_todays_birthdays(self) -> list:
        """
        Fetches all users whose birthday is today.
        It compares month and day, ignoring the year.
        """
        today = datetime.now(pytz.utc)
        today_month_day = f"{today.month:02d}-{today.day:02d}"
        
        with self._conn() as c:
            rows = c.execute(
                "SELECT user_id FROM users WHERE strftime('%m-%d', birthday) = ?",
                (today_month_day,)
            ).fetchall()
            return [row['user_id'] for row in rows]

    def vacuum_db(self) -> None:
        """Runs the VACUUM command to rebuild the database file, repacking it into a minimal amount of disk space."""
        with self._conn() as c:
            c.execute("VACUUM")

    def get_bot_user_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        """Finds a Telegram user's details from the 'users' table using a UUID."""
        query = """
            SELECT u.user_id, u.first_name, u.username
            FROM users u
            JOIN user_uuids uu ON u.user_id = uu.user_id
            WHERE uu.uuid = ?
        """
        with self._conn() as c:
            row = c.execute(query, (uuid,)).fetchone()
            return dict(row) if row else None

    def get_uuid_to_user_id_map(self) -> Dict[str, int]:
        """Creates a mapping from UUID strings to Telegram user_ids."""
        with self._conn() as c:
            rows = c.execute("SELECT uuid, user_id FROM user_uuids WHERE is_active=1").fetchall()
            return {row['uuid']: row['user_id'] for row in rows}
        
    def get_uuid_to_bot_user_map(self) -> Dict[str, Dict[str, Any]]:
        """
        FIXED: Uses a LEFT JOIN to ensure all active UUIDs are included in the map,
        even if their corresponding user entry is missing from the 'users' table.
        This makes the mapping more robust for debugging purposes.
        """
        query = """
            SELECT uu.uuid, u.user_id, u.first_name, u.username
            FROM user_uuids uu
            LEFT JOIN users u ON uu.user_id = u.user_id
            WHERE uu.is_active = 1
        """
        with self._conn() as c:
            rows = c.execute(query).fetchall()
            return {row['uuid']: dict(row) for row in rows}

db = DatabaseManager()