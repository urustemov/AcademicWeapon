"""Functional demo tests. Never touches the user's local demo database."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import db
# Must be set before importing app, which seeds the database on startup.
TMP = tempfile.TemporaryDirectory()
db.DB_PATH = Path(TMP.name) / 'test_apss.sqlite3'
from app import app
from fastapi.testclient import TestClient


def test_aac_and_student_permissions():
    with TestClient(app, follow_redirects=False) as staff:
        assert staff.get('/login').status_code==200
        resp=staff.post('/login',data={'email':'advisor@demo.example','password':'Demo1234!'})
        assert resp.status_code==303
        assert staff.get('/aac').status_code==200
        assert staff.get('/aac/students').status_code==200
        assert staff.get('/aac/student/1').status_code==200
        assert staff.get('/student').status_code==403
        token=staff.cookies.get('apss_demo_session')
        assert token is not None
        from itsdangerous import URLSafeSerializer
        from app import signer
        csrf=signer.loads(token)['csrf']
        assert staff.post('/aac/student/1/task',data={'_csrf':csrf,'title':'New test item','due_date':'2026-11-01','priority':'High'}).status_code==303
        assert db.one('SELECT id FROM tasks WHERE title=?',('New test item',))
        assert staff.post('/aac/student/1/goal',data={'_csrf':csrf,'title':'New demo goal','target':'Finish tasks'}).status_code==303
        assert staff.post('/aac/student/1/meeting',data={'_csrf':csrf,'topic':'New demo meeting','date':'2026-11-02'}).status_code==303
        assert staff.post('/aac/student/1/followup',data={'_csrf':csrf,'title':'Test followup','due_date':'2026-11-01','priority':'High'}).status_code==303
        assert staff.post('/aac/student/1/status',data={'_csrf':csrf,'status':'On Track'}).status_code==303
        assert staff.post('/aac/student/1/task',data={'_csrf':'invalid','title':'Bad','due_date':'2026-11-01'}).status_code==403
    with TestClient(app, follow_redirects=False) as student:
        resp=student.post('/login',data={'email':'student@demo.example','password':'Demo1234!'})
        assert resp.status_code==303
        assert student.get('/student').status_code==200
        assert student.get('/student/plan').status_code==200
        assert student.get('/student/checkin').status_code==200
        assert student.get('/student/meetings').status_code==200
        assert student.get('/aac/students').status_code==403
        from app import signer
        csrf=signer.loads(student.cookies['apss_demo_session'])['csrf']
        assert student.post('/student/task/1/status',data={'_csrf':csrf}).status_code==303
        assert student.post('/student/task/8/status',data={'_csrf':csrf}).status_code==404
        assert student.post('/student/checkin',data={'_csrf':csrf,'mood':'Okay','challenge':'Study habits','priority':'Math','needs_help':'yes'}).status_code==303
        assert db.one('SELECT COUNT(*) AS num FROM followups WHERE title LIKE ?',('%requested support%',))['num'] == 1
