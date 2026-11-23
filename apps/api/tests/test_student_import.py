"""Tests for bulk student intake and CSV export.

The properties under test are the ones an operator depends on when importing a
real cohort:

* a dry run writes nothing;
* a file with one bad row writes nothing at all (unless skipping is requested);
* re-running the same file is safe;
* a rejected file is reported per row, not as an opaque 500.
"""

from __future__ import annotations

import uuid

VALID_HEADER = "student_id,first_name,last_name,email\n"


def _login(client, email: str = "admin@school.portal", password: str = "password123"):
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response


def _number(prefix: str = "IMP") -> str:
    return f"STU-{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _upload(
    client,
    content: bytes,
    *,
    dry_run: bool = False,
    skip_invalid: bool = False,
    filename: str = "students.csv",
):
    return client.post(
        "/api/v1/students/import",
        params={"dry_run": dry_run, "skip_invalid": skip_invalid},
        files={"file": (filename, content, "text/csv")},
    )


def test_dry_run_validates_without_writing(client, db_session):
    from app.models.identity import Student

    _login(client)
    number = _number()
    content = (VALID_HEADER + f"{number},Anna,Kowalska,{number.lower()}@example.com\n").encode()

    response = _upload(client, content, dry_run=True)
    assert response.status_code == 200, response.text
    report = response.json()

    assert report["dry_run"] is True
    assert report["valid"] == 1
    assert report["created"] == 0
    assert report["rows"][0]["status"] == "VALID"
    assert (
        db_session.query(Student).filter(Student.student_id == number).first() is None
    )


def test_import_creates_student_and_working_account(client, db_session):
    from app.models.identity import Student

    _login(client)
    number = _number()
    email = f"{number.lower()}@example.com"
    content = (VALID_HEADER + f"{number},Anna,Kowalska,{email}\n").encode()

    report = _upload(client, content).json()
    assert report["created"] == 1, report
    password = report["rows"][0]["temporary_password"]
    assert password

    student = db_session.query(Student).filter(Student.student_id == number).first()
    assert student is not None
    assert student.user.email == email
    assert student.user.must_change_password is True

    # The one-time credential is real: the imported student can sign in with it.
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text


def test_import_rejects_populated_legacy_placement_columns(client, db_session):
    """Phase 8a: a populated legacy placement column is an explicit error."""
    from app.models.admission import AcademicAdmission, AcademicPlacement
    from app.models.audit import AuditLog
    from app.models.identity import Student, User

    _login(client)
    number = _number("PLACE")
    email = f"{number.lower()}@example.com"
    major = client.get("/api/v1/academics/majors").json()["items"][0]
    program = client.get("/api/v1/academics/programs").json()["items"][0]
    content = (
        "student_id,first_name,last_name,email,major_code,program_code,"
        "major_id,program_id,program_offering_id\n"
        f"{number},No,Placement,{email},{major['code']},{program['code']},"
        f"{uuid.uuid4()},{uuid.uuid4()},{uuid.uuid4()}\n"
    ).encode()

    audit_before = db_session.query(AuditLog).count()
    admissions_before = db_session.query(AcademicAdmission).count()
    placements_before = db_session.query(AcademicPlacement).count()
    report = _upload(client, content).json()

    assert report["aborted"] is True
    assert report["created"] == 0
    assert report["failed"] == 1
    row = report["rows"][0]
    assert row["code"] == "IMPORT_PLACEMENT_COLUMNS_RETIRED"
    assert "admission/placement workflow" in row["message"]
    for column in (
        "major_code",
        "program_code",
        "major_id",
        "program_id",
        "program_offering_id",
    ):
        assert column in row["message"]

    assert db_session.query(Student).filter(Student.student_id == number).first() is None
    assert db_session.query(User).filter(User.email == email).first() is None
    assert db_session.query(AcademicAdmission).count() == admissions_before
    assert db_session.query(AcademicPlacement).count() == placements_before
    assert db_session.query(AuditLog).count() == audit_before


def test_import_accepts_empty_legacy_placement_columns(client, db_session):
    """An old header with blank placement cells remains usable."""
    from app.models.admission import AcademicAdmission, AcademicPlacement
    from app.models.identity import Student

    _login(client)
    number = _number("EMPTY")
    email = f"{number.lower()}@example.com"
    content = (
        "student_id,first_name,last_name,email,major_code,program_code,"
        "major_id,program_id,program_offering_id\n"
        f"{number},Empty,Placement,{email},,,,,\n"
    ).encode()

    report = _upload(client, content).json()
    assert report["created"] == 1, report

    student = db_session.query(Student).filter(Student.student_id == number).one()
    assert (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.student_id == student.id)
        .count()
        == 0
    )
    assert (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == student.id)
        .count()
        == 0
    )


def test_skip_invalid_omits_only_rows_with_retired_placement(client, db_session):
    """Skipping bad rows never creates the rejected student or placement."""
    from app.models.admission import AcademicAdmission, AcademicPlacement
    from app.models.identity import Student

    _login(client)
    good = _number("GOOD")
    bad = _number("BAD")
    content = (
        "student_id,first_name,last_name,email,major_code\n"
        f"{good},Good,Row,{good.lower()}@example.com,\n"
        f"{bad},Bad,Row,{bad.lower()}@example.com,CS\n"
    ).encode()

    report = _upload(client, content, skip_invalid=True).json()

    assert report["aborted"] is False
    assert report["created"] == 1
    assert report["failed"] == 1
    good_student = (
        db_session.query(Student).filter(Student.student_id == good).one()
    )
    bad_student = (
        db_session.query(Student).filter(Student.student_id == bad).first()
    )
    assert bad_student is None
    assert (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.student_id == good_student.id)
        .count()
        == 0
    )
    assert (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == good_student.id)
        .count()
        == 0
    )


def test_one_invalid_row_aborts_the_whole_file(client, db_session):
    from app.models.identity import Student

    _login(client)
    good = _number("OK")
    bad = _number("BAD")
    content = (
        VALID_HEADER
        + f"{good},Grace,Hopper,{good.lower()}@example.com\n"
        # Missing email: a row that must not be silently dropped.
        + f"{bad},No,Email,\n"
    ).encode()

    response = _upload(client, content)
    assert response.status_code == 200, response.text
    report = response.json()

    assert report["aborted"] is True
    assert report["failed"] == 1
    assert report["created"] == 0
    statuses = {row["status"] for row in report["rows"]}
    assert "ERROR" in statuses
    # And the valid row was not applied either.
    assert db_session.query(Student).filter(Student.student_id == good).first() is None


def test_skip_invalid_imports_only_the_valid_rows(client, db_session):
    from app.models.identity import Student

    _login(client)
    good = _number("OK")
    bad = _number("BAD")
    content = (
        VALID_HEADER
        + f"{good},Grace,Hopper,{good.lower()}@example.com\n"
        + f"{bad},No,Email,\n"
    ).encode()

    report = _upload(client, content, skip_invalid=True).json()

    assert report["aborted"] is False
    assert report["created"] == 1
    assert report["failed"] == 1
    assert db_session.query(Student).filter(Student.student_id == good).first() is not None
    assert db_session.query(Student).filter(Student.student_id == bad).first() is None


def test_reimporting_the_same_file_skips_duplicates(client):
    _login(client)
    number = _number()
    content = (VALID_HEADER + f"{number},Anna,Kowalska,{number.lower()}@example.com\n").encode()

    assert _upload(client, content).json()["created"] == 1

    second = _upload(client, content).json()
    assert second["created"] == 0
    assert second["skipped"] == 1
    assert second["aborted"] is False
    assert second["rows"][0]["code"] == "DUPLICATE_STUDENT_NUMBER"


def test_duplicate_rows_inside_one_file_are_skipped(client):
    _login(client)
    number = _number()
    row = f"{number},Anna,Kowalska,{number.lower()}@example.com\n"

    report = _upload(client, (VALID_HEADER + row + row).encode()).json()

    assert report["created"] == 1
    assert report["skipped"] == 1
    assert report["rows"][1]["code"] == "DUPLICATE_IN_FILE"


def test_missing_required_column_is_rejected(client):
    _login(client)

    response = _upload(client, b"student_id,first_name,last_name\nX,A,B\n")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMPORT_MISSING_COLUMNS"


def test_invalid_date_is_reported_not_guessed(client):
    _login(client)
    number = _number()
    content = (
        "student_id,first_name,last_name,email,date_of_birth\n"
        f"{number},Anna,Kowalska,{number.lower()}@example.com,01/02/2004\n"
    ).encode()

    report = _upload(client, content).json()

    assert report["failed"] == 1
    assert report["rows"][0]["code"] == "INVALID_DATE_OF_BIRTH"
    assert report["aborted"] is True


def test_semicolon_delimited_file_with_bom_is_accepted(client):
    _login(client)
    number = _number("SEMI")
    content = (
        "\ufeffstudent_id;first_name;last_name;email\n"
        f"{number};Mei;Lin;{number.lower()}@example.com\n"
    ).encode()

    report = _upload(client, content).json()

    assert report["created"] == 1, report
    assert report["rows"][0]["status"] == "CREATED"


def test_export_returns_csv_for_management(client):
    _login(client)
    number = _number("EXP")
    content = (VALID_HEADER + f"{number},Export,Me,{number.lower()}@example.com\n").encode()
    _upload(client, content)

    response = client.get("/api/v1/students/export")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.splitlines()
    assert lines[0].startswith("student_id,first_name,last_name")
    assert any(number in line for line in lines[1:])


def test_export_neutralises_spreadsheet_formulas(client):
    _login(client)
    number = _number("FORM")
    content = (
        VALID_HEADER + f'{number},=SUM(1),"@cmd",{number.lower()}@example.com\n'
    ).encode()
    assert _upload(client, content).json()["created"] == 1

    response = client.get("/api/v1/students/export")

    assert "'=SUM(1)" in response.text
    assert "'@cmd" in response.text


def test_template_matches_the_importer_header(client):
    _login(client)

    response = client.get("/api/v1/students/import/template")

    assert response.status_code == 200
    header = response.text.splitlines()[0].split(",")
    # The template must satisfy the importer: every required column present.
    for column in ("student_id", "first_name", "last_name", "email"):
        assert column in header
    assert "major_code" not in header
    assert "program_code" not in header


def test_intake_and_export_are_denied_to_students(client):
    _login(client, "student@school.portal")

    assert _upload(client, (VALID_HEADER + "X,A,B,a@example.com\n").encode()).status_code == 403
    assert client.get("/api/v1/students/export").status_code == 403
    assert client.get("/api/v1/students/import/template").status_code == 403
