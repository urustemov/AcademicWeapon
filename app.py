"""Academic Weapon local-only demonstration web app. No production/student data allowed."""
from __future__ import annotations
import os
from pathlib import Path
import secrets
from datetime import date, datetime
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer, BadSignature

from db import BASE_DIR, seed_database, one, all_rows, run, password_verify

seed_database()
secret_path = BASE_DIR / '.apss_local_secret'
if not secret_path.exists():
    secret_path.write_text(secrets.token_urlsafe(48), encoding='utf-8')
signer = URLSafeSerializer(secret_path.read_text(encoding='utf-8'), salt='apss-local-demo-session')

app = FastAPI(title='Academic Weapon · AUCA Demo', docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')
templates = Jinja2Templates(directory=BASE_DIR / 'templates')


def nice_date(value):
    try:
        return datetime.fromisoformat(value).strftime('%b %d, %Y')
    except (TypeError, ValueError):
        return value or '—'


def initials(value):
    return ''.join(part[:1] for part in value.split()[:2]).upper()

templates.env.filters['nice_date'] = nice_date
templates.env.filters['initials'] = initials


def current_session(request):
    cookie = request.cookies.get('apss_demo_session')
    if not cookie:
        return None
    try:
        payload = signer.loads(cookie)
        if not isinstance(payload, dict) or 'uid' not in payload:
            return None
        user = one('SELECT id,email,display_name,role,student_id FROM users WHERE id=?', (payload['uid'],))
        if user:
            return {'user':user,'csrf':payload.get('csrf','')}
    except BadSignature:
        return None
    return None


def gate(request, role=None):
    session = current_session(request)
    if not session:
        return None
    if role and session['user']['role'] != role:
        raise HTTPException(403,'This demo account cannot access that page.')
    return session


def verify_csrf(request, session, form):
    if not session or not secrets.compare_digest(str(form.get('_csrf','')),str(session['csrf'])):
        raise HTTPException(403, 'Invalid form verification token. Refresh the page and retry.')


def page(request, template, **data):
    session = current_session(request)
    user = session['user'] if session else None
    return templates.TemplateResponse(request=request,name=template,context={
        'user':user, 'csrf':session['csrf'] if session else '',
        'today':date.today().isoformat(), 'active':data.pop('active',''), **data
    })


def bounce(path):
    return RedirectResponse(path, status_code=303)


def record(uid,event):
    run('INSERT INTO audit_logs(user_id,event) VALUES (?,?)',(uid,event))


@app.get('/')
def index(request:Request):
    session=gate(request)
    return bounce('/aac' if session['user']['role']=='aac' else '/student') if session else bounce('/login')


@app.get('/login')
def login_page(request:Request):
    if gate(request):return bounce('/')
    return page(request,'login.html')


@app.post('/login')
async def login_action(request:Request):
    form=await request.form()
    email=str(form.get('email','')).strip().lower()
    password=str(form.get('password',''))
    user=one('SELECT * FROM users WHERE email=?',(email,))
    if not user or not password_verify(password,user['password_hash']):
        return templates.TemplateResponse(request=request,name='login.html',context={
            'user':None,'active':'','csrf':'','today':date.today().isoformat(),
            'error':'Email or password is incorrect. Use one of the demo accounts.'},status_code=401)
    token=signer.dumps({'uid':user['id'],'csrf':secrets.token_urlsafe(24)})
    response=bounce('/aac' if user['role']=='aac' else '/student')
    response.set_cookie('apss_demo_session',token,max_age=60*60*12,httponly=True,samesite='lax',secure=False,path='/')
    return response


@app.post('/logout')
async def logout(request:Request):
    session=gate(request)
    if session:
        verify_csrf(request,session,await request.form())
    response=bounce('/login')
    response.delete_cookie('apss_demo_session',path='/')
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
    return page(request,'student_home.html',active='student_home',student=student,goals=goals,tasks=tasks[:5],meetings=meetings,completed=completed,total=len(tasks),pct=round(completed/max(len(tasks),1)*100))


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


@app.post('/student/task/{task_id}/status')
async def student_task_status(task_id:int, request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    task=one('SELECT * FROM tasks WHERE id=? AND student_id=?',(task_id,session['user']['student_id']))
    if not task:raise HTTPException(404)
    status='Completed' if task['status']!='Completed' else 'To Do'
    run('UPDATE tasks SET status=? WHERE id=?',(status,task_id))
    record(session['user']['id'],f'Student task #{task_id} status to {status}')
    return bounce('/student/plan')


@app.get('/student/checkin')
def student_checkin(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    sid=session['user']['student_id']
    recent=all_rows('SELECT * FROM checkins WHERE student_id=? ORDER BY id DESC LIMIT 5',(sid,))
    return page(request,'checkin.html',active='student_checkin',recent=recent,success=request.query_params.get('sent')=='1')


@app.post('/student/checkin')
async def student_checkin_action(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    mood=str(form.get('mood',''))
    if mood not in ('Good','Okay','Difficult'):raise HTTPException(400,'Select a check-in rating')
    challenge=str(form.get('challenge','')).strip()[:300]
    priority=str(form.get('priority','')).strip()[:300]
    help_requested=1 if form.get('needs_help')=='yes' else 0
    run('INSERT INTO checkins(student_id,mood,challenge,priority,needs_help) VALUES (?,?,?,?,?)',
        (session['user']['student_id'],mood,challenge,priority,help_requested))
    if help_requested:
        run('INSERT INTO followups(student_id,title,due_date,priority) VALUES (?,?,?,?)',
            (session['user']['student_id'],'Student requested support in weekly check-in',date.today().isoformat(),'High'))
    record(session['user']['id'],'Submitted weekly check-in')
    return bounce('/student/checkin?sent=1')


@app.get('/student/meetings')
def student_meetings(request:Request):
    session=gate(request,'student')
    if not session:return bounce('/login')
    meetings=all_rows('SELECT * FROM meetings WHERE student_id=? ORDER BY date DESC',(session['user']['student_id'],))
    return page(request,'student_meetings.html',active='student_meetings',meetings=meetings)


@app.get('/aac')
def aac_home(request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    students=all_rows('SELECT * FROM students ORDER BY name')
    recent=all_rows('''SELECT f.*,s.name,s.avatar,s.id AS sid FROM followups f JOIN students s ON s.id=f.student_id
               WHERE f.status="Open" ORDER BY CASE WHEN f.priority="High" THEN 0 ELSE 1 END,f.due_date LIMIT 6''')
    next_meetings=all_rows('''SELECT m.*,s.name,s.avatar FROM meetings m JOIN students s ON s.id=m.student_id
                     WHERE m.date>=? ORDER BY m.date LIMIT 5''',(date.today().isoformat(),))
    log=all_rows('SELECT * FROM audit_logs ORDER BY id DESC LIMIT 5')
    stat={'students':len(students),'active':sum(s['status']=='Active Plan' for s in students),'followups':len(all_rows('SELECT id FROM followups WHERE status="Open"')),'review':sum(s['status']=='Needs Review' for s in students)}
    return page(request,'aac_home.html',active='aac_home',stat=stat,students=students,followups=recent,meetings=next_meetings,logs=log)


@app.get('/aac/students')
def aac_students(request:Request,q:str='',status:str=''):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    query='SELECT * FROM students WHERE 1=1';params=[]
    if q:
        query+=' AND (LOWER(name) LIKE ? OR LOWER(student_code) LIKE ? OR LOWER(program) LIKE ?)'
        params += ['%'+q.lower()+'%']*3
    if status:
        query+=' AND status=?';params.append(status)
    query+=' ORDER BY name'
    students=all_rows(query,params)
    return page(request,'students.html',active='aac_students',students=students,q=q,status=status)


@app.get('/aac/student/{student_id}')
def aac_student_detail(student_id:int,request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    student=one('SELECT * FROM students WHERE id=?',(student_id,))
    if not student:raise HTTPException(404,'Demo student not found')
    goals=all_rows('SELECT * FROM goals WHERE student_id=? ORDER BY id',(student_id,))
    tasks=all_rows('SELECT * FROM tasks WHERE student_id=? ORDER BY due_date',(student_id,))
    meetings=all_rows('SELECT * FROM meetings WHERE student_id=? ORDER BY date DESC',(student_id,))
    followups=all_rows('SELECT * FROM followups WHERE student_id=? ORDER BY CASE WHEN status="Open" THEN 0 ELSE 1 END,due_date',(student_id,))
    checkins=all_rows('SELECT * FROM checkins WHERE student_id=? ORDER BY id DESC LIMIT 5',(student_id,))
    return page(request,'student_detail.html',active='aac_students',student=student,goals=goals,tasks=tasks,meetings=meetings,followups=followups,checkins=checkins)


def allowed_student(student_id):
    if not one('SELECT id FROM students WHERE id=?',(student_id,)):
        raise HTTPException(404,'Student not found')


@app.post('/aac/student/{student_id}/task')
async def aac_add_task(student_id:int,request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id)
    title=str(form.get('title','')).strip()[:140]
    if not title:raise HTTPException(400,'Title required')
    due=str(form.get('due_date',''))
    try:date.fromisoformat(due)
    except ValueError:raise HTTPException(400,'Invalid due date')
    priority=str(form.get('priority','Medium'))
    if priority not in ('Low','Medium','High'):priority='Medium'
    run('INSERT INTO tasks(student_id,title,details,due_date,priority) VALUES (?,?,?,?,?)',
        (student_id,title,str(form.get('details','')).strip()[:350],due,priority))
    record(session['user']['id'],f'Created task for demo student #{student_id}')
    return bounce(f'/aac/student/{student_id}#tasks')


@app.post('/aac/student/{student_id}/goal')
async def aac_add_goal(student_id:int,request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id)
    title=str(form.get('title','')).strip()[:140]
    target=str(form.get('target','')).strip()[:180]
    if not title or not target:raise HTTPException(400,'Goal and target required')
    run('INSERT INTO goals(student_id,title,target) VALUES (?,?,?)',(student_id,title,target))
    record(session['user']['id'],f'Created goal for demo student #{student_id}')
    return bounce(f'/aac/student/{student_id}#goals')


@app.post('/aac/student/{student_id}/meeting')
async def aac_add_meeting(student_id:int,request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id)
    topic=str(form.get('topic','')).strip()[:140]
    day=str(form.get('date',''))
    if not topic:raise HTTPException(400,'Topic required')
    try:date.fromisoformat(day)
    except ValueError:raise HTTPException(400,'Invalid date')
    run('INSERT INTO meetings(student_id,date,topic,advisor,notes) VALUES (?,?,?,?,?)',
        (student_id,day,topic,session['user']['display_name'],str(form.get('notes','')).strip()[:400]))
    record(session['user']['id'],f'Created meeting for demo student #{student_id}')
    return bounce(f'/aac/student/{student_id}#meetings')


@app.post('/aac/student/{student_id}/followup')
async def aac_add_followup(student_id:int,request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id)
    title=str(form.get('title','')).strip()[:150]
    day=str(form.get('due_date',''))
    if not title:raise HTTPException(400,'Title required')
    try:date.fromisoformat(day)
    except ValueError:raise HTTPException(400,'Invalid date')
    priority='High' if form.get('priority')=='High' else 'Normal'
    run('INSERT INTO followups(student_id,title,due_date,priority) VALUES (?,?,?,?)',(student_id,title,day,priority))
    record(session['user']['id'],f'Created follow-up for demo student #{student_id}')
    return bounce(f'/aac/student/{student_id}#followups')


@app.post('/aac/student/{student_id}/status')
async def aac_update_case_status(student_id:int,request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form);allowed_student(student_id)
    status=str(form.get('status',''))
    allowed=('Initial Assessment','Active Plan','On Track','Needs Review','Semester Review')
    if status not in allowed:raise HTTPException(400,'Invalid case status')
    run('UPDATE students SET status=? WHERE id=?',(status,student_id))
    record(session['user']['id'],f'Updated support case status for demo student #{student_id} to {status}')
    return bounce(f'/aac/student/{student_id}')


@app.post('/aac/task/{task_id}/status')
async def aac_update_task(task_id:int,request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    form=await request.form();verify_csrf(request,session,form)
    task=one('SELECT * FROM tasks WHERE id=?',(task_id,))
    if not task:raise HTTPException(404)
    status=str(form.get('status',''))
    if status not in ('To Do','In Progress','Completed'):raise HTTPException(400)
    run('UPDATE tasks SET status=? WHERE id=?',(status,task_id))
    record(session['user']['id'],f'Changed task #{task_id} to {status}')
    return bounce(f"/aac/student/{task['student_id']}#tasks")


@app.post('/aac/followup/{followup_id}/resolve')
async def aac_resolve_followup(followup_id:int,request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    verify_csrf(request,session,await request.form())
    f=one('SELECT * FROM followups WHERE id=?',(followup_id,))
    if not f:raise HTTPException(404)
    run('UPDATE followups SET status="Resolved" WHERE id=?',(followup_id,))
    record(session['user']['id'],f'Resolved follow-up #{followup_id}')
    return bounce(f"/aac/student/{f['student_id']}#followups")


@app.get('/aac/plans')
def aac_plans(request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    students=all_rows('''SELECT s.*,COUNT(g.id) AS goals_count FROM students s
                   LEFT JOIN goals g ON s.id=g.student_id GROUP BY s.id ORDER BY s.name''')
    return page(request,'plans.html',active='aac_plans',students=students)


@app.get('/aac/activity')
def aac_activity(request:Request):
    session=gate(request,'aac')
    if not session:return bounce('/login')
    logs=all_rows('SELECT * FROM audit_logs ORDER BY id DESC LIMIT 50')
    return page(request,'activity.html',active='aac_activity',logs=logs)


if __name__=='__main__':
    import uvicorn
    print('\nACADEMIC WEAPON LOCAL DEMO: http://127.0.0.1:8000\nThis app uses SYNTHETIC data only. Do not enter real academic records.\n')
    uvicorn.run(app,host='127.0.0.1',port=8000,log_level='warning')
