import sqlite3
import uuid
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import json
import os

# Local SQLite database file stored alongside this module
DB_PATH = os.path.join(os.path.dirname(__file__), "local_database.db")


def slot_key(label: str) -> str:
    """Canonical identity of a physical slot, tolerant of formatting differences.

    "Bed1-slot 7", "Bed1-slot7", "Bed1 slot 7", "bed 1 - slot 7" all map to the
    same key ("bed1slot7"), so a second machine cannot be opened in a slot that
    is already occupied just because the operator typed the label differently.
    Labels without a Bed/slot pattern (legacy / free-form IDs) fall back to a
    case- and separator-insensitive form of the whole label.
    """
    s = label or ''
    bm = re.search(r'bed\s*0*(\d+)', s, re.I)
    sm = re.search(r'slot\s*0*(\d+)', s, re.I)
    if bm and sm:
        return f"bed{int(bm.group(1))}slot{int(sm.group(1))}"
    if bm:
        return f"bed{int(bm.group(1))}"
    return re.sub(r'[^a-z0-9]', '', s.lower())


class LocalDB:
    """Database handler using local SQLite"""

    def __init__(self):
        self.db_path = DB_PATH
        self.init_db()

    def get_connection(self):
        """Get a SQLite database connection with row-as-dict support.

        A generous busy timeout lets a write wait for a transient lock (e.g.
        two overlapping writes, or a dev-server auto-reload where the old and
        new worker briefly coexist) instead of failing immediately with
        "database is locked".
        """
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_db(self):
        """Create tables if they don't exist"""
        conn = self.get_connection()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT,
                password_hash TEXT,
                role TEXT CHECK(role IN ('operator','access_person','admin')) DEFAULT 'operator',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS data_uploads (
                id TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                test_name TEXT NOT NULL,
                description TEXT,
                data TEXT,
                uploaded_at TEXT DEFAULT (datetime('now')),
                file_url TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS testing_sessions (
                id TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                test_name TEXT NOT NULL,
                start_time TEXT DEFAULT (datetime('now')),
                end_time TEXT,
                status TEXT CHECK(status IN ('running','completed','paused','cancelled')) DEFAULT 'running',
                notes TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS upload_config (
                id INTEGER PRIMARY KEY DEFAULT 1,
                interval_minutes INTEGER DEFAULT 240,
                updated_at TEXT DEFAULT (datetime('now')),
                updated_by TEXT REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_uploads_operator ON data_uploads(operator_id);
            CREATE INDEX IF NOT EXISTS idx_uploads_time    ON data_uploads(uploaded_at);
            CREATE INDEX IF NOT EXISTS idx_sessions_operator ON testing_sessions(operator_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_status   ON testing_sessions(status);
            CREATE INDEX IF NOT EXISTS idx_users_role        ON users(role);

            CREATE TABLE IF NOT EXISTS life_tests (
                id TEXT PRIMARY KEY,
                test_label TEXT NOT NULL,
                product TEXT NOT NULL,
                datecode TEXT,
                operator_id TEXT NOT NULL REFERENCES users(id),
                on_minutes REAL DEFAULT 8.0,
                off_minutes REAL DEFAULT 2.0,
                target_hours INTEGER DEFAULT 468,
                status TEXT CHECK(status IN ('running','completed','paused')) DEFAULT 'running',
                notes TEXT,
                completed_at TEXT,
                ecd TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sync_records (
                id TEXT PRIMARY KEY,
                life_test_id TEXT NOT NULL REFERENCES life_tests(id) ON DELETE CASCADE,
                machine_hours REAL NOT NULL,
                estimated_hours REAL,
                difference_minutes REAL DEFAULT 0,
                synced_at TEXT DEFAULT (datetime('now')),
                operator_id TEXT REFERENCES users(id),
                notes TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_syncs_life_test ON sync_records(life_test_id);
            CREATE INDEX IF NOT EXISTS idx_syncs_synced_at ON sync_records(synced_at);

            CREATE TABLE IF NOT EXISTS system_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                is_paused INTEGER NOT NULL DEFAULT 0,
                paused_at TEXT,
                paused_by TEXT REFERENCES users(id),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS system_pause_logs (
                id TEXT PRIMARY KEY,
                operator_id TEXT REFERENCES users(id),
                operator_name TEXT,
                pause_time TEXT NOT NULL,
                resume_time TEXT,
                total_paused_minutes REAL,
                notes TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Per-slot (individual life test) pause/resume audit log.
            -- Independent from system_pause_logs: each life test manages its
            -- own pause state, used for the 132-hour maintenance inspections.
            CREATE TABLE IF NOT EXISTS life_test_pause_logs (
                id TEXT PRIMARY KEY,
                life_test_id TEXT NOT NULL REFERENCES life_tests(id) ON DELETE CASCADE,
                operator_id TEXT REFERENCES users(id),
                operator_name TEXT,
                pause_time TEXT NOT NULL,
                resume_time TEXT,
                total_paused_minutes REAL,
                reason TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_lt_pause_logs_test ON life_test_pause_logs(life_test_id);

            -- Audit trail for every ECD create/edit. The ECD may be created once
            -- and corrected at most once within 7 days; this log records both.
            CREATE TABLE IF NOT EXISTS ecd_audit_logs (
                id TEXT PRIMARY KEY,
                life_test_id TEXT NOT NULL REFERENCES life_tests(id) ON DELETE CASCADE,
                action TEXT NOT NULL,            -- 'create' | 'edit'
                old_ecd TEXT,
                new_ecd TEXT,
                changed_at TEXT NOT NULL,
                operator_id TEXT REFERENCES users(id),
                operator_name TEXT,
                is_one_time_edit INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_ecd_audit_test ON ecd_audit_logs(life_test_id);
        """)
        conn.commit()
        conn.close()

        # Migrate existing databases: add new columns if absent
        conn2 = self.get_connection()
        for col in ('completed_at', 'ecd', 'paused_at',
                    'ecd_original', 'ecd_created_at', 'ecd_created_by', 'datecode'):
            try:
                conn2.execute(f"ALTER TABLE life_tests ADD COLUMN {col} TEXT")
                conn2.commit()
            except Exception:
                pass  # column already exists
        try:
            conn2.execute("ALTER TABLE life_tests ADD COLUMN ecd_edited INTEGER DEFAULT 0")
            conn2.commit()
        except Exception:
            pass  # column already exists
        conn2.close()

        # Migrate legacy databases: drop the UNIQUE constraint on test_label.
        # A slot name (e.g. "Bed1-slot 7") must be reusable — once the machine in
        # that slot finishes testing, the next machine takes the same slot. Slots
        # are distinguished by product + datecode, not by a globally unique label.
        # SQLite can't drop a column constraint in place, so rebuild the table
        # (preserving every column and row) only if the old UNIQUE index is present.
        conn3 = self.get_connection()
        try:
            row = conn3.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='life_tests'"
            ).fetchone()
            if row and row["sql"] and "UNIQUE" in row["sql"].upper():
                cols = [r[1] for r in conn3.execute("PRAGMA table_info(life_tests)").fetchall()]
                collist = ", ".join(cols)
                new_sql = row["sql"].replace("life_tests", "life_tests_new", 1)
                new_sql = new_sql.replace("test_label TEXT UNIQUE NOT NULL",
                                          "test_label TEXT NOT NULL")
                conn3.execute("PRAGMA foreign_keys=OFF")
                conn3.executescript(
                    "BEGIN;\n"
                    f"{new_sql};\n"
                    f"INSERT INTO life_tests_new ({collist}) SELECT {collist} FROM life_tests;\n"
                    "DROP TABLE life_tests;\n"
                    "ALTER TABLE life_tests_new RENAME TO life_tests;\n"
                    "COMMIT;"
                )
                conn3.execute("PRAGMA foreign_keys=ON")
        except Exception as e:
            print(f"test_label UNIQUE migration skipped: {e}")
        finally:
            conn3.close()
    
    # ==================== User Methods ====================

    def create_user(self, email: str, full_name: str, password: str, role: str) -> dict:
        """Create a new user with hashed password"""
        try:
            from security import hash_password
            password_hash = hash_password(password)
            user_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat() + 'Z'

            conn = self.get_connection()
            conn.execute(
                "INSERT INTO users (id, email, full_name, password_hash, role, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, email, full_name, password_hash, role, now, now)
            )
            conn.commit()
            conn.close()

            return {
                "success": True,
                "user": {
                    "id": user_id,
                    "email": email,
                    "full_name": full_name,
                    "role": role,
                    "created_at": now
                }
            }
        except sqlite3.IntegrityError:
            return {"success": False, "error": "Email already exists"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Get user by email"""
        try:
            conn = self.get_connection()
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """Get user by ID"""
        try:
            conn = self.get_connection()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None

    def update_password_hash(self, user_id: str, password_hash: str) -> bool:
        """Update a user's stored password hash (used to upgrade legacy hashes)"""
        conn = None
        try:
            now = datetime.utcnow().isoformat() + 'Z'
            conn = self.get_connection()
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (password_hash, now, user_id)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating password hash: {e}")
            return False
        finally:
            if conn is not None:
                conn.close()

    # ── Admin user management ──

    def list_users(self) -> List[dict]:
        """Return all users (without password hashes), newest first."""
        conn = None
        try:
            conn = self.get_connection()
            rows = conn.execute(
                "SELECT id, email, full_name, role, created_at FROM users "
                "ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"Error listing users: {e}")
            return []
        finally:
            if conn is not None:
                conn.close()

    def count_admins(self) -> int:
        """Number of admin accounts (used to prevent removing the last admin)."""
        conn = None
        try:
            conn = self.get_connection()
            return conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin'"
            ).fetchone()[0]
        except Exception as e:
            print(f"Error counting admins: {e}")
            return 0
        finally:
            if conn is not None:
                conn.close()

    def set_user_role(self, user_id: str, role: str) -> dict:
        """Change a user's role. Refuses to demote the last remaining admin."""
        conn = None
        try:
            conn = self.get_connection()
            row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                return {"success": False, "error": "User not found"}
            if row["role"] == "admin" and role != "admin" and self.count_admins() <= 1:
                return {"success": False, "error": "Cannot demote the last remaining admin."}
            now = datetime.utcnow().isoformat() + 'Z'
            conn.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
                (role, now, user_id)
            )
            conn.commit()
            return {"success": True, "id": user_id, "role": role}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    # Tables whose reference to a user must BLOCK deletion (substantive ownership).
    _USER_OWNED_BLOCKING = [("life_tests", "operator_id"),
                            ("data_uploads", "operator_id"),
                            ("testing_sessions", "operator_id")]
    # Nullable references to a user in history/audit logs — detached (SET NULL)
    # on delete so the log rows survive (anonymised) instead of blocking or being lost.
    _USER_REF_DETACH = [("sync_records", "operator_id"),
                        ("system_pause_logs", "operator_id"),
                        ("life_test_pause_logs", "operator_id"),
                        ("ecd_audit_logs", "operator_id"),
                        ("upload_config", "updated_by"),
                        ("system_state", "paused_by")]

    def delete_user(self, user_id: str) -> dict:
        """Delete a user. Refuses to delete the last admin or an account that
        owns substantive data (life tests / uploads / testing sessions). Incidental
        audit-log references are detached so historical logs are preserved."""
        conn = None
        try:
            conn = self.get_connection()
            row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                return {"success": False, "error": "User not found"}
            if row["role"] == "admin" and self.count_admins() <= 1:
                return {"success": False, "error": "Cannot delete the last remaining admin."}

            # Block if the account owns real work — deleting it would orphan or
            # cascade-destroy that data. Change the role to Observer instead.
            for table, col in self._USER_OWNED_BLOCKING:
                try:
                    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (user_id,)).fetchone()[0]
                except Exception:
                    n = 0  # table may not exist on older DBs
                if n:
                    return {"success": False,
                            "error": "This account owns life tests / uploads and cannot be deleted. "
                                     "Change its role to Observer instead."}

            # Detach incidental log/audit references (nullable FKs) so the delete
            # doesn't fail on them and the history rows are kept without attribution.
            for table, col in self._USER_REF_DETACH:
                try:
                    conn.execute(f"UPDATE {table} SET {col} = NULL WHERE {col} = ?", (user_id,))
                except Exception:
                    pass

            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            return {"success": True}
        except sqlite3.IntegrityError:
            return {"success": False,
                    "error": "This account is still linked to records and cannot be deleted. "
                             "Change its role to Observer instead."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    # ==================== Data Upload Methods ====================

    def upload_data(self, operator_id: str, test_name: str, description: str, data: dict) -> dict:
        """Upload test data"""
        try:
            upload_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat() + 'Z'

            conn = self.get_connection()
            conn.execute(
                "INSERT INTO data_uploads (id, operator_id, test_name, description, data, uploaded_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (upload_id, operator_id, test_name, description, json.dumps(data), now, now)
            )
            conn.commit()
            conn.close()

            return {
                "success": True,
                "upload": {
                    "id": upload_id,
                    "operator_id": operator_id,
                    "test_name": test_name,
                    "description": description,
                    "data": data,
                    "uploaded_at": now
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_uploads_by_operator(self, operator_id: str, limit: int = 50) -> List[dict]:
        """Get uploads by operator"""
        try:
            conn = self.get_connection()
            rows = conn.execute(
                "SELECT * FROM data_uploads WHERE operator_id = ? ORDER BY uploaded_at DESC LIMIT ?",
                (operator_id, limit)
            ).fetchall()
            conn.close()
            result = []
            for r in rows:
                row = dict(r)
                if row.get("data"):
                    row["data"] = json.loads(row["data"])
                result.append(row)
            return result
        except Exception as e:
            print(f"Error fetching uploads: {e}")
            return []

    def get_all_uploads(self, limit: int = 100) -> List[dict]:
        """Get all uploads"""
        try:
            conn = self.get_connection()
            rows = conn.execute(
                "SELECT * FROM data_uploads ORDER BY uploaded_at DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
            result = []
            for r in rows:
                row = dict(r)
                if row.get("data"):
                    row["data"] = json.loads(row["data"])
                result.append(row)
            return result
        except Exception as e:
            print(f"Error fetching uploads: {e}")
            return []

    def get_last_upload_time(self) -> Optional[datetime]:
        """Get the time of the last upload"""
        try:
            conn = self.get_connection()
            row = conn.execute(
                "SELECT uploaded_at FROM data_uploads ORDER BY uploaded_at DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row:
                return datetime.fromisoformat(row[0].rstrip("Z"))
            return None
        except Exception as e:
            print(f"Error fetching last upload: {e}")
            return None

    # ==================== Upload Interval Configuration ====================

    def get_upload_interval(self) -> int:
        """Get current upload interval in minutes"""
        try:
            conn = self.get_connection()
            row = conn.execute("SELECT interval_minutes FROM upload_config WHERE id = 1").fetchone()
            conn.close()
            return row[0] if row else 240
        except Exception as e:
            print(f"Error fetching upload interval: {e}")
            return 240

    def set_upload_interval(self, interval_minutes: int, updated_by: str) -> dict:
        """Set upload interval"""
        try:
            now = datetime.utcnow().isoformat() + 'Z'
            conn = self.get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO upload_config (id, interval_minutes, updated_at, updated_by) "
                "VALUES (1, ?, ?, ?)",
                (interval_minutes, now, updated_by)
            )
            conn.commit()
            conn.close()
            return {
                "success": True,
                "config": {
                    "id": 1,
                    "interval_minutes": interval_minutes,
                    "updated_at": now,
                    "updated_by": updated_by
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== Testing Time Methods ====================

    def create_testing_session(self, operator_id: str, test_name: str, notes: str = None) -> dict:
        """Create a new testing session"""
        try:
            session_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat() + 'Z'

            conn = self.get_connection()
            conn.execute(
                "INSERT INTO testing_sessions "
                "(id, operator_id, test_name, start_time, status, notes, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'running', ?, ?, ?)",
                (session_id, operator_id, test_name, now, notes, now, now)
            )
            conn.commit()
            conn.close()

            return {
                "success": True,
                "session": {
                    "id": session_id,
                    "operator_id": operator_id,
                    "test_name": test_name,
                    "start_time": now,
                    "end_time": None,
                    "status": "running",
                    "notes": notes
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def end_testing_session(self, session_id: str) -> dict:
        """End a testing session"""
        try:
            now = datetime.utcnow().isoformat() + 'Z'
            conn = self.get_connection()
            conn.execute(
                "UPDATE testing_sessions SET end_time = ?, status = 'completed', updated_at = ? WHERE id = ?",
                (now, now, session_id)
            )
            conn.commit()
            row = conn.execute("SELECT * FROM testing_sessions WHERE id = ?", (session_id,)).fetchone()
            conn.close()

            if row:
                r = dict(row)
                return {
                    "success": True,
                    "session": {
                        "id": r["id"],
                        "operator_id": r["operator_id"],
                        "test_name": r["test_name"],
                        "start_time": r["start_time"],
                        "end_time": r["end_time"],
                        "status": r["status"],
                        "notes": r["notes"]
                    }
                }
            return {"success": False, "error": "Failed to end session"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_active_tests(self) -> List[dict]:
        """Get all active testing sessions"""
        try:
            conn = self.get_connection()
            rows = conn.execute(
                """
                SELECT ts.id, ts.operator_id, ts.test_name, ts.start_time, ts.end_time,
                       ts.status, ts.notes, u.full_name as operator_name
                FROM testing_sessions ts
                LEFT JOIN users u ON ts.operator_id = u.id
                WHERE ts.status = 'running'
                ORDER BY ts.start_time DESC
                """
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"Error fetching active tests: {e}")
            return []

    def get_testing_history(self, operator_id: str = None, limit: int = 50) -> List[dict]:
        """Get testing session history"""
        try:
            conn = self.get_connection()
            if operator_id:
                rows = conn.execute(
                    """
                    SELECT ts.id, ts.operator_id, ts.test_name, ts.start_time, ts.end_time,
                           ts.status, ts.notes, u.full_name as operator_name
                    FROM testing_sessions ts
                    LEFT JOIN users u ON ts.operator_id = u.id
                    WHERE ts.operator_id = ?
                    ORDER BY ts.start_time DESC LIMIT ?
                    """,
                    (operator_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT ts.id, ts.operator_id, ts.test_name, ts.start_time, ts.end_time,
                           ts.status, ts.notes, u.full_name as operator_name
                    FROM testing_sessions ts
                    LEFT JOIN users u ON ts.operator_id = u.id
                    ORDER BY ts.start_time DESC LIMIT ?
                    """,
                    (limit,)
                ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"Error fetching testing history: {e}")
            return []

    def get_dashboard_stats(self) -> dict:
        """Get dashboard statistics"""
        try:
            conn = self.get_connection()
            total_uploads   = conn.execute("SELECT COUNT(*) FROM data_uploads").fetchone()[0]
            total_sessions  = conn.execute("SELECT COUNT(*) FROM testing_sessions").fetchone()[0]
            active_count    = conn.execute("SELECT COUNT(*) FROM testing_sessions WHERE status='running'").fetchone()[0]
            completed_count = conn.execute("SELECT COUNT(*) FROM testing_sessions WHERE status='completed'").fetchone()[0]
            operators_count = conn.execute("SELECT COUNT(*) FROM users WHERE role='operator'").fetchone()[0]
            last_row = conn.execute(
                "SELECT uploaded_at FROM data_uploads ORDER BY uploaded_at DESC LIMIT 1"
            ).fetchone()
            conn.close()

            last_upload = datetime.fromisoformat(last_row[0].rstrip("Z")) if last_row else None
            interval = self.get_upload_interval()
            next_upload = last_upload + timedelta(minutes=interval) if last_upload else None

            return {
                "total_uploads": total_uploads,
                "total_testing_sessions": total_sessions,
                "active_tests": active_count,
                "completed_tests": completed_count,
                "last_upload": last_upload,
                "next_scheduled_upload": next_upload,
                "current_interval_minutes": interval,
                "operators_count": operators_count
            }
        except Exception as e:
            print(f"Error fetching dashboard stats: {e}")
            return {
                "total_uploads": 0,
                "total_testing_sessions": 0,
                "active_tests": 0,
                "completed_tests": 0,
                "last_upload": None,
                "next_scheduled_upload": None,
                "current_interval_minutes": 240,
                "operators_count": 0
            }

    # ==================== ON Hour Calculation Methods ====================

    def calculate_on_hours_from_data(self, data: dict, pattern_key: str = "ul_8min_2min") -> dict:
        """Calculate ON hours from time series data"""
        try:
            from cycle_calculator import TimeSeriesAnalyzer

            data_points = data.get("data_points", []) or data.get("time_series", [])
            if not data_points:
                return {"on_hours": 0.0, "cycle_count": 0, "error": "No time series data found"}

            analyzer = TimeSeriesAnalyzer(pattern_key)
            on_hours, cycle_count = analyzer.analyze_states(data_points)
            return {
                "on_hours": on_hours,
                "cycle_count": cycle_count,
                "pattern": analyzer.get_cycle_info()
            }
        except Exception as e:
            print(f"Error calculating ON hours: {e}")
            return {"on_hours": 0.0, "cycle_count": 0, "error": str(e)}

    def get_cumulative_on_hours(self, operator_id: str = None) -> float:
        """Get cumulative ON hours for an operator or all operators"""
        try:
            conn = self.get_connection()
            if operator_id:
                rows = conn.execute(
                    "SELECT data FROM data_uploads WHERE operator_id = ? AND data IS NOT NULL",
                    (operator_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT data FROM data_uploads WHERE data IS NOT NULL"
                ).fetchall()
            conn.close()

            total = 0.0
            for row in rows:
                try:
                    d = json.loads(row[0])
                    total += float(d.get("on_hours", 0) or 0)
                except Exception:
                    pass
            return round(total, 2)
        except Exception as e:
            print(f"Error fetching cumulative ON hours: {e}")
            return 0.0

    def get_on_hours_progress(self, operator_id: str = None, target_on_hours: int = 468) -> dict:
        """Get ON hours progress toward target"""
        try:
            cumulative_on_hours = self.get_cumulative_on_hours(operator_id)
            progress_percent = min(
                (cumulative_on_hours / target_on_hours * 100) if target_on_hours > 0 else 0, 100.0
            )
            return {
                "cumulative_on_hours": cumulative_on_hours,
                "target_on_hours": target_on_hours,
                "progress_percent": round(progress_percent, 2),
                "remaining_hours": round(max(0, target_on_hours - cumulative_on_hours), 2),
                "is_complete": cumulative_on_hours >= target_on_hours
            }
        except Exception as e:
            print(f"Error calculating progress: {e}")
            return {
                "cumulative_on_hours": 0.0,
                "target_on_hours": target_on_hours,
                "progress_percent": 0.0,
                "remaining_hours": target_on_hours,
                "is_complete": False
            }


    # ==================== Life Test Methods ====================

    def create_life_test(self, test_label: str, product: str, operator_id: str,
                         on_minutes: float, off_minutes: float, target_hours: int,
                         initial_machine_hours: float, notes: str = None,
                         datecode: str = None) -> dict:
        """Create a new life test with its first sync (initial machine reading)"""
        conn = None
        try:
            lt_id = str(uuid.uuid4())
            sync_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat() + 'Z'
            conn = self.get_connection()
            # A slot may be reused across machines, but only one test may be ACTIVE
            # (running or paused) in a physical slot at a time. Match by the CANONICAL
            # slot identity — so "Bed1-slot 7" and "Bed1-slot7" count as the same
            # position — not by the raw label string. Completed tests free the slot.
            new_key = slot_key(test_label)
            for row in conn.execute(
                "SELECT test_label FROM life_tests WHERE status IN ('running','paused')"
            ).fetchall():
                if slot_key(row["test_label"]) == new_key:
                    return {"success": False,
                            "error": f"This slot is already occupied by an ongoing test "
                                     f"('{row['test_label']}'). It's the same position as "
                                     f"'{test_label}' regardless of spacing/formatting. "
                                     f"Complete or delete it before starting a new one here."}
            conn.execute(
                "INSERT INTO life_tests (id, test_label, product, datecode, operator_id, on_minutes, off_minutes, "
                "target_hours, status, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,'running',?,?,?)",
                (lt_id, test_label, product, datecode, operator_id, on_minutes, off_minutes, target_hours, notes, now, now)
            )
            conn.execute(
                "INSERT INTO sync_records (id, life_test_id, machine_hours, estimated_hours, "
                "difference_minutes, synced_at, operator_id, notes) VALUES (?,?,?,?,0,?,?,?)",
                (sync_id, lt_id, initial_machine_hours, initial_machine_hours, now, operator_id, "Initial reading")
            )
            conn.commit()
            return {"success": True, "id": lt_id, "test_label": test_label}
        except sqlite3.IntegrityError as e:
            return {"success": False, "error": f"Could not create test: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    def _attach_last_sync(self, conn, test: dict) -> dict:
        """Helper: attach last sync record to a test dict"""
        row = conn.execute(
            "SELECT s.*, u.full_name as operator_name FROM sync_records s "
            "LEFT JOIN users u ON s.operator_id = u.id "
            "WHERE s.life_test_id = ? ORDER BY s.synced_at DESC LIMIT 1",
            (test["id"],)
        ).fetchone()
        test["last_sync"] = dict(row) if row else None
        return test

    def get_life_tests(self, status: str = None) -> List[dict]:
        """List all life tests with their last sync"""
        try:
            conn = self.get_connection()
            if status:
                rows = conn.execute(
                    "SELECT lt.*, u.full_name as operator_name FROM life_tests lt "
                    "LEFT JOIN users u ON lt.operator_id = u.id WHERE lt.status = ? "
                    "ORDER BY lt.created_at DESC",
                    (status,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT lt.*, u.full_name as operator_name FROM life_tests lt "
                    "LEFT JOIN users u ON lt.operator_id = u.id ORDER BY lt.created_at DESC"
                ).fetchall()
            tests = [self._attach_last_sync(conn, dict(r)) for r in rows]
            conn.close()
            return tests
        except Exception as e:
            print(f"Error getting life tests: {e}")
            return []

    def get_life_test(self, lt_id: str) -> Optional[dict]:
        """Get a single life test with its last sync"""
        try:
            conn = self.get_connection()
            row = conn.execute(
                "SELECT lt.*, u.full_name as operator_name FROM life_tests lt "
                "LEFT JOIN users u ON lt.operator_id = u.id WHERE lt.id = ?",
                (lt_id,)
            ).fetchone()
            if not row:
                conn.close()
                return None
            test = self._attach_last_sync(conn, dict(row))
            conn.close()
            return test
        except Exception as e:
            print(f"Error getting life test: {e}")
            return None

    def add_sync_record(self, life_test_id: str, machine_hours: float,
                        estimated_hours: float, difference_minutes: float,
                        operator_id: str, notes: str = None) -> dict:
        """Record an operator sync"""
        conn = None
        try:
            sync_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat() + 'Z'
            conn = self.get_connection()
            conn.execute(
                "INSERT INTO sync_records (id, life_test_id, machine_hours, estimated_hours, "
                "difference_minutes, synced_at, operator_id, notes) VALUES (?,?,?,?,?,?,?,?)",
                (sync_id, life_test_id, machine_hours, estimated_hours, difference_minutes, now, operator_id, notes)
            )
            conn.execute("UPDATE life_tests SET updated_at = ? WHERE id = ?", (now, life_test_id))
            conn.commit()
            return {"success": True, "id": sync_id, "synced_at": now}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    def get_sync_records(self, life_test_id: str) -> List[dict]:
        """Get all sync records for a life test (oldest first)"""
        try:
            conn = self.get_connection()
            rows = conn.execute(
                "SELECT s.*, u.full_name as operator_name FROM sync_records s "
                "LEFT JOIN users u ON s.operator_id = u.id "
                "WHERE s.life_test_id = ? ORDER BY s.synced_at ASC",
                (life_test_id,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"Error getting sync records: {e}")
            return []

    def complete_life_test(self, lt_id: str) -> dict:
        """Mark a life test as completed and record the completion timestamp.

        If the test is completed while still paused, close its open pause log so
        its accumulated paused time stops growing forever (an open pause row is
        otherwise treated as still in-progress by the paused-time calculations).
        """
        conn = None
        try:
            now = datetime.utcnow().isoformat() + 'Z'
            now_dt = datetime.fromisoformat(now.rstrip('Z'))
            conn = self.get_connection()
            open_pause = conn.execute(
                "SELECT id, pause_time FROM life_test_pause_logs "
                "WHERE life_test_id = ? AND resume_time IS NULL ORDER BY pause_time DESC LIMIT 1",
                (lt_id,)
            ).fetchone()
            if open_pause:
                start = datetime.fromisoformat(open_pause["pause_time"].rstrip('Z'))
                mins = max(0.0, (now_dt - start).total_seconds() / 60.0)
                conn.execute(
                    "UPDATE life_test_pause_logs SET resume_time = ?, total_paused_minutes = ? WHERE id = ?",
                    (now, round(mins, 4), open_pause["id"])
                )
            conn.execute(
                "UPDATE life_tests SET status = 'completed', completed_at = ?, updated_at = ?, "
                "paused_at = NULL WHERE id = ?",
                (now, now, lt_id)
            )
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    # Number of days the initial ECD stays editable (one correction only).
    ECD_EDIT_WINDOW_DAYS = 7
    ECD_LOCK_MESSAGE = ("The ECD can only be modified once within 7 days "
                        "of its initial creation.")

    def set_ecd(self, lt_id: str, ecd_date: str,
                operator_id: str = None, operator_name: str = None) -> dict:
        """Create or edit a life test's Estimated Completion Date, enforcing the
        business rule server-side:

          * First non-empty set = initial creation (records original value,
            timestamp and author).
          * Exactly one edit is allowed, and only within 7 days of creation.
          * After that edit, or once 7 days elapse, the ECD is permanently locked.

        Every create/edit is written to ecd_audit_logs.
        """
        conn = None
        try:
            ecd_date = (ecd_date or "").strip()
            # Validate the format up front so a stray value (e.g. an ISO datetime
            # or "08/12/2026") can never be stored — advance_running_ecds parses
            # ECDs as strict YYYY-MM-DD and would otherwise silently skip them.
            if ecd_date:
                try:
                    datetime.strptime(ecd_date, "%Y-%m-%d")
                except ValueError:
                    return {"success": False, "error": "ECD must be a valid date in YYYY-MM-DD format."}
            conn = self.get_connection()
            row = conn.execute(
                "SELECT ecd, ecd_created_at, ecd_edited FROM life_tests WHERE id = ?",
                (lt_id,)
            ).fetchone()
            if not row:
                conn.close()
                return {"success": False, "error": "Life test not found"}
            row = dict(row)

            now = datetime.utcnow().isoformat() + 'Z'
            now_dt = datetime.fromisoformat(now.rstrip('Z'))
            created_at = row.get("ecd_created_at")
            edited = bool(row.get("ecd_edited"))
            current_ecd = row.get("ecd") or ""

            # ── Initial creation ──
            if not created_at:
                if not ecd_date:
                    conn.close()
                    return {"success": True, "ecd": "", "action": "none"}  # nothing to create
                audit_id = str(uuid.uuid4())
                conn.execute(
                    "UPDATE life_tests SET ecd = ?, ecd_original = ?, ecd_created_at = ?, "
                    "ecd_created_by = ?, ecd_edited = 0, updated_at = ? WHERE id = ?",
                    (ecd_date, ecd_date, now, operator_id, now, lt_id)
                )
                conn.execute(
                    "INSERT INTO ecd_audit_logs (id, life_test_id, action, old_ecd, new_ecd, "
                    "changed_at, operator_id, operator_name, is_one_time_edit, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (audit_id, lt_id, 'create', None, ecd_date, now, operator_id, operator_name, 0, now)
                )
                conn.commit()
                conn.close()
                return {"success": True, "ecd": ecd_date, "action": "create"}

            # ── Already created: only a single edit within the window is allowed ──
            created_dt = datetime.fromisoformat(created_at.rstrip('Z'))
            window_end = created_dt + timedelta(days=self.ECD_EDIT_WINDOW_DAYS)
            locked = edited or (now_dt > window_end)
            if locked:
                conn.close()
                return {"success": False, "error": self.ECD_LOCK_MESSAGE, "locked": True}

            if not ecd_date:
                conn.close()
                return {"success": False, "error": "ECD cannot be cleared once it has been set."}

            if ecd_date == current_ecd:
                conn.close()
                return {"success": True, "ecd": current_ecd, "action": "none"}  # no change, edit not consumed

            audit_id = str(uuid.uuid4())
            conn.execute(
                "UPDATE life_tests SET ecd = ?, ecd_edited = 1, updated_at = ? WHERE id = ?",
                (ecd_date, now, lt_id)
            )
            conn.execute(
                "INSERT INTO ecd_audit_logs (id, life_test_id, action, old_ecd, new_ecd, "
                "changed_at, operator_id, operator_name, is_one_time_edit, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (audit_id, lt_id, 'edit', current_ecd, ecd_date, now, operator_id, operator_name, 1, now)
            )
            conn.commit()
            conn.close()
            return {"success": True, "ecd": ecd_date, "action": "edit"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    def get_ecd_audit_logs(self, lt_id: str) -> List[dict]:
        """Return the ECD change history for a life test (newest first)."""
        try:
            conn = self.get_connection()
            rows = conn.execute(
                "SELECT * FROM ecd_audit_logs WHERE life_test_id = ? ORDER BY changed_at DESC",
                (lt_id,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"Error fetching ECD audit logs: {e}")
            return []

    def advance_running_ecds(self, days: int) -> int:
        """Push the ECD of every running test forward by `days` calendar days.

        Used on system resume so completion dates account for paused (non-working)
        days. Only tests that already have an ECD set are affected. Returns the
        number of tests updated.
        """
        if not days or days <= 0:
            return 0
        conn = None
        try:
            now = datetime.utcnow().isoformat() + 'Z'
            conn = self.get_connection()
            rows = conn.execute(
                "SELECT id, ecd FROM life_tests "
                "WHERE status = 'running' AND ecd IS NOT NULL AND ecd != ''"
            ).fetchall()
            count = 0
            for r in rows:
                try:
                    new_ecd = (datetime.strptime(r["ecd"], "%Y-%m-%d")
                               + timedelta(days=days)).strftime("%Y-%m-%d")
                    conn.execute(
                        "UPDATE life_tests SET ecd = ?, updated_at = ? WHERE id = ?",
                        (new_ecd, now, r["id"])
                    )
                    count += 1
                except Exception:
                    pass  # skip malformed ECD values
            conn.commit()
            conn.close()
            return count
        except Exception as e:
            print(f"Error advancing ECDs: {e}")
            return 0
        finally:
            if conn is not None:
                conn.close()

    def delete_life_test(self, lt_id: str) -> dict:
        """Delete a completed life test and all its associated data"""
        conn = None
        try:
            conn = self.get_connection()
            conn.execute("DELETE FROM sync_records WHERE life_test_id = ?", (lt_id,))
            conn.execute("DELETE FROM life_tests WHERE id = ?", (lt_id,))
            conn.commit()
            conn.close()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    def get_sync_quality_report(self) -> List[dict]:
        """Sync quality per life test (excludes the initial sync with diff=0)"""
        try:
            conn = self.get_connection()
            rows = conn.execute(
                """
                SELECT lt.id, lt.test_label, lt.product, lt.status,
                       COUNT(s.id) as total_syncs,
                       ROUND(AVG(ABS(s.difference_minutes)), 2) as avg_diff_minutes,
                       ROUND(MAX(ABS(s.difference_minutes)), 2) as max_diff_minutes
                FROM life_tests lt
                LEFT JOIN sync_records s ON lt.id = s.life_test_id AND s.difference_minutes != 0
                GROUP BY lt.id, lt.test_label, lt.product, lt.status
                ORDER BY lt.created_at DESC
                """
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"Error getting sync quality: {e}")
            return []


    # ==================== System Pause Methods ====================

    def get_system_state(self) -> dict:
        """Get current system pause state"""
        try:
            conn = self.get_connection()
            row = conn.execute("SELECT * FROM system_state WHERE id = 1").fetchone()
            active = conn.execute(
                "SELECT * FROM system_pause_logs WHERE resume_time IS NULL ORDER BY pause_time DESC LIMIT 1"
            ).fetchone()
            total_row = conn.execute(
                "SELECT COALESCE(SUM(total_paused_minutes), 0) FROM system_pause_logs WHERE total_paused_minutes IS NOT NULL"
            ).fetchone()
            conn.close()

            is_paused = bool(row["is_paused"]) if row else False
            paused_at = row["paused_at"] if row else None
            paused_by = row["paused_by"] if row else None
            total_minutes = float(total_row[0]) if total_row else 0.0

            if is_paused and paused_at:
                pause_start = datetime.fromisoformat(paused_at.rstrip('Z'))
                total_minutes += (datetime.utcnow() - pause_start).total_seconds() / 60.0

            return {
                "is_paused": is_paused,
                "paused_at": paused_at,
                "paused_by": paused_by,
                "active_pause_id": dict(active)["id"] if active else None,
                "total_paused_minutes_ever": round(total_minutes, 2)
            }
        except Exception as e:
            print(f"Error getting system state: {e}")
            return {"is_paused": False, "paused_at": None, "paused_by": None,
                    "active_pause_id": None, "total_paused_minutes_ever": 0.0}

    def pause_system(self, operator_id: str, operator_name: str, notes: str = None) -> dict:
        """Pause all system timers"""
        conn = None
        try:
            state = self.get_system_state()
            if state["is_paused"]:
                return {"success": False, "error": "System is already paused"}
            now = datetime.utcnow().isoformat() + 'Z'
            log_id = str(uuid.uuid4())
            conn = self.get_connection()
            conn.execute(
                "INSERT INTO system_pause_logs (id, operator_id, operator_name, pause_time, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (log_id, operator_id, operator_name, now, notes, now)
            )
            conn.execute(
                "INSERT OR REPLACE INTO system_state (id, is_paused, paused_at, paused_by, updated_at) "
                "VALUES (1, 1, ?, ?, ?)",
                (now, operator_id, now)
            )
            conn.commit()
            conn.close()
            return {"success": True, "paused_at": now, "pause_id": log_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    def resume_system(self, operator_id: str, operator_name: str, notes: str = None) -> dict:
        """Resume all system timers"""
        conn = None
        try:
            state = self.get_system_state()
            if not state["is_paused"]:
                return {"success": False, "error": "System is not paused"}
            now = datetime.utcnow().isoformat() + 'Z'
            now_dt = datetime.fromisoformat(now.rstrip('Z'))
            conn = self.get_connection()
            active = conn.execute(
                "SELECT * FROM system_pause_logs WHERE resume_time IS NULL ORDER BY pause_time DESC LIMIT 1"
            ).fetchone()
            duration_minutes = 0.0
            if active:
                pause_start = datetime.fromisoformat(dict(active)["pause_time"].rstrip('Z'))
                duration_minutes = (now_dt - pause_start).total_seconds() / 60.0
                conn.execute(
                    "UPDATE system_pause_logs SET resume_time = ?, total_paused_minutes = ? WHERE id = ?",
                    (now, round(duration_minutes, 4), dict(active)["id"])
                )
            conn.execute(
                "INSERT OR REPLACE INTO system_state (id, is_paused, paused_at, paused_by, updated_at) "
                "VALUES (1, 0, NULL, NULL, ?)",
                (now,)
            )
            conn.commit()
            conn.close()
            return {"success": True, "resumed_at": now, "total_paused_minutes": round(duration_minutes, 4)}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    def get_pause_logs(self, limit: int = 100) -> List[dict]:
        """Get all pause/resume log entries newest first"""
        try:
            conn = self.get_connection()
            rows = conn.execute(
                "SELECT * FROM system_pause_logs ORDER BY pause_time DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"Error fetching pause logs: {e}")
            return []

    def get_paused_seconds_between(self, since_iso: str, until_iso: str) -> float:
        """
        Return total seconds the system was paused within the [since_iso, until_iso] window.
        Only counts completed pause intervals (resume_time IS NOT NULL) within this window.
        """
        try:
            since_dt = datetime.fromisoformat(since_iso.rstrip('Z'))
            until_dt = datetime.fromisoformat(until_iso.rstrip('Z'))
            if until_dt <= since_dt:
                return 0.0
            conn = self.get_connection()
            rows = conn.execute(
                """
                SELECT pause_time, resume_time
                FROM system_pause_logs
                WHERE resume_time IS NOT NULL
                  AND pause_time < ?
                  AND resume_time > ?
                """,
                (until_iso, since_iso)
            ).fetchall()
            conn.close()
            total = 0.0
            for row in rows:
                p_start = datetime.fromisoformat(row[0].rstrip('Z'))
                p_end   = datetime.fromisoformat(row[1].rstrip('Z'))
                eff_start = max(p_start, since_dt)
                eff_end   = min(p_end,   until_dt)
                if eff_end > eff_start:
                    total += (eff_end - eff_start).total_seconds()
            return total
        except Exception as e:
            print(f"Error computing paused seconds: {e}")
            return 0.0

    # ==================== Per-Slot (Life Test) Pause Methods ====================

    def pause_life_test(self, lt_id: str, operator_id: str, operator_name: str,
                        reason: str) -> dict:
        """Pause a single life test (slot). A non-empty reason is mandatory."""
        reason = (reason or "").strip()
        if not reason:
            return {"success": False, "error": "A pause reason is required"}
        conn = None
        try:
            conn = self.get_connection()
            row = conn.execute("SELECT status FROM life_tests WHERE id = ?", (lt_id,)).fetchone()
            if not row:
                conn.close()
                return {"success": False, "error": "Life test not found"}
            if row["status"] != "running":
                conn.close()
                return {"success": False, "error": "Only running tests can be paused"}

            now = datetime.utcnow().isoformat() + 'Z'
            log_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO life_test_pause_logs "
                "(id, life_test_id, operator_id, operator_name, pause_time, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (log_id, lt_id, operator_id, operator_name, now, reason, now)
            )
            conn.execute(
                "UPDATE life_tests SET status = 'paused', paused_at = ?, updated_at = ? WHERE id = ?",
                (now, now, lt_id)
            )
            conn.commit()
            conn.close()
            return {"success": True, "paused_at": now, "pause_id": log_id, "reason": reason}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    def resume_life_test(self, lt_id: str, operator_id: str, operator_name: str) -> dict:
        """Resume a paused life test (slot), closing the open pause log and
        accumulating its duration. The test timer continues from where it stopped."""
        conn = None
        try:
            conn = self.get_connection()
            row = conn.execute("SELECT status, paused_at FROM life_tests WHERE id = ?", (lt_id,)).fetchone()
            if not row:
                conn.close()
                return {"success": False, "error": "Life test not found"}
            if row["status"] != "paused":
                conn.close()
                return {"success": False, "error": "Test is not paused"}

            now = datetime.utcnow().isoformat() + 'Z'
            now_dt = datetime.fromisoformat(now.rstrip('Z'))
            active = conn.execute(
                "SELECT * FROM life_test_pause_logs "
                "WHERE life_test_id = ? AND resume_time IS NULL ORDER BY pause_time DESC LIMIT 1",
                (lt_id,)
            ).fetchone()
            duration_minutes = 0.0
            if active:
                pause_start = datetime.fromisoformat(dict(active)["pause_time"].rstrip('Z'))
                duration_minutes = (now_dt - pause_start).total_seconds() / 60.0
                conn.execute(
                    "UPDATE life_test_pause_logs SET resume_time = ?, total_paused_minutes = ? WHERE id = ?",
                    (now, round(duration_minutes, 4), dict(active)["id"])
                )
            conn.execute(
                "UPDATE life_tests SET status = 'running', paused_at = NULL, updated_at = ? WHERE id = ?",
                (now, lt_id)
            )
            conn.commit()
            conn.close()
            return {"success": True, "resumed_at": now, "total_paused_minutes": round(duration_minutes, 4)}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if conn is not None:
                conn.close()

    def get_test_pause_logs(self, lt_id: str, limit: int = 100) -> List[dict]:
        """Get the pause/resume history for a single life test (newest first)."""
        try:
            conn = self.get_connection()
            rows = conn.execute(
                "SELECT p.*, u.full_name as user_full_name FROM life_test_pause_logs p "
                "LEFT JOIN users u ON p.operator_id = u.id "
                "WHERE p.life_test_id = ? ORDER BY p.pause_time DESC LIMIT ?",
                (lt_id, limit)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"Error fetching test pause logs: {e}")
            return []

    def _collect_closed_intervals(self, conn, lt_id: str) -> List[tuple]:
        """Return (start_dt, end_dt) tuples for every CLOSED pause interval that
        freezes this test's timeline: system-wide pauses PLUS this slot's own pauses.
        Open (in-progress) pauses are excluded — the caller freezes 'now' instead."""
        intervals = []
        sys_rows = conn.execute(
            "SELECT pause_time, resume_time FROM system_pause_logs WHERE resume_time IS NOT NULL"
        ).fetchall()
        slot_rows = conn.execute(
            "SELECT pause_time, resume_time FROM life_test_pause_logs "
            "WHERE life_test_id = ? AND resume_time IS NOT NULL",
            (lt_id,)
        ).fetchall()
        for r in list(sys_rows) + list(slot_rows):
            try:
                intervals.append((
                    datetime.fromisoformat(r[0].rstrip('Z')),
                    datetime.fromisoformat(r[1].rstrip('Z'))
                ))
            except Exception:
                pass
        return intervals

    def get_effective_paused_seconds(self, lt_id: str, since_iso: str, until_iso: str) -> float:
        """Total seconds this test's timeline was frozen within [since, until].

        Unions system-wide pauses with this slot's own pauses (merging any overlap,
        e.g. a slot under maintenance across a factory off-day) so paused time is
        never double-counted when excluded from effective testing time.
        """
        try:
            since_dt = datetime.fromisoformat(since_iso.rstrip('Z'))
            until_dt = datetime.fromisoformat(until_iso.rstrip('Z'))
            if until_dt <= since_dt:
                return 0.0
            conn = self.get_connection()
            intervals = self._collect_closed_intervals(conn, lt_id)
            conn.close()

            # Clip each interval to the window
            clipped = []
            for s, e in intervals:
                cs = max(s, since_dt)
                ce = min(e, until_dt)
                if ce > cs:
                    clipped.append((cs, ce))
            if not clipped:
                return 0.0

            # Merge overlapping intervals, then sum
            clipped.sort()
            total = 0.0
            cur_s, cur_e = clipped[0]
            for s, e in clipped[1:]:
                if s <= cur_e:
                    cur_e = max(cur_e, e)
                else:
                    total += (cur_e - cur_s).total_seconds()
                    cur_s, cur_e = s, e
            total += (cur_e - cur_s).total_seconds()
            return total
        except Exception as e:
            print(f"Error computing effective paused seconds: {e}")
            return 0.0

    def get_test_own_paused_seconds(self, lt_id: str) -> float:
        """Total time THIS slot has been paused for its own reasons (accumulated
        across all its pauses), including any currently-open pause in progress."""
        try:
            conn = self.get_connection()
            closed = conn.execute(
                "SELECT COALESCE(SUM(total_paused_minutes), 0) FROM life_test_pause_logs "
                "WHERE life_test_id = ? AND total_paused_minutes IS NOT NULL",
                (lt_id,)
            ).fetchone()[0]
            total_sec = float(closed or 0) * 60.0
            active = conn.execute(
                "SELECT pause_time FROM life_test_pause_logs "
                "WHERE life_test_id = ? AND resume_time IS NULL ORDER BY pause_time DESC LIMIT 1",
                (lt_id,)
            ).fetchone()
            conn.close()
            if active:
                ps = datetime.fromisoformat(active[0].rstrip('Z'))
                total_sec += max(0.0, (datetime.utcnow() - ps).total_seconds())
            return round(total_sec, 2)
        except Exception as e:
            print(f"Error computing test own paused seconds: {e}")
            return 0.0


db = LocalDB()




