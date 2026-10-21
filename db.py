"""Academic Weapon demonstration database. Synthetic records only."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
from datetime import date, timedelta

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'apss_demo.sqlite3'


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
    with connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS students (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          student_code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
          program TEXT NOT NULL, year INTEGER NOT NULL, gpa REAL NOT NULL,
          credit_load INTEGER NOT NULL, advisor TEXT NOT NULL, status TEXT NOT NULL,
          attention TEXT NOT NULL DEFAULT 'Regular', avatar TEXT NOT NULL DEFAULT 'DS'
        );
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
          display_name TEXT NOT NULL, role TEXT NOT NULL, student_id INTEGER,
          password_hash TEXT NOT NULL,
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
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS meetings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
          date TEXT NOT NULL, topic TEXT NOT NULL, advisor TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
          FOREIGN KEY(student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS checkins (
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          mood TEXT NOT NULL, challenge TEXT NOT NULL, priority TEXT NOT NULL, needs_help INTEGER NOT NULL,
          FOREIGN KEY(student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS followups (
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
          title TEXT NOT NULL, due_date TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'Normal',
          status TEXT NOT NULL DEFAULT 'Open',
          FOREIGN KEY(student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          event TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        ''')
        count = con.execute('SELECT COUNT(*) FROM students').fetchone()[0]
        if count:
            return
        names = [
            ('DEMO-1001', 'Alex Morgan', 'alex.morgan@example.com', 'Liberal Arts and Sciences', 2, 1.82, 24, 'AAC Advising Team', 'Active Plan', 'Follow-up Needed', 'AM'),
            ('DEMO-1002', 'Mira Taylor', 'mira.taylor@example.com', 'Psychology', 3, 2.05, 30, 'AAC Advising Team', 'On Track', 'Regular', 'MT'),
            ('DEMO-1003', 'Daniel Rivers', 'daniel.rivers@example.com', 'Business Administration', 2, 1.66, 24, 'AAC Advising Team', 'Needs Review', 'Priority Attention', 'DR'),
            ('DEMO-1004', 'Lea Brooks', 'lea.brooks@example.com', 'Computer Science', 1, 2.17, 30, 'AAC Advising Team', 'Active Plan', 'Regular', 'LB'),
            ('DEMO-1005', 'Noah Wells', 'noah.wells@example.com', 'Journalism', 3, 1.94, 27, 'AAC Advising Team', 'Initial Assessment', 'Follow-up Needed', 'NW'),
            ('DEMO-1006', 'Sam Parker', 'sam.parker@example.com', 'International Relations', 2, 2.12, 30, 'AAC Advising Team', 'On Track', 'Regular', 'SP'),
        ]
        con.executemany('''INSERT INTO students (student_code,name,email,program,year,gpa,credit_load,advisor,status,attention,avatar)
          VALUES (?,?,?,?,?,?,?,?,?,?,?)''', names)
        con.execute('INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
                    ('advisor@demo.example', 'AAC Demo Advisor', 'aac', None, password_hash('Demo1234!')))
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
            (1, 'Meet with your academic advisor', 'Review semester recovery goals.', tdstr(2), 'High', 'To Do'),
            (1, 'Complete Mathematics problem set', 'Exercises from current study unit.', tdstr(3), 'High', 'In Progress'),
            (1, 'Plan next week of studying', 'Set aside a 20-minute planning session.', tdstr(5), 'Medium', 'To Do'),
            (1, 'Review lecture notes', 'Summarize this week’s key concepts.', tdstr(-1), 'Low', 'Completed'),
            (1, 'Attend a tutoring session', 'Bring two questions to the session.', tdstr(-2), 'Medium', 'Completed'),
            (2, 'Submit psychology reflection', 'Reflection draft and final checks.', tdstr(4), 'Medium', 'In Progress'),
            (2, 'AAC check-in', 'Discuss academic progress.', tdstr(7), 'Medium', 'To Do'),
            (3, 'Schedule urgent advisor check-in', 'Review recent academic difficulties.', tdstr(1), 'High', 'To Do'),
            (4, 'Prepare a weekly timetable', 'Review your workload.', tdstr(6), 'Low', 'To Do'),
            (5, 'Complete initial self-assessment', 'Share any learning challenges.', tdstr(2), 'Medium', 'To Do'),
            (6, 'Attend writing support', 'Review research paper outline.', tdstr(6), 'Medium', 'Completed')
        ]
        con.executemany('INSERT INTO tasks(student_id,title,details,due_date,priority,status) VALUES (?,?,?,?,?,?)', tasks)
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
        con.execute('INSERT INTO checkins(student_id,mood,challenge,priority,needs_help) VALUES (?,?,?,?,?)',
                    (1,'Okay','Time management','Finish the mathematics practice set',0))
