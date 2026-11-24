# Migration rehearsal report (synthetic data)

Generated: 2026-11-24T07:45:06.744578
Database: `scumain_rehearsal` (rebuilt from scratch for this run)

## Institutional totals

| Measure | Count |
|---|---:|
| Intakes planned | 4 |
| Students | 12 |
| Housing assignments created | 12 |
| Immigration profiles | 12 |
| Immigration conflicts | 0 |
| Immigration auto-verified | 0 |
| Activation links issued | 12 |
| Accounts activated | 4 |
| Accounts awaiting activation | 8 |

## Per intake

| Intake | Status | Students | Housed | Immigration | Timetable | Blocking | Warnings |
|---|---|---:|---:|---:|---|---:|---:|
| 2025-FALL | PLANNED | 3 | 3 | 3 | CLEAN | 0 | 0 |
| 2026-SPRING | PLANNED | 3 | 3 | 3 | CLEAN | 0 | 0 |
| 2026-FALL | ACTIVE | 3 | 3 | 3 | CLEAN | 0 | 0 |
| 2027-SPRING | PLANNED | 3 | 3 | 3 | CLEAN | 0 | 0 |

## Unresolved findings

None. Every intake's timetable matched its academic structure.

## Notes

- Synthetic data only; no institutional records were used.
- Accounts are created without a password and cannot sign in until the
  single-use activation link is completed.
- The rehearsal is repeatable: re-running the migration matches existing
  records instead of duplicating them (asserted by
  `tests/test_migration_rehearsal.py`).
