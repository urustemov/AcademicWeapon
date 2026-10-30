"""Academic Weapon FastAPI application."""
from __future__ import annotations
import os
from collections import defaultdict, deque
from pathlib import Path
import secrets
import logging
import sqlite3
import requests as external_requests
from datetime import date, datetime, time, timedelta
from time import monotonic
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool


BASE_PATH = Path(__file__).resolve().parent
auth_logger = logging.getLogger('academic_weapon.auth')


def load_local_env():
    """Load simple KEY=VALUE settings without adding another dependency."""
    env_path = BASE_PATH / '.env'
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_local_env()

from db import BASE_DIR, DB_PATH, DEMO_MODE, seed_database, one, all_rows, run, password_verify

try:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token
except ImportError:  # The login page explains that dependencies still need setup.
    google_requests = None
    google_id_token = None

APP_ENV = os.getenv('APP_ENV', 'development').strip().lower()
IS_PRODUCTION = APP_ENV == 'production'
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '').strip()
GOOGLE_WORKSPACE_DOMAIN = os.getenv('GOOGLE_WORKSPACE_DOMAIN', 'auca.kg').strip().lower()
SESSION_TTL_SECONDS = int(os.getenv('SESSION_TTL_SECONDS', str(60 * 60 * 12)))
SESSION_COOKIE_SECURE = os.getenv(
    'SESSION_COOKIE_SECURE', '1' if IS_PRODUCTION else '0'
).strip().lower() in {'1', 'true', 'yes', 'on'}
SESSION_COOKIE_NAME = '__Host-academic_weapon_session' if IS_PRODUCTION else 'apss_demo_session'
ALLOWED_HOSTS = [
    host.strip() for host in os.getenv(
        'ALLOWED_HOSTS', '127.0.0.1,localhost,testserver'
    ).split(',') if host.strip()
]
LOGIN_RATE_LIMIT = int(os.getenv('LOGIN_RATE_LIMIT', '20' if IS_PRODUCTION else '1000'))
LOGIN_RATE_WINDOW_SECONDS = int(os.getenv('LOGIN_RATE_WINDOW_SECONDS', '900'))
ACADEMIC_TIMEZONE = ZoneInfo(os.getenv('ACADEMIC_TIMEZONE', 'Asia/Bishkek'))
CANONICAL_HOST = os.getenv('CANONICAL_HOST', '').strip().lower()
CANONICAL_ALIAS_HOSTS = {
    host.strip().lower() for host in os.getenv('CANONICAL_ALIAS_HOSTS', '').split(',')
    if host.strip()
}
AAC_TRACKER_API_URL = os.getenv(
    'AAC_TRACKER_API_URL',
    'https://script.google.com/macros/s/'
    'AKfycbz4T_jINuAElAm-fvtIRKtj1gVV5teevGL9D1u1dFb4RFJ0GDmkZHFXcf5HxA-52S0OEg/exec',
).strip()

STAFF_GREETINGS = (
    'Welcome back, {name}.',
    'Hi, dear {name}.',
    'How are you today, {name}?',
    'Great to see you, {name}.',
    'You look wonderful today, {name}.',
    'You look sharp today, {name}.',
    'Ready to make a difference, {name}?',
    'Your energy is inspiring, {name}.',
    'Keep up the wonderful work, {name}.',
    'You make support feel personal, {name}.',
    'Another bright day with you, {name}.',
    'Your dedication stands out, {name}.',
    'The team is stronger with you, {name}.',
    "You've got this, {name}.",
    "Here's to a productive day, {name}.",
    'Your kindness makes a difference, {name}.',
    'Nice to see you, {name}.',
    "Let's make today count, {name}.",
    'Your positive attitude shines, {name}.',
)
AAC_TRACKER_API_KEY = os.getenv('AAC_TRACKER_API_KEY', '').strip()


def staff_greeting_name(user: dict) -> str:
    email = str(user.get('email','')).strip().casefold()
    if email == 'atsungur_g@auca.kg':
        return 'Görkem Bey'
    if email == 'karabaev_d@auca.kg':
        return 'Daniyar Agai'
    return (str(user.get('display_name','')).strip().split() or ['there'])[0]

if IS_PRODUCTION:
    if DEMO_MODE:
        raise RuntimeError('APSS_DEMO_MODE must be 0 in production.')
    if not GOOGLE_CLIENT_ID:
        raise RuntimeError('GOOGLE_CLIENT_ID is required in production.')
    if not SESSION_COOKIE_SECURE:
        raise RuntimeError('SESSION_COOKIE_SECURE must be enabled in production.')
    if not DB_PATH.is_absolute():
        raise RuntimeError('APSS_DB_PATH must be an absolute persistent path in production.')
    if not CANONICAL_HOST:
        raise RuntimeError('CANONICAL_HOST is required in production.')
    if CANONICAL_HOST not in ALLOWED_HOSTS:
        raise RuntimeError('CANONICAL_HOST must be included in ALLOWED_HOSTS.')
    if not CANONICAL_ALIAS_HOSTS.issubset(set(ALLOWED_HOSTS)):
        raise RuntimeError('Every CANONICAL_ALIAS_HOSTS entry must be included in ALLOWED_HOSTS.')
    if not 300 <= SESSION_TTL_SECONDS <= 60 * 60 * 24:
        raise RuntimeError('SESSION_TTL_SECONDS must be between 300 and 86400 in production.')
    if LOGIN_RATE_LIMIT < 1 or LOGIN_RATE_WINDOW_SECONDS < 1:
        raise RuntimeError('Login rate-limit settings must be positive in production.')

session_secret = os.getenv('SESSION_SECRET', '').strip()
if not session_secret:
    if IS_PRODUCTION:
        raise RuntimeError('SESSION_SECRET is required in production.')
    secret_path = BASE_DIR / '.apss_local_secret'
    if not secret_path.exists():
        secret_path.write_text(secrets.token_urlsafe(48), encoding='utf-8')
    session_secret = secret_path.read_text(encoding='utf-8').strip()

seed_database()
signer = URLSafeTimedSerializer(
    session_secret,
    # Binding sessions to the selected database prevents a user ID from one
    # environment being reused after switching between demo and real data.
    salt=f'academic-weapon-session:{DB_PATH.resolve()}',
)

app = FastAPI(title='Academic Weapon · AUCA', docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
if IS_PRODUCTION:
    app.add_middleware(HTTPSRedirectMiddleware)
app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')
templates = Jinja2Templates(directory=BASE_DIR / 'templates')


@app.middleware('http')
async def add_security_headers(request: Request, call_next):
    request_host = (request.url.hostname or '').lower()
    if (
        IS_PRODUCTION
        and CANONICAL_HOST
        and request_host in CANONICAL_ALIAS_HOSTS
        and request.url.path != '/healthz'
    ):
        target = f'https://{CANONICAL_HOST}{request.url.path}'
        if request.url.query:
            target = f'{target}?{request.url.query}'
        response = RedirectResponse(target, status_code=308)
    else:
        response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin-allow-popups'
    if not request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store'
    if IS_PRODUCTION:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self' https://accounts.google.com; "
            "script-src 'self' 'unsafe-inline' https://accounts.google.com; "
            "style-src 'self' 'unsafe-inline' https://accounts.google.com; "
            "frame-src https://accounts.google.com; "
            "connect-src 'self' https://accounts.google.com; "
            "img-src 'self' data: https://*.googleusercontent.com; "
            "font-src 'self' data:; upgrade-insecure-requests"
        )
    return response


login_attempts = defaultdict(deque)


def login_client_key(request: Request) -> str:
    return request.client.host if request.client else 'unknown'


def enforce_login_rate_limit(request: Request):
    """Apply a small in-process throttle to authentication endpoints."""
    key = login_client_key(request)
    now = monotonic()
    attempts = login_attempts[key]
    cutoff = now - LOGIN_RATE_WINDOW_SECONDS
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    if len(attempts) >= LOGIN_RATE_LIMIT:
        raise HTTPException(429, 'Too many sign-in attempts. Please wait and try again.')
    attempts.append(now)


def clear_login_rate_limit(request: Request):
    login_attempts.pop(login_client_key(request), None)


def nice_date(value):
    try:
        return datetime.fromisoformat(value).strftime('%b %d, %Y')
    except (TypeError, ValueError):
        return value or '—'


def nice_datetime(value):
    try:
        return datetime.fromisoformat(value).strftime('%b %d, %Y · %H:%M')
    except (TypeError, ValueError):
        return value or '—'


def chat_updates_payload(messages, user_id):
    """Serialize chat rows for the live UI without exposing unrelated fields."""
    return {
        'messages': [
            {
                'id': message['id'],
                'body': message['body'],
                'created_at': message['created_at'],
                'created_label': nice_datetime(message['created_at']),
                'sender_name': 'You' if message['sender_user_id'] == user_id else message['sender_name'],
                'own': message['sender_user_id'] == user_id,
            }
            for message in messages
        ]
    }


def chat_after_id(request):
    try:
        return max(0, int(request.query_params.get('after', '0')))
    except (TypeError, ValueError):
        raise HTTPException(400, 'Invalid message cursor.')


def chat_send_response(request, redirect_url):
    if request.headers.get('x-chat-live') == '1':
        return JSONResponse({'ok': True})
    return bounce(redirect_url)


def initials(value):
    return ''.join(part[:1] for part in value.split()[:2]).upper()


YEAR_LABELS = {
    1: 'Freshman',
    2: 'Sophomore',
    3: 'Junior',
    4: 'Senior',
}

WEEKDAYS = (
    ('Mon', 'Monday'),
    ('Tue', 'Tuesday'),
    ('Wed', 'Wednesday'),
    ('Thu', 'Thursday'),
    ('Fri', 'Friday'),
    ('Sat', 'Saturday'),
    ('Sun', 'Sunday'),
)

COURSE_SLOTS = (
    ('08:00-09:15', '08:00', '09:15', '8:00–9:15'),
    ('09:25-10:40', '09:25', '10:40', '9:25–10:40'),
    ('10:50-12:05', '10:50', '12:05', '10:50–12:05'),
    ('12:45-14:00', '12:45', '14:00', '12:45–14:00'),
    ('14:10-15:25', '14:10', '15:25', '14:10–15:25'),
    ('15:35-17:00', '15:35', '17:00', '15:35–17:00'),
)

STAFF_ROLES = {'advisor', 'advising_team'}
ADVISING_TEAM_GROUP_EMAILS = frozenset({
    'urustemov_s@auca.kg',
    'kydyrgychova_u@auca.kg',
    'tynyeva_a@auca.kg',
    'zhakypov_a@auca.kg',
})
CASE_STATUSES = (
    'Initial Assessment',
    'On Track',
    'Needs Review',
    'Academic Leave',
    'Dismissed',
)
TRACKER_STATUS_OPTIONS = (
    'Resolved','Pending','Waiting for Student','Waiting for Office','Closed',
    "On student's decision",
)


def is_team_group_member(user):
    """The shared channel is restricted to the four named Advising Team members."""
    return bool(
        user
        and user.get('role') == 'advising_team'
        and str(user.get('email', '')).strip().casefold() in ADVISING_TEAM_GROUP_EMAILS
    )


def team_group_unread_count(user):
    if not is_team_group_member(user):
        return 0
    unread = one(
        '''SELECT COUNT(*) AS total FROM team_group_messages
           WHERE sender_user_id<>?
             AND id>COALESCE(
               (SELECT last_read_message_id FROM team_group_reads WHERE user_id=?),0
             )''',
        (user['id'],user['id']),
    )
    return unread['total'] if unread else 0


def academic_now():
    """Current university-local time; separated for predictable tests."""
    return datetime.now(ACADEMIC_TIMEZONE)


def weekly_checkin_state(student_id, now=None):
    """Return the active Monday-based check-in window for a student."""
    now = now or academic_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=ACADEMIC_TIMEZONE)
    else:
        now = now.astimezone(ACADEMIC_TIMEZONE)
    monday = now.date() - timedelta(days=now.weekday())
    opens_at = datetime.combine(monday + timedelta(days=4), time(17, 0), ACADEMIC_TIMEZONE)
    closes_at = datetime.combine(monday + timedelta(days=6), time(23, 59, 59, 999999), ACADEMIC_TIMEZONE)
    week_key = monday.isoformat()
    submission = one(
        'SELECT * FROM checkins WHERE student_id=? AND week_key=? ORDER BY id DESC LIMIT 1',
        (student_id, week_key),
    )
    if submission:
        status = 'completed'
    elif opens_at <= now <= closes_at:
        status = 'open'
    else:
        status = 'closed'
    next_opens_at = (
        opens_at + timedelta(days=7)
        if submission
        else (opens_at if now < opens_at else opens_at + timedelta(days=7))
    )
    return {
        'status': status,
        'is_open': status == 'open',
        'is_completed': status == 'completed',
        'week_key': week_key,
        'submission': submission,
        'opens_at': opens_at,
        'closes_at': closes_at,
        'next_opens_at': next_opens_at,
        'window_label': (
            f"Friday {opens_at.strftime('%b %d')} at 17:00 – "
            f"Sunday {closes_at.strftime('%b %d')} at 23:59"
        ),
        'next_open_label': next_opens_at.strftime('%A, %b %d at %H:%M'),
    }


def create_student_notification(student_id, kind, title, body, link='/student'):
    return run(
        'INSERT INTO notifications(student_id,kind,title,body,link,created_at) VALUES (?,?,?,?,?,?)',
        (student_id, kind, title[:120], body[:300], link, academic_now().isoformat(timespec='seconds')),
    )


def student_notification_context(student_id, now=None):
    rows = all_rows(
        'SELECT * FROM notifications WHERE student_id=? ORDER BY id DESC LIMIT 8',
        (student_id,),
    )
    notifications = [
        {
            **item,
            'is_unread': not item['read_at'],
            'open_link': f"/student/notification/{item['id']}",
        }
        for item in rows
    ]
    state = weekly_checkin_state(student_id, now)
    reminder_active = state['is_open'] and not state['is_completed']
    if reminder_active:
        notifications.insert(0, {
            'id': None,
            'kind': 'checkin',
            'title': 'Weekly Check-in reminder',
            'body': 'Complete this week’s reflection before Sunday at 23:59.',
            'created_at': '',
            'read_at': None,
            'is_unread': True,
            'open_link': '/student/checkin',
        })
    unread_persisted = one(
        'SELECT COUNT(*) AS total FROM notifications WHERE student_id=? AND read_at IS NULL',
        (student_id,),
    )
    persisted_count = unread_persisted['total'] if unread_persisted else 0
    return notifications, persisted_count + int(reminder_active), persisted_count


def year_label(value):
    """Return the student-facing academic standing for a numeric year."""
    try:
        return YEAR_LABELS.get(int(value), str(value))
    except (TypeError, ValueError):
        return value or '—'


templates.env.filters['nice_date'] = nice_date
templates.env.filters['nice_datetime'] = nice_datetime
templates.env.filters['initials'] = initials
templates.env.filters['year_label'] = year_label
templates.env.globals['case_statuses'] = CASE_STATUSES


def current_session(request):
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie:
        return None
    try:
        payload = signer.loads(cookie, max_age=SESSION_TTL_SECONDS)
        if not isinstance(payload, dict) or 'uid' not in payload:
            return None
        user = one('SELECT id,email,display_name,role,student_id,active FROM users WHERE id=?', (payload['uid'],))
        if user and user['active']:
            return {'user':user,'csrf':payload.get('csrf','')}
    except BadSignature:
        return None
    return None


def gate(request, role=None):
    session = current_session(request)
    if not session:
        return None
    if role and session['user']['role'] != role:
        raise HTTPException(403,'This account cannot access that page.')
    return session


def gate_staff(request):
    session = gate(request)
    if not session:
        return None
    if session['user']['role'] not in STAFF_ROLES:
        raise HTTPException(403,'This account cannot access that page.')
    return session


def allowed_student(student_id, session):
    student = one('SELECT * FROM students WHERE id=? AND active=1',(student_id,))
    if not student:
        raise HTTPException(404,'Student not found')
    if (
        session['user']['role'] == 'advisor'
        and student['advisor'].strip().casefold() != session['user']['display_name'].strip().casefold()
    ):
        raise HTTPException(403,'Advisors can access only their assigned advisees.')
    return student


def can_edit_meeting(meeting, user):
    """Return whether this staff user owns the meeting's edit scope."""
    if meeting.get('owner_role') == 'advisor':
        return user['role'] == 'advisor' and meeting.get('created_by_user_id') == user['id']
    return user['role'] == 'advising_team'


def require_meeting_editor(meeting, user):
    if not can_edit_meeting(meeting, user):
        if meeting.get('owner_role') == 'advisor':
            detail = 'Only the Advisor who scheduled this meeting can edit it.'
        else:
            detail = 'Only Advising Team members can edit this meeting.'
        raise HTTPException(403, detail)


def staff_student_filter(session, table_alias=''):
    """SQL suffix and params limiting an Advisor to assigned advisees."""
    if session['user']['role'] == 'advising_team':
        return '', []
    prefix = f'{table_alias}.' if table_alias else ''
    return f' AND LOWER({prefix}advisor)=LOWER(?)', [session['user']['display_name']]


def verify_csrf(request, session, form):
    if not session or not secrets.compare_digest(str(form.get('_csrf','')),str(session['csrf'])):
        raise HTTPException(403, 'Invalid form verification token. Refresh the page and retry.')


def page(request, template, **data):
    session = current_session(request)
    user = session['user'] if session else None
    unread_chat_count = 0
    notifications = []
    unread_notification_count = 0
    unread_persisted_notification_count = 0
    if user and user['role'] == 'student' and user['student_id']:
        unread = one(
            'SELECT COUNT(*) AS total FROM chat_messages WHERE student_id=? AND read_by_student=0',
            (user['student_id'],),
        )
        unread_chat_count = unread['total'] if unread else 0
        notifications, unread_notification_count, unread_persisted_notification_count = student_notification_context(user['student_id'])
    elif user and user['role'] in STAFF_ROLES:
        if user['role'] == 'advising_team':
            unread = one(
                '''SELECT COUNT(*) AS total FROM chat_messages
                   WHERE read_by_aac=0 AND staff_user_id=?''',
                (user['id'],),
            )
        else:
            unread = one(
                '''SELECT COUNT(*) AS total FROM chat_messages m
                   JOIN students s ON s.id=m.student_id
                   WHERE m.read_by_aac=0 AND m.staff_user_id=?
                     AND LOWER(s.advisor)=LOWER(?)''',
                (user['id'],user['display_name']),
            )
        unread_chat_count = unread['total'] if unread else 0
        internal_unread = one(
            '''SELECT COUNT(*) AS total FROM staff_messages
               WHERE recipient_user_id=? AND read_at IS NULL''',
            (user['id'],),
        )
        unread_chat_count += internal_unread['total'] if internal_unread else 0
        unread_chat_count += team_group_unread_count(user)
    return templates.TemplateResponse(request=request,name=template,context={
        'user':user, 'csrf':session['csrf'] if session else '',
        'today':academic_now().date().isoformat(), 'active':data.pop('active',''),
        'google_client_id':GOOGLE_CLIENT_ID,
        'google_login_uri':str(request.url_for('google_login')) if GOOGLE_CLIENT_ID else '',
        'google_workspace_domain':GOOGLE_WORKSPACE_DOMAIN,
        'demo_mode':DEMO_MODE,
        'local_login_enabled':DEMO_MODE and not IS_PRODUCTION,
        'unread_chat_count':unread_chat_count,
        'notifications':notifications,
        'unread_notification_count':unread_notification_count,
        'unread_persisted_notification_count':unread_persisted_notification_count,
        **data
    })


def bounce(path):
    return RedirectResponse(path, status_code=303)


def record(uid,event):
    run('INSERT INTO audit_logs(user_id,event) VALUES (?,?)',(uid,event))


def tracker_api_call(action,user,payload=None):
    """Call the private Apps Script bridge without exposing its key to browsers."""
    if not AAC_TRACKER_API_KEY:
        raise HTTPException(503,'AAC Tracker connection is not configured yet.')
    request_body={
        'apiKey':AAC_TRACKER_API_KEY,
        'action':str(action),
        'actorEmail':user['email'],
        'payload':payload or {},
    }
    try:
        response=external_requests.post(
            AAC_TRACKER_API_URL,json=request_body,timeout=(5,30),allow_redirects=True,
            headers={'Accept':'application/json','User-Agent':'AcademicWeapon/1.0'},
        )
    except external_requests.RequestException as exc:
        auth_logger.warning('AAC Tracker API request failed: %s',type(exc).__name__)
        raise HTTPException(502,'AAC Tracker is temporarily unavailable. Please try again.')
    if 'accounts.google.com' in response.url:
        raise HTTPException(503,'AAC Tracker API deployment still requires interactive Google sign-in.')
    try:
        result=response.json()
    except ValueError:
        auth_logger.warning('AAC Tracker returned a non-JSON response with status %s',response.status_code)
        raise HTTPException(502,'AAC Tracker returned an unexpected response.')
    if response.status_code>=400:
        raise HTTPException(502,'AAC Tracker could not complete the request.')
    if not isinstance(result,dict) or not result.get('ok'):
        message=str(result.get('error','AAC Tracker request failed.'))[:240] if isinstance(result,dict) else 'AAC Tracker request failed.'
        raise HTTPException(400,message)
    return result.get('data')


def tracker_api_session(request):
    session=gate(request,'advising_team')
    if not session:
        raise HTTPException(401,'Sign-in required.')
    return session


def clean_tracker_visit_payload(payload):
    if not isinstance(payload,dict):
        raise HTTPException(400,'Invalid visit data.')
    topics=payload.get('topics',[])
    if not isinstance(topics,list):
        raise HTTPException(400,'Select at least one topic.')
    cleaned={
        'advisor':str(payload.get('advisor','')).strip()[:120],
        'studentId':str(payload.get('studentId','')).strip()[:40],
        'topics':[str(topic).strip()[:160] for topic in topics[:12] if str(topic).strip()],
        'question':str(payload.get('question','')).strip()[:3000],
        'action':str(payload.get('action','')).strip()[:3000],
        'followUp':str(payload.get('followUp','No')).strip()[:20],
        'followUpDate':str(payload.get('followUpDate','')).strip()[:20],
        'status':str(payload.get('status','Resolved')).strip()[:80],
        'notes':str(payload.get('notes','')).strip()[:5000],
    }
    if not cleaned['studentId'] or not cleaned['topics'] or not cleaned['question'] or not cleaned['action']:
        raise HTTPException(400,'Student, topic, situation, and action are required.')
    if cleaned['followUp'] not in {'Yes','No'}:
        raise HTTPException(400,'Invalid follow-up selection.')
    if cleaned['followUp']=='Yes' and not cleaned['followUpDate']:
        raise HTTPException(400,'Follow-up date is required.')
    if cleaned['followUpDate']:
        try:date.fromisoformat(cleaned['followUpDate'])
        except ValueError:raise HTTPException(400,'Enter a valid follow-up date.')
    return cleaned


def activity_rows(user, limit=50):
    """Return the audit scope allowed for the current staff role."""
    select_sql = '''SELECT a.*,COALESCE(u.display_name,'Unknown user') AS actor_name,
                           COALESCE(u.role,'unknown') AS actor_role,
                           s.student_code AS actor_student_code
                    FROM audit_logs a
                    LEFT JOIN users u ON u.id=a.user_id
                    LEFT JOIN students s ON s.id=u.student_id'''
    if user['role'] == 'advising_team':
        return all_rows(select_sql+' ORDER BY a.id DESC LIMIT ?',(limit,))
    return all_rows(
        select_sql+'''
          WHERE a.user_id=?
             OR (u.role='student' AND s.active=1 AND LOWER(s.advisor)=LOWER(?))
          ORDER BY a.id DESC LIMIT ?''',
        (user['id'],user['display_name'],limit),
    )


def refresh_credit_load(student_id):
    """Keep the student credit load equal to the sum of scheduled courses."""
    total=one('SELECT COALESCE(SUM(credits),0) AS total FROM schedule_courses WHERE student_id=?',(student_id,))
    run('UPDATE students SET credit_load=? WHERE id=?',(total['total'],student_id))


def issue_session(user):
    token=signer.dumps({'uid':user['id'],'csrf':secrets.token_urlsafe(24)})
    response=bounce('/student' if user['role']=='student' else '/aac')
    response.set_cookie(
        SESSION_COOKIE_NAME, token, max_age=SESSION_TTL_SECONDS,
        httponly=True, samesite='lax', secure=SESSION_COOKIE_SECURE, path='/'
    )
    return response


def verify_google_credential(credential: str):
    if not GOOGLE_CLIENT_ID:
        raise RuntimeError('Google sign-in is not configured.')
    if google_id_token is None or google_requests is None:
        raise RuntimeError('Google authentication dependency is not installed.')
    return google_id_token.verify_oauth2_token(
        credential,
        google_requests.Request(),
        GOOGLE_CLIENT_ID,
    )


@app.get('/')
def index(request:Request):
    session=gate(request)
    return bounce('/student' if session['user']['role']=='student' else '/aac') if session else bounce('/login')


@app.get('/healthz', include_in_schema=False)
def healthz():
    try:
        database=one('SELECT 1 AS healthy')
    except sqlite3.Error as error:
        auth_logger.error('Database health check failed: %s', type(error).__name__)
        raise HTTPException(503, 'Service unavailable') from error
    if not database or database['healthy'] != 1:
        raise HTTPException(503, 'Service unavailable')
    return {'status':'ok'}


@app.get('/login')
def login_page(request:Request):
    if gate(request):return bounce('/')
    error_codes = {
        'google_unavailable': 'Google sign-in is not configured yet.',
        'google_invalid': 'Google could not verify this sign-in. Please try again.',
        'wrong_domain': f'Use your {GOOGLE_WORKSPACE_DOMAIN} Google account.',
        'not_enrolled': 'This email is not on the current Academic Probation access list.',
        'inactive': 'This account is not active. Please contact the AAC.',
    }
    return page(request,'login.html',error=error_codes.get(request.query_params.get('error','')))


@app.post('/login')
async def login_action(request:Request):
    if not DEMO_MODE or IS_PRODUCTION:
        raise HTTPException(404, 'Local password sign-in is disabled.')
    enforce_login_rate_limit(request)
    form=await request.form()
    email=str(form.get('email','')).strip().lower()
    password=str(form.get('password',''))
    user=one('SELECT * FROM users WHERE email=?',(email,))
    if not user or not password_verify(password,user['password_hash']):
        return templates.TemplateResponse(request=request,name='login.html',context={
            'user':None,'active':'','csrf':'','today':date.today().isoformat(),
            'google_client_id':GOOGLE_CLIENT_ID,
            'google_login_uri':str(request.url_for('google_login')) if GOOGLE_CLIENT_ID else '',
            'google_workspace_domain':GOOGLE_WORKSPACE_DOMAIN,
            'demo_mode':DEMO_MODE,
            'local_login_enabled':True,
            'error':'Email or password is incorrect.'},status_code=401)
    if not user.get('active', 1):
        return bounce('/login?error=inactive')
    clear_login_rate_limit(request)
    return issue_session(user)


@app.post('/auth/google', name='google_login')
async def google_login(request:Request):
    if not GOOGLE_CLIENT_ID:
        return bounce('/login?error=google_unavailable')
    enforce_login_rate_limit(request)
    form=await request.form()
    csrf_form=str(form.get('g_csrf_token',''))
    csrf_cookie=str(request.cookies.get('g_csrf_token',''))
    if not csrf_form or not csrf_cookie or not secrets.compare_digest(csrf_form,csrf_cookie):
        raise HTTPException(400,'Invalid Google sign-in verification token.')
    credential=str(form.get('credential',''))
    try:
        identity=verify_google_credential(credential)
    except (ValueError, RuntimeError) as error:
        # Never log the credential itself. The exception contains only the
        # verification reason (expiry, audience, certificate, and so on).
        auth_logger.warning(
            'Google credential verification failed: %s: %s',
            type(error).__name__,
            error,
        )
        return bounce('/login?error=google_invalid')

    hosted_domain=str(identity.get('hd','')).strip().lower()
    email=str(identity.get('email','')).strip().lower()
    google_sub=str(identity.get('sub','')).strip()
    if hosted_domain != GOOGLE_WORKSPACE_DOMAIN or not identity.get('email_verified'):
        return bounce('/login?error=wrong_domain')
    if not email or not google_sub:
        return bounce('/login?error=google_invalid')

    user=one('SELECT * FROM users WHERE LOWER(email)=?',(email,))
    if not user:
        return bounce('/login?error=not_enrolled')
    if not user['active']:
        return bounce('/login?error=inactive')
    if user['role']=='student':
        student=one('SELECT id,active FROM students WHERE id=?',(user['student_id'],))
        if not student or not student['active']:
            return bounce('/login?error=inactive')
    linked_user=one('SELECT id FROM users WHERE google_sub=?',(google_sub,))
    if linked_user and linked_user['id']!=user['id']:
        return bounce('/login?error=google_invalid')
    if user.get('google_sub') and not secrets.compare_digest(user['google_sub'],google_sub):
        return bounce('/login?error=google_invalid')
    if not user.get('google_sub'):
        run('UPDATE users SET google_sub=? WHERE id=?',(google_sub,user['id']))
    record(user['id'],'Signed in with Google Workspace')
    clear_login_rate_limit(request)
    return issue_session(user)


@app.post('/logout')
async def logout(request:Request):
    session=gate(request)
    if session:
        verify_csrf(request,session,await request.form())
    response=bounce('/login')
    response.delete_cookie(
        SESSION_COOKIE_NAME, path='/', secure=SESSION_COOKIE_SECURE, samesite='lax'
    )
    return response


@app.get('/student')
def student_home(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    sid=session['user']['student_id']
    student=one('SELECT * FROM students WHERE id=?',(sid,))
    goals=all_rows('SELECT * FROM goals WHERE student_id=? ORDER BY id',(sid,))
    tasks=all_rows('SELECT * FROM tasks WHERE student_id=? ORDER BY CASE WHEN status="Completed" THEN 1 ELSE 0 END,due_date',(sid,))
    meetings=all_rows('SELECT * FROM meetings WHERE student_id=? AND date>=? ORDER BY date LIMIT 3',(sid,date.today().isoformat()))
    completed=sum(1 for x in tasks if x['status']=='Completed')
    return page(request,'student_home.html',active='student_home',student=student,goals=goals,tasks=tasks[:5],meetings=meetings,completed=completed,total=len(tasks),pct=round(completed/max(len(tasks),1)*100),checkin_state=weekly_checkin_state(sid))


@app.get('/student/plan')
def student_plan(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    sid=session['user']['student_id']
    student=one('SELECT * FROM students WHERE id=?',(sid,))
    goals=all_rows('SELECT * FROM goals WHERE student_id=?',(sid,))
    tasks=all_rows('SELECT * FROM tasks WHERE student_id=? ORDER BY due_date',(sid,))
    completed=sum(x['status']=='Completed' for x in tasks)
    return page(request,'plan.html',active='student_plan',student=student,goals=goals,tasks=tasks,completed=completed,pct=round(completed/max(len(tasks),1)*100),is_aac=False)


def build_schedule_context(student_id:int,raw_week:str=''):
    """Build the shared weekly timetable used by students and AAC staff."""
    try:selected_day=date.fromisoformat(raw_week) if raw_week else date.today()
    except ValueError:selected_day=date.today()
    week_start=selected_day-timedelta(days=selected_day.weekday())
    week_end=week_start+timedelta(days=6)
    student=one('SELECT * FROM students WHERE id=?',(student_id,))
    if not student:raise HTTPException(404,'Student not found')
    courses=all_rows('SELECT * FROM schedule_courses WHERE student_id=? ORDER BY start_time,name COLLATE NOCASE',(student_id,))
    meetings=all_rows(
        'SELECT * FROM meetings WHERE student_id=? AND date BETWEEN ? AND ? ORDER BY date,time,topic COLLATE NOCASE',
        (student_id,week_start.isoformat(),week_end.isoformat()),
    )
    days=[]
    for offset,(code,label) in enumerate(WEEKDAYS):
        calendar_day=week_start+timedelta(days=offset)
        days.append({
            'code':code,'label':label,'date':calendar_day.isoformat(),
            'date_label':calendar_day.strftime('%b %d'),'is_today':calendar_day==date.today(),
            'entries':[],
        })
    day_by_code={day['code']:day for day in days}

    def time_minutes(value):
        try:
            hour,minute=value.split(':',1)
            return int(hour)*60+int(minute)
        except (AttributeError,TypeError,ValueError):
            return 24*60+1

    schedule_rows=[]
    rows_by_key={}
    for slot_id,start_time,end_time,label in COURSE_SLOTS:
        row={
            'key':slot_id,'label':label,'kind':'fixed','sort_order':time_minutes(start_time),
            'cells':{code:[] for code,_ in WEEKDAYS},
        }
        schedule_rows.append(row)
        rows_by_key[slot_id]=row

    def custom_row(key,label,sort_order,kind='custom'):
        if key not in rows_by_key:
            row={
                'key':key,'label':label,'kind':kind,'sort_order':sort_order,
                'cells':{code:[] for code,_ in WEEKDAYS},
            }
            schedule_rows.append(row)
            rows_by_key[key]=row
        return rows_by_key[key]

    for course in courses:
        entry={'kind':'course',**course,'sort_time':course['start_time']}
        exact_slot=next(
            (slot for slot in COURSE_SLOTS if slot[1]==course['start_time'] and slot[2]==course['end_time']),
            None,
        )
        if exact_slot:
            row=rows_by_key[exact_slot[0]]
        else:
            row=custom_row(
                f"course-{course['start_time']}-{course['end_time']}",
                f"{course['start_time']}–{course['end_time']}",
                time_minutes(course['start_time']),
            )
        for code in course['days'].split(','):
            if code in day_by_code:
                day_by_code[code]['entries'].append(entry)
                row['cells'][code].append(entry)

    for meeting in meetings:
        try:day_offset=(date.fromisoformat(meeting['date'])-week_start).days
        except ValueError:continue
        if not 0<=day_offset<len(days):continue
        code=days[day_offset]['code']
        entry={'kind':'meeting',**meeting,'sort_time':meeting['time'] or '99:99'}
        day_by_code[code]['entries'].append(entry)
        if not meeting['time']:
            row=custom_row('unscheduled','Time not set',24*60+1,'unscheduled')
        else:
            containing_slot=next(
                (slot for slot in COURSE_SLOTS if slot[1]<=meeting['time']<slot[2]),
                None,
            )
            if containing_slot:
                row=rows_by_key[containing_slot[0]]
            else:
                row=custom_row(
                    f"meeting-{meeting['time']}",meeting['time'],time_minutes(meeting['time'])
                )
        row['cells'][code].append(entry)

    for day in days:
        day['entries'].sort(key=lambda item:(item['sort_time'],0 if item['kind']=='meeting' else 1))
    for row in schedule_rows:
        for entries in row['cells'].values():
            entries.sort(key=lambda item:(item['sort_time'],0 if item['kind']=='meeting' else 1))
    schedule_rows.sort(key=lambda row:(row['sort_order'],0 if row['kind']=='fixed' else 1,row['label']))
    return dict(
        student=student,courses=courses,days=days,weekdays=WEEKDAYS,course_slots=COURSE_SLOTS,
        schedule_rows=schedule_rows,week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        week_title=f"{week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}",
        previous_week=(week_start-timedelta(days=7)).isoformat(),
        next_week=(week_start+timedelta(days=7)).isoformat(),
        current_week=(date.today()-timedelta(days=date.today().weekday())).isoformat(),
    )


@app.get('/student/schedule')
def student_schedule(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    context=build_schedule_context(
        session['user']['student_id'],request.query_params.get('week','')
    )
    return page(
        request,'schedule.html',active='student_schedule',schedule_readonly=False,
        schedule_url='/student/schedule',profile_url='',**context,
    )


def chat_contacts(student):
    """Available people a student may contact, with their personal advisor first."""
    staff = all_rows(
        '''SELECT id,email,display_name,role FROM users
           WHERE active=1 AND role IN ('advisor','advising_team')
           ORDER BY display_name COLLATE NOCASE'''
    )
    advisor_name = student['advisor'].strip()
    team_order = {
        'kydyrgychova_u@auca.kg': 0,
        'tynyeva_a@auca.kg': 1,
        'zhakypov_a@auca.kg': 2,
        'urustemov_s@auca.kg': 3,
    }
    contacts = []
    advisor_found = False
    for person in staff:
        is_personal = person['display_name'].strip().casefold() == advisor_name.casefold()
        if person['role'] == 'advisor' and not is_personal:
            continue
        advisor_found = advisor_found or is_personal
        contacts.append({**person,'available':True,'is_personal':is_personal})
    contacts.sort(key=lambda item:(
        not item['is_personal'],
        item['role']!='advisor',
        team_order.get(item['email'].casefold(),99),
        item['display_name'].casefold(),
    ))
    if advisor_name and advisor_name.casefold() != 'aac advising team' and not advisor_found:
        contacts.insert(0,{
            'id':None,'email':'','display_name':advisor_name,'role':'advisor',
            'available':False,'is_personal':True,
        })
    return contacts


def select_chat_contact(contacts, requested_id=None, preferred_id=None):
    available = [contact for contact in contacts if contact['available']]
    try:
        requested_id = int(requested_id) if requested_id not in (None,'') else None
    except (TypeError,ValueError):
        requested_id = None
    for contact in available:
        if contact['id'] == requested_id:
            return contact
    for contact in available:
        if contact['id'] == preferred_id:
            return contact
    return available[0] if available else None


def staff_chat_contact(student, user, requested_id=None):
    """Return only this staff member's private thread for the student."""
    own_contact = next(
        (
            contact for contact in chat_contacts(student)
            if contact['available'] and contact['id'] == user['id']
        ),
        None,
    )
    if not own_contact:
        raise HTTPException(403,'You do not have a private chat channel with this student.')
    if requested_id not in (None,''):
        try:
            requested_id = int(requested_id)
        except (TypeError,ValueError):
            raise HTTPException(403,'You cannot access another staff member’s conversation.')
        if requested_id != user['id']:
            raise HTTPException(403,'You cannot access another staff member’s conversation.')
    return own_contact


def chat_thread(student_id:int, staff_user_id:int):
    return all_rows('''
        SELECT m.*,u.display_name AS sender_name,u.role AS sender_role
        FROM chat_messages m
        JOIN users u ON u.id=m.sender_user_id
        WHERE m.student_id=? AND m.staff_user_id=?
        ORDER BY m.id
    ''',(student_id,staff_user_id))


def internal_staff_peer(user, peer_id):
    try:
        peer_id = int(peer_id)
    except (TypeError,ValueError):
        raise HTTPException(404,'Staff contact not found.')
    peer = one(
        '''SELECT id,email,display_name,role FROM users
           WHERE id=? AND active=1 AND role IN ('advisor','advising_team')''',
        (peer_id,),
    )
    allowed_pair = (
        peer
        and peer['id'] != user['id']
        and 'advising_team' in {user['role'],peer['role']}
    )
    if not allowed_pair:
        raise HTTPException(
            403,
            'Internal chat is available between Advising Team members and their Advisor contacts.',
        )
    return peer


def internal_staff_contacts(user):
    if user['role'] == 'advising_team':
        contacts = all_rows(
            '''SELECT id,email,display_name,role FROM users
               WHERE active=1 AND role IN ('advisor','advising_team') AND id<>?
               ORDER BY role='advising_team' DESC,display_name COLLATE NOCASE''',
            (user['id'],),
        )
    else:
        contacts = all_rows(
            '''SELECT id,email,display_name,role FROM users
               WHERE active=1 AND role='advising_team'
               ORDER BY display_name COLLATE NOCASE'''
        )
    for contact in contacts:
        last = one(
            '''SELECT body,created_at FROM staff_messages
               WHERE (sender_user_id=? AND recipient_user_id=?)
                  OR (sender_user_id=? AND recipient_user_id=?)
               ORDER BY id DESC LIMIT 1''',
            (user['id'],contact['id'],contact['id'],user['id']),
        )
        unread = one(
            '''SELECT COUNT(*) AS total FROM staff_messages
               WHERE sender_user_id=? AND recipient_user_id=? AND read_at IS NULL''',
            (contact['id'],user['id']),
        )
        contact['last_message'] = last['body'] if last else ''
        contact['last_message_at'] = last['created_at'] if last else ''
        contact['unread_count'] = unread['total'] if unread else 0
    contacts.sort(key=lambda contact:(
        not bool(contact['unread_count']),
        not bool(contact['last_message_at']),
        contact['display_name'].casefold(),
    ))
    return contacts


def team_group_context(user):
    if not is_team_group_member(user):
        return None
    placeholders = ','.join('?' for _ in ADVISING_TEAM_GROUP_EMAILS)
    members = all_rows(
        f'''SELECT id,email,display_name FROM users
            WHERE active=1 AND role='advising_team'
              AND LOWER(email) IN ({placeholders})
            ORDER BY display_name COLLATE NOCASE''',
        tuple(sorted(ADVISING_TEAM_GROUP_EMAILS)),
    )
    latest = one(
        '''SELECT m.body,m.created_at,u.display_name AS sender_name
           FROM team_group_messages m
           JOIN users u ON u.id=m.sender_user_id
           ORDER BY m.id DESC LIMIT 1'''
    )
    return {
        'members':members,
        'member_names':', '.join(member['display_name'] for member in members),
        'last_message':latest['body'] if latest else '',
        'last_message_at':latest['created_at'] if latest else '',
        'last_sender':latest['sender_name'] if latest else '',
        'unread_count':team_group_unread_count(user),
    }


@app.get('/student/chat')
def student_chat(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    sid=session['user']['student_id']
    student=one('SELECT * FROM students WHERE id=? AND active=1',(sid,))
    if not student:raise HTTPException(404,'Student not found')
    contacts=chat_contacts(student)
    selected_contact=select_chat_contact(contacts,request.query_params.get('contact'))
    if not selected_contact:raise HTTPException(503,'No advising contacts are available yet.')
    run(
        '''UPDATE chat_messages SET read_by_student=1
           WHERE student_id=? AND staff_user_id=? AND read_by_student=0''',
        (sid,selected_contact['id']),
    )
    return page(
        request,'chat.html',active='student_chat',student=student,
        messages=chat_thread(sid,selected_contact['id']),contacts=contacts,selected_contact=selected_contact,
        chat_action='/student/chat',
        chat_live_url=f'/student/chat/updates?contact={selected_contact["id"]}',
        back_url='/student',back_label='Back to Dashboard',is_aac=False,
    )


@app.get('/student/chat/updates')
def student_chat_updates(request:Request):
    session=gate(request,'student')
    if not session:raise HTTPException(401,'Sign-in required.')
    sid=session['user']['student_id']
    student=one('SELECT * FROM students WHERE id=? AND active=1',(sid,))
    if not student:raise HTTPException(404,'Student not found')
    selected_contact=select_chat_contact(chat_contacts(student),request.query_params.get('contact'))
    if not selected_contact:raise HTTPException(400,'Choose an available advising contact.')
    messages=all_rows(
        '''SELECT m.*,u.display_name AS sender_name
           FROM chat_messages m JOIN users u ON u.id=m.sender_user_id
           WHERE m.student_id=? AND m.staff_user_id=? AND m.id>?
           ORDER BY m.id''',
        (sid,selected_contact['id'],chat_after_id(request)),
    )
    if messages:
        run(
            '''UPDATE chat_messages SET read_by_student=1
               WHERE student_id=? AND staff_user_id=? AND read_by_student=0''',
            (sid,selected_contact['id']),
        )
    return JSONResponse(chat_updates_payload(messages,session['user']['id']))


@app.post('/student/chat')
async def student_send_chat(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    sid=session['user']['student_id']
    student=one('SELECT * FROM students WHERE id=? AND active=1',(sid,))
    if not student:raise HTTPException(404,'Student not found')
    contacts=chat_contacts(student)
    selected_contact=select_chat_contact(contacts,form.get('contact'))
    if not selected_contact:raise HTTPException(400,'Choose an available advising contact.')
    body=str(form.get('body','')).strip()
    if not body:raise HTTPException(400,'Message cannot be empty')
    if len(body)>2000:raise HTTPException(400,'Message is too long')
    run(
        '''INSERT INTO chat_messages
           (student_id,staff_user_id,sender_user_id,body,created_at,read_by_student,read_by_aac)
           VALUES (?,?,?,?,?,1,0)''',
        (sid,selected_contact['id'],session['user']['id'],body,academic_now().isoformat(timespec='seconds')),
    )
    record(session['user']['id'],f'Sent a chat message to {selected_contact["display_name"]}')
    return chat_send_response(
        request,f'/student/chat?contact={selected_contact["id"]}#latest'
    )


@app.post('/student/schedule/course')
async def student_add_schedule_course(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    sid=session['user']['student_id']
    name=str(form.get('name','')).strip()[:120]
    room=str(form.get('room','')).strip()[:60]
    instructor=str(form.get('instructor','')).strip()[:100]
    slot_id=str(form.get('time_slot','')).strip()
    slot=next((slot for slot in COURSE_SLOTS if slot[0]==slot_id),None)
    selected_days=set(form.getlist('days'))
    days=[code for code,_ in WEEKDAYS if code in selected_days]
    try:
        credits=int(str(form.get('credits','')).strip())
    except (TypeError,ValueError):
        raise HTTPException(400,'Enter valid course credits.')
    if not name or not room or not instructor or not days or not slot:
        raise HTTPException(400,'Complete all course fields and select at least one day.')
    if not 1<=credits<=12:
        raise HTTPException(400,'Credits must be between 1 and 12.')
    _,start_time,end_time,_=slot
    run(
        'INSERT INTO schedule_courses(student_id,name,credits,room,instructor,days,start_time,end_time) VALUES (?,?,?,?,?,?,?,?)',
        (sid,name,credits,room,instructor,','.join(days),start_time,end_time),
    )
    refresh_credit_load(sid)
    record(session['user']['id'],f'Added course to schedule: {name}')
    week=str(form.get('week','')).strip()
    try:week=date.fromisoformat(week).isoformat() if week else ''
    except ValueError:week=''
    return bounce('/student/schedule'+(f'?week={week}' if week else ''))


@app.post('/student/schedule/course/{course_id}/delete')
async def student_delete_schedule_course(course_id:int,request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    sid=session['user']['student_id']
    course=one('SELECT * FROM schedule_courses WHERE id=? AND student_id=?',(course_id,sid))
    if not course:raise HTTPException(404,'Course not found')
    run('DELETE FROM schedule_courses WHERE id=?',(course_id,))
    refresh_credit_load(sid)
    record(session['user']['id'],f'Removed course from schedule: {course["name"]}')
    week=str(form.get('week','')).strip()
    try:week=date.fromisoformat(week).isoformat() if week else ''
    except ValueError:week=''
    return bounce('/student/schedule'+(f'?week={week}' if week else ''))


@app.post('/student/task/{task_id}/status')
async def student_task_status(task_id:int, request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    task=one('SELECT * FROM tasks WHERE id=? AND student_id=?',(task_id,session['user']['student_id']))
    if not task:raise HTTPException(404)
    status='Completed' if task['status']!='Completed' else 'To Do'
    run('UPDATE tasks SET status=? WHERE id=?',(status,task_id))
    record(session['user']['id'],f'Updated task status: {task["title"]} → {status}')
    return bounce('/student/plan#tasks')


@app.post('/student/task')
async def student_create_task(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    sid=session['user']['student_id']
    title=str(form.get('title','')).strip()
    details=str(form.get('details','')).strip()
    due_date=str(form.get('due_date','')).strip()
    priority=str(form.get('priority','Medium')).strip()
    status=str(form.get('status','To Do')).strip()
    if not title or not due_date:return bounce('/student/plan#tasks')
    if priority not in ('Low','Medium','High'):priority='Medium'
    if status not in ('To Do','In Progress','Completed'):status='To Do'
    run('INSERT INTO tasks(student_id,title,details,due_date,priority,status,source) VALUES (?,?,?,?,?,?,?)',
        (sid,title,details,due_date,priority,status,'student'))
    record(session['user']['id'],f'Student created own task: {title}')
    return bounce('/student/plan#tasks')


@app.post('/student/task/{task_id}/edit')
async def student_edit_task(task_id:int, request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    sid=session['user']['student_id']
    task=one('SELECT * FROM tasks WHERE id=? AND student_id=?',(task_id,sid))
    if not task:raise HTTPException(404)
    title=str(form.get('title',task['title'])).strip() or task['title']
    details=str(form.get('details',task['details'])).strip()
    due_date=str(form.get('due_date',task['due_date'])).strip() or task['due_date']
    priority=str(form.get('priority',task['priority'])).strip()
    status=str(form.get('status',task['status'])).strip()
    if priority not in ('Low','Medium','High'):priority=task['priority']
    if status not in ('To Do','In Progress','Completed'):status=task['status']
    run('UPDATE tasks SET title=?,details=?,due_date=?,priority=?,status=? WHERE id=?',
        (title,details,due_date,priority,status,task_id))
    record(session['user']['id'],f'Edited task: {title}')
    return bounce('/student/plan#tasks')


@app.post('/student/task/{task_id}/update_fields')
async def student_update_task_fields(task_id:int, request:Request):
    """Quick inline update: priority and/or status only."""
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    sid=session['user']['student_id']
    task=one('SELECT * FROM tasks WHERE id=? AND student_id=?',(task_id,sid))
    if not task:raise HTTPException(404)
    priority=str(form.get('priority',task['priority'])).strip()
    status=str(form.get('status',task['status'])).strip()
    if priority not in ('Low','Medium','High'):priority=task['priority']
    if status not in ('To Do','In Progress','Completed'):status=task['status']
    run('UPDATE tasks SET priority=?,status=? WHERE id=?',(priority,status,task_id))
    record(session['user']['id'],f'Updated task: {task["title"]} · {priority}/{status}')
    return bounce('/student/plan#tasks')


@app.post('/student/task/{task_id}/delete')
async def student_delete_task(task_id:int, request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    sid=session['user']['student_id']
    task=one('SELECT * FROM tasks WHERE id=? AND student_id=?',(task_id,sid))
    if not task:raise HTTPException(404)
    run('DELETE FROM tasks WHERE id=?',(task_id,))
    record(session['user']['id'],f'Deleted task: {task["title"]}')
    return bounce('/student/plan#tasks')


@app.get('/student/checkin')
def student_checkin(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    sid=session['user']['student_id']
    recent=all_rows('SELECT * FROM checkins WHERE student_id=? ORDER BY id DESC LIMIT 5',(sid,))
    return page(request,'checkin.html',active='student_checkin',recent=recent,success=request.query_params.get('sent')=='1',checkin_state=weekly_checkin_state(sid))


@app.post('/student/checkin')
async def student_checkin_action(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    sid=session['user']['student_id']
    checkin_state=weekly_checkin_state(sid)
    if checkin_state['is_completed']:
        raise HTTPException(409,'This week’s check-in has already been submitted.')
    if not checkin_state['is_open']:
        raise HTTPException(403,'Weekly Check-in is available Friday 17:00 through Sunday 23:59, Bishkek time.')
    mood=str(form.get('mood',''))
    if mood not in ('Good','Okay','Difficult'):raise HTTPException(400,'Select a check-in rating')
    challenge=str(form.get('challenge','')).strip()[:300]
    priority=str(form.get('priority','')).strip()[:300]
    help_requested=1 if form.get('needs_help')=='yes' else 0
    try:
        run('INSERT INTO checkins(student_id,mood,challenge,priority,needs_help,week_key,created_at) VALUES (?,?,?,?,?,?,?)',
            (sid,mood,challenge,priority,help_requested,checkin_state['week_key'],academic_now().isoformat(timespec='seconds')))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409,'This week’s check-in has already been submitted.') from exc
    if help_requested:
        run('INSERT INTO followups(student_id,title,due_date,priority) VALUES (?,?,?,?)',
            (sid,'Student requested support in weekly check-in',academic_now().date().isoformat(),'High'))
    record(session['user']['id'],'Submitted weekly check-in')
    return bounce('/student/checkin?sent=1')


@app.get('/student/notification/{notification_id}')
def student_open_notification(notification_id:int, request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    notification=one(
        'SELECT * FROM notifications WHERE id=? AND student_id=?',
        (notification_id,session['user']['student_id']),
    )
    if not notification:raise HTTPException(404,'Notification not found')
    run('UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=?',
        (academic_now().isoformat(timespec='seconds'),notification_id))
    link=notification['link'] if str(notification['link']).startswith('/student') else '/student'
    return bounce(link)


@app.post('/student/notifications/read')
async def student_read_notifications(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    run('UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE student_id=?',
        (academic_now().isoformat(timespec='seconds'),session['user']['student_id']))
    return bounce('/student')


@app.get('/student/meetings')
def student_meetings(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    meetings=all_rows('SELECT * FROM meetings WHERE student_id=? ORDER BY date DESC',(session['user']['student_id'],))
    return page(request,'student_meetings.html',active='student_meetings',meetings=meetings)


@app.get('/student/deadlines')
def student_deadlines(request: Request):
    session = gate(request, 'student')
    if not session:
        return bounce('/login')
    sid = session['user']['student_id']
    deadlines = all_rows('SELECT * FROM deadlines WHERE student_id=? ORDER BY CASE WHEN status="Completed" THEN 1 ELSE 0 END, due_date, due_time', (sid,))

    # Group and stack deadlines by course to calculate earned grade percentages per course
    courses_map = {}
    for d in deadlines:
        raw_name = d['course'].strip()
        key = raw_name.lower()
        if key not in courses_map:
            courses_map[key] = {
                'name': raw_name,
                'total_weight': 0,
                'earned_weight': 0,
                'pending_weight': 0,
                'total_count': 0,
                'completed_count': 0,
                'pending_count': 0,
            }
        courses_map[key]['total_count'] += 1
        courses_map[key]['total_weight'] += d['weight']
        if d['status'] == 'Completed':
            courses_map[key]['earned_weight'] += d['weight']
            courses_map[key]['completed_count'] += 1
        else:
            courses_map[key]['pending_weight'] += d['weight']
            courses_map[key]['pending_count'] += 1

    courses_summary = sorted(courses_map.values(), key=lambda c: c['name'].lower())
    completed_count = sum(1 for d in deadlines if d['status'] == 'Completed')
    pending_count = len(deadlines) - completed_count

    return page(request, 'deadlines.html', active='student_deadlines',
                deadlines=deadlines, courses_summary=courses_summary,
                completed_count=completed_count, pending_count=pending_count,
                today=date.today().isoformat())


@app.post('/student/deadline')
async def student_add_deadline(request: Request):
    session = gate(request, 'student')
    if not session:
        return bounce('/login')
    form = await request.form()
    verify_csrf(request, session, form)
    course = str(form.get('course', '')).strip()[:100]
    topic = str(form.get('topic', '')).strip()[:150]
    due_date = str(form.get('due_date', ''))
    due_time = str(form.get('due_time', '23:59')).strip()[:10] or '23:59'
    try:
        weight = int(form.get('weight', 10))
        if weight < 0 or weight > 100:
            weight = 10
    except (ValueError, TypeError):
        weight = 10

    if not course or not topic:
        raise HTTPException(400, 'Course and assignment topic are required')
    try:
        date.fromisoformat(due_date)
    except ValueError:
        raise HTTPException(400, 'Invalid deadline date')

    sid = session['user']['student_id']
    run('INSERT INTO deadlines(student_id, course, topic, due_date, due_time, weight) VALUES (?,?,?,?,?,?)',
        (sid, course, topic, due_date, due_time, weight))
    record(session['user']['id'], f'Added deadline for {course}: {topic} ({weight}%)')
    return bounce('/student/deadlines')


@app.post('/student/deadline/{deadline_id}/toggle')
async def student_toggle_deadline(deadline_id: int, request: Request):
    session = gate(request, 'student')
    if not session:
        return bounce('/login')
    form = await request.form()
    verify_csrf(request, session, form)
    sid = session['user']['student_id']
    item = one('SELECT * FROM deadlines WHERE id=? AND student_id=?', (deadline_id, sid))
    if not item:
        raise HTTPException(404, 'Deadline not found')
    new_status = 'Pending' if item['status'] == 'Completed' else 'Completed'
    run('UPDATE deadlines SET status=? WHERE id=?', (new_status, deadline_id))
    record(session['user']['id'], f'Updated deadline: {item["course"]} · {item["topic"]} → {new_status}')
    return bounce('/student/deadlines')


@app.post('/student/deadline/{deadline_id}/delete')
async def student_delete_deadline(deadline_id: int, request: Request):
    session = gate(request, 'student')
    if not session:
        return bounce('/login')
    form = await request.form()
    verify_csrf(request, session, form)
    sid = session['user']['student_id']
    item = one('SELECT * FROM deadlines WHERE id=? AND student_id=?', (deadline_id, sid))
    if not item:
        raise HTTPException(404, 'Deadline not found')
    run('DELETE FROM deadlines WHERE id=? AND student_id=?', (deadline_id, sid))
    record(session['user']['id'], f'Deleted deadline: {item["course"]} · {item["topic"]}')
    return bounce('/student/deadlines')


@app.get('/aac')
def aac_home(request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    greeting=secrets.choice(STAFF_GREETINGS).format(name=staff_greeting_name(session['user']))
    scope,scope_params=staff_student_filter(session)
    students=all_rows('SELECT * FROM students WHERE active=1'+scope+' ORDER BY name',scope_params)
    scope_s,scope_s_params=staff_student_filter(session,'s')
    recent=all_rows('''SELECT f.*,s.name,s.avatar,s.id AS sid FROM followups f JOIN students s ON s.id=f.student_id
               WHERE f.status="Open" AND s.active=1'''+scope_s+''' ORDER BY CASE WHEN f.priority="High" THEN 0 ELSE 1 END,f.due_date LIMIT 6''',scope_s_params)
    next_meetings=all_rows('''SELECT m.*,s.name,s.avatar FROM meetings m JOIN students s ON s.id=m.student_id
                     WHERE m.date>=? AND s.active=1'''+scope_s+''' ORDER BY m.date LIMIT 5''',[academic_now().date().isoformat(),*scope_s_params])
    log=activity_rows(session['user'],5)
    visible_ids={student['id'] for student in students}
    open_followups=all_rows('SELECT student_id FROM followups WHERE status="Open"')
    stat={'students':len(students),'on_track':sum(s['status']=='On Track' for s in students),'followups':sum(f['student_id'] in visible_ids for f in open_followups),'review':sum(s['status']=='Needs Review' for s in students)}
    return page(request,'aac_home.html',active='aac_home',greeting=greeting,stat=stat,students=students,followups=recent,meetings=next_meetings,logs=log)


@app.get('/aac/tracker')
def aac_tracker(request:Request):
    session=gate(request,'advising_team')
    if not session:return bounce('/login')
    return page(
        request,'tracker.html',active='aac_tracker',
        tracker_configured=bool(AAC_TRACKER_API_KEY),
    )


@app.get('/aac/tracker/api/bootstrap')
async def aac_tracker_bootstrap(request:Request):
    session=tracker_api_session(request)
    data=await run_in_threadpool(tracker_api_call,'bootstrap',session['user'],{})
    return JSONResponse(data)


@app.get('/aac/tracker/api/students')
async def aac_tracker_students(request:Request,q:str=''):
    session=tracker_api_session(request)
    query=q.strip()[:120]
    if not query:return JSONResponse([])
    data=await run_in_threadpool(tracker_api_call,'searchStudents',session['user'],{'query':query})
    return JSONResponse(data)


@app.get('/aac/tracker/api/student/{student_code}')
async def aac_tracker_student(student_code:str,request:Request):
    session=tracker_api_session(request)
    code=student_code.strip()[:40]
    if not code:raise HTTPException(400,'Student ID is required.')
    data=await run_in_threadpool(tracker_api_call,'getStudentProfile',session['user'],{'studentId':code})
    return JSONResponse(data)


@app.get('/aac/tracker/api/followups')
async def aac_tracker_followups(request:Request,advisor:str='',bucket:str='all'):
    session=tracker_api_session(request)
    mode=bucket.strip().lower()
    if mode not in {'all','overdue','today','next7','completed'}:
        raise HTTPException(400,'Invalid follow-up filter.')
    data=await run_in_threadpool(
        tracker_api_call,'getFollowUps',session['user'],
        {'advisor':advisor.strip()[:120],'bucket':mode},
    )
    return JSONResponse(data)


@app.get('/aac/tracker/api/report')
async def aac_tracker_report(
    request:Request,from_date:str='',to_date:str='',advisor:str='',program:str='',status:str='',
):
    session=tracker_api_session(request)
    for value in (from_date,to_date):
        if value:
            try:date.fromisoformat(value)
            except ValueError:raise HTTPException(400,'Enter valid report dates.')
    filters={
        'from':from_date,'to':to_date,'advisor':advisor.strip()[:120],
        'program':program.strip()[:120],'status':status.strip()[:80],
    }
    data=await run_in_threadpool(tracker_api_call,'getReport',session['user'],filters)
    return JSONResponse(data)


@app.post('/aac/tracker/api/visit')
async def aac_tracker_save_visit(request:Request):
    session=tracker_api_session(request)
    verify_csrf(request,session,{'_csrf':request.headers.get('X-CSRF-Token','')})
    try:payload=await request.json()
    except ValueError:raise HTTPException(400,'Invalid visit data.')
    cleaned=clean_tracker_visit_payload(payload)
    data=await run_in_threadpool(tracker_api_call,'saveVisit',session['user'],cleaned)
    record(session['user']['id'],f'Recorded AAC Tracker visit for student {cleaned["studentId"]}')
    return JSONResponse(data)


@app.post('/aac/tracker/api/visit/{row_number}/status')
async def aac_tracker_update_visit_status(row_number:int,request:Request):
    session=tracker_api_session(request)
    verify_csrf(request,session,{'_csrf':request.headers.get('X-CSRF-Token','')})
    if row_number<2:raise HTTPException(400,'Invalid Tracker row.')
    try:payload=await request.json()
    except ValueError:raise HTTPException(400,'Invalid status update.')
    status=str(payload.get('status','')).strip() if isinstance(payload,dict) else ''
    if status not in TRACKER_STATUS_OPTIONS:raise HTTPException(400,'Invalid Tracker status.')
    data=await run_in_threadpool(
        tracker_api_call,'updateVisitStatus',session['user'],
        {'rowNumber':row_number,'status':status},
    )
    record(session['user']['id'],f'Updated AAC Tracker row {row_number} to {status}')
    return JSONResponse(data)


@app.get('/aac/students')
def aac_students(
    request:Request,
    q:str='',
    status:str='',
    faculty:str='',
    year:str='',
    sort:str='az',
):
    session=gate_staff(request)
    if not session:return bounce('/login')
    if status not in CASE_STATUSES:status=''
    scope,scope_params=staff_student_filter(session)
    faculties=[row['program'] for row in all_rows('SELECT DISTINCT program FROM students WHERE active=1'+scope+' ORDER BY program COLLATE NOCASE',scope_params)]
    years=[str(row['year']) for row in all_rows('SELECT DISTINCT year FROM students WHERE active=1'+scope+' ORDER BY year',scope_params)]
    if faculty not in faculties:faculty=''
    if year not in years:year=''
    if sort not in ('az','za'):sort='az'
    query='SELECT * FROM students WHERE active=1'+scope;params=list(scope_params)
    if q:
        query+=' AND (LOWER(name) LIKE ? OR LOWER(student_code) LIKE ? OR LOWER(program) LIKE ?)'
        params += ['%'+q.lower()+'%']*3
    if status:
        query+=' AND status=?';params.append(status)
    if faculty:
        query+=' AND program=?';params.append(faculty)
    if year:
        query+=' AND year=?';params.append(int(year))
    query+=' ORDER BY name COLLATE NOCASE '+('DESC' if sort=='za' else 'ASC')
    students=all_rows(query,params)
    return page(
        request,'students.html',active='aac_students',students=students,
        q=q,status=status,faculty=faculty,year=year,sort=sort,
        faculties=faculties,years=years,
    )


@app.get('/aac/messages')
def aac_messages(request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    scope,scope_params=staff_student_filter(session,'s')
    message_scope=' AND m.staff_user_id=?'
    message_params=[session['user']['id']]
    threads=all_rows('''
        SELECT s.*,
          (SELECT body FROM chat_messages m WHERE m.student_id=s.id'''+message_scope+''' ORDER BY m.id DESC LIMIT 1) AS last_message,
          (SELECT created_at FROM chat_messages m WHERE m.student_id=s.id'''+message_scope+''' ORDER BY m.id DESC LIMIT 1) AS last_message_at,
          (SELECT staff_user_id FROM chat_messages m WHERE m.student_id=s.id'''+message_scope+''' ORDER BY m.id DESC LIMIT 1) AS last_contact_id,
          (SELECT COUNT(*) FROM chat_messages m WHERE m.student_id=s.id AND m.read_by_aac=0'''+message_scope+''') AS unread_count
        FROM students s
        WHERE s.active=1'''+scope+'''
        ORDER BY (last_message_at IS NULL),last_message_at DESC,s.name COLLATE NOCASE
    ''',[*message_params,*message_params,*message_params,*message_params,*scope_params])
    return page(
        request,'messages.html',active='aac_messages',threads=threads,
        staff_contacts=internal_staff_contacts(session['user']),
        team_group=team_group_context(session['user']),
    )


@app.get('/aac/team-chat')
def aac_team_group_chat(request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    if not is_team_group_member(session['user']):
        raise HTTPException(403,'This group chat is limited to the four Advising Team members.')
    context=team_group_context(session['user'])
    messages=all_rows(
        '''SELECT m.*,u.display_name AS sender_name
           FROM team_group_messages m
           JOIN users u ON u.id=m.sender_user_id
           ORDER BY m.id'''
    )
    last_message_id=messages[-1]['id'] if messages else 0
    run(
        '''INSERT INTO team_group_reads(user_id,last_read_message_id,read_at)
           VALUES (?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             last_read_message_id=excluded.last_read_message_id,
             read_at=excluded.read_at''',
        (session['user']['id'],last_message_id,academic_now().isoformat(timespec='seconds')),
    )
    return page(
        request,'team_chat.html',active='aac_messages',messages=messages,
        members=context['members'],
    )


@app.get('/aac/team-chat/updates')
def aac_team_group_chat_updates(request:Request):
    session=gate_staff(request)
    if not session:raise HTTPException(401,'Sign-in required.')
    if not is_team_group_member(session['user']):
        raise HTTPException(403,'This group chat is limited to the four Advising Team members.')
    messages=all_rows(
        '''SELECT m.*,u.display_name AS sender_name
           FROM team_group_messages m JOIN users u ON u.id=m.sender_user_id
           WHERE m.id>? ORDER BY m.id''',
        (chat_after_id(request),),
    )
    if messages:
        run(
            '''INSERT INTO team_group_reads(user_id,last_read_message_id,read_at)
               VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 last_read_message_id=MAX(last_read_message_id,excluded.last_read_message_id),
                 read_at=excluded.read_at''',
            (
                session['user']['id'],messages[-1]['id'],
                academic_now().isoformat(timespec='seconds'),
            ),
        )
    return JSONResponse(chat_updates_payload(messages,session['user']['id']))


@app.post('/aac/team-chat')
async def aac_send_team_group_chat(request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    if not is_team_group_member(session['user']):
        raise HTTPException(403,'This group chat is limited to the four Advising Team members.')
    form=await request.form();verify_csrf(request,session,form)
    body=str(form.get('body','')).strip()
    if not body:raise HTTPException(400,'Message cannot be empty')
    if len(body)>2000:raise HTTPException(400,'Message is too long')
    run(
        '''INSERT INTO team_group_messages(sender_user_id,body,created_at)
           VALUES (?,?,?)''',
        (session['user']['id'],body,academic_now().isoformat(timespec='seconds')),
    )
    record(session['user']['id'],'Sent a message in the Advising Team group chat')
    return chat_send_response(request,'/aac/team-chat#latest')


@app.get('/aac/staff-chat/{peer_id}')
def aac_staff_chat(peer_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    peer=internal_staff_peer(session['user'],peer_id)
    run(
        '''UPDATE staff_messages SET read_at=?
           WHERE sender_user_id=? AND recipient_user_id=? AND read_at IS NULL''',
        (academic_now().isoformat(timespec='seconds'),peer['id'],session['user']['id']),
    )
    messages=all_rows(
        '''SELECT m.*,u.display_name AS sender_name
           FROM staff_messages m JOIN users u ON u.id=m.sender_user_id
           WHERE (m.sender_user_id=? AND m.recipient_user_id=?)
              OR (m.sender_user_id=? AND m.recipient_user_id=?)
           ORDER BY m.id''',
        (session['user']['id'],peer['id'],peer['id'],session['user']['id']),
    )
    return page(
        request,'staff_chat.html',active='aac_messages',peer=peer,messages=messages,
    )


@app.get('/aac/staff-chat/{peer_id}/updates')
def aac_staff_chat_updates(peer_id:int,request:Request):
    session=gate_staff(request)
    if not session:raise HTTPException(401,'Sign-in required.')
    peer=internal_staff_peer(session['user'],peer_id)
    messages=all_rows(
        '''SELECT m.*,u.display_name AS sender_name
           FROM staff_messages m JOIN users u ON u.id=m.sender_user_id
           WHERE m.id>? AND ((m.sender_user_id=? AND m.recipient_user_id=?)
              OR (m.sender_user_id=? AND m.recipient_user_id=?))
           ORDER BY m.id''',
        (
            chat_after_id(request),session['user']['id'],peer['id'],
            peer['id'],session['user']['id'],
        ),
    )
    if messages:
        run(
            '''UPDATE staff_messages SET read_at=?
               WHERE sender_user_id=? AND recipient_user_id=? AND read_at IS NULL''',
            (academic_now().isoformat(timespec='seconds'),peer['id'],session['user']['id']),
        )
    return JSONResponse(chat_updates_payload(messages,session['user']['id']))


@app.post('/aac/staff-chat/{peer_id}')
async def aac_send_staff_chat(peer_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    peer=internal_staff_peer(session['user'],peer_id)
    body=str(form.get('body','')).strip()
    if not body:raise HTTPException(400,'Message cannot be empty')
    if len(body)>2000:raise HTTPException(400,'Message is too long')
    run(
        '''INSERT INTO staff_messages
           (sender_user_id,recipient_user_id,body,created_at)
           VALUES (?,?,?,?)''',
        (session['user']['id'],peer['id'],body,academic_now().isoformat(timespec='seconds')),
    )
    record(session['user']['id'],f'Sent a private staff message to user #{peer["id"]}')
    return chat_send_response(request,f'/aac/staff-chat/{peer["id"]}#latest')


@app.get('/aac/student/{student_id}')
def aac_student_detail(student_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    student=allowed_student(student_id,session)
    advisor_options=[]
    if session['user']['role']=='advising_team':
        advisor_options=all_rows(
            '''SELECT id,email,display_name,role FROM users
               WHERE active=1 AND role IN ('advisor','advising_team')
               ORDER BY CASE role WHEN 'advisor' THEN 0 ELSE 1 END,
                        LOWER(display_name),id'''
        )
    goals=all_rows('SELECT * FROM goals WHERE student_id=? ORDER BY id',(student_id,))
    tasks=all_rows('SELECT * FROM tasks WHERE student_id=? ORDER BY due_date',(student_id,))
    meetings=all_rows('SELECT * FROM meetings WHERE student_id=? ORDER BY date DESC',(student_id,))
    for meeting in meetings:
        meeting['can_edit']=can_edit_meeting(meeting,session['user'])
    followups=all_rows('SELECT * FROM followups WHERE student_id=? ORDER BY CASE WHEN status="Open" THEN 0 ELSE 1 END,due_date',(student_id,))
    checkins=all_rows('SELECT * FROM checkins WHERE student_id=? ORDER BY id DESC LIMIT 5',(student_id,))
    return page(
        request,'student_detail.html',active='aac_students',student=student,
        advisor_options=advisor_options,goals=goals,tasks=tasks,meetings=meetings,
        followups=followups,checkins=checkins,
    )


@app.post('/aac/student/{student_id}/advisor')
async def aac_update_student_advisor(student_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    if session['user']['role']!='advising_team':
        raise HTTPException(403,'Only Advising Team members can change assigned advisors.')
    form=await request.form();verify_csrf(request,session,form)
    student=allowed_student(student_id,session)
    try:
        advisor_user_id=int(str(form.get('advisor_user_id','')))
    except ValueError:
        raise HTTPException(400,'Select a valid advisor.')
    advisor=one(
        '''SELECT id,display_name,role FROM users
           WHERE id=? AND active=1 AND role IN ('advisor','advising_team')''',
        (advisor_user_id,),
    )
    if not advisor:
        raise HTTPException(400,'Select an active Advisor or Advising Team member.')
    previous_advisor=student['advisor']
    if previous_advisor.strip().casefold()!=advisor['display_name'].strip().casefold():
        run('UPDATE students SET advisor=? WHERE id=?',(advisor['display_name'],student_id))
        record(
            session['user']['id'],
            f'Reassigned student #{student_id} from {previous_advisor} to {advisor["display_name"]}',
        )
    return bounce(f'/aac/student/{student_id}#advisor-assignment')


@app.get('/aac/student/{student_id}/schedule')
def aac_student_schedule(student_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    allowed_student(student_id,session)
    context=build_schedule_context(student_id,request.query_params.get('week',''))
    return page(
        request,'schedule.html',active='aac_students',schedule_readonly=True,
        schedule_url=f'/aac/student/{student_id}/schedule',
        profile_url=f'/aac/student/{student_id}',**context,
    )


@app.get('/aac/student/{student_id}/chat')
def aac_student_chat(student_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    student=allowed_student(student_id,session)
    selected_contact=staff_chat_contact(
        student,session['user'],request.query_params.get('contact')
    )
    contacts=[selected_contact]
    run(
        '''UPDATE chat_messages SET read_by_aac=1
           WHERE student_id=? AND staff_user_id=? AND read_by_aac=0''',
        (student_id,selected_contact['id']),
    )
    return page(
        request,'chat.html',active='aac_messages',student=student,
        messages=chat_thread(student_id,selected_contact['id']),contacts=contacts,selected_contact=selected_contact,
        chat_action=f'/aac/student/{student_id}/chat',
        chat_live_url=f'/aac/student/{student_id}/chat/updates?contact={selected_contact["id"]}',
        back_url=f'/aac/student/{student_id}',
        back_label='Back to Student Profile',is_aac=True,
    )


@app.get('/aac/student/{student_id}/chat/updates')
def aac_student_chat_updates(student_id:int,request:Request):
    session=gate_staff(request)
    if not session:raise HTTPException(401,'Sign-in required.')
    student=allowed_student(student_id,session)
    selected_contact=staff_chat_contact(
        student,session['user'],request.query_params.get('contact')
    )
    messages=all_rows(
        '''SELECT m.*,u.display_name AS sender_name
           FROM chat_messages m JOIN users u ON u.id=m.sender_user_id
           WHERE m.student_id=? AND m.staff_user_id=? AND m.id>?
           ORDER BY m.id''',
        (student_id,selected_contact['id'],chat_after_id(request)),
    )
    if messages:
        run(
            '''UPDATE chat_messages SET read_by_aac=1
               WHERE student_id=? AND staff_user_id=? AND read_by_aac=0''',
            (student_id,selected_contact['id']),
        )
    return JSONResponse(chat_updates_payload(messages,session['user']['id']))


@app.post('/aac/student/{student_id}/chat')
async def aac_send_chat(student_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    student=allowed_student(student_id,session)
    selected_contact=staff_chat_contact(student,session['user'],form.get('contact'))
    body=str(form.get('body','')).strip()
    if not body:raise HTTPException(400,'Message cannot be empty')
    if len(body)>2000:raise HTTPException(400,'Message is too long')
    run(
        '''INSERT INTO chat_messages
           (student_id,staff_user_id,sender_user_id,body,created_at,read_by_student,read_by_aac)
           VALUES (?,?,?,?,?,0,1)''',
        (student_id,selected_contact['id'],session['user']['id'],body,academic_now().isoformat(timespec='seconds')),
    )
    record(session['user']['id'],f'Sent a chat message to student #{student_id}')
    return chat_send_response(
        request,
        f'/aac/student/{student_id}/chat?contact={selected_contact["id"]}#latest',
    )



@app.post('/aac/student/{student_id}/goal')
async def aac_add_goal(student_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id,session)
    title=str(form.get('title','')).strip()[:140]
    if not title:raise HTTPException(400,'Goal title required')
    run('INSERT INTO goals(student_id,title,target) VALUES (?,?,?)',(student_id,title,''))
    record(session['user']['id'],f'Created goal for student #{student_id}')
    return bounce(f'/aac/student/{student_id}#goals')


@app.post('/aac/student/{student_id}/goal/{goal_id}')
async def aac_update_goal(student_id:int,goal_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id,session)
    goal=one('SELECT id FROM goals WHERE id=? AND student_id=?',(goal_id,student_id))
    if not goal:raise HTTPException(404,'Goal not found')
    title=str(form.get('title','')).strip()[:140]
    status=str(form.get('status','')).strip()
    if not title:raise HTTPException(400,'Goal title required')
    if status not in ('In Progress','Completed'):raise HTTPException(400,'Invalid goal status')
    run('UPDATE goals SET title=?,status=? WHERE id=? AND student_id=?',(title,status,goal_id,student_id))
    record(session['user']['id'],f'Updated goal #{goal_id} for student #{student_id}')
    return bounce(f'/aac/student/{student_id}#goals')


@app.post('/aac/student/{student_id}/meeting')
async def aac_add_meeting(student_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id,session)
    topic=str(form.get('topic','')).strip()[:140]
    day=str(form.get('date',''))
    meeting_time=str(form.get('time','')).strip()
    if not topic:raise HTTPException(400,'Topic required')
    try:
        date.fromisoformat(day)
        datetime.strptime(meeting_time,'%H:%M')
    except ValueError:raise HTTPException(400,'Enter a valid meeting date and time')
    meeting_id=run(
        '''INSERT INTO meetings
           (student_id,date,time,topic,advisor,notes,created_by_user_id,owner_role)
           VALUES (?,?,?,?,?,?,?,?)''',
        (
            student_id,day,meeting_time,topic,session['user']['display_name'],
            str(form.get('notes','')).strip()[:400],session['user']['id'],session['user']['role'],
        ),
    )
    meeting_day=datetime.fromisoformat(day).strftime('%b %d, %Y')
    create_student_notification(
        student_id,'appointment','New advising appointment',
        f'{topic} · {meeting_day} at {meeting_time} with {session["user"]["display_name"]}.',
        '/student/meetings',
    )
    record(session['user']['id'],f'Created meeting for student #{student_id}')
    return bounce(f'/aac/student/{student_id}#meetings')


@app.post('/aac/student/{student_id}/meeting/{meeting_id}/time')
async def aac_update_meeting_time(student_id:int,meeting_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id,session)
    meeting=one('SELECT * FROM meetings WHERE id=? AND student_id=?',(meeting_id,student_id))
    if not meeting:raise HTTPException(404,'Meeting not found')
    require_meeting_editor(meeting,session['user'])
    meeting_time=str(form.get('time','')).strip()
    try:datetime.strptime(meeting_time,'%H:%M')
    except ValueError:raise HTTPException(400,'Enter a valid meeting time')
    run('UPDATE meetings SET time=? WHERE id=?',(meeting_time,meeting_id))
    action='Changed' if meeting['time'] else 'Assigned'
    meeting_day=datetime.fromisoformat(meeting['date']).strftime('%b %d, %Y')
    create_student_notification(
        student_id,'appointment','Advising appointment updated',
        f'{meeting["topic"]} · {meeting_day} at {meeting_time}.',
        '/student/meetings',
    )
    record(session['user']['id'],f'{action} time for meeting #{meeting_id}: {meeting_time}')
    return bounce(f'/aac/student/{student_id}#meetings')


@app.post('/aac/student/{student_id}/followup')
async def aac_add_followup(student_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id,session)
    title=str(form.get('title','')).strip()[:150]
    day=str(form.get('due_date',''))
    if not title:raise HTTPException(400,'Title required')
    try:date.fromisoformat(day)
    except ValueError:raise HTTPException(400,'Invalid date')
    priority='High' if form.get('priority')=='High' else 'Normal'
    run('INSERT INTO followups(student_id,title,due_date,priority) VALUES (?,?,?,?)',(student_id,title,day,priority))
    record(session['user']['id'],f'Created follow-up for student #{student_id}')
    return bounce(f'/aac/student/{student_id}#followups')


@app.post('/aac/student/{student_id}/status')
async def aac_update_case_status(student_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id,session)
    status=str(form.get('status',''))
    if status not in CASE_STATUSES:raise HTTPException(400,'Invalid case status')
    run('UPDATE students SET status=? WHERE id=?',(status,student_id))
    record(session['user']['id'],f'Updated support case status for student #{student_id} to {status}')
    return bounce(f'/aac/student/{student_id}')



@app.post('/aac/followup/{followup_id}/resolve')
async def aac_resolve_followup(followup_id:int,request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    verify_csrf(request,session,await request.form())
    f=one('SELECT * FROM followups WHERE id=?',(followup_id,))
    if not f:raise HTTPException(404)
    allowed_student(f['student_id'],session)
    run('UPDATE followups SET status="Resolved" WHERE id=?',(followup_id,))
    record(session['user']['id'],f'Resolved follow-up #{followup_id}')
    return bounce(f"/aac/student/{f['student_id']}#followups")


@app.get('/aac/plans')
def aac_plans(request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    scope,scope_params=staff_student_filter(session,'s')
    students=all_rows('''SELECT s.*,COUNT(g.id) AS goals_count FROM students s
                   LEFT JOIN goals g ON s.id=g.student_id WHERE s.active=1'''+scope+''' GROUP BY s.id ORDER BY s.name''',scope_params)
    return page(request,'plans.html',active='aac_plans',students=students)


@app.get('/aac/activity')
def aac_activity(request:Request):
    session=gate_staff(request)
    if not session:return bounce('/login')
    logs=activity_rows(session['user'],50)
    return page(request,'activity.html',active='aac_activity',logs=logs)


if __name__=='__main__':
    import uvicorn
    mode = 'DEMO' if DEMO_MODE else 'RESTRICTED LOCAL DATA'
    print(f'\nACADEMIC WEAPON {mode}: http://127.0.0.1:8000\n')
    uvicorn.run('app:app',host='127.0.0.1',port=8000,reload=True,log_level='warning')
