"""Functional demo tests. Never touches the user's local demo database."""
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import db
# Must be set before importing app, which seeds the database on startup.
TMP = tempfile.TemporaryDirectory()
db.DB_PATH = Path(TMP.name) / 'test_apss.sqlite3'
from app import app
import app as app_module
from fastapi.testclient import TestClient


def test_google_verification_dependencies_are_available():
    assert app_module.google_id_token is not None
    assert app_module.google_requests is not None


def test_health_check_and_baseline_security_headers():
    with TestClient(app,follow_redirects=False) as client:
        response=client.get('/healthz')
        assert response.status_code==200 and response.json()=={'status':'ok'}
        login=client.get('/login')
        assert login.headers['x-content-type-options']=='nosniff'
        assert login.headers['x-frame-options']=='DENY'
        assert login.headers['x-permitted-cross-domain-policies']=='none'
        assert login.headers['cross-origin-opener-policy']=='same-origin-allow-popups'
        assert login.headers['referrer-policy']=='strict-origin-when-cross-origin'
        assert login.headers['cache-control']=='no-store'
        assert '/static/aac-logo-on-dark.png' in login.text
        assert '<link rel="icon" type="image/png" href="/static/aac-logo-on-light.png">' in login.text
        assert 'login-theme-logo' not in login.text


def test_render_alias_redirects_to_the_official_domain(monkeypatch):
    monkeypatch.setattr(app_module, 'IS_PRODUCTION', True)
    monkeypatch.setattr(app_module, 'CANONICAL_HOST', 'advising.auca.kg')
    monkeypatch.setattr(app_module, 'CANONICAL_ALIAS_HOSTS', {'testserver'})
    with TestClient(app, follow_redirects=False) as client:
        redirect = client.get('/login?error=inactive')
        assert redirect.status_code == 308
        assert redirect.headers['location'] == 'https://advising.auca.kg/login?error=inactive'
        assert redirect.headers['x-content-type-options'] == 'nosniff'
        health = client.get('/healthz')
        assert health.status_code == 200


def test_local_password_login_is_disabled_outside_demo(monkeypatch):
    monkeypatch.setattr(app_module,'DEMO_MODE',False)
    with TestClient(app,follow_redirects=False) as client:
        page=client.get('/login')
        assert page.status_code==200
        assert 'id="loginForm"' not in page.text
        assert client.post('/login',data={
            'email':'student@demo.example','password':'Demo1234!',
        }).status_code==404


def test_aac_overview_has_a_personalized_random_greeting(monkeypatch):
    assert len(app_module.STAFF_GREETINGS) >= 15
    assert app_module.staff_greeting_name({
        'email':'atsungur_g@auca.kg', 'display_name':'Görkem Atsungur',
    }) == 'Görkem Bey'
    assert app_module.staff_greeting_name({
        'email':'karabaev_d@auca.kg', 'display_name':'Daniyar Karabaev',
    }) == 'Daniyar Agai'
    monkeypatch.setattr(app_module.secrets, 'choice', lambda options: options[0])
    with TestClient(app, follow_redirects=False) as client:
        assert client.post('/login', data={
            'email':'advisor@demo.example', 'password':'Demo1234!',
        }).status_code == 303
        overview = client.get('/aac')
        assert overview.status_code == 200
        assert 'data-staff-greeting' in overview.text
        assert 'Welcome back, AAC.' in overview.text
        assert 'style.css?v=20261029-1' in overview.text


def test_private_chat_permissions_and_unread_state():
    advisor_body='<b>Can we review the private-chat test plan?</b>'
    student_body='Yes, private-chat test received.'
    advisor_id=db.one('SELECT id FROM users WHERE email=?',('advisor@demo.example',))['id']

    with TestClient(app,follow_redirects=False) as staff:
        assert staff.post('/login',data={'email':'advisor@demo.example','password':'Demo1234!'}).status_code==303
        csrf=app_module.signer.loads(staff.cookies['apss_demo_session'])['csrf']
        assert staff.get('/aac/messages').status_code==200
        chat=staff.get('/aac/student/1/chat')
        assert chat.status_code==200 and 'Alex Morgan' in chat.text
        response=staff.post('/aac/student/1/chat',data={'_csrf':csrf,'body':advisor_body})
        assert response.status_code==303
        advisor_message=db.one('SELECT * FROM chat_messages WHERE body=? ORDER BY id DESC LIMIT 1',(advisor_body,))
        assert advisor_message['student_id']==1
        assert advisor_message['read_by_student']==0 and advisor_message['read_by_aac']==1
        assert staff.get('/student/chat').status_code==403

    with TestClient(app,follow_redirects=False) as student:
        assert student.post('/login',data={'email':'student@demo.example','password':'Demo1234!'}).status_code==303
        assert 'nav-count' in student.get('/student').text
        chat=student.get('/student/chat')
        assert chat.status_code==200
        assert '&lt;b&gt;Can we review the private-chat test plan?&lt;/b&gt;' in chat.text
        assert db.one('SELECT read_by_student FROM chat_messages WHERE id=?',(advisor_message['id'],))['read_by_student']==1
        csrf=app_module.signer.loads(student.cookies['apss_demo_session'])['csrf']
        assert student.post('/student/chat',data={'_csrf':csrf,'body':student_body}).status_code==303
        student_message=db.one('SELECT * FROM chat_messages WHERE body=? ORDER BY id DESC LIMIT 1',(student_body,))
        assert student_message['read_by_student']==1 and student_message['read_by_aac']==0
        assert student.get('/aac/messages').status_code==403
        assert student.post('/aac/student/2/chat',data={'_csrf':csrf,'body':'Not allowed'}).status_code==403

    with TestClient(app,follow_redirects=False) as staff:
        assert staff.post('/login',data={'email':'advisor@demo.example','password':'Demo1234!'}).status_code==303
        inbox=staff.get('/aac/messages')
        assert inbox.status_code==200 and student_body in inbox.text
        assert db.one('SELECT read_by_aac FROM chat_messages WHERE id=?',(student_message['id'],))['read_by_aac']==0
        updates=staff.get(
            f'/aac/student/1/chat/updates?contact={advisor_id}&after={advisor_message["id"]}'
        )
        assert updates.status_code==200
        assert updates.json()['messages']==[{
            'id':student_message['id'],'body':student_body,
            'created_at':student_message['created_at'],
            'created_label':app_module.nice_datetime(student_message['created_at']),
            'sender_name':'Alex Morgan','own':False,
        }]
        assert db.one('SELECT read_by_aac FROM chat_messages WHERE id=?',(student_message['id'],))['read_by_aac']==1
        assert staff.get('/aac/student/1/chat').status_code==200


def test_three_roles_and_direct_contact_isolation():
    advisor_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('limited.advisor@demo.example','Limited Advisor','advisor',None,db.password_hash('Demo1234!')),
    )
    umut_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('umut@demo.example','Umut Kydyrgychova','advising_team',None,db.password_hash('Demo1234!')),
    )
    db.run('UPDATE students SET advisor=? WHERE id=2',('Limited Advisor',))

    with TestClient(app,follow_redirects=False) as student:
        assert student.post('/login',data={'email':'student@demo.example','password':'Demo1234!'}).status_code==303
        contacts=student.get('/student/chat')
        assert contacts.status_code==200 and 'Umut Kydyrgychova' in contacts.text
        csrf=app_module.signer.loads(student.cookies['apss_demo_session'])['csrf']
        body='A message only for Umut.'
        assert student.post('/student/chat',data={'_csrf':csrf,'contact':str(umut_id),'body':body}).status_code==303
        message=db.one('SELECT * FROM chat_messages WHERE body=?',(body,))
        assert message['staff_user_id']==umut_id
        assert body in student.get(f'/student/chat?contact={umut_id}').text
        assert body not in student.get('/student/chat').text

    with TestClient(app,follow_redirects=False) as advisor:
        assert advisor.post('/login',data={'email':'limited.advisor@demo.example','password':'Demo1234!'}).status_code==303
        directory=advisor.get('/aac/students')
        assert directory.status_code==200 and 'Mira Taylor' in directory.text
        assert 'Alex Morgan' not in directory.text
        assert advisor.get('/aac/student/2').status_code==200
        assert advisor.get('/aac/student/1').status_code==403
        assert advisor.get('/aac/student/2/chat').status_code==200
        assert advisor.get('/aac/student/1/chat').status_code==403
        csrf=app_module.signer.loads(advisor.cookies['apss_demo_session'])['csrf']
        assert advisor.post('/aac/student/1/chat',data={'_csrf':csrf,'contact':str(advisor_id),'body':'Forbidden'}).status_code==403

    with TestClient(app,follow_redirects=False) as team:
        assert team.post('/login',data={'email':'advisor@demo.example','password':'Demo1234!'}).status_code==303
        assert team.get('/aac/student/1').status_code==200
        assert team.get('/aac/student/2').status_code==200
        assert body not in team.get('/aac/messages').text
        inspected=team.get(f'/aac/student/1/chat?contact={umut_id}')
        assert inspected.status_code==403
        assert db.one('SELECT read_by_aac FROM chat_messages WHERE id=?',(message['id'],))['read_by_aac']==0
        csrf=app_module.signer.loads(team.cookies['apss_demo_session'])['csrf']
        assert team.post('/aac/student/1/chat',data={
            '_csrf':csrf,'contact':str(umut_id),'body':'Trying another staff thread',
        }).status_code==403

    with TestClient(app,follow_redirects=False) as umut:
        assert umut.post('/login',data={'email':'umut@demo.example','password':'Demo1234!'}).status_code==303
        inbox=umut.get('/aac/messages')
        assert inbox.status_code==200 and body in inbox.text
        inspected=umut.get(f'/aac/student/1/chat?contact={umut_id}')
        assert inspected.status_code==200 and body in inspected.text
        assert db.one('SELECT read_by_aac FROM chat_messages WHERE id=?',(message['id'],))['read_by_aac']==1


def test_private_team_to_advisor_chat():
    advisor_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('internal.advisor@demo.example','Internal Advisor','advisor',None,db.password_hash('Demo1234!')),
    )
    team_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('internal.team@demo.example','Internal Team Member','advising_team',None,db.password_hash('Demo1234!')),
    )
    other_team_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('other.team@demo.example','Other Team Member','advising_team',None,db.password_hash('Demo1234!')),
    )
    assert advisor_id and team_id and other_team_id
    first_message='Confidential question for the assigned Advisor.'
    reply='Confidential Advisor reply.'
    team_message='Private coordination between two Advising Team members.'

    with TestClient(app,follow_redirects=False) as team:
        assert team.post('/login',data={'email':'internal.team@demo.example','password':'Demo1234!'}).status_code==303
        inbox=team.get('/aac/messages')
        assert inbox.status_code==200 and 'Internal Advisor' in inbox.text
        assert 'data-message-directory="advisors"' in inbox.text
        assert 'data-message-directory="students"' in inbox.text
        assert inbox.text.count('data-message-search')==2
        assert 'Search by name or email' in inbox.text
        assert 'Search by name, student code, or department' in inbox.text
        assert 'style.css?v=20261029-1' in inbox.text
        assert '/static/aac-logo-on-dark.png' in inbox.text
        csrf=app_module.signer.loads(team.cookies['apss_demo_session'])['csrf']
        assert team.post(f'/aac/staff-chat/{advisor_id}',data={
            '_csrf':csrf,'body':first_message,
        }).status_code==303

    with TestClient(app,follow_redirects=False) as other_team:
        assert other_team.post('/login',data={'email':'other.team@demo.example','password':'Demo1234!'}).status_code==303
        assert first_message not in other_team.get('/aac/messages').text
        own_thread=other_team.get(f'/aac/staff-chat/{advisor_id}')
        assert own_thread.status_code==200 and first_message not in own_thread.text
        csrf=app_module.signer.loads(other_team.cookies['apss_demo_session'])['csrf']
        assert other_team.post(f'/aac/staff-chat/{team_id}',data={
            '_csrf':csrf,'body':team_message,
        }).status_code==303

    with TestClient(app,follow_redirects=False) as advisor:
        assert advisor.post('/login',data={'email':'internal.advisor@demo.example','password':'Demo1234!'}).status_code==303
        inbox=advisor.get('/aac/messages')
        assert inbox.status_code==200 and first_message in inbox.text
        updates=advisor.get(f'/aac/staff-chat/{team_id}/updates?after=0')
        assert updates.status_code==200
        assert updates.json()['messages'][-1]['body']==first_message
        assert updates.json()['messages'][-1]['own'] is False
        thread=advisor.get(f'/aac/staff-chat/{team_id}')
        assert thread.status_code==200 and first_message in thread.text
        csrf=app_module.signer.loads(advisor.cookies['apss_demo_session'])['csrf']
        live_send=advisor.post(f'/aac/staff-chat/{team_id}',data={
            '_csrf':csrf,'body':reply,
        },headers={'X-Chat-Live':'1','Accept':'application/json'})
        assert live_send.status_code==200 and live_send.json()=={'ok':True}
        assert advisor.get(f'/aac/staff-chat/{advisor_id}').status_code==403

    with TestClient(app,follow_redirects=False) as team:
        assert team.post('/login',data={'email':'internal.team@demo.example','password':'Demo1234!'}).status_code==303
        assert reply in team.get(f'/aac/staff-chat/{advisor_id}').text
        assert team_message in team.get(f'/aac/staff-chat/{other_team_id}').text

    with TestClient(app,follow_redirects=False) as student:
        assert student.post('/login',data={'email':'student@demo.example','password':'Demo1234!'}).status_code==303
        assert student.get(f'/aac/staff-chat/{advisor_id}').status_code==403


def test_named_advising_team_group_chat_and_unread_state():
    members=(
        ('urustemov_s@auca.kg','Serdar Urustemov'),
        ('kydyrgychova_u@auca.kg','Umut Kydyrgychova'),
        ('tynyeva_a@auca.kg','Aizada Tynyeva'),
        ('zhakypov_a@auca.kg','Aidar Zhakypov'),
    )
    member_ids={}
    for email,name in members:
        member_ids[email]=db.run(
            '''INSERT INTO users(email,display_name,role,student_id,password_hash)
               VALUES (?,?,?,?,?)''',
            (email,name,'advising_team',None,db.password_hash('Demo1234!')),
        )
    outsider_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('nonmember.team@demo.example','Nonmember Team','advising_team',None,db.password_hash('Demo1234!')),
    )
    assert outsider_id and len(member_ids)==4
    body='<b>Private four-person group message.</b>'
    live_body='Message sent without a page refresh.'

    with TestClient(app,follow_redirects=False) as serdar:
        assert serdar.post('/login',data={
            'email':'urustemov_s@auca.kg','password':'Demo1234!',
        }).status_code==303
        inbox=serdar.get('/aac/messages')
        assert inbox.status_code==200 and 'Advising Team · Group Chat' in inbox.text
        assert '4 members' in inbox.text
        csrf=app_module.signer.loads(serdar.cookies['apss_demo_session'])['csrf']
        assert serdar.post('/aac/team-chat',data={'_csrf':csrf,'body':body}).status_code==303
        live_send=serdar.post(
            '/aac/team-chat',data={'_csrf':csrf,'body':live_body},
            headers={'X-Chat-Live':'1','Accept':'application/json'},
        )
        assert live_send.status_code==200 and live_send.json()=={'ok':True}

    with TestClient(app,follow_redirects=False) as umut:
        assert umut.post('/login',data={
            'email':'kydyrgychova_u@auca.kg','password':'Demo1234!',
        }).status_code==303
        inbox=umut.get('/aac/messages')
        assert live_body in inbox.text and '2 unread' in inbox.text
        updates=umut.get('/aac/team-chat/updates?after=0')
        assert updates.status_code==200
        assert [message['body'] for message in updates.json()['messages'][-2:]]==[body,live_body]
        assert updates.json()['messages'][-1]['own'] is False
        thread=umut.get('/aac/team-chat')
        assert thread.status_code==200
        assert '&lt;b&gt;Private four-person group message.&lt;/b&gt;' in thread.text
        assert db.one(
            'SELECT last_read_message_id FROM team_group_reads WHERE user_id=?',
            (member_ids['kydyrgychova_u@auca.kg'],),
        )['last_read_message_id']>0
        assert '0 unread' in umut.get('/aac/messages').text

    with TestClient(app,follow_redirects=False) as outsider:
        assert outsider.post('/login',data={
            'email':'nonmember.team@demo.example','password':'Demo1234!',
        }).status_code==303
        assert 'Advising Team · Group Chat' not in outsider.get('/aac/messages').text
        assert outsider.get('/aac/team-chat').status_code==403
        assert outsider.get('/aac/team-chat/updates?after=0').status_code==403
        csrf=app_module.signer.loads(outsider.cookies['apss_demo_session'])['csrf']
        assert outsider.post('/aac/team-chat',data={'_csrf':csrf,'body':'Forbidden'}).status_code==403

    with TestClient(app,follow_redirects=False) as student:
        assert student.post('/login',data={'email':'student@demo.example','password':'Demo1234!'}).status_code==303
        assert student.get('/aac/team-chat').status_code==403


def test_meeting_edits_follow_creator_role_and_owner():
    owner_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('meeting.owner@demo.example','Meeting Owner','advisor',None,db.password_hash('Demo1234!')),
    )
    second_team_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('meeting.team@demo.example','Meeting Team Member','advising_team',None,db.password_hash('Demo1234!')),
    )
    assert owner_id and second_team_id
    db.run('UPDATE students SET advisor=? WHERE id=6',('Meeting Owner',))

    with TestClient(app,follow_redirects=False) as advisor:
        assert advisor.post('/login',data={'email':'meeting.owner@demo.example','password':'Demo1234!'}).status_code==303
        csrf=app_module.signer.loads(advisor.cookies['apss_demo_session'])['csrf']
        assert advisor.post('/aac/student/6/meeting',data={
            '_csrf':csrf,'topic':'Advisor-owned meeting','date':date.today().isoformat(),'time':'10:00',
        }).status_code==303
        advisor_meeting=db.one('SELECT * FROM meetings WHERE topic=?',('Advisor-owned meeting',))
        assert advisor_meeting['created_by_user_id']==owner_id and advisor_meeting['owner_role']=='advisor'
        assert advisor.post(
            f'/aac/student/6/meeting/{advisor_meeting["id"]}/time',
            data={'_csrf':csrf,'time':'10:15'},
        ).status_code==303

    with TestClient(app,follow_redirects=False) as team:
        assert team.post('/login',data={'email':'advisor@demo.example','password':'Demo1234!'}).status_code==303
        csrf=app_module.signer.loads(team.cookies['apss_demo_session'])['csrf']
        profile=team.get('/aac/student/6')
        assert profile.status_code==200 and 'Managed by the assigned Advisor' in profile.text
        assert team.post(
            f'/aac/student/6/meeting/{advisor_meeting["id"]}/time',
            data={'_csrf':csrf,'time':'10:30'},
        ).status_code==403
        assert team.post('/aac/student/6/meeting',data={
            '_csrf':csrf,'topic':'Team-owned meeting','date':date.today().isoformat(),'time':'11:00',
        }).status_code==303
        team_meeting=db.one('SELECT * FROM meetings WHERE topic=?',('Team-owned meeting',))
        assert team_meeting['owner_role']=='advising_team'

    with TestClient(app,follow_redirects=False) as advisor:
        assert advisor.post('/login',data={'email':'meeting.owner@demo.example','password':'Demo1234!'}).status_code==303
        csrf=app_module.signer.loads(advisor.cookies['apss_demo_session'])['csrf']
        profile=advisor.get('/aac/student/6')
        assert profile.status_code==200 and 'Managed by Advising Team' in profile.text
        assert advisor.post(
            f'/aac/student/6/meeting/{team_meeting["id"]}/time',
            data={'_csrf':csrf,'time':'11:15'},
        ).status_code==403

    with TestClient(app,follow_redirects=False) as teammate:
        assert teammate.post('/login',data={'email':'meeting.team@demo.example','password':'Demo1234!'}).status_code==303
        csrf=app_module.signer.loads(teammate.cookies['apss_demo_session'])['csrf']
        assert teammate.post(
            f'/aac/student/6/meeting/{team_meeting["id"]}/time',
            data={'_csrf':csrf,'time':'11:30'},
        ).status_code==303
        assert db.one('SELECT time FROM meetings WHERE id=?',(team_meeting['id'],))['time']=='11:30'


def test_activity_log_is_scoped_to_assigned_advisees_and_all_team_activity():
    assigned_advisor_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('activity.advisor@demo.example','Activity Advisor','advisor',None,db.password_hash('Demo1234!')),
    )
    other_advisor_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('other.activity.advisor@demo.example','Other Activity Advisor','advisor',None,db.password_hash('Demo1234!')),
    )
    student_user_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('mira.activity@demo.example','Mira Taylor','student',2,db.password_hash('Demo1234!')),
    )
    assert assigned_advisor_id and other_advisor_id and student_user_id
    db.run('UPDATE students SET advisor=? WHERE id=2',('Activity Advisor',))
    task_title='Advisee activity visibility test'

    with TestClient(app,follow_redirects=False) as student:
        assert student.post('/login',data={
            'email':'mira.activity@demo.example','password':'Demo1234!',
        }).status_code==303
        csrf=app_module.signer.loads(student.cookies['apss_demo_session'])['csrf']
        assert student.post('/student/task',data={
            '_csrf':csrf,'title':task_title,'due_date':'2026-11-10',
            'priority':'Medium','status':'To Do',
        }).status_code==303

    with TestClient(app,follow_redirects=False) as assigned_advisor:
        assert assigned_advisor.post('/login',data={
            'email':'activity.advisor@demo.example','password':'Demo1234!',
        }).status_code==303
        activity=assigned_advisor.get('/aac/activity')
        assert activity.status_code==200
        assert task_title in activity.text
        assert 'Initiated by Mira Taylor' in activity.text
        assert 'Student' in activity.text and 'DEMO-1002' in activity.text

    with TestClient(app,follow_redirects=False) as other_advisor:
        assert other_advisor.post('/login',data={
            'email':'other.activity.advisor@demo.example','password':'Demo1234!',
        }).status_code==303
        activity=other_advisor.get('/aac/activity')
        assert activity.status_code==200
        assert task_title not in activity.text

    with TestClient(app,follow_redirects=False) as team:
        assert team.post('/login',data={
            'email':'advisor@demo.example','password':'Demo1234!',
        }).status_code==303
        activity=team.get('/aac/activity')
        assert activity.status_code==200
        assert task_title in activity.text
        assert 'Initiated by Mira Taylor' in activity.text


def test_only_advising_team_can_reassign_a_student_advisor():
    student_id=db.run('''INSERT INTO students
        (student_code,name,email,program,year,gpa,credit_load,advisor,status,attention,avatar)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(
        'TEST-ADVISOR-CHANGE','Advisor Change Student','advisor.change.student@auca.kg',
        'LAS',2,1.90,0,'AAC Advising Team','Initial Assessment','Regular','AC',
    ))
    replacement_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('replacement.advisor@demo.example','Reassignment Advisor','advisor',None,db.password_hash('Demo1234!')),
    )
    alternative_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('alternative.advisor@demo.example','Alternative Advisor','advisor',None,db.password_hash('Demo1234!')),
    )
    student_user_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('advisor.change.student@auca.kg','Advisor Change Student','student',student_id,db.password_hash('Demo1234!')),
    )
    assert student_id and replacement_id and alternative_id and student_user_id

    with TestClient(app,follow_redirects=False) as team:
        assert team.post('/login',data={
            'email':'advisor@demo.example','password':'Demo1234!',
        }).status_code==303
        profile=team.get(f'/aac/student/{student_id}')
        assert profile.status_code==200
        assert 'Change advisor' in profile.text
        assert f'action="/aac/student/{student_id}/advisor"' in profile.text
        assert 'Reassignment Advisor' in profile.text
        csrf=app_module.signer.loads(team.cookies['apss_demo_session'])['csrf']
        invalid=team.post(f'/aac/student/{student_id}/advisor',data={
            '_csrf':csrf,'advisor_user_id':str(student_user_id),
        })
        assert invalid.status_code==400
        changed=team.post(f'/aac/student/{student_id}/advisor',data={
            '_csrf':csrf,'advisor_user_id':str(replacement_id),
        })
        assert changed.status_code==303
        assert changed.headers['location']==f'/aac/student/{student_id}#advisor-assignment'
        assert db.one('SELECT advisor FROM students WHERE id=?',(student_id,))['advisor']=='Reassignment Advisor'
        assert 'Reassignment Advisor' in team.get(f'/aac/student/{student_id}').text

    with TestClient(app,follow_redirects=False) as advisor:
        assert advisor.post('/login',data={
            'email':'replacement.advisor@demo.example','password':'Demo1234!',
        }).status_code==303
        profile=advisor.get(f'/aac/student/{student_id}')
        assert profile.status_code==200
        assert 'Change advisor' not in profile.text
        csrf=app_module.signer.loads(advisor.cookies['apss_demo_session'])['csrf']
        forbidden=advisor.post(f'/aac/student/{student_id}/advisor',data={
            '_csrf':csrf,'advisor_user_id':str(alternative_id),
        })
        assert forbidden.status_code==403
        assert db.one('SELECT advisor FROM students WHERE id=?',(student_id,))['advisor']=='Reassignment Advisor'

    audit=db.one(
        'SELECT event FROM audit_logs WHERE event LIKE ? ORDER BY id DESC LIMIT 1',
        (f'Reassigned student #{student_id}%',),
    )
    assert audit and 'Reassignment Advisor' in audit['event']


def test_aac_tracker_is_native_and_available_only_to_advising_team(monkeypatch):
    calls=[]

    def fake_tracker_call(action,user,payload=None):
        calls.append((action,user['email'],payload or {}))
        if action=='bootstrap':
            return {
                'currentUser':{'email':user['email'],'advisor':'Test Advisor','name':'Test Advisor'},
                'advisors':['Test Advisor','Umut Kydyrgychova'],
                'topics':['Academic Probation','Academic Progress'],
                'statuses':list(app_module.TRACKER_STATUS_OPTIONS),
                'programs':['LAS','SFW'],
                'dashboard':{
                    'today':2,'openFollowUps':3,'overdue':1,'next7':2,
                    'byAdvisor':[{'label':'Test Advisor','value':2}],
                    'byTopic':[{'label':'Academic Progress','value':2}],
                    'recent':[],
                },
            }
        if action=='searchStudents':
            return [{'id':'54321','name':'Aibek Aibekov','email':'urustemov_se@auca.kg','program':'LAS','year':'1','gpa':'3.4'}]
        if action=='getStudentProfile':
            return {'student':{'id':'54321','name':'Aibek Aibekov','email':'urustemov_se@auca.kg','program':'LAS','year':'1','gpa':'3.4'},'visits':[]}
        if action=='getFollowUps':
            return []
        if action=='getReport':
            return {
                'total':3,'uniqueStudents':1,
                'byProgram':[{'label':'LAS','value':3}],
                'uniqueByProgram':[{'label':'LAS','value':1}],
                'byYear':[{'label':'Year 1','value':3}],
                'uniqueByYear':[{'label':'Year 1','value':1}],
                'byStatus':[],
                'gpaBands':[{'label':'3.00–4.00','value':3}],
                'uniqueGpaBands':[{'label':'3.00–4.00','value':1}],
            }
        if action=='saveVisit':
            return {'ok':True,'row':25,'student':{'id':'54321','name':'Aibek Aibekov'}}
        if action=='updateVisitStatus':
            return {'ok':True}
        raise AssertionError(f'Unexpected Tracker action: {action}')

    monkeypatch.setattr(app_module,'AAC_TRACKER_API_KEY','test-private-key')
    monkeypatch.setattr(app_module,'tracker_api_call',fake_tracker_call)
    advisor_id=db.run(
        'INSERT INTO users(email,display_name,role,student_id,password_hash) VALUES (?,?,?,?,?)',
        ('tracker.advisor@demo.example','Tracker Test Advisor','advisor',None,db.password_hash('Demo1234!')),
    )
    assert advisor_id

    with TestClient(app,follow_redirects=False) as team:
        assert team.post('/login',data={
            'email':'advisor@demo.example','password':'Demo1234!',
        }).status_code==303
        home=team.get('/aac')
        assert home.status_code==200 and 'href="/aac/tracker"' in home.text
        tracker=team.get('/aac/tracker')
        assert tracker.status_code==200
        assert 'data-tracker-root' in tracker.text
        assert 'ADVISING TEAM ONLY' in tracker.text
        assert 'Dashboard' in tracker.text and 'New Visit' in tracker.text
        assert 'Unique Student Visits' in tracker.text
        assert 'Unique Students by Program' in tracker.text
        assert 'Visits by Year' in tracker.text
        assert 'Unique Students by Year' in tracker.text
        assert 'GPA Distribution by Unique Students' in tracker.text
        assert 'tracker.js?v=20261029-1' in tracker.text
        assert 'script.google.com' not in tracker.text
        assert '/static/tracker.js' in tracker.text
        assert team.get('/aac/tracker/open').status_code==404

        bootstrap=team.get('/aac/tracker/api/bootstrap')
        assert bootstrap.status_code==200 and bootstrap.json()['dashboard']['today']==2
        students=team.get('/aac/tracker/api/students?q=Aibek')
        assert students.status_code==200 and students.json()[0]['id']=='54321'
        profile=team.get('/aac/tracker/api/student/54321')
        assert profile.status_code==200 and profile.json()['student']['name']=='Aibek Aibekov'
        assert team.get('/aac/tracker/api/followups?bucket=invalid').status_code==400
        assert team.get('/aac/tracker/api/followups?bucket=next7').status_code==200
        assert team.get('/aac/tracker/api/report?from_date=not-a-date').status_code==400
        report=team.get('/aac/tracker/api/report?program=LAS')
        assert report.status_code==200
        assert report.json()['total']==3
        assert report.json()['uniqueStudents']==1
        assert report.json()['uniqueByProgram']==[{'label':'LAS','value':1}]
        assert report.json()['uniqueByYear']==[{'label':'Year 1','value':1}]
        assert report.json()['uniqueGpaBands']==[{'label':'3.00–4.00','value':1}]

        csrf=app_module.signer.loads(team.cookies['apss_demo_session'])['csrf']
        visit=team.post('/aac/tracker/api/visit',headers={'X-CSRF-Token':csrf},json={
            'advisor':'Test Advisor','studentId':'54321','topics':['Academic Progress'],
            'question':'Review semester progress','action':'Agreed on next steps',
            'followUp':'No','followUpDate':'','status':'Resolved','notes':'',
        })
        assert visit.status_code==200 and visit.json()['row']==25
        assert team.post('/aac/tracker/api/visit',json={}).status_code==403
        status=team.post('/aac/tracker/api/visit/25/status',headers={'X-CSRF-Token':csrf},json={'status':'Closed'})
        assert status.status_code==200 and status.json()=={'ok':True}
        assert ('saveVisit','advisor@demo.example',{
            'advisor':'Test Advisor','studentId':'54321','topics':['Academic Progress'],
            'question':'Review semester progress','action':'Agreed on next steps',
            'followUp':'No','followUpDate':'','status':'Resolved','notes':'',
        }) in calls

    with TestClient(app,follow_redirects=False) as advisor:
        assert advisor.post('/login',data={
            'email':'tracker.advisor@demo.example','password':'Demo1234!',
        }).status_code==303
        home=advisor.get('/aac')
        assert home.status_code==200 and 'href="/aac/tracker"' not in home.text
        assert advisor.get('/aac/tracker').status_code==403
        assert advisor.get('/aac/tracker/api/bootstrap').status_code==403

    with TestClient(app,follow_redirects=False) as student:
        assert student.post('/login',data={
            'email':'student@demo.example','password':'Demo1234!',
        }).status_code==303
        assert 'href="/aac/tracker"' not in student.get('/student').text
        assert student.get('/aac/tracker').status_code==403
        assert student.get('/aac/tracker/api/bootstrap').status_code==403


def test_aac_and_student_permissions(monkeypatch):
    monkeypatch.setattr(
        app_module,
        'academic_now',
        lambda: datetime(2026,10,30,18,0,tzinfo=app_module.ACADEMIC_TIMEZONE),
    )
    with TestClient(app, follow_redirects=False) as staff:
        assert staff.get('/login').status_code==200
        resp=staff.post('/login',data={'email':'advisor@demo.example','password':'Demo1234!'})
        assert resp.status_code==303
        assert staff.get('/aac').status_code==200
        students_page=staff.get('/aac/students')
        assert students_page.status_code==200
        assert 'Active Plan' not in students_page.text
        assert 'Semester Review' not in students_page.text
        assert 'All departments' in students_page.text
        assert 'All faculties' not in students_page.text
        filtered=staff.get('/aac/students?faculty=Computer%20Science&year=1&sort=za')
        assert filtered.status_code==200
        assert 'Lea Brooks' in filtered.text
        assert 'Alex Morgan' not in filtered.text
        assert 'Freshman' in filtered.text
        assert 'Year 1' not in filtered.text
        year_filtered=staff.get('/aac/students?year=3')
        assert 'Mira Taylor' in year_filtered.text and 'Noah Wells' in year_filtered.text
        assert 'Lea Brooks' not in year_filtered.text
        assert 'Junior' in year_filtered.text
        assert 'Year 3' not in year_filtered.text
        reverse_sorted=staff.get('/aac/students?sort=za').text
        assert reverse_sorted.index('Sam Parker') < reverse_sorted.index('Noah Wells') < reverse_sorted.index('Alex Morgan')
        student_profile=staff.get('/aac/student/1')
        assert student_profile.status_code==200
        assert 'SOPHOMORE' in student_profile.text
        assert 'Assigned Advisor' in student_profile.text
        assert 'AAC Advising Team' in student_profile.text
        assert '/aac/student/1/schedule' in student_profile.text
        staff_schedule=staff.get('/aac/student/1/schedule')
        assert staff_schedule.status_code==200
        assert 'Alex Morgan' in staff_schedule.text and 'Weekly Schedule' in staff_schedule.text
        assert 'View only' in staff_schedule.text
        assert 'Add course to the schedule' not in staff_schedule.text
        assert '/aac/student/1/schedule?week=' in staff_schedule.text
        assert staff.get('/student').status_code==403
        token=staff.cookies.get('apss_demo_session')
        assert token is not None
        from itsdangerous import URLSafeSerializer
        from app import signer
        csrf=signer.loads(token)['csrf']
        # AAC can no longer add/modify tasks (tasks are student-owned)
        assert staff.post('/aac/student/1/task',data={'_csrf':csrf,'title':'New test item','due_date':'2026-11-01','priority':'High'}).status_code==404
        assert staff.post('/aac/task/1/status',data={'_csrf':csrf,'status':'Completed'}).status_code==404
        assert staff.post('/aac/student/1/goal',data={'_csrf':csrf,'title':'New demo goal'}).status_code==303
        new_goal=db.one('SELECT * FROM goals WHERE student_id=1 AND title=?',('New demo goal',))
        assert new_goal and new_goal['target']==''
        assert staff.post(f'/aac/student/1/goal/{new_goal["id"]}',data={'_csrf':csrf,'title':'Edited demo goal','status':'Completed'}).status_code==303
        updated_goal=db.one('SELECT * FROM goals WHERE id=?',(new_goal['id'],))
        assert updated_goal['title']=='Edited demo goal' and updated_goal['status']=='Completed'
        assert staff.post(f'/aac/student/1/goal/{new_goal["id"]}',data={'_csrf':csrf,'title':'Edited demo goal','status':'Unknown'}).status_code==400
        assert staff.post(f'/aac/student/2/goal/{new_goal["id"]}',data={'_csrf':csrf,'title':'Wrong student','status':'Completed'}).status_code==404
        goal_profile=staff.get('/aac/student/1').text
        assert 'Edited demo goal' in goal_profile and 'Edit Academic Goal' in goal_profile
        assert 'Target Metric / Behavior' not in goal_profile
        assert staff.post('/aac/student/1/meeting',data={'_csrf':csrf,'topic':'New demo meeting','date':date.today().isoformat(),'time':'14:05'}).status_code==303
        new_meeting=db.one('SELECT * FROM meetings WHERE student_id=1 AND topic=?',('New demo meeting',))
        assert new_meeting and new_meeting['time']=='14:05'
        assert db.one('SELECT * FROM notifications WHERE student_id=1 AND title=?',('New advising appointment',))
        assert staff.post(f'/aac/student/1/meeting/{new_meeting["id"]}/time',data={'_csrf':csrf,'time':'14:07'}).status_code==303
        assert db.one('SELECT time FROM meetings WHERE id=?',(new_meeting['id'],))['time']=='14:07'
        untimed_meeting=db.one("SELECT * FROM meetings WHERE student_id=1 AND time='' ORDER BY id LIMIT 1")
        assert untimed_meeting
        assert staff.post(f'/aac/student/1/meeting/{untimed_meeting["id"]}/time',data={'_csrf':csrf,'time':'09:30'}).status_code==303
        assert db.one('SELECT time FROM meetings WHERE id=?',(untimed_meeting['id'],))['time']=='09:30'
        profile_with_times=staff.get('/aac/student/1').text
        assert 'Change time' in profile_with_times and '14:07' in profile_with_times and '09:30' in profile_with_times
        assert staff.post('/aac/student/1/followup',data={'_csrf':csrf,'title':'Test followup','due_date':'2026-11-01','priority':'High'}).status_code==303
        assert staff.post('/aac/student/1/status',data={'_csrf':csrf,'status':'Active Plan'}).status_code==400
        assert staff.post('/aac/student/1/status',data={'_csrf':csrf,'status':'On Track'}).status_code==303
        assert staff.post('/aac/student/1/status',data={'_csrf':csrf,'status':'Academic Leave'}).status_code==303
        assert db.one('SELECT status FROM students WHERE id=1')['status']=='Academic Leave'
        assert staff.post('/aac/student/1/status',data={'_csrf':csrf,'status':'Dismissed'}).status_code==303
        assert db.one('SELECT status FROM students WHERE id=1')['status']=='Dismissed'
        activity=staff.get('/aac/activity')
        assert activity.status_code==200
        assert 'Initiated by AAC Demo Advisor' in activity.text
        assert 'Initiated by User #' not in activity.text
        assert staff.get('/student/deadlines').status_code==403
        assert staff.get('/student/schedule').status_code==403
    with TestClient(app, follow_redirects=False) as student:
        resp=student.post('/login',data={'email':'student@demo.example','password':'Demo1234!'})
        assert resp.status_code==303
        assert student.get('/student').status_code==200
        dashboard=student.get('/student').text
        assert 'Notifications' in dashboard and 'New advising appointment' in dashboard
        assert student.get('/student/plan').status_code==200
        schedule_page=student.get('/student/schedule')
        assert schedule_page.status_code==200
        assert 'New demo meeting' in schedule_page.text and '14:07' in schedule_page.text
        assert 'BETWEEN CLASSES' in schedule_page.text
        assert student.get('/student/deadlines').status_code==200
        checkin_page=student.get('/student/checkin')
        assert checkin_page.status_code==200
        assert 'Friday Oct 30 at 17:00' in checkin_page.text
        assert 'Submit Weekly Check-in' in checkin_page.text
        assert student.get('/student/meetings').status_code==200
        assert student.get('/aac/students').status_code==403
        assert student.get('/aac/student/1/schedule').status_code==403
        assert student.post(f'/aac/student/1/meeting/{new_meeting["id"]}/time',data={'time':'10:00'}).status_code==403
        from app import signer
        csrf=signer.loads(student.cookies['apss_demo_session'])['csrf']
        # A semester course repeats on its selected weekdays, but contributes credits only once.
        assert student.post('/student/schedule/course',data={
            '_csrf':csrf,'name':'Student Success Seminar','credits':'6','room':'315',
            'instructor':'Smith','days':['Mon','Wed'],'time_slot':'09:25-10:40',
        }).status_code==303
        scheduled_course=db.one('SELECT * FROM schedule_courses WHERE name=?',('Student Success Seminar',))
        assert scheduled_course and scheduled_course['days']=='Mon,Wed'
        assert scheduled_course['start_time']=='09:25' and scheduled_course['end_time']=='10:40'
        assert db.one('SELECT credit_load FROM students WHERE id=1')['credit_load']==6
        schedule_page=student.get('/student/schedule')
        assert schedule_page.text.count('<strong>Student Success Seminar</strong>')==4
        assert '9:25–10:40' in schedule_page.text
        assert student.post(f'/student/schedule/course/{scheduled_course["id"]}/delete',data={'_csrf':csrf}).status_code==303
        assert db.one('SELECT credit_load FROM students WHERE id=1')['credit_load']==0
        # Student can create, edit, and delete their own tasks
        assert student.post('/student/task',data={'_csrf':csrf,'title':'My own task','due_date':'2026-11-10','priority':'Medium','status':'To Do'}).status_code==303
        new_task=db.one('SELECT id FROM tasks WHERE title=?',('My own task',))
        assert new_task
        tid=new_task['id']
        assert student.post(f'/student/task/{tid}/edit',data={'_csrf':csrf,'title':'My edited task','due_date':'2026-11-12','priority':'High','status':'In Progress'}).status_code==303
        assert student.post(f'/student/task/{tid}/update_fields',data={'_csrf':csrf,'priority':'Low','status':'To Do'}).status_code==303
        assert student.post(f'/student/task/{tid}/delete',data={'_csrf':csrf}).status_code==303
        assert student.post('/student/deadline',data={'_csrf':csrf,'course':'History 101','topic':'Term Paper','due_date':'2026-11-15','due_time':'23:59','weight':'20'}).status_code==303
        assert db.one('SELECT id FROM deadlines WHERE topic=?',('Term Paper',))
        assert student.post('/student/deadline/1/toggle',data={'_csrf':csrf}).status_code==303
        assert student.post('/student/task/1/status',data={'_csrf':csrf}).status_code==303
        assert student.post('/student/checkin',data={'_csrf':csrf,'mood':'Okay','challenge':'Study habits','priority':'Math','needs_help':'yes'}).status_code==303
        assert student.post('/student/checkin',data={'_csrf':csrf,'mood':'Good','challenge':'','priority':'','needs_help':'no'}).status_code==409
        assert db.one('SELECT COUNT(*) AS num FROM followups WHERE title LIKE ?',('%requested support%',))['num'] == 1
        completed_page=student.get('/student/checkin').text
        assert 'This week’s Check-in is complete' in completed_page
        assert 'Submit Weekly Check-in' not in completed_page
        appointment_notification=db.one('SELECT * FROM notifications WHERE student_id=1 ORDER BY id DESC LIMIT 1')
        assert student.get(f'/student/notification/{appointment_notification["id"]}').status_code==303
        assert db.one('SELECT read_at FROM notifications WHERE id=?',(appointment_notification['id'],))['read_at']


def test_weekly_checkin_window_uses_bishkek_time():
    tz=app_module.ACADEMIC_TIMEZONE
    before=app_module.weekly_checkin_state(2,datetime(2026,10,23,16,59,tzinfo=tz))
    opened=app_module.weekly_checkin_state(2,datetime(2026,10,23,17,0,tzinfo=tz))
    sunday=app_module.weekly_checkin_state(2,datetime(2026,10,25,23,59,tzinfo=tz))
    monday=app_module.weekly_checkin_state(2,datetime(2026,10,26,0,0,tzinfo=tz))
    assert before['status']=='closed'
    assert opened['status']=='open' and opened['week_key']=='2026-10-19'
    assert sunday['status']=='open'
    assert monday['status']=='closed' and monday['next_opens_at'].isoformat().startswith('2026-10-30T17:00:00')


def test_google_workspace_login_requires_allowlisted_active_user(monkeypatch):
    student_id=db.run('''INSERT INTO students
        (student_code,name,email,program,year,gpa,credit_load,advisor,status,attention,avatar)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(
        'TEST-2001','Allowed Student','allowed@auca.kg','SFW',2,1.95,0,
        'AAC Advising Team','Initial Assessment','Regular','AS'
    ))
    db.run('''INSERT INTO users(email,display_name,role,student_id,password_hash)
        VALUES (?,?,?,?,?)''',('allowed@auca.kg','Allowed Student','student',student_id,'!google-only!'))
    monkeypatch.setattr(app_module,'GOOGLE_CLIENT_ID','test-client.apps.googleusercontent.com')
    identities={
        'valid':{'sub':'google-user-1','email':'allowed@auca.kg','email_verified':True,'hd':'auca.kg'},
        'unknown':{'sub':'google-user-2','email':'unknown@auca.kg','email_verified':True,'hd':'auca.kg'},
        'wrong-domain':{'sub':'google-user-3','email':'allowed@auca.kg','email_verified':True,'hd':'gmail.com'},
    }
    monkeypatch.setattr(app_module,'verify_google_credential',lambda credential:identities[credential])

    with TestClient(app,follow_redirects=False) as client:
        client.cookies.set('g_csrf_token','csrf-test')
        response=client.post('/auth/google',data={'credential':'valid','g_csrf_token':'csrf-test'})
        assert response.status_code==303 and response.headers['location']=='/student'
        assert db.one('SELECT google_sub FROM users WHERE email=?',('allowed@auca.kg',))['google_sub']=='google-user-1'

    with TestClient(app,follow_redirects=False) as client:
        client.cookies.set('g_csrf_token','csrf-test')
        response=client.post('/auth/google',data={'credential':'unknown','g_csrf_token':'csrf-test'})
        assert response.status_code==303 and response.headers['location']=='/login?error=not_enrolled'
        response=client.post('/auth/google',data={'credential':'wrong-domain','g_csrf_token':'csrf-test'})
        assert response.status_code==303 and response.headers['location']=='/login?error=wrong_domain'
        assert client.post('/auth/google',data={'credential':'valid','g_csrf_token':'bad-token'}).status_code==400
