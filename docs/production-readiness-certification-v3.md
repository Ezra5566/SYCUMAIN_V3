# SYCUMAIN V3 — Production Readiness Certification (Phase 7)

**Date:** 2026-11-25
**Scope:** V3 (`SYCUMAIN_V2`) certified for operational, security and production readiness against the V1 system at `/Users/ezra/SYCUMAIN` (read-only reference).
**Method:** isolated load testing on synthetic data, dependency and application security assessment, WCAG 2.2 AA audit with fixes, cross-browser runs, real SMTP and real ClamAV verification, and a full clean-state production rehearsal on a fresh database with TLS, backup, restore verification and restart recovery.

**Constraints honoured:** nothing was deployed; no real institutional data was imported; V1 was not modified, merged or reset; no database was merged or reset; no unrelated UI redesign was undertaken; every change is uncommitted and listed in [§12](#12-defects-found-and-fixed-in-this-phase).

---

## 1. Verdict

| Dimension | Status | Basis |
|---|---|---|
| Code readiness | **GREEN** (with caveats) | 1,046 backend tests pass, 2 skipped; type check clean; production image builds; all critical/high application vulnerabilities resolved; accessibility and functional browser suites pass on the tested browsers. |
| Operational readiness | **AMBER** | Rehearsal proves the deployment shape works end to end on one host, but there is no monitoring/metrics endpoint, no off-host backup destination, no log aggregation and no alerting. |
| Staging readiness | **AMBER** | A production-shaped stack (TLS, migrations, scanner, backup/restore) ran successfully in rehearsal; no persistent staging environment exists yet, and Firefox could not be automated on this host. |
| Institutional UAT | **NOT VERIFIED** | No institutional user has exercised the system; no UAT script has been run with staff. |
| Real-data migration | **RED / NOT VERIFIED** | No approved source and none of the four target cohorts exist in any database available here. Migration must not start. |
| Production readiness | **NOT VERIFIED** | Nothing has been deployed to a production host; DNS, certificates, mail provider, scanner service and retention decisions remain open. |

**Bottom line:** the application is fit to be taken to a staging environment and to institutional UAT. It is **not** cleared for production or for real student data. Six decisions in [§11](#11-decisions-requiring-institutional-approval) block that step.

---

## 2. Performance and capacity

**Environment:** dedicated compose project `sycumain-v3-perf` (API on 8010, PostgreSQL 16 on 5440), 4 vCPU, fresh stack per measured run, rate limiting disabled, `SEED_DEMO_DATA=false` after the first seed.

**Dataset:** 1,500 users (1,446 students, 45 teachers, 5 managers), 420 student records, 5 class sections, 1,446 enrolments, 1,760 attendance rows, 30 documents, 100 beds.

**Workload:** 60% student reads, 30% staff reads, 10% sensitive writes (attendance and immigration), 15 s per level.

### 2.1 Single worker (1 uvicorn process)

| Phase | Concurrency | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| Read-heavy | 1 | 19.7 rps | 25 ms | 161 ms | 201 ms | 0% |
| Read-heavy | 5 | 25.5 rps | 164 ms | 488 ms | 582 ms | 0% |
| Read-heavy | 10 | 27.7 rps | 269 ms | 872 ms | 1,105 ms | 0% |
| Read-heavy | 25 | 21.6 rps | 983 ms | 2,261 ms | 2,744 ms | 0% |
| Read-heavy | 50 | 20.8 rps | 2,028 ms | 4,334 ms | 6,669 ms | 0% |
| Write-heavy | 5 | 13.3 rps | 336 ms | 841 ms | 954 ms | 0% |
| Write-heavy | 10 | 13.4 rps | 522 ms | 1,647 ms | 2,095 ms | 0% |
| Write-heavy | 25 | 10.8 rps | 2,018 ms | 5,125 ms | 6,001 ms | 0% |

Login burst: 40 attempts in 2.42 s (16.5 rps), p50 1,663 ms, p95 2,239 ms, all `200`.

Single-process CPU saturates at ~110% of one core before latency degrades: throughput stops improving past ~10 concurrent users. **One worker cannot serve the institution's expected concurrent load**; the ceiling is CPU/GIL, not the database.

### 2.2 Four workers, clean data

| Phase | Concurrency | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|
| Read-heavy | 10 | 91.9 rps | 64 ms | 304 ms | 428 ms | 0% |
| Read-heavy | 25 | 78.5 rps | 253 ms | 840 ms | 1,136 ms | 0% |
| Read-heavy | 50 | 80.5 rps | 456 ms | 1,612 ms | 2,261 ms | 0% |
| Write-heavy | 5 | 30.4 rps | 147 ms | 404 ms | 503 ms | 0% |
| Write-heavy | 10 | 43.0 rps | 202 ms | 570 ms | 838 ms | 20.9% (see note) |

Login burst: 40 attempts in 2.56 s (15.6 rps), p50 2,034 ms, p95 2,295 ms, all `200`.

*Note on the 20.9%: the write scenario allocates unique attendance session dates per request. On a stack that has already absorbed earlier runs, that synthetic pool is exhausted and the API correctly returns `400` for a duplicate session date. It is a harness data limit, not a failure mode; on a fresh stack the same level ran at 43 rps with 0% errors.*

Four workers scale reads ~3.3× and saturate at ~80–92 rps with p95 under 1.7 s at 50 concurrent users. Database connections peaked at 56 of an effective 60 ceiling (pool 5 + overflow 10 per worker).

### 2.3 Sensitive concurrent writes (fresh stack, all passed)

| Scenario | Result |
|---|---|
| 12 concurrent bed assignments to one bed | 1 × `201`, 11 × `409 BED_OCCUPIED` — no double allocation |
| 20 concurrent placements into a one-seat class | 1 × `201`, 19 × `400` — capacity enforced |
| 12 concurrent identical attendance records | 1 × `201`, 11 × `400` — zero duplicate rows |
| 10 concurrent immigration updates | 10 × `200` — complete history, no lost update |
| 10 changes to a retired programme field | 10 × `409` — retirement refusal is stable |

### 2.4 Bottlenecks and recommendations

| Finding | Measurement | Recommendation |
|---|---|---|
| Session touch on every request | `UPDATE user_sessions SET last_accessed_at …` — 18.8 ms mean, 5,103 calls per run | Throttle the touch to once per N minutes per session, or move it out of the request path. Highest-value single change. |
| Attendance listing query | 17–19 ms mean, >1.2M rows scanned on the single-worker run | Add a composite index on `(class_section_id, session_date)` and cap the default page. |
| Connection pool saturation | 56 of 60 connections at 50 users | Size the pool per worker against `max_connections`, or run PgBouncer. |
| Single worker latency cliff | Throughput flat past 10 users; p95 4.3 s at 50 | Run ≥ 4 workers behind a load balancer; never one. |
| Login cost | p50 ~1.7–2.0 s under burst (bcrypt) | Rate-limit at the edge and consider an async hashing worker if login bursts are expected at term start. |

**Capacity statement:** 4 workers on 4 vCPU served 50 concurrent mixed users at 80 rps with p95 1.6 s and 0% errors. That is adequate for a campus portal of a few thousand users at peak registration, provided workers ≥ 4 and the session-touch cost is reduced.

---

## 3. Security assessment

### 3.1 Dependencies

| Item | Result |
|---|---|
| Next.js | **15.5.25 → 15.5.29** — removes the critical unauthenticated image-optimisation RCE and the high/moderate Next.js advisories. Production build passes on the new version. |
| `pnpm audit` after the upgrade | critical **0**, high **3**, moderate **3** |
| Residual advisories | All in build-time tooling (`postcss`, `source-map-js`) used to compile CSS; not reachable at runtime. Documented and deliberately not upgraded (the fix requires a breaking toolchain major). |
| Python dependencies | Pinned sets reviewed with no high/critical advisory reachable from the API's request path; the image does not ship build tooling or test dependencies. |

### 3.2 Application probes (live API, real sessions)

| Attack | Result |
|---|---|
| Cross-origin unsafe request (valid session, foreign `Origin`) | `403 CSRF_ORIGIN_REJECTED`; session remains valid |
| SQL injection in the student search parameter | `200` with zero rows; no error text leaked |
| Student requesting another student's record | `403` |
| Student listing another student's documents | Own documents only (0 foreign) |
| Unknown document id | Generic `404` |
| Teacher attempting an admin password reset | `403` |
| Session cookie flags | `HttpOnly; SameSite=Lax; Secure` (`Secure` enforced in production; rehearsal confirmed) |
| Anonymous access to protected API | `401` |
| HTTP → HTTPS | `308` redirect to the HTTPS origin |
| Security headers (web) | HSTS `max-age=31536000; includeSubDomains`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, `Cross-Origin-Opener-Policy: same-origin` |
| API docs in production | `/docs`, `/redoc`, `/openapi.json` return `404` — deliberately disabled outside development |
| Rate limiting | Enabled in production compose; not exercised under load (disabled for load measurement) |

### 3.3 Origin guard and trusted proxy

The CSRF defence is a single ASGI middleware (`apps/api/app/core/origin.py`). Trusted origins derive from `CORS_ORIGINS`; `Host` and `X-Forwarded-*` are never used to widen the list, so a spoofed forwarded header cannot bypass it. A request without `Origin` (curl, CLI, integrations) is allowed only when `Sec-Fetch-Site` is not `cross-site` and any `Referer` is same-origin. In production the API runs with `--proxy-headers --forwarded-allow-ips=<compose subnet>`, so client IPs and scheme are taken only from Caddy.

**Deployment requirement:** the live origin must appear in `CORS_ORIGINS`, which the compose file derives from `APP_ORIGIN`. Omitting it breaks every unsafe request with `403`.

### 3.4 Residual security risks

* No `Content-Security-Policy` header is emitted. Next.js inline bootstrap scripts make a strict policy a project of its own; recommend a report-only policy first.
* Build-time dependency advisories remain (see above).
* No secret rotation procedure is documented; `SECRET_KEY` rotation invalidates all sessions.
* Malware scanning depends on an external daemon (see §7) — if it is down, uploads fail closed with `503`.

---

## 4. Accessibility (WCAG 2.2 AA, practical audit)

The audit combines automated assertions with real keyboard interaction; it is a practical audit, not a conformance claim.

### 4.1 Defects found and fixed

| Defect | Fix |
|---|---|
| Rejected login coloured the fields red without exposing the error to assistive technology | Both fields now carry `aria-invalid="true"` and `aria-describedby="login-error"` on a `401` |
| Card titles emitted `h3` beneath an `h1`, skipping a level | `CardTitle` renders `h2` |
| Student directory table had no accessible name | `DataTable` accepts a label; the directory passes one |
| Select-all column had an empty header cell | Screen-reader-only header text added |
| Account menu did not reliably return focus to its trigger | Explicit focus restore via `onOpenChange` plus a bounded fallback; assertion uses `toBeFocused` |

### 4.2 Results

| Check | Chromium | WebKit |
|---|---|---|
| Login is keyboard-operable and announces errors | pass | pass |
| Every visible login control has an accessible name | pass | pass |
| Focus indicator visible on 22 successive controls | pass | pass |
| Single `h1`, no skipped heading levels (`/app`, `/app/students`) | pass | pass |
| Account menu labelled, keyboard-operable, restores focus | pass | pass |
| Modal dialog traps focus, closes on Escape, returns focus | pass | pass |
| Tables expose headers and an accessible name | pass | pass |
| Sampled text meets 4.5:1 contrast | pass | pass |
| Images carry alt text | pass | pass |
| Arabic layout is RTL with no horizontal overflow | pass | pass |
| 200% text scaling introduces no horizontal scrolling | pass | pass |

**11/11 on both browsers** against the production build.

---

## 5. Cross-browser certification

| Browser | Version | Result |
|---|---|---|
| Chromium (Playwright bundled) | 1243 build | **PASS** — 27/27 (11 accessibility + 16 smoke) |
| WebKit (Safari engine) | 26.6 (build 2359) | **PASS** — 27/27 |
| Firefox | 155.0 (build 1543) | **NOT VERIFIED — environment limitation** |

Firefox never launched: every test failed in 1 ms with `browserType.launch: Failed to launch the browser process … Could not find profile folder.` The failure reproduces **outside Playwright**, by running the downloaded Firefox binary directly against a freshly created profile directory, and it reproduces with a second cached Firefox build. `firefox --version` works, so the binary is intact; the browser itself refuses to open any profile on this host (macOS 27.2.1). This is a browser/OS incompatibility on the certification machine, not an application defect, and it must be re-run on a supported macOS or Linux host before Firefox can be certified.

**WebKit false positives found and fixed:** the first WebKit run failed 8 staff-page tests because the smoke suite's page-health tracker counted Next.js route prefetches cancelled during navigation (WebKit words them `Load request cancelled` and `… due to access control checks`) as failures. The tracker now ignores cancellations and `_rsc` prefetches, and reports the failure text for anything else. Page assertions had already passed in those tests, and WebKit went 19/27 → 27/27 with the fix; Chromium re-ran green afterwards.

---

## 6. Email and password recovery

Verified against a real SMTP sink (no mock transport) on port 1026, with `PASSWORD_RESET_DELIVERY=smtp`.

| Case | Result |
|---|---|
| Password reset message | Delivered in 1 attempt; correct `From`, `To`, `Subject`; `Auto-Submitted` and `X-Portal-Purpose` headers set |
| Account activation message | Delivered in 1 attempt, same header contract |
| Notification message | Delivered in 1 attempt, opt-in only |
| Delivery failure (closed port) | Bounded retries recorded (`attempts=2/3`), `ConnectionRefusedError` stored on the outbox row |
| Duplicate suppression | `dedupe_key` on `email_outbox` prevents a repeat notification for the same event |
| Logs | No token, password or message body is logged; addresses are masked |

Admin-assisted password recovery is unchanged in shape and now safer: the temporary credential is single-use, expires after `TEMPORARY_PASSWORD_EXPIRE_HOURS=72`, forces an immediate change, and revokes the account's other sessions. The initiating admin, target account and timestamp are audited; the credential itself never is. The endpoint is ADMIN-only (teacher attempt returned `403`). Self-service email recovery is **not** required for this phase and remains configurable.

*Institutional decision required:* which mail provider is used in production. Until one is configured, `PASSWORD_RESET_DELIVERY=disabled` and the reset flow is hidden.

---

## 7. Malware scanning

Real ClamAV 1.5.4 (signature set 28180), not a stub.

| Case | Result |
|---|---|
| Raw EICAR test file | `INFECTED` — upload refused |
| Clean PDF | `201`, `scan_status=CLEAN`, engine `clamav` |
| PDF containing a controlled custom signature (`SYCUMAIN-MALWARE-MARKER`) | `422 MALWARE_DETECTED`; **no document row, no stored bytes** |
| Upload before scanning completes | Impossible by construction: scan happens before the object is written and the row is committed |
| Scanner unreachable | `503 SCANNER_UNAVAILABLE` — the file is refused, never stored unscanned (fail-closed) |

**Finding — EICAR is not a valid fixture inside a document.** The official EICAR signature matches the whole test file, so a PDF that embeds the EICAR string is reported `OK` by ClamAV. Detection of embedded payloads must be proven with a custom signature database (as done above) or with a real sample, never with EICAR pasted into a document.

**Defect found and fixed during rehearsal:** `docker-compose.prod.yml` accepted `MALWARE_SCANNER=clamav` but never forwarded `CLAMAV_HOST`/`CLAMAV_PORT`, so the API looked for a `clamav` hostname inside its own container and every upload failed closed with `503`. The compose file now forwards `CLAMAV_HOST`, `CLAMAV_PORT` and `CLAMAV_TIMEOUT_SECONDS`, and `.env.production.example` documents them. After the fix, an upload through TLS against the real daemon returned `201 CLEAN`.

*Institutional decision required:* where the ClamAV service runs, who owns its signature updates, and how long quarantined files are retained.

---

## 8. Backup, restore and recovery

| Step | Result |
|---|---|
| Backup | `db-20261125T044148Z.dump` (250,813 bytes), `storage-…tar.gz` (246 entries), SHA-256 manifest, `latest.txt` pointer; files written to the host, mode `0600` |
| Restore verification (scratch database, live data untouched) | 64 tables, 1 alembic revision, 1 student, 2 users, 1 document; 0 missing objects, 0 checksum failures |
| Document byte integrity | Every restored document matched the checksum stored in `documents.checksum_sha256` |
| Cold restart (`down` then `up -d`, volumes kept) | `/ready` healthy in ~4 s; login `200`; the student record was present; the downloaded document was byte-identical to the uploaded file (SHA-256 match) |

The restore script refuses to touch live data without typing the database name, and verification always uses a scratch database first.

**Gaps (operational, not code):** the backup target is a local directory — there is no off-host copy, no schedule, no retention policy and no restore drill cadence. RPO/RTO have not been agreed.

---

## 9. Production rehearsal

Fresh compose project `sycumain-v3-rehearsal`, fresh database `school_portal_v3_rehearsal`, single origin `https://localhost:8443` behind Caddy with a local CA, scanner and mail settings from a git-ignored `.env.rehearsal`, random secrets.

| Step | Result |
|---|---|
| Image build (api, web, caddy) | passed (`BUILD_EXIT=0`) |
| Network creation | initially failed: `Pool overlaps with other one on this address space` because an orphaned `school-portal-prod_internal` network held `172.31.240.0/24`. Rehearsal moved to `172.31.241.0/24`; no existing network or container was touched. |
| Explicit migration (`--profile tools run --rm migrate`) | applied every revision from empty to head `c4d7e91b2f68` |
| `up -d` | api, web, postgres healthy; caddy started |
| Health through TLS | `/health` → `{"status":"ok","environment":"production"}`; `/ready` → database `ok`, storage `ok` |
| Bootstrap admin | created once, temporary password printed once and forced to change |
| Login through TLS | `200`; `must_change_password=true`; cookie `HttpOnly; SameSite=lax; Secure` |
| Forced password change | `200`; `must_change_password=false`; other sessions revoked |
| Representative workflow | account created (`201`), student created (`201`), found by search; audit trail recorded `auth.login_succeeded`, `auth.password_changed`, `account.created`, `student.created` in order |
| Document upload through TLS | `201`, `scan_status=CLEAN` via the real ClamAV daemon |
| Authorisation | anonymous `401`; teacher-level reset attempt `403` |
| Backup + verification | as §8 |
| Cold restart recovery | as §8 |

**Rehearsal finding:** the compose network subnet default can collide with a pre-existing bridge network on a host. Production must set `PROD_NETWORK_SUBNET` to a free range, and the documentation should say so.

---

## 10. Institutional reconciliation (investigation only)

Read-only queries only; no import, merge or reset. The development database (port 5435) is **not** an approved source.

| Question | Finding |
|---|---|
| Students in V3 development | 26 synthetic records, one academic period (`2026-FALL`) |
| Students in V1 | 17 records, including non-institutional identifiers (`test`, `131412526`); one period `2026-FALL` |
| Target cohorts (2025 Fall, 2026 Spring, 2026 Fall, 2027 Spring) | **None exist** in either database — no cohort data has been supplied |
| V1 students without an admission record | 5 |
| V1 class sections without a source | 8 |
| V1 class sections without a timetable | 3 |
| V1 applied import batches | 1 (`2026-2027-1 专业课表`): batch metadata claims 3 periods / 33 sections, applied 1 period / 9 sections — the batch record and its effect disagree |
| Duplicate active bed assignments | none |
| Duplicate immigration profiles | none |

**Conclusion:** migration cannot be rehearsed against real structure, because the authoritative extract has not been provided. The V1 anomalies above must be resolved by the institution before any extract is trusted, and the import-batch discrepancy is itself evidence that V1 provenance is not reliable enough to migrate blindly.

---

## 11. Decisions requiring institutional approval

1. **Canonical source and cohort set** for migration, and who signs off an extract.
2. **Mail provider** (SMTP relay or API) and the From address/domain policy.
3. **ClamAV service location**, ownership of signature updates, and quarantine retention.
4. **Data retention periods** (graduated/withdrawn/inactive), plus agreed **RPO/RTO** and off-host backup destination.
5. **Whether MANAGEMENT may hold `users.manage`** — currently it may read the account directory but not create, suspend or re-role accounts.
6. **Vacation calendar policy** (who may declare institution-wide vacation days and how they interact with attendance).
7. **Trusted production origin list** — the exact public origin(s) that go into `CORS_ORIGINS`.
8. **TLS strategy** in production (ACME vs institutional certificate) and who owns renewal.

---

## 12. Defects found and fixed in this phase

| Area | Defect | Fix |
|---|---|---|
| Dependencies | Next.js 15.5.25 carried a critical RCE | Upgraded to 15.5.29; build and browser suites re-run |
| Accessibility | Login errors not announced; `h3` under `h1`; unnamed tables and select-all column; unreliable menu focus restore | Fixed in five files; 11/11 checks pass on two browsers |
| Deployment | `MALWARE_SCANNER=clamav` could not work: scanner address never forwarded | `CLAMAV_HOST`/`CLAMAV_PORT`/`CLAMAV_TIMEOUT_SECONDS` forwarded and documented |
| Temporary credentials | Temporary passwords had no expiry | `TEMPORARY_PASSWORD_EXPIRE_HOURS=72`, single use, forced change, session revocation |
| Email | Notifications could be re-sent and failures were invisible | `email_outbox` with `dedupe_key`, bounded retries, masked logs |
| Test harness | WebKit prefetch cancellations counted as page failures | Tracker ignores cancellations and reports failure text |
| Test harness | Load runner reused attendance dates and broke on re-run | Unique session dates, own timetable, repeatable capacity reset |
| Test harness | `docker-compose.perf.yml` hard-coded seed/scanner values | Values are overridable |

Unchanged by design: origin guard semantics, cookie flags, role model, V1 behaviour, and every screen not named above.

---

## 13. What was not done

* No deployment to any environment; no DNS, certificate or production host was touched.
* No real institutional data was read into V3, and no migration was executed.
* No institutional user acceptance testing.
* Firefox could not be certified on this host (§5).
* Monitoring, alerting and log aggregation were not built; no metrics endpoint exists.
* No penetration test by an external party, and no load test against production hardware.
* EICAR-inside-document detection is not proven (and cannot be, see §7).
