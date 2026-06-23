from datetime import datetime, timedelta
from typing import Optional, Dict, List
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD


class SupabaseDB:
    """Database handler using direct PostgreSQL connection"""
    
    def __init__(self):
        self.db_config = {
            'host': DB_HOST,
            'port': int(DB_PORT),
            'database': DB_NAME,
            'user': DB_USER,
            'password': DB_PASSWORD
        }
    
    def get_connection(self):
        """Get a database connection"""
        return psycopg2.connect(**self.db_config)
    
    # ==================== User Methods ====================
    
    def create_user(self, email: str, full_name: str, password: str, role: str) -> dict:
        """Create a new user with hashed password"""
        try:
            import hashlib
            # Simple password hashing (in production, use bcrypt or similar)
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                INSERT INTO users (email, full_name, password_hash, role, created_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, email, full_name, role, created_at
                """,
                (email, full_name, password_hash, role, datetime.utcnow())
            )
            
            user = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()
            
            if user:
                return {
                    "success": True,
                    "user": {
                        "id": str(user[0]),
                        "email": user[1],
                        "full_name": user[2],
                        "role": user[3],
                        "created_at": user[4]
                    }
                }
            return {"success": False, "error": "Failed to create user"}
        except psycopg2.IntegrityError:
            return {"success": False, "error": "Email already exists"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Get user by email"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
            return dict(user) if user else None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None
    
    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """Get user by ID"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM users WHERE id::text = %s", (user_id,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
            return dict(user) if user else None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None
    
    # ==================== Data Upload Methods ====================
    
    def upload_data(self, operator_id: str, test_name: str, description: str, data: dict) -> dict:
        """Upload test data"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                INSERT INTO data_uploads (operator_id, test_name, description, data, uploaded_at)
                VALUES (%s::uuid, %s, %s, %s::jsonb, %s)
                RETURNING id, operator_id, test_name, description, data, uploaded_at
                """,
                (operator_id, test_name, description, json.dumps(data), datetime.utcnow())
            )
            
            upload = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()
            
            if upload:
                return {
                    "success": True,
                    "upload": {
                        "id": str(upload[0]),
                        "operator_id": str(upload[1]),
                        "test_name": upload[2],
                        "description": upload[3],
                        "data": upload[4] if isinstance(upload[4], dict) else json.loads(upload[4]) if upload[4] else {},
                        "uploaded_at": upload[5]
                    }
                }
            return {"success": False, "error": "Failed to insert data"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_uploads_by_operator(self, operator_id: str, limit: int = 50) -> List[dict]:
        """Get uploads by operator"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT * FROM data_uploads 
                WHERE operator_id::text = %s
                ORDER BY uploaded_at DESC
                LIMIT %s
                """,
                (operator_id, limit)
            )
            uploads = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(u) for u in uploads]
        except Exception as e:
            print(f"Error fetching uploads: {e}")
            return []
    
    def get_all_uploads(self, limit: int = 100) -> List[dict]:
        """Get all uploads"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT * FROM data_uploads
                ORDER BY uploaded_at DESC
                LIMIT %s
                """,
                (limit,)
            )
            uploads = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(u) for u in uploads]
        except Exception as e:
            print(f"Error fetching uploads: {e}")
            return []
    
    def get_last_upload_time(self) -> Optional[datetime]:
        """Get the time of the last upload"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT uploaded_at FROM data_uploads ORDER BY uploaded_at DESC LIMIT 1"
            )
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                return result[0]
            return None
        except Exception as e:
            print(f"Error fetching last upload: {e}")
            return None
    
    # ==================== Upload Interval Configuration ====================
    
    def get_upload_interval(self) -> int:
        """Get current upload interval in minutes"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT interval_minutes FROM upload_config WHERE id = 1")
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                return result[0]
            return 240
        except Exception as e:
            print(f"Error fetching upload interval: {e}")
            return 240
    
    def set_upload_interval(self, interval_minutes: int, updated_by: str) -> dict:
        """Set upload interval"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                INSERT INTO upload_config (id, interval_minutes, updated_at, updated_by)
                VALUES (1, %s, %s, %s::uuid)
                ON CONFLICT (id) DO UPDATE SET 
                    interval_minutes = %s,
                    updated_at = %s,
                    updated_by = %s::uuid
                RETURNING id, interval_minutes, updated_at, updated_by
                """,
                (interval_minutes, datetime.utcnow(), updated_by, interval_minutes, datetime.utcnow(), updated_by)
            )
            
            config = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()
            
            if config:
                return {
                    "success": True,
                    "config": {
                        "id": config[0],
                        "interval_minutes": config[1],
                        "updated_at": config[2],
                        "updated_by": str(config[3])
                    }
                }
            return {"success": False, "error": "Failed to update interval"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ==================== Testing Time Methods ====================
    
    def create_testing_session(self, operator_id: str, test_name: str, notes: str = None) -> dict:
        """Create a new testing session"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                INSERT INTO testing_sessions (operator_id, test_name, start_time, status, notes)
                VALUES (%s::uuid, %s, %s, 'running', %s)
                RETURNING id, operator_id, test_name, start_time, end_time, status, notes
                """,
                (operator_id, test_name, datetime.utcnow(), notes)
            )
            
            session = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()
            
            if session:
                return {
                    "success": True,
                    "session": {
                        "id": str(session[0]),
                        "operator_id": str(session[1]),
                        "test_name": session[2],
                        "start_time": session[3],
                        "end_time": session[4],
                        "status": session[5],
                        "notes": session[6]
                    }
                }
            return {"success": False, "error": "Failed to create session"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def end_testing_session(self, session_id: str) -> dict:
        """End a testing session"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                UPDATE testing_sessions
                SET end_time = %s, status = 'completed'
                WHERE id::text = %s
                RETURNING id, operator_id, test_name, start_time, end_time, status, notes
                """,
                (datetime.utcnow(), session_id)
            )
            
            session = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()
            
            if session:
                return {
                    "success": True,
                    "session": {
                        "id": str(session[0]),
                        "operator_id": str(session[1]),
                        "test_name": session[2],
                        "start_time": session[3],
                        "end_time": session[4],
                        "status": session[5],
                        "notes": session[6]
                    }
                }
            return {"success": False, "error": "Failed to end session"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_active_tests(self) -> List[dict]:
        """Get all active testing sessions"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT ts.id::text as id, ts.operator_id::text as operator_id, ts.test_name, 
                       ts.start_time, ts.end_time, ts.status, ts.notes, 
                       u.full_name as operator_name
                FROM testing_sessions ts
                LEFT JOIN users u ON ts.operator_id = u.id
                WHERE ts.status = 'running'
                ORDER BY ts.start_time DESC
                """
            )
            tests = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(t) for t in tests]
        except Exception as e:
            print(f"Error fetching active tests: {e}")
            return []
    
    def get_testing_history(self, operator_id: str = None, limit: int = 50) -> List[dict]:
        """Get testing session history"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            if operator_id:
                cursor.execute(
                    """
                    SELECT ts.id::text as id, ts.operator_id::text as operator_id, ts.test_name, 
                           ts.start_time, ts.end_time, ts.status, ts.notes,
                           u.full_name as operator_name
                    FROM testing_sessions ts
                    LEFT JOIN users u ON ts.operator_id = u.id
                    WHERE ts.operator_id::text = %s
                    ORDER BY ts.start_time DESC
                    LIMIT %s
                    """,
                    (operator_id, limit)
                )
            else:
                cursor.execute(
                    """
                    SELECT ts.id::text as id, ts.operator_id::text as operator_id, ts.test_name, 
                           ts.start_time, ts.end_time, ts.status, ts.notes,
                           u.full_name as operator_name
                    FROM testing_sessions ts
                    LEFT JOIN users u ON ts.operator_id = u.id
                    ORDER BY ts.start_time DESC
                    LIMIT %s
                    """,
                    (limit,)
                )
            
            history = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return [dict(h) for h in history]
        except Exception as e:
            print(f"Error fetching testing history: {e}")
            return []
    
    def get_dashboard_stats(self) -> dict:
        """Get dashboard statistics"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM data_uploads")
            total_uploads = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM testing_sessions")
            total_sessions = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM testing_sessions WHERE status = 'running'")
            active_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM testing_sessions WHERE status = 'completed'")
            completed_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT uploaded_at FROM data_uploads ORDER BY uploaded_at DESC LIMIT 1")
            last_upload_result = cursor.fetchone()
            last_upload = last_upload_result[0] if last_upload_result else None
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'operator'")
            operators_count = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            interval = self.get_upload_interval()
            next_upload = None
            if last_upload:
                next_upload = last_upload + timedelta(minutes=interval)
            
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
            
            # Extract time series data from the uploaded data
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
            cursor = conn.cursor()
            
            if operator_id:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM((data->>'on_hours')::float), 0)
                    FROM data_uploads
                    WHERE (data->>'on_hours') IS NOT NULL
                    AND operator_id::text = %s
                    """,
                    (operator_id,)
                )
            else:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM((data->>'on_hours')::float), 0)
                    FROM data_uploads
                    WHERE (data->>'on_hours') IS NOT NULL
                    """
                )
            
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            return round(result[0], 2) if result else 0.0
        except Exception as e:
            print(f"Error fetching cumulative ON hours: {e}")
            return 0.0
    
    def get_on_hours_progress(self, operator_id: str = None, target_on_hours: int = 468) -> dict:
        """Get ON hours progress toward target"""
        try:
            cumulative_on_hours = self.get_cumulative_on_hours(operator_id)
            progress_percent = min((cumulative_on_hours / target_on_hours * 100) if target_on_hours > 0 else 0, 100.0)
            
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


db = SupabaseDB()
