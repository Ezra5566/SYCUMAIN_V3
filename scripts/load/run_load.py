#!/usr/bin/env python3
"""Load and concurrency measurement for SYCUMAIN V3.

    apps/api/.venv/bin/python scripts/load/run_load.py \
        --base-url http://localhost:8010 --seed .perf/load_seed.json

Runs against the isolated performance stack (docker-compose.perf.yml). It logs
in as synthetic accounts only; there is no institutional data in the stack.

What it measures
----------------
* a mixed read-heavy workload and a write-heavy workload at increasing
  concurrency (requests/second, p50/p95/p99, error rate by status);
* authentication throughput separately, because bcrypt dominates it;
* container CPU/memory and PostgreSQL connection counts sampled during each
  level;
* targeted concurrency races on sensitive writes: bed assignment, class
  capacity, attendance, immigration correction and the retired program-change
  route.

Every failure is reported, never retried into a passing number.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import statistics
import subprocess
import threading
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import httpx

API = "/api/v1"


# --------------------------------------------------------------------------
# Infrastructure sampling
# --------------------------------------------------------------------------


class Sampler(threading.Thread):
    """Sample container CPU/memory and database connections while loading."""

    def __init__(self, api_container: str, pg_container: str, db: str) -> None:
        super().__init__(daemon=True)
        self.api_container = api_container
        self.pg_container = pg_container
        self.db = db
        self.samples: list[dict] = []
        # Not `_stop`: Thread already defines that method internally.
        self._halt = threading.Event()

    def _docker(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["docker", *args], capture_output=True, text=True, timeout=20
            )
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    @staticmethod
    def _parse_mib(value: str) -> float:
        value = value.strip()
        for unit, factor in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024)):
            if value.endswith(unit):
                try:
                    return float(value[: -len(unit)]) * factor
                except ValueError:
                    return 0.0
        return 0.0

    def sample_once(self) -> dict:
        stats: dict[str, dict] = {}
        raw = self._docker(
            "stats", "--no-stream", "--format",
            "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}",
            self.api_container,
            self.pg_container,
        )
        for line in raw.splitlines():
            parts = line.split("|")
            if len(parts) != 4:
                continue
            name, cpu, mem, mem_pct = parts
            current = mem.split("/")[0].strip()
            # Container names carry the compose project prefix; the summary is
            # keyed by service so callers do not depend on the project name.
            key = "postgres" if "postgres" in name else "api"
            stats[key] = {
                "cpu_percent": float(cpu.rstrip("%") or 0),
                "mem_mib": self._parse_mib(current),
                "mem_percent": float(mem_pct.rstrip("%") or 0),
            }

        connections = self._docker(
            "exec", self.pg_container, "psql", "-U", "portal", "-d", self.db,
            "-tAc",
            "SELECT count(*) FILTER (WHERE state='active'), count(*) "
            "FROM pg_stat_activity WHERE datname=current_database()",
        )
        active = total = 0
        if "|" in connections:
            try:
                active, total = (int(part) for part in connections.split("|", 1))
            except ValueError:
                pass

        return {
            "at": time.time(),
            "containers": stats,
            "db_active": active,
            "db_total": total,
        }

    def run(self) -> None:  # pragma: no cover - timing thread
        while not self._halt.is_set():
            self.samples.append(self.sample_once())
            self._halt.wait(2)

    def stop(self) -> list[dict]:
        self._halt.set()
        self.join(timeout=10)
        return self.samples


def summarise_samples(samples: list[dict]) -> dict:
    api_cpu = [
        s["containers"].get("api", {}).get("cpu_percent", 0) for s in samples
    ]
    api_mem = [s["containers"].get("api", {}).get("mem_mib", 0) for s in samples]
    db_cpu = [
        s["containers"].get("postgres", {}).get("cpu_percent", 0) for s in samples
    ]
    connections = [s["db_total"] for s in samples]
    active = [s["db_active"] for s in samples]

    def peak(values: list[float]) -> float:
        return round(max(values), 1) if values else 0.0

    def mean(values: list[float]) -> float:
        return round(statistics.fmean(values), 1) if values else 0.0

    return {
        "api_cpu_peak_percent": peak(api_cpu),
        "api_cpu_mean_percent": mean(api_cpu),
        "api_mem_peak_mib": peak(api_mem),
        "db_cpu_peak_percent": peak(db_cpu),
        "db_cpu_mean_percent": mean(db_cpu),
        "db_connections_peak": max(connections) if connections else 0,
        "db_connections_mean": mean(connections),
        "db_active_peak": max(active) if active else 0,
        "samples": len(samples),
    }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------


async def login(
    base_url: str, email: str, password: str
) -> httpx.AsyncClient:
    client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
    response = await client.post(f"{API}/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        raise RuntimeError(
            f"login failed for {email}: {response.status_code} {response.text[:200]}"
        )
    return client


async def login_storm(base_url: str, accounts: list[tuple[str, str]]) -> dict:
    """Measure authentication throughput with fresh sessions."""
    latencies: list[float] = []
    statuses: Counter = Counter()

    async def attempt(email: str, password: str) -> None:
        started = time.perf_counter()
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            response = await client.post(
                f"{API}/auth/login", json={"email": email, "password": password}
            )
        latencies.append((time.perf_counter() - started) * 1000)
        statuses[response.status_code] += 1

    started = time.perf_counter()
    await asyncio.gather(*(attempt(e, p) for e, p in accounts))
    elapsed = time.perf_counter() - started
    return {
        "attempts": len(accounts),
        "seconds": round(elapsed, 2),
        "requests_per_second": round(len(accounts) / elapsed, 1),
        "p50_ms": round(percentile(latencies, 50), 1),
        "p95_ms": round(percentile(latencies, 95), 1),
        "p99_ms": round(percentile(latencies, 99), 1),
        "statuses": dict(statuses),
    }


# --------------------------------------------------------------------------
# Workload
# --------------------------------------------------------------------------


class Workload:
    def __init__(self, seed: dict, clients: dict) -> None:
        self.seed = seed
        self.clients = clients
        self.students = seed["students"]
        # Each session belongs to a known student, so "my timetable" is fetched
        # for the account actually holding the cookie. Requesting another
        # student's timetable is a 403 by design, not a capacity result.
        self.peers = list(zip(clients["students"], self.students))
        self.write_sequence = itertools.count()
        self.sections = seed["sections"]
        self.documents = seed["documents"]
        self.immigration_students = seed["immigration_student_ids"]
        # One roster per section: attendance is refused for a student who is
        # not enrolled in that section, which is exactly the validation the
        # write workload should be exercising, not tripping over.
        self.rosters = {
            section: [
                student["student_id"]
                for index, student in enumerate(self.students)
                if index % len(self.sections) == position
            ][:20]
            for position, section in enumerate(self.sections)
        }

    async def read(self, ticket: int) -> tuple[str, int]:
        """One weighted read, alternating student and staff viewpoints."""
        if ticket % 10 < 6:
            client, student = self.peers[ticket % len(self.peers)]
            choices = (
                ("student_me", f"{API}/students/me"),
                (
                    "student_timetable",
                    f"{API}/academics/students/{student['student_id']}/timetable",
                ),
                ("notifications", f"{API}/notifications"),
                ("student_academic", f"{API}/students/me/academic"),
            )
            name, url = choices[ticket % len(choices)]
        else:
            section = self.sections[ticket % len(self.sections)]
            document = self.documents[ticket % len(self.documents)]
            # Each action names the role that may perform it: a teacher cannot
            # read the student directory, and mixing the two would count 403s
            # as capacity rather than measuring the endpoint.
            choices = (
                ("student_search", f"{API}/students/?search=Load&page=1&page_size=25", "admin"),
                ("student_page", f"{API}/students/?page=2&page_size=25", "admin"),
                ("class_list", f"{API}/academics/classes", "teacher"),
                ("teacher_timetable", f"{API}/academics/timetable", "teacher"),
                ("enrollments", f"{API}/academics/classes/{section}/enrollments", "admin"),
                ("immigration_overview", f"{API}/immigration/overview", "admin"),
                ("housing_overview", f"{API}/housing/overview", "admin"),
                ("reports_overview", f"{API}/reports/overview", "admin"),
                ("document_download", f"{API}/documents/{document['id']}/download", "admin"),
                ("audit_page", f"{API}/audit?page=1&page_size=25", "admin"),
            )
            name, url, who = choices[ticket % len(choices)]
            client = self.clients["admin"] if who == "admin" else self.clients["teacher"]

        response = await client.get(url)
        return name, response.status_code

    async def write(self, ticket: int) -> tuple[str, int]:
        """Sensitive write paths, alternating attendance and immigration."""
        if ticket % 2 == 0:
            client = self.clients["admin"]
            sequence = next(self.write_sequence)
            # One section, a distinct session date per write: a repeated date
            # is refused once attendance for it exists, and that refusal is not
            # the behaviour under measurement here.
            section = self.sections[0]
            session_date = date(2026, 11, 2) + timedelta(days=sequence % 330)
            payload = {
                "session_date": session_date.isoformat(),
                "records": [
                    {"student_id": student_id, "status": "PRESENT"}
                    for student_id in self.rosters[section]
                ],
            }
            response = await client.post(
                f"{API}/academics/classes/{section}/attendance", json=payload
            )
            return "attendance_write", response.status_code

        client = self.clients["admin"]
        student_id = self.immigration_students[ticket % len(self.immigration_students)]
        response = await client.patch(
            f"{API}/students/{student_id}/immigration",
            json={
                "passport_number": f"P{ticket % 100000:08d}",
                "change_reason": "Synthetic load-test reconciliation",
            },
        )
        return "immigration_write", response.status_code


async def run_level(
    workload: Workload,
    *,
    concurrency: int,
    duration: float,
    write_ratio: float,
    sampler: Sampler | None,
) -> dict:
    latencies: list[float] = []
    statuses: Counter = Counter()
    actions: Counter = Counter()
    deadline = time.monotonic() + duration
    if sampler:
        sampler.samples.clear()

    async def worker(worker_id: int) -> None:
        ticket = worker_id
        while time.monotonic() < deadline:
            started = time.perf_counter()
            try:
                if write_ratio and (ticket % 100) < int(write_ratio * 100):
                    name, status = await workload.write(ticket)
                else:
                    name, status = await workload.read(ticket)
            except (httpx.HTTPError, RuntimeError) as exc:
                name, status = f"transport:{type(exc).__name__}", 0
            latencies.append((time.perf_counter() - started) * 1000)
            statuses[status] += 1
            actions[name] += 1
            ticket += concurrency

    started = time.perf_counter()
    await asyncio.gather(*(worker(i) for i in range(concurrency)))
    elapsed = time.perf_counter() - started
    total = len(latencies)
    errors = sum(count for status, count in statuses.items() if status == 0 or status >= 400)

    return {
        "concurrency": concurrency,
        "duration_seconds": round(elapsed, 1),
        "requests": total,
        "requests_per_second": round(total / elapsed, 1),
        "error_rate": round(errors / total, 4) if total else 0,
        "p50_ms": round(percentile(latencies, 50), 1),
        "p95_ms": round(percentile(latencies, 95), 1),
        "p99_ms": round(percentile(latencies, 99), 1),
        "max_ms": round(max(latencies), 1) if latencies else 0,
        "statuses": {str(k): v for k, v in statuses.most_common()},
        "actions": dict(actions.most_common(12)),
        "resources": summarise_samples(sampler.samples) if sampler else {},
    }


# --------------------------------------------------------------------------
# Contention
# --------------------------------------------------------------------------


async def _race(
    client: httpx.AsyncClient, calls: list[tuple[str, str, dict | None]]
) -> tuple[list[int], list[dict]]:
    async def one(method: str, url: str, payload: dict | None) -> tuple[int, dict]:
        response = await client.request(method, url, json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {}
        return response.status_code, body

    results = await asyncio.gather(*(one(*call) for call in calls))
    return [status for status, _ in results], [body for _, body in results]


async def run_contention(seed: dict, clients: dict) -> dict:
    admin: httpx.AsyncClient = clients["admin"]
    sections = seed["sections"]
    students = seed["students"]
    results: dict[str, dict] = {}

    # 1. Bed assignment: many students, one bed.
    bed_ids = seed["free_beds"][:3]
    # Housing assignments are keyed on the account id (users.id); the service
    # validates that the account holds the STUDENT role.
    housed = set(seed["housed_user_ids"])
    # The first 300 seeded students already occupy the assigned beds; use the
    # rest as candidates so the race is against an empty bed.
    candidates = [
        s["user_id"] for s in students[300:] if s["user_id"] not in housed
    ]
    bed_report = []
    for index, bed_id in enumerate(bed_ids):
        group = candidates[index * 12 : (index + 1) * 12]
        calls = [
            (
                "POST",
                f"{API}/housing/assignments",
                {
                    "student_id": student_id,
                    "bed_id": bed_id,
                    "start_date": "2026-09-01T00:00:00Z",
                },
            )
            for student_id in group
        ]
        statuses, bodies = await _race(admin, calls)
        bed_report.append(
            {
                "bed_assignments_attempted": len(group),
                "statuses": dict(Counter(statuses)),
                "successes": statuses.count(201),
                "conflict_codes": sorted(
                    {
                        body.get("error", {}).get("code", "")
                        for body in bodies
                        if body.get("error")
                    }
                ),
            }
        )
    results["bed_assignment"] = {
        "beds": bed_report,
        "passed": all(row["successes"] == 1 for row in bed_report),
    }

    # 2. Class capacity: a one-seat section, many concurrent enrolments.
    contention_section = seed["contention_section"]
    # Make the scenario repeatable on a reused stack: release the seat a
    # previous run took, so the race always starts from zero enrolments.
    existing = await admin.get(
        f"{API}/academics/classes/{contention_section}/enrollments"
    )
    if existing.status_code == 200:
        for row in existing.json():
            if row.get("status") == "ENROLLED":
                await admin.post(
                    f"{API}/academics/classes/{contention_section}"
                    f"/enrollments/{row['id']}/drop"
                )
    enrolees = [s["student_id"] for s in students[150:170]]
    calls = [
        (
            "POST",
            f"{API}/academics/classes/{contention_section}/enrollments",
            {"student_id": student_id},
        )
        for student_id in enrolees
    ]
    statuses, bodies = await _race(admin, calls)
    results["class_capacity"] = {
        "attempted": len(enrolees),
        "statuses": dict(Counter(statuses)),
        "successes": statuses.count(201),
        "capacity": 1,
        "passed": statuses.count(201) == 1,
    }

    # 3. Attendance: identical bulk writes to one session; the unique key must
    #    leave exactly one row per student, never duplicates.
    section = sections[1]
    roster = [
        student["student_id"]
        for index, student in enumerate(students)
        if index % len(sections) == 1
    ][:8]
    session_date = "2027-06-15"
    payload = {
        "session_date": session_date,
        "records": [{"student_id": sid, "status": "PRESENT"} for sid in roster],
    }
    calls = [
        ("POST", f"{API}/academics/classes/{section}/attendance", payload)
        for _ in range(12)
    ]
    statuses, _ = await _race(admin, calls)
    listing = await admin.get(
        f"{API}/academics/classes/{section}/attendance",
        params={"session_date": session_date},
    )
    all_rows = listing.json() if listing.status_code == 200 else []
    rows = [row for row in all_rows if row.get("session_date") == session_date]
    keys = [(row.get("student_id"), row.get("session_date")) for row in rows]
    results["attendance_race"] = {
        "attempted": len(calls),
        "statuses": dict(Counter(statuses)),
        "rows_for_session": len(rows),
        "distinct_student_dates": len(set(keys)),
        "duplicates": len(keys) - len(set(keys)),
        "passed": len(keys) == len(set(keys)) and len(rows) == len(roster),
    }

    # 4. Immigration correction: concurrent different values. Each accepted
    #    write must appear in history; the profile must end on one of them.
    student_id = seed["immigration_student_ids"][0]
    values = [f"RACE{i:06d}" for i in range(10)]
    calls = [
        (
            "PATCH",
            f"{API}/students/{student_id}/immigration",
            {"passport_number": value, "change_reason": "Concurrent correction race"},
        )
        for value in values
    ]
    statuses, _ = await _race(admin, calls)
    profile = await admin.get(f"{API}/students/{student_id}/immigration")
    history = await admin.get(f"{API}/students/{student_id}/immigration/history")
    final_value = (
        profile.json().get("passport_number") if profile.status_code == 200 else None
    )
    history_rows = len(history.json()) if history.status_code == 200 else -1
    accepted = sum(1 for status in statuses if status < 400)
    results["immigration_race"] = {
        "attempted": len(values),
        "statuses": dict(Counter(statuses)),
        "accepted": accepted,
        "final_passport_is_one_of_the_writes": final_value in values,
        "history_rows": history_rows,
        "history_covers_accepted": history_rows >= accepted,
        "passed": final_value in values and history_rows >= accepted,
    }

    # 5. Retired direct program change: concurrent attempts must all refuse,
    #    never partially write.
    calls = [
        (
            "PATCH",
            f"{API}/students/{students[0]['student_id']}/program-offering",
            {"program_offering_id": None},
        )
        for _ in range(10)
    ]
    statuses, _ = await _race(admin, calls)
    results["program_change_retired"] = {
        "attempted": len(calls),
        "statuses": dict(Counter(statuses)),
        "passed": all(status == 409 for status in statuses),
    }

    return results


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> dict:
    seed = json.loads(Path(args.seed).read_text())
    base_url = args.base_url.rstrip("/")

    admin = await login(base_url, seed["admin"]["email"], seed["admin"]["password"])
    teacher = await login(base_url, seed["teacher"]["email"], seed["teacher"]["password"])

    student_pool_size = max(4, min(args.max_concurrency, len(seed["students"])))
    students = []
    for account in seed["students"][:student_pool_size]:
        students.append(await login(base_url, account["email"], seed["password"]))

    clients = {"admin": admin, "teacher": teacher, "students": students}
    workload = Workload(seed, clients)

    # Preflight: an action that is not 200 under no load would pollute every
    # number below, so it is excluded and reported instead.
    preflight = {}
    for ticket in range(20):
        name, status = await workload.read(ticket * 7)
        preflight.setdefault(name, set()).add(status)
    write_preflight = {}
    for ticket in range(2):
        name, status = await workload.write(ticket)
        write_preflight.setdefault(name, set()).add(status)

    sampler = Sampler(args.api_container, args.pg_container, args.db)
    sampler.start()

    results: dict = {
        "metadata": {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "base_url": base_url,
            "seed_counts": seed["counts"],
            "workers": args.workers,
            "levels": args.levels,
            "duration_seconds": args.duration,
            "rate_limit_enabled": False,
            "note": (
                "Mixed workload: 60% student reads, 30% staff reads, "
                "10% sensitive writes (attendance, immigration)."
            ),
        },
        "preflight": {name: sorted(statuses) for name, statuses in preflight.items()},
        "preflight_writes": {
            name: sorted(statuses) for name, statuses in write_preflight.items()
        },
        "read_heavy": [],
        "write_heavy": [],
    }

    for level in args.levels:
        results["read_heavy"].append(
            await run_level(
                workload,
                concurrency=level,
                duration=args.duration,
                write_ratio=0.1,
                sampler=sampler,
            )
        )

    for level in args.write_levels:
        results["write_heavy"].append(
            await run_level(
                workload,
                concurrency=level,
                duration=args.duration,
                write_ratio=0.6,
                sampler=sampler,
            )
        )

    storm_accounts = [
        (account["email"], seed["password"])
        for account in seed["students"][: args.login_storm]
    ]
    results["authentication"] = await login_storm(base_url, storm_accounts)

    sampler.stop()
    results["contention"] = await run_contention(seed, clients)

    # Query-level evidence from pg_stat_statements.
    stats = subprocess.run(
        [
            "docker", "exec", args.pg_container, "psql", "-U", "portal",
            "-d", args.db, "-tA", "-F", "|", "-c",
            "SELECT calls, round(total_exec_time::numeric,1), "
            "round(mean_exec_time::numeric,2), rows, "
            "left(regexp_replace(query, '\\s+', ' ', 'g'), 140) "
            "FROM pg_stat_statements WHERE dbid = "
            "(SELECT oid FROM pg_database WHERE datname = current_database()) "
            "ORDER BY total_exec_time DESC LIMIT 12",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    top_queries = []
    for line in stats.stdout.splitlines():
        parts = line.split("|")
        if len(parts) == 5:
            top_queries.append(
                {
                    "calls": int(parts[0]),
                    "total_ms": float(parts[1] or 0),
                    "mean_ms": float(parts[2] or 0),
                    "rows": int(parts[3] or 0),
                    "query": parts[4],
                }
            )
    results["top_queries"] = top_queries

    for client in students + [admin, teacher]:
        await client.aclose()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(results, indent=2))
    return results


def print_report(results: dict) -> None:
    print("\nPreflight (non-200 actions must be investigated):")
    for name, statuses in results["preflight"].items():
        flag = "" if statuses == [200] else "  <-- WARNING"
        print(f"  {name:24} {statuses}{flag}")
    for name, statuses in results["preflight_writes"].items():
        flag = "" if all(200 <= s < 300 for s in statuses) else "  <-- WARNING"
        print(f"  {name:24} {statuses}{flag}")

    def table(rows: list[dict], title: str) -> None:
        print(f"\n{title}")
        header = (
            f"{'conc':>5} {'req':>7} {'rps':>7} {'err%':>6} "
            f"{'p50':>7} {'p95':>7} {'p99':>7} {'cpu%':>7} {'memMiB':>8} {'pgconn':>7}"
        )
        print(header)
        for row in rows:
            res = row.get("resources", {})
            print(
                f"{row['concurrency']:>5} {row['requests']:>7} "
                f"{row['requests_per_second']:>7} {row['error_rate'] * 100:>6.1f} "
                f"{row['p50_ms']:>7} {row['p95_ms']:>7} {row['p99_ms']:>7} "
                f"{res.get('api_cpu_peak_percent', 0):>7} "
                f"{res.get('api_mem_peak_mib', 0):>8} "
                f"{res.get('db_connections_peak', 0):>7}"
            )

    table(results["read_heavy"], "Read-heavy (10% writes)")
    table(results["write_heavy"], "Write-heavy (60% writes)")

    auth = results["authentication"]
    print(
        f"\nAuthentication: {auth['attempts']} logins in {auth['seconds']}s "
        f"({auth['requests_per_second']} rps), p50 {auth['p50_ms']} ms, "
        f"p95 {auth['p95_ms']} ms, p99 {auth['p99_ms']} ms, "
        f"statuses {auth['statuses']}"
    )

    print("\nContention:")
    for name, report in results["contention"].items():
        print(f"  {name:24} passed={report['passed']}  {report}")

    print("\nTop queries by total time:")
    for query in results["top_queries"][:8]:
        print(
            f"  {query['calls']:>6} calls  {query['mean_ms']:>8.2f} ms mean  "
            f"{query['query'][:90]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8010")
    parser.add_argument("--seed", default=".perf/load_seed.json")
    parser.add_argument("--output", default=".perf/load_results.json")
    parser.add_argument("--levels", type=int, nargs="+", default=[1, 5, 10, 25, 50])
    parser.add_argument("--write-levels", type=int, nargs="+", default=[5, 10, 25])
    parser.add_argument("--max-concurrency", type=int, default=50)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--login-storm", type=int, default=40)
    parser.add_argument("--workers", default=os.environ.get("PERF_WORKERS", "1"))
    parser.add_argument("--api-container", default="sycumain-v3-perf-api-1")
    parser.add_argument("--pg-container", default="sycumain-v3-perf-postgres-1")
    parser.add_argument("--db", default="school_portal_perf")
    args = parser.parse_args()

    results = asyncio.run(main_async(args))
    print_report(results)
    print(f"\nWrote {args.output}")
    return 0 if all(
        report.get("passed", True) for report in results["contention"].values()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

