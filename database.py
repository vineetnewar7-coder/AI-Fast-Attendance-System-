import os
import datetime, hashlib
import psycopg2, psycopg2.extras
import pandas as pd
import streamlit as st
import config

# TCP keepalives and sequential SSL mode fallbacks are configured below.
# This prevents serverless Neon DB instances from closing idle connections during cold starts.
def get_conn():
    if not config.DATABASE_URL:
        st.error("❌ DATABASE_URL not set.")
        return None
    last_err = None
    for sslmode in ("require", "prefer", "disable"):
        try:
            return psycopg2.connect(
                config.DATABASE_URL, sslmode=sslmode,
                connect_timeout=10,
                keepalives=1, keepalives_idle=30,
                keepalives_interval=5, keepalives_count=3,
            )
        except psycopg2.OperationalError as e:
            last_err = e
    st.error(f"❌ DB error: {last_err}")
    return None

def _exec(sql, params=(), fetch=None, commit=False):
    """Generic execution wrapper that handles connection life cycles, custom commits, and transaction rollbacks."""
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            c.execute(sql, params)
            if commit: conn.commit()
            if fetch == "one":  return c.fetchone()
            if fetch == "all":  return c.fetchall()
            if commit:          return True
    except Exception as e:
        print(f"[DB] {e}")
        try: conn.rollback()
        except: pass
        return None
    finally:
        conn.close()

def init_db():
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id SERIAL PRIMARY KEY, name TEXT NOT NULL,
                    code TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS students (
                    id SERIAL PRIMARY KEY,
                    tenant_id INT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, roll_number TEXT NOT NULL,
                    phone_number TEXT DEFAULT '',
                    UNIQUE(tenant_id, roll_number)
                );
                CREATE TABLE IF NOT EXISTS subjects (
                    id SERIAL PRIMARY KEY,
                    tenant_id INT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, UNIQUE(tenant_id, name)
                );
                CREATE TABLE IF NOT EXISTS attendance_log (
                    id SERIAL PRIMARY KEY,
                    student_id INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    date DATE NOT NULL DEFAULT CURRENT_DATE,
                    subject TEXT NOT NULL DEFAULT 'General',
                    status TEXT NOT NULL DEFAULT 'A',
                    marked_at TIMESTAMPTZ,
                    message_sent BOOLEAN NOT NULL DEFAULT FALSE,
                    UNIQUE(student_id, date, subject)
                );
            """)
        conn.commit()
    except Exception as e:
        st.warning(f"init_db: {e}")
    finally:
        conn.close()

def generate_mock_data(tid):
    """Populates PostgreSQL with realistic mock students, subjects, and logs for recruitment demo purposes."""
    conn = get_conn()
    if not conn: return False, "No Database Connection"
    try:
        with conn.cursor() as c:
            # 1. Insert Mock Subjects
            subjects = ["Computer Science", "Mathematics", "Physics"]
            for sub in subjects:
                c.execute("INSERT INTO subjects(tenant_id,name) VALUES(%s,%s) ON CONFLICT DO NOTHING", (tid, sub))
            
            # 2. Insert Mock Students
            students = [
                ("VINEET KUMAR", "101", "+919999999999"),
                ("RAMESH SHARMA", "102", "+918888888888"),
                ("PRIYA PATEL", "103", "+917777777777"),
                ("AMIT SINGH", "104", "+916666666666"),
                ("SARA KHAN", "105", "")
            ]
            for name, roll, phone in students:
                c.execute("""
                    INSERT INTO students(tenant_id,name,roll_number,phone_number)
                    VALUES(%s,%s,%s,%s) ON CONFLICT(tenant_id,roll_number) DO NOTHING
                """, (tid, name, roll, phone))
            
            conn.commit()
            
            # Fetch active student IDs
            c.execute("SELECT id FROM students WHERE tenant_id=%s", (tid,))
            student_ids = [r[0] for r in c.fetchall()]
            
            # 3. Create mock today's logs with different statuses
            today = datetime.date.today()
            for idx, sid in enumerate(student_ids):
                status_cs = "P" if idx % 2 == 0 else "A"
                c.execute("""
                    INSERT INTO attendance_log(student_id,date,subject,status,marked_at)
                    VALUES(%s,%s,%s,%s,NOW())
                    ON CONFLICT(student_id,date,subject) DO UPDATE SET status=%s, marked_at=NOW()
                """, (sid, today, "Computer Science", status_cs, status_cs))
                
                status_math = "P" if idx % 3 == 0 else "A"
                c.execute("""
                    INSERT INTO attendance_log(student_id,date,subject,status,marked_at)
                    VALUES(%s,%s,%s,%s,NOW())
                    ON CONFLICT(student_id,date,subject) DO UPDATE SET status=%s, marked_at=NOW()
                """, (sid, today, "Mathematics", status_math, status_math))
        
        conn.commit()
        return True, "✅ Successfully seeded mock subjects, students, and attendance logs!"
    except Exception as e:
        return False, f"DB Error: {e}"
    finally:
        conn.close()

# --- Authentication and Tenant Registration ---
def _hash(pw): return hashlib.sha256(pw.encode()).hexdigest()

def tenant_register(name, code, pw):
    conn = get_conn()
    if not conn: return False, "No DB"
    try:
        with conn.cursor() as c:
            c.execute("INSERT INTO tenants(name,code,password_hash) VALUES(%s,%s,%s)",
                      (name.strip(), code.strip().upper(), _hash(pw)))
        conn.commit(); return True, "✅ Registered!"
    except psycopg2.errors.UniqueViolation:
        return False, "Code already taken."
    except Exception as e:
        return False, str(e)
    finally: conn.close()

def tenant_login(code, pw):
    row = _exec(
        "SELECT id,name,code FROM tenants WHERE code=%s AND password_hash=%s",
        (code.strip().upper(), _hash(pw)), fetch="one"
    )
    return dict(row) if row else None

# --- Course and Subject Records Management ---
def get_subjects(tid):
    rows = _exec("SELECT name FROM subjects WHERE tenant_id=%s ORDER BY name",
                 (tid,), fetch="all")
    return [r["name"] for r in rows] if rows else []

def add_subject(tid, name):
    ok = _exec("INSERT INTO subjects(tenant_id,name) VALUES(%s,%s) ON CONFLICT DO NOTHING",
               (tid, name.strip()), commit=True)
    return (True,"Added!") if ok is not None else (False,"DB error")

def del_subject(tid, name):
    _exec("DELETE FROM subjects WHERE tenant_id=%s AND name=%s", (tid,name), commit=True)

# --- Student Identity Parsing and Record Keeping ---
def _roll(lbl):
    if '_' in lbl:
        suf = lbl.rsplit('_',1)[-1]
        if suf.isdigit(): return suf
    return f"NR-{lbl.upper()}"

def _disp(lbl): return (lbl.split('_')[0] if '_' in lbl else lbl).upper()

def _name(lbl):
    return (lbl.split('_')[0] if '_' in lbl else lbl).upper()

def _has_roll_in_label(lbl):
    return '_' in lbl and lbl.rsplit('_', 1)[-1].isdigit()

def _find_student(c, tid, label):
    roll = _roll(label)
    nm   = _name(label)
    c.execute(
        "SELECT COUNT(*) FROM students WHERE tenant_id=%s AND UPPER(name)=%s",
        (tid, nm),
    )
    name_count = c.fetchone()[0]
    if name_count > 1 or _has_roll_in_label(label):
        c.execute(
            "SELECT id,phone_number FROM students WHERE tenant_id=%s AND roll_number=%s",
            (tid, roll),
        )
        row = c.fetchone()
        if row:
            return row
    if name_count >= 1:
        c.execute(
            "SELECT id,phone_number FROM students WHERE tenant_id=%s AND UPPER(name)=%s",
            (tid, nm),
        )
        row = c.fetchone()
        if row:
            return row
    c.execute(
        "SELECT id,phone_number FROM students WHERE tenant_id=%s AND roll_number=%s",
        (tid, roll),
    )
    return c.fetchone()

def get_students(tid):
    conn = get_conn()
    if not conn: return pd.DataFrame()
    try:
        return pd.read_sql_query(
            'SELECT name AS "Name", roll_number AS "Roll", phone_number AS "Phone" '
            'FROM students WHERE tenant_id=%s ORDER BY name', conn, params=(tid,))
    finally: conn.close()

def save_student(tid, name, roll, phone=""):
    ok = _exec("""INSERT INTO students(tenant_id,name,roll_number,phone_number)
                  VALUES(%s,%s,%s,%s)
                  ON CONFLICT(tenant_id,roll_number)
                  DO UPDATE SET name=EXCLUDED.name, phone_number=EXCLUDED.phone_number""",
               (tid, name.upper().strip(), str(roll).strip(), str(phone).strip()),
               commit=True)
    return (True,"Saved!") if ok is not None else (False,"DB error")

def del_student(tid, roll):
    """Deletes a student record safely from the cloud database without managing local file deletion."""
    roll = str(roll).strip()
    _exec("DELETE FROM students WHERE tenant_id=%s AND roll_number=%s",
          (tid, roll), commit=True)

def ensure_students(tid, class_names):
    if not class_names:
        return
    conn = get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as c:
            for lbl in class_names:
                nm   = _name(lbl)
                roll = _roll(lbl)
                if _has_roll_in_label(lbl):
                    c.execute(
                        """INSERT INTO students(tenant_id,name,roll_number)
                           VALUES(%s,%s,%s) ON CONFLICT(tenant_id,roll_number) DO NOTHING""",
                        (tid, nm, roll),
                    )
                    continue
                c.execute(
                    "SELECT 1 FROM students WHERE tenant_id=%s AND UPPER(name)=%s",
                    (tid, nm),
                )
                if c.fetchone():
                    continue
                c.execute(
                    """INSERT INTO students(tenant_id,name,roll_number)
                       VALUES(%s,%s,%s) ON CONFLICT(tenant_id,roll_number) DO NOTHING""",
                    (tid, nm, roll),
                )
        conn.commit()
    finally:
        conn.close()

# --- Attendance Tracking and Logging Operations ---
def load_attendance(tid, subject, date=None):
    conn = get_conn()
    if not conn: return pd.DataFrame(columns=['Name','Roll','Phone','Status'])
    try:
        d = date or datetime.date.today()
        return pd.read_sql_query("""
            SELECT s.name AS "Name", s.roll_number AS "Roll",
                   s.phone_number AS "Phone",
                   COALESCE(a.status,'A') AS "Status"
            FROM   students s
            LEFT JOIN attendance_log a
                   ON a.student_id=s.id AND a.date=%s AND a.subject=%s
            WHERE  s.tenant_id=%s ORDER BY s.name
        """, conn, params=(d, subject, tid))
    except Exception as e:
        print(f"[load_attendance] {e}")
        return pd.DataFrame(columns=['Name', 'Roll', 'Phone', 'Status'])
    finally:
        conn.close()

load_data = load_attendance

def reset_today_attendance(tid, subject=None):
    conn = get_conn()
    if not conn:
        return
    try:
        today = datetime.date.today()
        with conn.cursor() as c:
            if subject:
                c.execute("""
                    DELETE FROM attendance_log a
                    USING students s
                    WHERE a.student_id = s.id AND s.tenant_id = %s
                      AND a.date = %s AND a.subject = %s
                """, (tid, today, subject))
            else:
                c.execute("""
                    DELETE FROM attendance_log a
                    USING students s
                    WHERE a.student_id = s.id AND s.tenant_id = %s
                      AND a.date = %s
                """, (tid, today))
        conn.commit()
    except Exception as e:
        print(f"[reset_today_attendance] {e}")
    finally:
        conn.close()

def mark_present(tid, subject, label):
    roll = _roll(label)
    sk   = f"done_{subject}_{roll}"
    if st.session_state.get(sk): return False, None
    conn = get_conn()
    if not conn: return False, None
    try:
        today = datetime.date.today()
        with conn.cursor() as c:
            row = _find_student(c, tid, label)
            if not row:
                c.execute(
                    "INSERT INTO students(tenant_id,name,roll_number) VALUES(%s,%s,%s) RETURNING id,phone_number",
                    (tid, _name(label), roll),
                )
                sid, phone = c.fetchone()
                conn.commit()
            else:
                sid, phone = row
        with conn.cursor() as c:
            c.execute("SELECT status,message_sent FROM attendance_log "
                      "WHERE student_id=%s AND date=%s AND subject=%s",
                      (sid, today, subject))
            ex = c.fetchone()
        if ex and ex[0]=='P':
            st.session_state[sk]=True; return False, None
        with conn.cursor() as c:
            c.execute("""INSERT INTO attendance_log(student_id,date,subject,status,marked_at,message_sent)
                         VALUES(%s,%s,%s,'P',NOW(),FALSE)
                         ON CONFLICT(student_id,date,subject)
                         DO UPDATE SET status='P', marked_at=NOW()""",
                      (sid, today, subject))
        conn.commit()
        st.session_state[sk] = True
        notify = not (ex and ex[1])
        return True, (phone if notify else None)
    except Exception as e:
        print(f"[mark_present] {e}"); return False, None
    finally: conn.close()

def flag_msg_sent(tid, subject, label):
    _exec("""UPDATE attendance_log SET message_sent=TRUE WHERE date=%s AND subject=%s
             AND student_id=(SELECT id FROM students WHERE tenant_id=%s AND roll_number=%s)""",
          (datetime.date.today(), subject, tid, _roll(label)), commit=True)

def load_history(tid, date, subject):
    conn = get_conn()
    if not conn: return pd.DataFrame()
    try:
        return pd.read_sql_query("""
            SELECT s.name AS "Name", s.roll_number AS "Roll",
                   COALESCE(a.status,'A') AS "Status", a.marked_at AS "Marked At"
            FROM   students s
            LEFT JOIN attendance_log a ON a.student_id=s.id AND a.date=%s AND a.subject=%s
            WHERE  s.tenant_id=%s ORDER BY s.name
        """, conn, params=(date, subject, tid))
    finally: conn.close()
