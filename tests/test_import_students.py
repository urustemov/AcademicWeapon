from pathlib import Path

from openpyxl import Workbook

import db
from import_students import ImportValidationError, read_students, synchronize


def make_workbook(path: Path, duplicate_email: bool = False):
    workbook=Workbook()
    sheet=workbook.active
    sheet.title='Academic Probation (62)'
    sheet.append(['Student Name','Student ID','Program','Year of Standing','Student E-mail','CGPA',"Advisor's Name, Surname"])
    sheet.append(['Student One','1001','SFW','Freshman','student.one@auca.kg',1.75,'Advisor One'])
    sheet.append(['Student Two','1002','BA','Sophomore','student.one@auca.kg' if duplicate_email else 'student.two@auca.kg',2.10,'Advisor Two'])
    workbook.save(path)


def test_import_parser_validates_minimum_access_fields(tmp_path):
    source=tmp_path/'students.xlsx'
    make_workbook(source)
    records=read_students(source)
    assert len(records)==2
    assert records[0].year==1
    assert records[0].advisor=='Advisor One'
    assert records[1].email=='student.two@auca.kg'


def test_import_parser_rejects_duplicate_email(tmp_path):
    source=tmp_path/'students.xlsx'
    make_workbook(source,duplicate_email=True)
    try:
        read_students(source)
        assert False,'Expected duplicate email validation error'
    except ImportValidationError as error:
        assert 'duplicate email' in str(error)


def test_synchronize_creates_google_only_accounts_in_separate_database(tmp_path):
    source=tmp_path/'students.xlsx'
    database=tmp_path/'academic_weapon.sqlite3'
    make_workbook(source)
    records=read_students(source)
    original_path,original_mode=db.DB_PATH,db.DEMO_MODE
    try:
        result=synchronize(records,database,deactivate_missing=True)
        assert result['students_created']==2
        assert result['login_accounts_created']==2
        with db.connect() as connection:
            assert connection.execute('SELECT COUNT(*) FROM students WHERE active=1').fetchone()[0]==2
            assert connection.execute('SELECT advisor FROM students WHERE student_code=?',('1001',)).fetchone()['advisor']=='Advisor One'
            account=connection.execute('SELECT password_hash,google_sub,active FROM users WHERE email=?',('student.one@auca.kg',)).fetchone()
            assert account['password_hash']=='!google-only!'
            assert account['google_sub'] is None and account['active']==1
            team=connection.execute(
                'SELECT role,password_hash FROM users WHERE email=?',
                ('urustemov_s@auca.kg',),
            ).fetchone()
            assert team['role']=='advising_team'
            assert team['password_hash']=='!google-only!'
    finally:
        db.DB_PATH,db.DEMO_MODE=original_path,original_mode
