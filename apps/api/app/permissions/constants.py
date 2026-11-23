"""Permission constants and role-permission mappings."""

# All permissions organized by module
ALL_PERMISSIONS: dict[str, list[dict[str, str]]] = {
    "student": [
        {"codename": "student.view", "description": "View student profiles"},
        {"codename": "student.create", "description": "Create student records"},
        {"codename": "student.edit", "description": "Edit student profiles"},
        {"codename": "student.archive", "description": "Archive student records"},
    ],
    "immigration": [
        # `immigration.view` covers a student's *own* record. The overview is a
        # different surface: it exposes every student's document status, so it
        # needs its own permission rather than reusing the self-service one.
        {"codename": "immigration.view", "description": "View own immigration records"},
        {
            "codename": "immigration.view_all",
            "description": "View immigration records for all students",
        },
        {"codename": "immigration.edit", "description": "Edit immigration records"},
        {"codename": "immigration.review_change", "description": "Review change requests"},
        {"codename": "immigration.manage_documents", "description": "Manage immigration documents"},
        {
            "codename": "immigration.submit_change",
            "description": "Submit immigration change requests",
        },
    ],
    "housing": [
        {"codename": "housing.view", "description": "View housing information"},
        {
            "codename": "housing.view_all",
            "description": "Browse the whole dormitory (buildings, rooms and occupants)",
        },
        {"codename": "housing.create", "description": "Create housing resources"},
        {"codename": "housing.assign", "description": "Assign students to rooms"},
        {"codename": "housing.transfer", "description": "Transfer room assignments"},
        {"codename": "housing.edit", "description": "Edit housing resources"},
        {"codename": "housing.manage_issues", "description": "Manage housing issues"},
    ],
    "academic": [
        {"codename": "academic.view", "description": "View academic data"},
        {"codename": "academic.manage_majors", "description": "Manage majors"},
        {"codename": "academic.manage_programs", "description": "Manage programs"},
        {"codename": "academic.manage_courses", "description": "Manage courses"},
        {"codename": "academic.manage_classes", "description": "Manage classes/sections"},
        {"codename": "academic.manage_timetable", "description": "Manage timetable"},
        {"codename": "academic.manage_enrollment", "description": "Manage enrollments"},
        {"codename": "academic.manage_classrooms", "description": "Manage classrooms"},
        {"codename": "academic.manage_periods", "description": "Manage academic periods"},
        {"codename": "academic.manage_teachers", "description": "Manage teacher assignments"},
        {"codename": "attendance.view", "description": "View attendance records"},
        {"codename": "attendance.edit", "description": "Edit attendance records"},
        # Recording a general absence is not editing a register. It is
        # institution-wide and section-free, so it is named for the act rather
        # than folded into `attendance.edit`, which stays scoped to existing
        # section-level records.
        {
            "codename": "attendance.record_class",
            "description": "Record institution-wide class absences",
        },
        {
            "codename": "attendance.record_dormitory",
            "description": "Record dormitory absences",
        },
        # Dormitory attendance is a separate domain: it runs on every calendar
        # day, is driven by housing stays rather than by the academic calendar,
        # and is closed to teachers. Reading it therefore needs its own
        # permission instead of reusing the academic `attendance.view`.
        {
            "codename": "attendance.view_dormitory",
            "description": "View dormitory attendance records",
        },
        {
            "codename": "attendance.manage_calendar",
            "description": "Manage working-day calendar exceptions",
        },
        # Commencement is the date from which attendance is expected to count.
        # It is an institutional approval, not part of a teacher's register.
        {
            "codename": "attendance.manage_commencement",
            "description": "Approve and correct attendance commencement dates",
        },
        # Phase 3: attendance is stored as student absences per admission
        # episode, so recording is its own scoped permission. Teachers hold it
        # for their own students; the endpoint enforces the section assignment.
        {
            "codename": "attendance.record_absence",
            "description": "Record and correct student absences",
        },
        {"codename": "grades.view", "description": "View grades"},
        {"codename": "grades.edit", "description": "Edit grades"},
        {
            "codename": "grades.publish",
            "description": "Publish assessment results to students",
        },
        {"codename": "exams.view", "description": "View examinations"},
        {"codename": "exams.manage", "description": "Create and edit examinations"},
        # Recording a result is separable from administering the calendar: a
        # teacher may enter marks for the sections they teach without gaining
        # the ability to schedule, reschedule or cancel examinations.
        {
            "codename": "exams.record_results",
            "description": "Record and correct examination results",
        },
        {"codename": "exams.publish", "description": "Publish examination results"},
    ],
    "admission": [
        {
            "codename": "academic.view_admissions",
            "description": "View admissions and placements",
        },
        {
            "codename": "academic.manage_admissions",
            "description": "Create and edit admissions",
        },
        {
            "codename": "academic.activate_admission",
            "description": "Activate an admitted episode",
        },
        {
            "codename": "academic.end_admission",
            "description": "Complete or withdraw an admission",
        },
        {
            "codename": "academic.manage_placements",
            "description": "Create and supersede placements",
        },
        {
            "codename": "academic.authorize_placement",
            "description": "Authorize earlier-intake placement",
        },
        {
            "codename": "academic.approve_admission_change",
            "description": "Approve or reject admission changes",
        },
        {
            "codename": "academic.confirm_admission_management",
            "description": "Fill the Management verification slot",
        },
        {
            "codename": "academic.confirm_admission_admin",
            "description": "Fill the Admin verification slot",
        },
        {
            "codename": "academic.correct_period_dates",
            "description": "Correct official intake dates",
        },
        {
            "codename": "academic.correct_admission_status",
            "description": "Correct a terminal admission status",
        },
        {
            "codename": "academic.correct_original_admission",
            "description": "Replace an original admission",
        },
    ],
    "announcement": [
        {"codename": "announcement.view", "description": "View announcements"},
        {"codename": "announcement.create", "description": "Create announcements"},
        {"codename": "announcement.edit", "description": "Edit announcements"},
        {"codename": "announcement.publish", "description": "Publish announcements"},
    ],
    "support": [
        {"codename": "support.view", "description": "View support tickets"},
        {"codename": "support.create", "description": "Create support tickets"},
        {"codename": "support.manage", "description": "Manage support tickets"},
        {"codename": "support.assign", "description": "Assign support tickets"},
        {"codename": "support.respond", "description": "Respond to support tickets"},
        {"codename": "support.resolve", "description": "Resolve or close support tickets"},
    ],
    "notifications": [
        {"codename": "notifications.view", "description": "View own notifications"},
        {"codename": "notifications.manage", "description": "Manage notifications"},
    ],
    "documents": [
        {"codename": "documents.view", "description": "View documents"},
        {"codename": "documents.upload", "description": "Upload documents"},
        {"codename": "documents.manage", "description": "Manage and delete documents"},
    ],
    "reports": [
        {"codename": "reports.view", "description": "View reports"},
    ],
    "audit": [
        {"codename": "audit.view", "description": "View audit logs"},
    ],
    "users": [
        {"codename": "users.view", "description": "View user accounts"},
        {"codename": "users.manage", "description": "Manage all user accounts"},
        {
            "codename": "users.manage_students",
            "description": "Create and manage student accounts only",
        },
    ],
    "permissions": [
        {"codename": "permissions.manage", "description": "Manage permissions"},
    ],
    "system": [
        {"codename": "system.manage", "description": "Manage system settings"},
    ],
}

# Role -> permission mappings (seeded on startup)
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "ADMIN": [
        # Admin has all permissions
        perm
        for perms in ALL_PERMISSIONS.values()
        for perm in [p["codename"] for p in perms]
    ],
    "MANAGEMENT": [
        "student.view",
        "student.create",
        "student.edit",
        "student.archive",
        "immigration.view",
        "immigration.view_all",
        "immigration.edit",
        "immigration.review_change",
        "immigration.manage_documents",
        "housing.view",
        "housing.view_all",
        "housing.create",
        "housing.assign",
        "housing.transfer",
        "housing.edit",
        "housing.manage_issues",
        "academic.view",
        "academic.manage_majors",
        "academic.manage_programs",
        "academic.manage_courses",
        "academic.manage_periods",
        "academic.manage_classes",
        "academic.manage_classrooms",
        "academic.manage_teachers",
        "academic.manage_timetable",
        "academic.manage_enrollment",
        # Phase 0: `attendance.edit` alone never allowed a Management user to
        # read an attendance record. View is granted here because the edit
        # permission already implies reading, and class recording is a
        # Management act, not a teacher one. Phase 1 adds calendar
        # administration. Dormitory recording stays ungranted: that workflow
        # does not exist yet, so Management acquires it only in the phase that
        # builds it.
        "attendance.view",
        "attendance.edit",
        "attendance.record_class",
        "attendance.record_absence",
        "attendance.manage_calendar",
        "attendance.manage_commencement",
        # The dormitory workflow now exists, so Management acquires the two
        # dormitory permissions. Teachers deliberately do not: a class roster
        # is not a residential roster.
        "attendance.record_dormitory",
        "attendance.view_dormitory",
        "grades.edit",
        # Examinations: Management runs the operational calendar, records and
        # corrects results, and publishes them. Admin holds all of these
        # automatically through the all-permissions mapping above.
        "exams.view",
        "exams.manage",
        "exams.record_results",
        "exams.publish",
        "announcement.view",
        "announcement.create",
        "announcement.edit",
        "announcement.publish",
        "support.view",
        "support.create",
        "support.manage",
        "support.assign",
        "support.respond",
        "support.resolve",
        "notifications.view",
        "notifications.manage",
        "documents.view",
        "documents.upload",
        "documents.manage",
        "reports.view",
        "audit.view",
        # Admission operations. Deliberately excludes both slot-specific
        # verification permissions and the original-pointer correction, which
        # remain Admin-only.
        "academic.view_admissions",
        "academic.manage_admissions",
        "academic.activate_admission",
        "academic.end_admission",
        "academic.manage_placements",
        "academic.authorize_placement",
        "academic.approve_admission_change",
        "academic.confirm_admission_management",
        "academic.correct_period_dates",
        # Operational account administration: management onboards students and
        # resets their passwords, but must not touch staff or admin accounts.
        "users.view",
        "users.manage_students",
    ],
    "TEACHER": [
        "student.view",
        "academic.view",
        "attendance.view",
        "attendance.edit",
        # Phase 3: a teacher records absences for students enrolled in the
        # sections they are assigned to. The endpoint still enforces that
        # assignment; the permission alone opens no other student.
        "attendance.record_absence",
        "grades.view",
        "grades.edit",
        # A teacher sees examinations of the sections they are assigned to and
        # records results for those sections only. The service recomputes that
        # scope on every request; the permission alone opens nothing else.
        # Teachers cannot schedule or publish: those remain institutional acts.
        "exams.view",
        "exams.record_results",
        "announcement.view",
        "announcement.create",
        "support.view",
        "support.create",
        "support.respond",
        "notifications.view",
        # Teachers deliberately have no document permission. Class membership
        # grants academic scope, never access to passports or private files.
    ],
    "STUDENT": [
        "student.view",
        "academic.view",
        "attendance.view",
        # Read-only self-service for dormitory attendance. The `/dormitory/me`
        # endpoint resolves the student from the session, and every staff
        # surface re-checks for a staff role, so the permission alone never
        # exposes another resident's record.
        "attendance.view_dormitory",
        "grades.view",
        # Read-only examinations: the schedule of the sections they are enrolled
        # in, and their own results once the institution publishes them.
        "exams.view",
        "housing.view",
        "immigration.view",
        "immigration.submit_change",
        "announcement.view",
        "support.view",
        "support.create",
        "notifications.view",
        "documents.view",
        "documents.upload",
    ],
}
