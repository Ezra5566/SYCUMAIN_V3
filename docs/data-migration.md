# Institutional data migration

This document describes the import capability that exists in SYCUMAIN V2 today,
what each channel guarantees, and what it deliberately refuses to do. It is the
operational contract for the office that runs a migration — not a plan.

## What can be imported

| Channel | Endpoint | File / payload | Writes |
|---|---|---|---|
| Students | `POST /api/v1/students/import` | CSV (multipart) | Student record + account provisioned for activation (no password) |
| Housing allocations | `POST /api/v1/housing/import/preview` then `/import/apply` | CSV (multipart) | `housing_assignments` only |
| Immigration values | `POST /api/v1/immigration/import/preview` then `/import/apply` | JSON batch keyed by student number | Profile fields, always unverified |

All three channels identify a person by **student number**. Immigration also
accepts the internal record id for callers that already hold one, but a
migration sheet never needs a UUID.

Templates: `GET /api/v1/students/import/template` and
`GET /api/v1/housing/import/template`.

Every channel is restricted by permission (`student.create`, `housing.assign`,
`immigration.edit`) and every applied run is written to the audit log
(`student.import.applied`, `housing.import.applied`,
`immigration.import.applied`).

## Invariants

These are enforced server-side; the UI only reflects them.

1. **Preview writes nothing.** A preview is a pure read of the file against the
   database. It is the same code path the apply uses, so what the operator sees
   is what would be written.
2. **One invalid row refuses the batch.** Students and housing refuse the whole
   file when any row is invalid, rather than leaving half a cohort or half a
   floor behind. Rows that are merely already satisfied (an existing student, an
   occupied bed) are *skipped* and reported, not treated as failures.
3. **Nothing is overwritten silently.**
   - Housing never transfers a student or evicts an occupant; both are reported
     as skipped.
   - Immigration fills blank fields only. A differing existing value is a
     reported conflict whether or not the profile is verified — an import never
     replaces what the institution already recorded, and never ignores a
     difference without saying so.
   - A row whose values already match is reported as `UNCHANGED` and counted as
     skipped, not as "applied".
4. **Imported immigration is never verified.** Values imported from a file are
   stored as `UNVERIFIED`, `verified_at`/`verified_by` cleared, and a version
   entry records the import. Verification remains an explicit act by an
   authorized administrator.
5. **Dates are not guessed.** `01/02/2026` is rejected; only `YYYY-MM-DD` is
   accepted.
6. **Structure is resolved, not created.** A housing row naming a building,
   room or bed that does not exist is an unresolved reference. Buildings and
   beds are created through the structure endpoints, where the operator sees
   what is being added.
7. **Re-running is safe.** A second run of the same student file skips existing
   students; a second run of the same housing file reports the same rows as
   skipped. Duplicates inside one file are detected before the database sees
   them.
8. **An imported account cannot be signed into.** Migration-created accounts
   carry no usable password and an `activation_required` flag; login refuses
   them with `ACCOUNT_NOT_ACTIVATED` before any password comparison, and only a
   single-use activation link converts them into a normal account. The import
   report never contains a token or a password.
9. **Housing applies in one transaction.** All assignments in a batch commit
   together; an integrity conflict (for example a concurrent assignment to the
   same bed) rolls the whole batch back and the report says it was aborted.

## Running a migration

1. Export the existing sheet to CSV (UTF-8; comma, semicolon or tab
   delimiters are accepted).
2. Download the template and align the columns. Unknown columns are ignored;
   missing required columns are a file-level error.
3. Preview. Review the row report: `VALID` (will be written), `SKIPPED` (already
   present / occupied / duplicate) and `ERROR` (must be corrected).
4. Correct every `ERROR`. Skip nothing silently: a skipped row is a decision, so
   record why in the migration log kept by the office.
5. Confirm. The apply re-validates the file from scratch; it does not trust the
   earlier preview.
6. Reconcile against the source: total source rows, accepted, imported,
   matched, skipped, rejected, unresolved references, duplicate conflicts. The
   report returns the first six directly; unresolved references and duplicate
   conflicts are the `ERROR` and `SKIPPED` codes respectively.
7. Verify in the database that relationships resolved: the assignment points at
   the right bed, the student is the same person as in the source, and the
   counts match.

Pass `source_reference` on the housing apply (for example
`Housing sheet September 2026`). It is stored on each created assignment and in
the audit entry, which is what makes a later dispute answerable.

## Migrated student accounts

A migrated student receives an account, never a shared or temporary password.

1. **Creation or match by student number.** A row whose number already exists
   with the same email is reported `MATCHED` / `EXISTING_STUDENT_MATCHED`; the
   existing profile and account are linked, never overwritten.
2. **Duplicate identities are refused, not merged.** Number with a different
   email is `IDENTITY_MISMATCH`; an email already belonging to another number is
   `AMBIGUOUS_IDENTITY`; a row without an email is `MISSING_CONTACT`. Each is a
   reported row, and the batch is refused rather than guessing.
3. **No usable password is stored.** The account is written with an unusable
   hash and `activation_required = true`. There is no plaintext temporary
   password anywhere in the response, the database, the logs or the report.
4. **Activation token.** 32 random bytes from the OS CSPRNG; the database keeps
   only the SHA-256 hash. One live token per account, seven-day expiry,
   consumed atomically in one transaction, invalidated on use or reissue.
5. **Identity verification before activation.** A staff-issued link requires
   `identity_verified: true` and records who issued it and the reference they
   gave. Self-service cannot mint a link for an account it cannot sign into.
6. **The raw token is not distributed by the system.** It appears in the issue
   response only when `ACTIVATION_RETURN_LINK=true`, a development-only switch
   that the production configuration validator rejects. Production requires an
   `https` `ACTIVATION_LINK_BASE` and delivers the link out of band.
7. **States are explicit.** `GET /api/v1/auth/activation/{token}` reports
   `VALID`, `EXPIRED`, `USED` or `UNKNOWN` before the student types a password,
   and the activation page tells them to request a new link instead of showing
   a dead form.
8. **Recovery paths cover the exceptions.** An expired link is reissued by an
   administrator (`POST /api/v1/users/{id}/activation`, which revokes the
   previous token); a student without an accessible mailbox is activated at the
   counter through the same issuance, with the identity check recorded; password
   reset and change are the existing audited flows and are unchanged.
9. **Audit.** `account.activation.issued`, `account.activation.completed`,
   `account.activation.revoked`, `auth.login.blocked` (activation) and the
   migration batch itself are all audit entries. Tokens are hashed in the audit
   payload, as everywhere else.

`GET /api/v1/users/migration/account-report` returns the migration view:
accounts created, existing accounts matched, still awaiting activation,
missing contact information, ambiguous matches, and accounts needing
administrative intervention, grouped by intake. Emails are masked; no
credential field exists in the schema.

Onboarding by an admissions officer (`POST /students/onboarding`) is a separate
flow and still issues a temporary password with forced change. That path is
unchanged by this work and is *not* used for migration.

## Academic intakes

The four intakes — 2025 Fall, 2026 Spring, 2026 Fall, 2027 Spring — are
academic periods, not labels on a student row. A student's intake is the
period of their `AcademicPlacement`, which points at a `ProgramOffering` of the
correct period; enrollments and timetable entries hang off the section, which
belongs to the offering and therefore to the period.

`POST /api/v1/academics/intakes/plan` plans the periods idempotently:

- an existing period with the same dates is left alone and reported as
  `EXISTING`;
- the same code with different dates is reported as `CONFLICT` and **not**
  overwritten;
- a future period (start date after today) cannot be planned as `ACTIVE`;
  `FUTURE_INTAKE_CANNOT_BE_ACTIVE` is returned instead.

`GET /api/v1/academics/intakes/summary` shows, per intake, students, housed
students, immigration profiles, timetable status and blocking findings. History
is additive: planning never deletes a period, a placement or an enrollment.

The 2027 Spring intake is prepared as `PLANNED`. Nothing activates its students
before admissions and the placement rules allow it; the planning endpoint
refuses `ACTIVE` for a future period, and a student cannot be placed into an
earlier intake without the authorization the placement rules already require.

## Existing timetable reconciliation

The imported timetable is reconciled, not re-imported. `GET
/api/v1/academics/timetable/reconciliation?period_code=...` returns, per intake:

- sections without an offering, and sections whose offering belongs to another
  period;
- timetable entries without a section, or whose section belongs to another
  period;
- duplicates (same section, weekday, start time);
- invalid intervals (`end <= start`) and invalid weekdays;
- room double-bookings and teacher double-bookings within one period;
- sections with no teacher assignment, and teachers assigned to sections of a
  different period;
- enrollments that cross intakes (a student enrolled in a section of a period
  they are not placed in).

The report is **read-only**. It never repairs, deletes or replaces a row:
repairs go through the existing audited timetable endpoints, so every change has
an author and a reason. When a record lacks the information needed to decide
(a section with no offering, a slot with no teacher), the report says so instead
of guessing an association.

Visibility follows placement, not the calendar: a student sees entries for
sections they are enrolled in, a teacher sees entries for sections they are
assigned to, and Management/Admin see and administer the whole intake with the
corresponding permissions.

### What the migrated timetable actually contains

The source map (`docs/scu-timetable-domain-map.json`) describes three periods:
2025 autumn, 2026 spring, 2026 autumn. It contains no 2027 spring timetable and
no section-level teacher assignment for every slot. Reconciliation therefore
reports 2027 Spring as structure-only pending source data, and any section
without an offering is listed as unresolved rather than connected by inference.
This is the honest state of the data, not a limitation of the report.

## Migration order

The order below is the contract; the tooling may execute independent steps in
a different sequence, but no later step may run before its inputs exist.

1. Academic periods and their program offerings.
2. Student records and identity matching (student number first).
3. Admissions and placements into the correct intake and program.
4. Housing assignments, by student number.
5. Immigration records, by student number, always unverified.
6. Timetable reconciliation against the academic structure; repairs through
   audited endpoints.
7. Account provisioning and activation, last, so a broken placement never
   produces a usable account.

## Rehearsal

`apps/api/scripts/rehearsal_report.py` rebuilds a scratch database
(`scumain_rehearsal`), plans the four intakes, imports twelve synthetic
students, places them, houses them, imports their immigration values,
reconciles each intake's timetable, provisions the accounts, completes four
activations and re-runs the account report. It writes
`docs/migration-rehearsal-report.md` and `.json`.

`tests/test_migration_rehearsal.py` runs the same pipeline inside the test
database and asserts the invariants above, including that a second run creates
no duplicates.

The rehearsal proves the pipeline is coherent and repeatable on synthetic data.
It does **not** certify a real institutional migration: real files, real
identities, the institutional authorization and the security/recovery sign-off
are still required before any real student receives an activation link.

## Rollback and compensation

There is no "undo import" button, and this is intentional: an import is followed
by real edits, and a rollback that ignored those edits would destroy work. What
can be done instead is stated per channel.

| Channel | Reversible? | How |
|---|---|---|
| Students | Partially | Students can be archived (`POST /students/{id}/archive`), which preserves the record and its history. Deleting is not offered. Accounts created by the import should be disabled individually. |
| Housing | Yes, with history preserved | End each assignment through `POST /housing/assignments/{id}/end`. The row is retained with `status = ENDED`, so the import remains traceable and attendance history stays intact. Re-importing the same file after ending is possible, but should be treated as a new migration. |
| Immigration | Value-level only | The profile keeps a version history. Values can be corrected through the profile update, which records the change. An import cannot be "un-run" wholesale. |

What cannot be reversed: activation links already delivered to students
(the database stores only their hash, so a link cannot be recovered — it can
only be revoked and reissued), notifications already sent, and any document
files already uploaded.

## Limits of this capability

Honest list of what is **not** built:

- **CSV only for students and housing; JSON for immigration.** XLSX is not
  parsed; the office must save the sheet as CSV, and immigration values are
  submitted as a normalized JSON batch keyed by student number. That is a real
  usability gap for a registrar with a spreadsheet of passport data.
- **No import-history screen.** The audit log is the record of who imported
  what and when; there is no dedicated page with per-batch status.
- **No resumable batches.** A 5 MB / 500-row cap per file is enforced; larger
  migrations must be split, and each part is its own audited batch.
- **No configurable duplicate-matching rules.** Students match on student number
  or email; housing matches on student number plus bed coordinates. The rules
  are fixed and documented rather than per-import.
- **Housing import assigns; it does not transfer.** A student who already has an
  active assignment is skipped and must be moved through the transfer workflow,
  which records the decision.
- **No automatic verification** of imported immigration documents.

## Data protection

- Passport and immigration values are not written to application logs; imports
  log counts and a source reference, not record contents.
- Imported CSV files are parsed in the request and are not retained by the API.
- Templates contain no personal data.
- Real institutional data must not be imported into a development or
  demonstration environment. Use synthetic data for testing.
