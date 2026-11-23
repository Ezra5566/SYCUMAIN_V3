# Attendance commencement — historical backfill strategy

**Status: prepared, not executed.** No commencement record exists for any
historical admission, and this document does not create one. Phase 2 ships the
schema, the approval workflow and the reconciliation view; populating history is
a separate, staff-confirmed operation.

## Why there is no automatic backfill

A commencement is an institutional decision: it is the date from which absences
start to count for a real student's record. Deriving it automatically from
`max(intake start, activation date)` would fabricate that decision for every
existing student, and the suggestion itself may be wrong for anyone who joined
late, was re-admitted, or whose intake dates were later corrected. The policy is
therefore: **history is confirmed by an authorized member of staff, one episode
at a time.**

## What exists today instead

`GET /api/v1/attendance/commencements?status=MISSING` lists every ACTIVE
admission episode that has no current commencement, with:

- the student's name and student number,
- the intake and its official start date,
- the activation date,
- the server-computed suggested date, and which of the two dates produced it.

`status=RECORDED` lists episodes already commenced, and `status=ALL` lists both.
This is the reconciliation surface: it is a live read, it writes nothing, and it
is restricted to `attendance.manage_commencement` (Admin and Management).

## Procedure if the institution decides to reconcile history

1. **Authorize the scope.** Confirm, in writing, which intakes are in scope and
   which role confirms them. Admin and Management act independently — no second
   approver is required, and none may be added by the backfill.
2. **Read the queue.** Filter to `MISSING`, page through the results, and export
   the list for the office's own reconciliation (the API returns the same fields
   the screen shows).
3. **Classify each episode** against the enrolment register:
   - matches the suggestion → approve as `SCHEDULED`;
   - joined later, with documentary evidence → `LATE_JOIN` plus the explanation;
   - date established from another institutional source → `MANUAL` plus the
     reason.
4. **Approve individually** through `POST /students/{student_id}/admissions/{
   admission_id}/commencement`. Each approval records the actor, timestamp,
   reason and the suggestion that was confirmed, and is audited as
   `academic.commencement.approved`.
5. **Correct, never overwrite.** A date entered wrongly is corrected through the
   corrections endpoint, which supersedes the previous row and keeps it in the
   history and the audit log.
6. **Verify.** Re-read `status=MISSING`; the reconciled episodes disappear from
   that view. Any episode still listed was not confirmed and must not be assumed.

## What such a reconciliation must not do

- No bulk insert, no scripted loop that invents dates, no `INSERT` from the
  suggestion column, and no migration that backfills rows.
- No commencement for a `PENDING`, `ADMITTED`, `COMPLETED`, `WITHDRAWN` or
  `CANCELLED` episode: only ACTIVE episodes can be commenced.
- No attendance records, no retrospective absences and no percentages are
  created by commencing a student.
- No transfer of a commencement from an earlier episode to a new one: each
  episode is approved on its own.
- No calendar change may be used as a shortcut to move a commencement date.

## Rollback

There is nothing to roll back until staff have approved records. Once they have,
a commenced episode can be corrected (supersession) but not deleted — the table
guards against deletion, and an approved date is part of the student's record.
The documented rollback for a mistaken approval is a correction with a reason,
which leaves both the mistake and the fix visible in the history.
