"""Academic Weapon database helpers.

The application still defaults to the synthetic demo database. A separate
database can be selected with ``APSS_DB_PATH`` and demo seeding can be disabled
with ``APSS_DEMO_MODE=0`` before importing real records.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent


def env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


DB_PATH = Path(os.getenv('APSS_DB_PATH', str(BASE_DIR / 'apss_demo.sqlite3'))).expanduser()
DEMO_MODE = env_flag('APSS_DEMO_MODE', True)


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 390_000)
    return f'{salt}${digest.hex()}'


def password_verify(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split('$', 1)
        return secrets.compare_digest(password_hash(password, salt), stored)
    except ValueError:
        return False


def one(sql: str, params=()):
    with connect() as con:
        r = con.execute(sql, params).fetchone()
        return dict(r) if r else None


def all_rows(sql: str, params=()):
    with connect() as con:
        return [dict(row) for row in con.execute(sql, params).fetchall()]


def run(sql: str, params=()):
    with connect() as con:
        return con.execute(sql, params).lastrowid


def seed_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS students (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          student_code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
          program TEXT NOT NULL, year INTEGER NOT NULL, gpa REAL NOT NULL,
          credit_load INTEGER NOT NULL, advisor TEXT NOT NULL, status TEXT NOT NULL,
          attention TEXT NOT NULL DEFAULT 'Regular', avatar TEXT NOT NULL DEFAULT 'DS',
          active INTEGER NOT NULL DEFAULT 1,
          source TEXT NOT NULL DEFAULT 'demo',
          synced_at TEXT
        );
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
          display_name TEXT NOT NULL, role TEXT NOT NULL, student_id INTEGER,
          password_hash TEXT NOT NULL, google_sub TEXT,
          active INTEGER NOT NULL DEFAULT 1,
          FOREIGN KEY(student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS goals (
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
          title TEXT NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'In Progress',
          FOREIGN KEY(student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
          title TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', due_date TEXT NOT NULL,
          priority TEXT NOT NULL DEFAULT 'Medium', status TEXT NOT NULL DEFAULT 'To Do',
          source TEXT NOT NULL DEFAULT 'aac',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS meetings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
          date TEXT NOT NULL, time TEXT NOT NULL DEFAULT '', topic TEXT NOT NULL,
          advisor TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
          created_by_user_id INTEGER,
          owner_role TEXT NOT NULL DEFAULT 'advising_team',
          FOREIGN KEY(student_id) REFERENCES students(id),
          FOREIGN KEY(created_by_user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS schedule_courses (
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
          name TEXT NOT NULL, credits INTEGER NOT NULL,
          room TEXT NOT NULL DEFAULT '', instructor TEXT NOT NULL,
          days TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS checkins (
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          mood TEXT NOT NULL, challenge TEXT NOT NULL, priority TEXT NOT NULL, needs_help INTEGER NOT NULL,
          week_key TEXT,
          FOREIGN KEY(student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          student_id INTEGER NOT NULL,
          kind TEXT NOT NULL,
          title TEXT NOT NULL,
          body TEXT NOT NULL DEFAULT '',
          link TEXT NOT NULL DEFAULT '/student',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          read_at TEXT,
          FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS notifications_student_idx
          ON notifications(student_id,id DESC);
        CREATE TABLE IF NOT EXISTS followups (
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
          title TEXT NOT NULL, due_date TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'Normal',
          status TEXT NOT NULL DEFAULT 'Open',
          FOREIGN KEY(student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS deadlines (
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
          course TEXT NOT NULL, topic TEXT NOT NULL,
          due_date TEXT NOT NULL, due_time TEXT NOT NULL DEFAULT '23:59',
          weight INTEGER NOT NULL DEFAULT 10,
          status TEXT NOT NULL DEFAULT 'Pending',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          student_id INTEGER NOT NULL,
          staff_user_id INTEGER,
          sender_user_id INTEGER NOT NULL,
          body TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          read_by_student INTEGER NOT NULL DEFAULT 0,
          read_by_aac INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
          FOREIGN KEY(sender_user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS chat_messages_student_id_idx
          ON chat_messages(student_id,id);
        CREATE TABLE IF NOT EXISTS staff_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sender_user_id INTEGER NOT NULL,
          recipient_user_id INTEGER NOT NULL,
          body TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          read_at TEXT,
          FOREIGN KEY(sender_user_id) REFERENCES users(id) ON DELETE CASCADE,
          FOREIGN KEY(recipient_user_id) REFERENCES users(id) ON DELETE CASCADE,
          CHECK(sender_user_id <> recipient_user_id)
        );
        CREATE INDEX IF NOT EXISTS staff_messages_participants_idx
          ON staff_messages(sender_user_id,recipient_user_id,id);
        CREATE INDEX IF NOT EXISTS staff_messages_unread_idx
          ON staff_messages(recipient_user_id,read_at,id);
        CREATE TABLE IF NOT EXISTS audit_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          event TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        ''')
        student_columns = {row[1] for row in con.execute('PRAGMA table_info(students)')}
        if 'active' not in student_columns:
            con.execute("ALTER TABLE students ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        if 'source' not in student_columns:
            con.execute("ALTER TABLE students ADD COLUMN source TEXT NOT NULL DEFAULT 'demo'")
        if 'synced_at' not in student_columns:
            con.execute('ALTER TABLE students ADD COLUMN synced_at TEXT')
        con.execute("UPDATE students SET status='On Track' WHERE status='Active Plan'")
        con.execute("UPDATE students SET status='Needs Review' WHERE status='Semester Review'")
        con.execute(
            "UPDATE students SET status='Initial Assessment' "
            "WHERE status NOT IN ('Initial Assessment','On Track','Needs Review')"
        )

        user_columns = {row[1] for row in con.execute('PRAGMA table_info(users)')}
        if 'google_sub' not in user_columns:
            con.execute('ALTER TABLE users ADD COLUMN google_sub TEXT')
        if 'active' not in user_columns:
            con.execute('ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
        con.execute("UPDATE users SET role='advising_team' WHERE role='aac'")
        staff_names = (
            ('Serdar Urustemov', 'urustemov_s@auca.kg'),
            ('Umut Kydyrgychova', 'kydyrgychova_u@auca.kg'),
            ('Aizada Tynyeva', 'tynyeva_a@auca.kg'),
            ('Aidar Zhakypov', 'zhakypov_a@auca.kg'),
        )
        con.executemany(
            "UPDATE users SET display_name=?,role='advising_team' WHERE LOWER(email)=LOWER(?)",
            staff_names,
        )
        con.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub_unique ON users(google_sub) WHERE google_sub IS NOT NULL')

        chat_columns = {row[1] for row in con.execute('PRAGMA table_info(chat_messages)')}
        if 'staff_user_id' not in chat_columns:
            con.execute('ALTER TABLE chat_messages ADD COLUMN staff_user_id INTEGER')
        con.execute(
            '''UPDATE chat_messages SET staff_user_id=sender_user_id
               WHERE staff_user_id IS NULL AND sender_user_id IN
                 (SELECT id FROM users WHERE role IN ('advisor','advising_team'))'''
        )
        default_staff = con.execute(
            "SELECT id FROM users WHERE role='advising_team' AND active=1 ORDER BY id LIMIT 1"
        ).fetchone()
        if default_staff:
            con.execute(
                'UPDATE chat_messages SET staff_user_id=? WHERE staff_user_id IS NULL',
                (default_staff[0],),
            )
        con.execute(
            'CREATE INDEX IF NOT EXISTS chat_messages_conversation_idx '
            'ON chat_messages(student_id,staff_user_id,id)'
        )

        meeting_columns = {row[1] for row in con.execute('PRAGMA table_info(meetings)')}
        if 'time' not in meeting_columns:
            con.execute("ALTER TABLE meetings ADD COLUMN time TEXT NOT NULL DEFAULT ''")
        if 'created_by_user_id' not in meeting_columns:
            con.execute('ALTER TABLE meetings ADD COLUMN created_by_user_id INTEGER')
        if 'owner_role' not in meeting_columns:
            con.execute(
                "ALTER TABLE meetings ADD COLUMN owner_role TEXT NOT NULL DEFAULT 'advising_team'"
            )

        # Preserve ownership for existing meetings where the advisor name can
        # be matched to an active account. Unmatched legacy records remain
        # team-owned so that no individual Advisor can unexpectedly take them
        # over merely because a display name happens to change later.
        con.execute(
            '''UPDATE meetings
               SET created_by_user_id=(
                 SELECT u.id FROM users u
                 WHERE LOWER(u.display_name)=LOWER(meetings.advisor)
                   AND u.role IN ('advisor','advising_team')
                 ORDER BY u.active DESC,u.id
                 LIMIT 1
               )
               WHERE created_by_user_id IS NULL'''
        )
        con.execute(
            '''UPDATE meetings SET owner_role='advisor'
               WHERE created_by_user_id IN (SELECT id FROM users WHERE role='advisor')'''
        )
        con.execute(
            "UPDATE meetings SET owner_role='advising_team' "
            "WHERE owner_role NOT IN ('advisor','advising_team')"
        )

        checkin_columns = {row[1] for row in con.execute('PRAGMA table_info(checkins)')}
        if 'week_key' not in checkin_columns:
            con.execute('ALTER TABLE checkins ADD COLUMN week_key TEXT')

        # Assign legacy submissions to their Monday-based academic week. If an
        # older installation allowed multiple submissions in one week, keep
        # the newest one as the weekly completion record without deleting any
        # history.
        bishkek = ZoneInfo('Asia/Bishkek')
        legacy_checkins = con.execute(
            'SELECT id,student_id,created_at FROM checkins WHERE week_key IS NULL ORDER BY id DESC'
        ).fetchall()
        claimed_weeks = {
            (row[0], row[1])
            for row in con.execute('SELECT student_id,week_key FROM checkins WHERE week_key IS NOT NULL')
        }
        for item in legacy_checkins:
            try:
                created = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                local_day = created.astimezone(bishkek).date()
                week_key = (local_day - timedelta(days=local_day.weekday())).isoformat()
            except (TypeError, ValueError):
                continue
            identity = (item['student_id'], week_key)
            if identity in claimed_weeks:
                continue
            con.execute('UPDATE checkins SET week_key=? WHERE id=?', (week_key, item['id']))
            claimed_weeks.add(identity)
        con.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS checkins_student_week_unique '
            'ON checkins(student_id,week_key) WHERE week_key IS NOT NULL'
        )

        # Restricted local environment: a Google-only Advisor account used to
        # demonstrate the limited Advisor workspace, plus the deduplicated
        # AUCA Advisor directory. Advising Team accounts are intentionally not
        # included here and therefore keep their separate, broader role.
        if not DEMO_MODE:
            advisor_accounts = (
                ('Elena Burova', 'burova_e@auca.kg'),
                ('Taalaibek Imanaliev', 'imanaliev_t@auca.kg'),
                ('Talant Asan uulu', 'asanov_ta@auca.kg'),
                ('Mehrigul Ablezova', 'ablezova_m@auca.kg'),
                ('Edil Kamil uulu', 'edil_k@auca.kg'),
                ('Begimay Abdraeva', 'abdraeva_b@auca.kg'),
                ('Altynay Halmurzaeva', 'halmurzaeva_a@auca.kg'),
                ('James Hart', 'hart_j@auca.kg'),
                ('Nurbek Madmarov', 'madmarov_n@auca.kg'),
                ('Asel Kyrgyzbaeva', 'kyrgyzbaeva_a@auca.kg'),
                ('Akylai Muktarbek kyzy', 'muktarbek_a@auca.kg'),
                ('Nazgul Jenish', 'jenish_n@auca.kg'),
                ('Gorkem Atsungur', 'atsungur_g@auca.kg'),
                ('Zamira Muratalieva', 'muratalieva_z@auca.kg'),
                ('Aida Aidarova', 'aidarova_a@auca.kg'),
                ('Nathaniel Matala', 'matala_n@auca.kg'),
                ('Mirko Tasic', 'tasic_m@auca.kg'),
                ('Christopher Baker', 'baker_ch@auca.kg'),
                ('Azim Jeenbaev', 'jeenbaev_a@auca.kg'),
                ('Kanykei Kasybekova', 'kasybekova_k@auca.kg'),
                ('Bholenath Dutta', 'dutta_b@auca.kg'),
                ('Kamila Mateeva', 'mateeva_k@auca.kg'),
                ('Asanbaeva Dinara', 'asanbaeva_d@auca.kg'),
                ('Seiitbekova Begaiym', 'seiitbekova_be@auca.kg'),
                ('Karabaev Daniyar', 'karabaev_d@auca.kg'),
                ('Kangeldieva Janna', 'kangeldieva_j@auca.kg'),
                ('Elena Chigibaeva', 'chigibaeva_e@auca.kg'),
                ('Daniiar Usenov', 'usenov_d@auca.kg'),
                ('Uulkan Kambaralieva', 'kambaralieva_u@auca.kg'),
                ('Mohira Suyarkulova', 'suyarkulova_m@auca.kg'),
                ('Galina Gorborukova', 'gorborukova_g@auca.kg'),
                ('Srdjan Uljevic', 'uljevic_s@auca.kg'),
                ('Sagynbek Orunbaev', 'orunbaev_s@auca.kg'),
                ('Gulzat Esenalieva', 'esenalieva_gu@auca.kg'),
                ('Aijamal Sarybaeva', 'sarybaeva_a@auca.kg'),
                ('Lyubov Altynnikova', 'altynnikova_l@auca.kg'),
                ('Elvira Kushbekova', 'kushbekova_e@auca.kg'),
                ('Mary Cond', 'conde_m@auca.kg'),
                ('Sultan Usuvaliev', 'usuvaliev_s@auca.kg'),
                ('Zhumanazar Koychubekov', 'koichubekov_zh@auca.kg'),
                ('Kanykei Orozoeva', 'orozoeva_k@auca.kg'),
            )
            con.executemany(
                '''INSERT INTO users(email,display_name,role,student_id,password_hash,active)
                   VALUES (?,?,\'advisor\',NULL,\'!google-only!\',1)
                   ON CONFLICT(email) DO UPDATE SET
                     display_name=excluded.display_name,
                     role=CASE
                       WHEN users.role=\'advising_team\' THEN users.role
                       ELSE \'advisor\'
                     END,
                     student_id=CASE
                       WHEN users.role=\'advising_team\' THEN users.student_id
                       ELSE NULL
                     END,
                     active=1''',
                ((email,name) for name,email in advisor_accounts),
            )
            con.execute(
                '''INSERT INTO users(email,display_name,role,student_id,password_hash,active)
                   VALUES (?,?,?,?,?,1)
                   ON CONFLICT(email) DO UPDATE SET
                     display_name=excluded.display_name,
                     role=excluded.role,
                     student_id=NULL,
                     active=1''',
                ('advising@auca.kg','Test Advisor','advisor',None,'!google-only!'),
            )
            con.execute(
                "UPDATE students SET advisor='Test Advisor' WHERE LOWER(email)=LOWER(?)",
                ('urustemov_se@auca.kg',),
            )

        count = con.execute('SELECT COUNT(*) FROM students').fetchone()[0]
        td = date.today()
        tdstr = lambda days: (td+timedelta(days=days)).isoformat()
        if count:
            try:
                d_count = con.execute('SELECT COUNT(*) FROM deadlines').fetchone()[0]
                if DEMO_MODE and not d_count and con.execute('SELECT COUNT(*) FROM students WHERE id=1 AND source="demo"').fetchone()[0]:
                    sample_deadlines = [
                        (1, 'Psychology 101', 'Reflection paper', tdstr(4), '23:59', 15, 'Pending'),
                        (1, 'Calculus I', 'Problem Set 4 & Quiz', tdstr(2), '17:00', 10, 'Pending'),
                        (1, 'Academic Writing', 'Midterm Research Essay', tdstr(9), '23:59', 20, 'Pending'),
                    ]
                    con.executemany('INSERT INTO deadlines(student_id,course,topic,due_date,due_time,weight,status) VALUES (?,?,?,?,?,?,?)', sample_deadlines)
            except (sqlite3.OperationalError, sqlite3.IntegrityError):
                pass
            return
        if not DEMO_MODE:
            return
        names = [
            ('DEMO-1001', 'Alex Morgan', 'alex.morgan@example.com', 'Liberal Arts and Sciences', 2, 1.82, 24, 'AAC Advising Team', 'On Track', 'Follow-up Needed', 'AM'),
            ('DEMO-1002', 'Mira Taylor', 'mira.taylor@example.com', 'Psychology', 3, 2.05, 30, 'AAC Advising Team', 'On Track', 'Regular', 'MT'),
            ('DEMO-1003', 'Daniel Rivers', 'daniel.rivers@example.com', 'Business Administration', 2, 1.66, 24, 'AAC Advising Team', 'Needs Review', 'Priority Attention', 'DR'),
            ('DEMO-1004', 'Lea Brooks', 'lea.brooks@example.com', 'Computer Science', 1, 2.17, 30, 'AAC Advising Team', 'On Track', 'Regular', 'LB'),
            ('DEMO-1005', 'Noah Wells', 'noah.wells@example.com', 'Journalism', 3, 1.94, 27, 'AAC Advising Team', 'Initial Assessment', 'Follow-up Needed', 'NW'),
            ('DEMO-1006', 'Sam Parker', 'sam.parker@example.com', 'International Relations', 2, 2.12, 30, 'AAC Advising Team', 'On Track', 'Regular', 'SP'),
        ]
        con.executemany('''INSERT INTO students (student_code,name,email,program,year,gpa,credit_load,advisor,status,attention,avatar)
          VALUES (?,?,?,?,?,?,?,?,?,?,?)''', names)
        con.execute('INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
                    ('advisor@demo.example', 'AAC Demo Advisor', 'advising_team', None, password_hash('Demo1234!')))
        con.execute('INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
                    ('student@demo.example', 'Alex Morgan', 'student', 1, password_hash('Demo1234!')))
        goals = [
            (1, 'Strengthen semester GPA', 'Reach a GPA of 2.50'),
            (1, 'Improve assignment submission', 'Submit 90% of tasks on time'),
            (1, 'Build consistent study habits', 'Study 5 days each week'),
            (2, 'Maintain positive momentum', 'Complete scheduled check-ins'),
            (3, 'Improve course attendance', 'Attend all scheduled classes'),
            (4, 'Manage study load', 'Complete a weekly plan'),
            (5, 'Create a recovery plan', 'Meet with the AAC case manager'),
            (6, 'Strengthen writing skills', 'Visit writing support weekly')
        ]
        con.executemany('INSERT INTO goals (student_id,title,target) VALUES (?,?,?)', goals)
        td = date.today()
        tdstr = lambda days: (td+timedelta(days=days)).isoformat()
        tasks = [
            (1, 'Review lecture notes', 'Summarize this week’s key concepts.', tdstr(-1), 'Low', 'Completed', 'student'),
            (1, 'Attend a tutoring session', 'Bring two questions to the session.', tdstr(-2), 'Medium', 'Completed', 'student'),
            (1, 'Complete Mathematics problem set', 'Exercises from current study unit.', tdstr(3), 'High', 'In Progress', 'student'),
            (1, 'Plan next week of studying', 'Set aside a 20-minute planning session.', tdstr(5), 'Medium', 'To Do', 'student'),
            (2, 'Submit psychology reflection', 'Reflection draft and final checks.', tdstr(4), 'Medium', 'In Progress', 'student'),
            (3, 'Schedule advisor check-in', 'Review recent academic difficulties.', tdstr(1), 'High', 'To Do', 'student'),
            (4, 'Prepare a weekly timetable', 'Review your workload.', tdstr(6), 'Low', 'To Do', 'student'),
            (5, 'Complete self-assessment', 'Share any learning challenges.', tdstr(2), 'Medium', 'To Do', 'student'),
            (6, 'Attend writing support session', 'Review research paper outline.', tdstr(6), 'Medium', 'Completed', 'student'),
        ]
        con.executemany('INSERT INTO tasks(student_id,title,details,due_date,priority,status,source) VALUES (?,?,?,?,?,?,?)', tasks)
        meetings = [
            (1, tdstr(2), 'Recovery plan check-in', 'AAC Demo Advisor', 'Confirm next action steps'),
            (1, tdstr(-8), 'Initial consultation', 'AAC Demo Advisor', 'Discussed goals and study habits'),
            (2, tdstr(7), 'Midterm review', 'AAC Demo Advisor', 'Review progress'),
            (3, tdstr(1), 'Academic support meeting', 'AAC Demo Advisor', 'Explore available support'),
            (4, tdstr(9), 'Routine progress review', 'AAC Demo Advisor', ''),
            (5, tdstr(3), 'Initial consultation', 'AAC Demo Advisor', ''),
        ]
        con.executemany('INSERT INTO meetings (student_id,date,topic,advisor,notes) VALUES (?,?,?,?,?)', meetings)
        followups = [
            (1,'Confirm tutoring attendance',tdstr(3),'Normal','Open'),
            (3,'Contact student for academic review',tdstr(1),'High','Open'),
            (5,'Send initial assessment reminder',tdstr(2),'Normal','Open'),
            (2,'Confirm current course plan',tdstr(-3),'Normal','Resolved')
        ]
        con.executemany('INSERT INTO followups(student_id,title,due_date,priority,status) VALUES (?,?,?,?,?)', followups)
        previous_week = (td - timedelta(days=td.weekday()+7)).isoformat()
        con.execute('INSERT INTO checkins(student_id,mood,challenge,priority,needs_help,week_key) VALUES (?,?,?,?,?,?)',
                    (1,'Okay','Time management','Finish the mathematics practice set',0,previous_week))
        sample_deadlines = [
            (1, 'Psychology 101', 'Reflection paper', tdstr(4), '23:59', 15, 'Pending'),
            (1, 'Calculus I', 'Problem Set 4 & Quiz', tdstr(2), '17:00', 10, 'Pending'),
            (1, 'Academic Writing', 'Midterm Research Essay', tdstr(9), '23:59', 20, 'Pending'),
        ]
        con.executemany('INSERT INTO deadlines(student_id,course,topic,due_date,due_time,weight,status) VALUES (?,?,?,?,?,?,?)', sample_deadlines)
