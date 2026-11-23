# Institutional data migration

This document describes the import capability that exists in SYCUMAIN V2 today,
what each channel guarantees, and what it deliberately refuses to do. It is the
operational contract for the office that runs a migration — not a plan.

## What can be imported

| Channel | Endpoint | File / payload | Writes |
|---|---|---|---|
| Students | `POST /api/v1/students/import` | CSV (multipart) | Student record + login account |
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
8. **Housing applies in one transaction.** All assignments in a batch commit
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

## Rollback and compensation

There is no "undo import" button, and this is intentional: an import is followed
by real edits, and a rollback that ignored those edits would destroy work. What
can be done instead is stated per channel.

| Channel | Reversible? | How |
|---|---|---|
| Students | Partially | Students can be archived (`POST /students/{id}/archive`), which preserves the record and its history. Deleting is not offered. Accounts created by the import should be disabled individually. |
| Housing | Yes, with history preserved | End each assignment through `POST /housing/assignments/{id}/end`. The row is retained with `status = ENDED`, so the import remains traceable and attendance history stays intact. Re-importing the same file after ending is possible, but should be treated as a new migration. |
| Immigration | Value-level only | The profile keeps a version history. Values can be corrected through the profile update, which records the change. An import cannot be "un-run" wholesale. |

What cannot be reversed: temporary passwords issued to imported students (they
exist only in the response and are never stored in plaintext), notifications
already delivered, and any document files already uploaded.

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
