# SCU Timetable — Complete Source-to-Database Mapping Appendix

**Status:** design artifact only. No academic record was created, changed or deleted.

**Source:** `docs/scu-timetable-reference.json`  
**Source SHA-256:** `91a36ccea191b0e205f828e138eb5d4d3afe3b9a0ae2aa46b442decc0eeb95d4`  
**Companion:** `docs/scu-timetable-implementation-plan.md`  
**Reconciliation:** `docs/scu-timetable-reconciliation-report.md`

---

## Key convention

Every key below is an **internal reference key**, prefixed `ref:v1:`. None is an official course code, section code, period code or university identifier. Official codes remain null until SCU supplies them.

| Entity | Internal key rule |
|---|---|
| Period | `ref:v1:period:<source semester id>` |
| Offering | `ref:v1:offering:<source offering id>` |
| Course | `ref:v1:course:<normalised course name>` |
| Room | `ref:v1:room:<room code>` |
| Section | `ref:v1:section:<sha256(semester, course, sorted offering ids)[:20]>` |
| Session | `ref:v1:session:<sha256(semester, course, day, start, end, room, sorted offering ids)[:24]>` |
| Raw row | `ref:v1:raw:<sha256(semester, offering id, raw row ordinal)[:20]>` |

The keys are deterministic so a re-import of the same source produces the same keys. They are not displayed as official codes in the portal.

---

## 1. Periods

| Source ID | Source name | Chinese name | Declared format | Resolved format | Proposed live period | Period source key | Status |
|---|---|---|---|---|---|---|---|
| `2026-autumn` | 2026 Autumn | 2026秋季 | `standard8` | **block4** | `2026-FALL` — candidate, not certified | `ref:v1:period:2026-autumn` | block4 resolution documented; period mapping pending |
| `2026-spring` | 2026 Spring | 2026春季 | `standard8` | **standard8** | Not created until dates and official code are supplied | `ref:v1:period:2026-spring` | blocked by missing dates |
| `2025-autumn` | 2025 Autumn | 2025秋季 | `standard8` | **standard8** | Not created until dates and official code are supplied | `ref:v1:period:2025-autumn` | blocked by missing dates |

The source has no start/end dates. `2026-FALL` is only a proposed match for `2026-autumn`; it is not confirmed by the source. `VFY1` is a legacy period and is not part of this import.

---

## 2. Proposed parent-program mapping

No source program name is mapped automatically. The six BBA/BCS offering links are proposals requiring review. The remaining nine offerings stay with `program_id = NULL`. No major or program records are created by the import.

| Source program name | Existing candidate | Proposed action | Status |
|---|---|---|---|
| Business Administration | BUS / BBA | Review proposal; do not apply until approved | Proposed only — not applied |
| Computer Science and Technology | CS / BCS | Review proposal; do not apply until approved | Proposed only — not applied |
| Artificial Intelligence | — (existing `english` major is AI-named but its code conflicts) | Leave parent null; do not invent a parent | Blocked — no program |
| Chinese Language (Elementary Level) | — | Leave parent null; do not invent a parent | Unmapped — no official parent record |
| Chinese Language (Intermediate Level) | — | Leave parent null; do not invent a parent | Unmapped — no official parent record |
| Civil Engineering | — | Leave parent null; do not invent a parent | Unmapped — no official parent record |
| Chinese Language and Literature | — | Leave parent null; do not invent a parent | Unmapped — no official parent record |
| Robotics Engineering | — | Leave parent null; do not invent a parent | Unmapped — no official parent record |

`BAL` / `ENG` (English) and the orphan AI-named major `english` are legacy records. They are not deleted or rewritten by this mapping.

---

## 3. Program offerings

All 15 offerings are period-specific. `program_id` is null unless the proposed BBA/BCS mapping is approved. `source_id` is the source identifier, not an official university code.

| Source offering ID | Period | Source name | Chinese name | Schedule rows | Source key | Proposed parent |
|---|---|---|---|---:|---|---|
| `chinese-elementary-2026a` | `2026-autumn` | Chinese Language (Elementary Level) 1 | 初级汉语言文学（国际）1 | 3 | `ref:v1:offering:chinese-elementary-2026a` | — |
| `chinese-intermediate-2026a` | `2026-autumn` | Chinese Language (Intermediate Level) 1 | 中级汉语言文学（国际）1 | 3 | `ref:v1:offering:chinese-intermediate-2026a` | — |
| `ai-2026a` | `2026-autumn` | Artificial Intelligence (International) 1 | 人工智能（国际）1 | 4 | `ref:v1:offering:ai-2026a` | — (existing `english` major is AI-named but its code conflicts) |
| `civil-2026a` | `2026-autumn` | Civil Engineering (International) 1 | 土木工程（国际）1 | 4 | `ref:v1:offering:civil-2026a` | — |
| `business-2026a` | `2026-autumn` | Business Administration (International) 1 | 工商管理（国际）1 | 4 | `ref:v1:offering:business-2026a` | BUS / BBA |
| `cs-2026a` | `2026-autumn` | Computer Science and Technology (International) 1 | 计算机科学与技术（国际）1 | 5 | `ref:v1:offering:cs-2026a` | CS / BCS |
| `civil-engineering-2026s` | `2026-spring` | Civil Engineering (International) 1 | 土木工程（国际）1 | 7 | `ref:v1:offering:civil-engineering-2026s` | — |
| `ai-2026s` | `2026-spring` | Artificial Intelligence (International) 1 | 人工智能（国际）1 | 7 | `ref:v1:offering:ai-2026s` | — (existing `english` major is AI-named but its code conflicts) |
| `cs-2026s` | `2026-spring` | Computer Science and Technology (International) 1 | 计算机科学与技术（国际）1 | 8 | `ref:v1:offering:cs-2026s` | CS / BCS |
| `chinese-lit-2026s` | `2026-spring` | Chinese Language and Literature (International) 1 | 汉语言文学（国际）1 | 3 | `ref:v1:offering:chinese-lit-2026s` | — |
| `business-2026s` | `2026-spring` | Business Administration (International) 1 | 工商管理（国际）1 | 5 | `ref:v1:offering:business-2026s` | BUS / BBA |
| `ai-2025a` | `2025-autumn` | Artificial Intelligence (International) 1 | 人工智能（国际）1 | 5 | `ref:v1:offering:ai-2025a` | — (existing `english` major is AI-named but its code conflicts) |
| `cs-2025a` | `2025-autumn` | Computer Science and Technology (International) 1 | 计算机科学与技术（国际）1 | 5 | `ref:v1:offering:cs-2025a` | CS / BCS |
| `business-2025a` | `2025-autumn` | Business Administration (International) 1 | 工商管理（国际）1 | 7 | `ref:v1:offering:business-2025a` | BUS / BBA |
| `robotics-2025a` | `2025-autumn` | Robotics Engineering (International) 1 | 机器人工程（国际）1 | 6 | `ref:v1:offering:robotics-2025a` | — |

**Counts:** 15 offerings; 6 proposed BBA/BCS parent links; 9 parent-null offerings.

---

## 4. Courses

All 26 source course labels map to one course row per distinct label. Official code, Chinese name and credits are absent from the source. `code` and `credits` are approved nullable; missing credits are stored as `NULL`, never an invented default.

| Internal course key | Source course name | Semesters | Official code | Credits | Chinese name |
|---|---|---|---|---|---|
| `ref:v1:course:ai-ethics-international` | AI Ethics (International) | `2025-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:ai-thinking-and-ethics-international` | AI Thinking and Ethics (International) | `2025-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:advanced-mathematics-a-1` | Advanced Mathematics (A) 1 | `2026-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:architectural-mechanics-international` | Architectural Mechanics (International) | `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:business-and-technology-international` | Business and Technology (International) | `2025-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:chinese-language` | Chinese Language | `2026-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:chinese-major-1-2-international` | Chinese, Major 1-2 (International) | `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:chinese-major-2-1-international` | Chinese, Major 2-1 (International) | `2025-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:civil-engineering-drawing-international` | Civil Engineering Drawing (International) | `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:computer-organization-principles-international` | Computer Organization Principles (International) | `2025-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:data-structures-and-algorithms-international` | Data Structures and Algorithms (International) | `2025-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:digital-electronic-technology` | Digital Electronic Technology | `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:discrete-mathematics-international` | Discrete Mathematics (International) | `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:fundamentals-of-electronic-technology-international` | Fundamentals of Electronic Technology (International) | `2025-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:fundamentals-of-programming-international` | Fundamentals of Programming (International) | `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:human-resource-management-international` | Human Resource Management (International) | `2025-autumn`, `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:introduction-to-the-major` | Introduction to the Major | `2026-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:introduction-to-the-major-group-1` | Introduction to the Major (Group 1) | `2026-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:introduction-to-the-major-group-2` | Introduction to the Major (Group 2) | `2026-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:maths-a2-international` | MATHS (A2) (International) | `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:management-international` | Management (International) | `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:microeconomics-international` | Microeconomics (International) | `2025-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:organizational-behavior-international` | Organizational Behavior (International) | `2025-autumn` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:prompt-engineering-international` | Prompt Engineering (International) | `2025-autumn`, `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:python-programming-international` | Python Programming (International) | `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |
| `ref:v1:course:university-physics-a-1-international` | University Physics A 1 (International) | `2026-spring` | **null** (not supplied) | **null** (not supplied) | **null** (not supplied) |

**Counts:** 26 course records; 7 existing courses untouched; 33 total if all 26 are created.

---

## 5. Rooms

| Room code | Building | Campus | Source key | Capacity | Status |
|---|---|---|---|---|---|
| `N103` | N | Main | `ref:v1:room:n103` | **null** (approved) | `AVAILABLE` (scheduling state) |
| `N104` | N | Main | `ref:v1:room:n104` | **null** (approved) | `AVAILABLE` (scheduling state) |
| `N105` | N | Main | `ref:v1:room:n105` | **null** (approved) | `AVAILABLE` (scheduling state) |
| `N106` | N | Main | `ref:v1:room:n106` | **null** (approved) | `AVAILABLE` (scheduling state) |
| `N107` | N | Main | `ref:v1:room:n107` | **null** (approved) | `AVAILABLE` (scheduling state) |
| `N301` | N | Main | `ref:v1:room:n301` | **null** (approved) | `AVAILABLE` (scheduling state) |
| `N302` | N | Main | `ref:v1:room:n302` | **null** (approved) | `AVAILABLE` (scheduling state) |
| `G309` | G | Main | `ref:v1:room:g309` | **null** (approved) | `AVAILABLE` (scheduling state) |
| `G310` | G | Main | `ref:v1:room:g310` | **null** (approved) | `AVAILABLE` (scheduling state) |
| `G315` | G | Main | `ref:v1:room:g315` | **null** (approved) | `AVAILABLE` (scheduling state) |
| `G410` | G | Main | `ref:v1:room:g410` | **null** (approved) | `AVAILABLE` (scheduling state) |

**Counts:** 11 rooms; 5 existing rooms untouched; 16 total.

---

## 6. Sections

Sections are derived by semester + course label + exact set of program offerings. No official section code exists. Sections marked **HELD** are staged only because of the unresolved N103 conflict; they are not live class sections.

| Internal section key | Period | Course | Offering IDs | Sessions | Status | Note |
|---|---|---|---|---:|---|---|
| `ref:v1:section:b3781e87f3fe230d6186` | `2025-autumn` | AI Ethics (International) | `ai-2025a` | 2 | **HELD** | N103 room conflict — institutional confirmation required; no live booking |
| `ref:v1:section:72b4ca9503f2e4703c88` | `2025-autumn` | AI Thinking and Ethics (International) | `robotics-2025a` | 2 | **HELD** | N103 room conflict — institutional confirmation required; no live booking |
| `ref:v1:section:d1dd8dab20738f4d6232` | `2025-autumn` | Business and Technology (International) | `business-2025a` | 1 | LIVE | — |
| `ref:v1:section:feeccdd0c056db240de2` | `2025-autumn` | Chinese, Major 2-1 (International) | `ai-2025a`, `business-2025a`, `cs-2025a`, `robotics-2025a` | 2 | LIVE | — |
| `ref:v1:section:e81f00eff6e4ca807dc4` | `2025-autumn` | Computer Organization Principles (International) | `cs-2025a` | 2 | LIVE | — |
| `ref:v1:section:9925cc2345c7b1446b7a` | `2025-autumn` | Data Structures and Algorithms (International) | `cs-2025a` | 1 | LIVE | — |
| `ref:v1:section:5b7981573088f2d0a107` | `2025-autumn` | Fundamentals of Electronic Technology (International) | `robotics-2025a` | 1 | LIVE | — |
| `ref:v1:section:1e7cd6fd797e2370bb54` | `2025-autumn` | Human Resource Management (International) | `business-2025a` | 2 | LIVE | — |
| `ref:v1:section:8d77ce560b6b0ecb4cd9` | `2025-autumn` | Microeconomics (International) | `business-2025a` | 1 | LIVE | — |
| `ref:v1:section:15be152b200c5f48addc` | `2025-autumn` | Organizational Behavior (International) | `business-2025a` | 1 | LIVE | — |
| `ref:v1:section:c4489c8850dfd91fbca5` | `2025-autumn` | Prompt Engineering (International) | `ai-2025a`, `robotics-2025a` | 1 | LIVE | — |
| `ref:v1:section:866b54b20860e34c43b2` | `2026-autumn` | Advanced Mathematics (A) 1 | `ai-2026a`, `business-2026a`, `civil-2026a`, `cs-2026a` | 1 | LIVE | — |
| `ref:v1:section:006815c6eddba07f37c6` | `2026-autumn` | Chinese Language | `ai-2026a`, `business-2026a`, `civil-2026a`, `cs-2026a` | 2 | LIVE | — |
| `ref:v1:section:ca3eee001d167c63c508` | `2026-autumn` | Chinese Language | `chinese-elementary-2026a` | 3 | LIVE | — |
| `ref:v1:section:d1d486f9e2d28b85932f` | `2026-autumn` | Chinese Language | `chinese-intermediate-2026a` | 3 | LIVE | — |
| `ref:v1:section:083707aa1428c6e8bbfc` | `2026-autumn` | Introduction to the Major | `ai-2026a` | 1 | LIVE | — |
| `ref:v1:section:81922c31678aaac0cb02` | `2026-autumn` | Introduction to the Major | `business-2026a` | 1 | LIVE | — |
| `ref:v1:section:0d226101ebc3e831f8cc` | `2026-autumn` | Introduction to the Major | `civil-2026a` | 1 | LIVE | — |
| `ref:v1:section:3c722ac84007113ae7a7` | `2026-autumn` | Introduction to the Major (Group 1) | `cs-2026a` | 1 | LIVE | — |
| `ref:v1:section:0f469177db9393732656` | `2026-autumn` | Introduction to the Major (Group 2) | `cs-2026a` | 1 | LIVE | — |
| `ref:v1:section:f55345e90e5648c85bbe` | `2026-spring` | Architectural Mechanics (International) | `civil-engineering-2026s` | 2 | LIVE | — |
| `ref:v1:section:ecfbfb8b0649fe4fb9ea` | `2026-spring` | Chinese, Major 1-2 (International) | `ai-2026s`, `business-2026s`, `civil-engineering-2026s`, `cs-2026s` | 1 | LIVE | — |
| `ref:v1:section:ec8ba49b25d82bc7a34e` | `2026-spring` | Chinese, Major 1-2 (International) | `chinese-lit-2026s` | 3 | LIVE | — |
| `ref:v1:section:96d3623b2f2522083701` | `2026-spring` | Civil Engineering Drawing (International) | `civil-engineering-2026s` | 2 | LIVE | — |
| `ref:v1:section:276c1eca28c0bf95889f` | `2026-spring` | Digital Electronic Technology | `cs-2026s` | 2 | LIVE | — |
| `ref:v1:section:4d6558ba9649b3b9c743` | `2026-spring` | Discrete Mathematics (International) | `cs-2026s` | 2 | LIVE | — |
| `ref:v1:section:6c0ec4dd7daafe325d13` | `2026-spring` | Fundamentals of Programming (International) | `cs-2026s` | 1 | LIVE | — |
| `ref:v1:section:4fb87df7bf87e94de6a9` | `2026-spring` | Human Resource Management (International) | `business-2026s` | 2 | LIVE | — |
| `ref:v1:section:4c6835e32af575f4d12c` | `2026-spring` | Management (International) | `business-2026s` | 1 | LIVE | — |
| `ref:v1:section:f5b5ecfb8ca150a82568` | `2026-spring` | MATHS (A2) (International) | `ai-2026s`, `business-2026s`, `civil-engineering-2026s`, `cs-2026s` | 1 | LIVE | — |
| `ref:v1:section:423235516af30c85b346` | `2026-spring` | Prompt Engineering (International) | `ai-2026s` | 2 | LIVE | — |
| `ref:v1:section:db0fad16f1abbd622b3f` | `2026-spring` | Python Programming (International) | `ai-2026s` | 2 | LIVE | — |
| `ref:v1:section:17bfebc7714fdef97beb` | `2026-spring` | University Physics A 1 (International) | `ai-2026s`, `civil-engineering-2026s`, `cs-2026s` | 1 | LIVE | — |

**Counts:** 33 sections; 31 live; 2 held; 51 section-to-offering links (49 live, 2 held).

---

## 7. Sessions

Each row is one unique weekly session after exact cross-program duplicates were merged. `HELD` sessions are preserved in staging and are **not inserted** into `timetable_entries`.

| Internal session key | Period | Course | Day | Slot | Time | Room | Offering IDs | Section key | Status |
|---|---|---|---|---|---|---|---|---|---|
| `ref:v1:session:c97108b5e01ab1c7708cf7ab` | `2025-autumn` | AI Ethics (International) | Monday (0) | `3-4` | 10:20–12:00 | N103 | `ai-2025a` | `ref:v1:section:b3781e87f3fe230d6186` | **HELD** |
| `ref:v1:session:119283525312862cef10b4be` | `2025-autumn` | AI Ethics (International) | Wednesday (2) | `3-4` | 10:20–12:00 | N103 | `ai-2025a` | `ref:v1:section:b3781e87f3fe230d6186` | **HELD** |
| `ref:v1:session:882fcb758cca850dce1d2d88` | `2025-autumn` | AI Thinking and Ethics (International) | Monday (0) | `3-4` | 10:20–12:00 | N103 | `robotics-2025a` | `ref:v1:section:72b4ca9503f2e4703c88` | **HELD** |
| `ref:v1:session:fcae968aaba130a50008478a` | `2025-autumn` | AI Thinking and Ethics (International) | Wednesday (2) | `3-4` | 10:20–12:00 | N103 | `robotics-2025a` | `ref:v1:section:72b4ca9503f2e4703c88` | **HELD** |
| `ref:v1:session:9e72e66d6c97702157bc4cab` | `2025-autumn` | Business and Technology (International) | Tuesday (1) | `3-4` | 10:20–12:00 | N104 | `business-2025a` | `ref:v1:section:d1dd8dab20738f4d6232` | LIVE |
| `ref:v1:session:d9ced92731cef09705f7dd37` | `2025-autumn` | Chinese, Major 2-1 (International) | Wednesday (2) | `1-2` | 8:20–10:00 | N107 | `ai-2025a`, `cs-2025a`, `business-2025a`, `robotics-2025a` | `ref:v1:section:feeccdd0c056db240de2` | LIVE |
| `ref:v1:session:c5bdb85c5fa4680a1bb7321d` | `2025-autumn` | Chinese, Major 2-1 (International) | Thursday (3) | `3-4` | 10:20–12:00 | N107 | `ai-2025a`, `cs-2025a`, `business-2025a`, `robotics-2025a` | `ref:v1:section:feeccdd0c056db240de2` | LIVE |
| `ref:v1:session:999304c25075a48618ff0dd3` | `2025-autumn` | Computer Organization Principles (International) | Tuesday (1) | `3-4` | 10:20–12:00 | N302 | `cs-2025a` | `ref:v1:section:e81f00eff6e4ca807dc4` | LIVE |
| `ref:v1:session:63f31f342f01dd7698f38143` | `2025-autumn` | Computer Organization Principles (International) | Friday (4) | `3-4` | 10:20–12:00 | N302 | `cs-2025a` | `ref:v1:section:e81f00eff6e4ca807dc4` | LIVE |
| `ref:v1:session:248ec4a89492f804f328a655` | `2025-autumn` | Data Structures and Algorithms (International) | Monday (0) | `1-4` | 8:20–12:00 | N104 | `cs-2025a` | `ref:v1:section:9925cc2345c7b1446b7a` | LIVE |
| `ref:v1:session:34977cc3a0d3c1c28c2ef578` | `2025-autumn` | Fundamentals of Electronic Technology (International) | Tuesday (1) | `5-8` | 13:30–17:00 | N105 | `robotics-2025a` | `ref:v1:section:5b7981573088f2d0a107` | LIVE |
| `ref:v1:session:32e17d2f83c0ded2a25f4824` | `2025-autumn` | Human Resource Management (International) | Tuesday (1) | `5-6` | 13:30–15:10 | N104 | `business-2025a` | `ref:v1:section:1e7cd6fd797e2370bb54` | LIVE |
| `ref:v1:session:64b5ad72a5cb6f0082de762f` | `2025-autumn` | Human Resource Management (International) | Tuesday (1) | `7` | 15:20–16:05 | N104 | `business-2025a` | `ref:v1:section:1e7cd6fd797e2370bb54` | LIVE |
| `ref:v1:session:8305a52312ba6854a135c2d7` | `2025-autumn` | Microeconomics (International) | Wednesday (2) | `3-4` | 10:20–12:00 | N104 | `business-2025a` | `ref:v1:section:8d77ce560b6b0ecb4cd9` | LIVE |
| `ref:v1:session:163a6c65dc0b16a87c6770da` | `2025-autumn` | Organizational Behavior (International) | Monday (0) | `5-6` | 13:30–15:10 | N105 | `business-2025a` | `ref:v1:section:15be152b200c5f48addc` | LIVE |
| `ref:v1:session:61ba70a8871c957c0825916e` | `2025-autumn` | Prompt Engineering (International) | Thursday (3) | `5-8` | 13:30–17:00 | N103 | `ai-2025a`, `robotics-2025a` | `ref:v1:section:c4489c8850dfd91fbca5` | LIVE |
| `ref:v1:session:eceda0518556071e291572fc` | `2026-autumn` | Advanced Mathematics (A) 1 | Thursday (3) | `5-8` | 13:30–17:00 | G310 | `ai-2026a`, `civil-2026a`, `business-2026a`, `cs-2026a` | `ref:v1:section:866b54b20860e34c43b2` | LIVE |
| `ref:v1:session:65eff7933c8e9872d8b0094e` | `2026-autumn` | Chinese Language | Monday (0) | `5-8` | 13:30–17:00 | N107 | `chinese-elementary-2026a` | `ref:v1:section:ca3eee001d167c63c508` | LIVE |
| `ref:v1:session:ef74b8a2abcfeac9513d0866` | `2026-autumn` | Chinese Language | Monday (0) | `1-4` | 8:20–12:00 | N107 | `chinese-intermediate-2026a` | `ref:v1:section:d1d486f9e2d28b85932f` | LIVE |
| `ref:v1:session:32d5f00c807fe32978ba6a4d` | `2026-autumn` | Chinese Language | Monday (0) | `1-2` | 8:20–10:00 | G410 | `ai-2026a`, `civil-2026a`, `business-2026a`, `cs-2026a` | `ref:v1:section:006815c6eddba07f37c6` | LIVE |
| `ref:v1:session:71552bd7d97050699358d29d` | `2026-autumn` | Chinese Language | Tuesday (1) | `5-8` | 13:30–17:00 | N107 | `chinese-elementary-2026a` | `ref:v1:section:ca3eee001d167c63c508` | LIVE |
| `ref:v1:session:ec9c376ab6ed60ecef569bbd` | `2026-autumn` | Chinese Language | Wednesday (2) | `5-8` | 13:30–17:00 | N107 | `chinese-intermediate-2026a` | `ref:v1:section:d1d486f9e2d28b85932f` | LIVE |
| `ref:v1:session:1e34d4c2c7df53b2ac66564d` | `2026-autumn` | Chinese Language | Wednesday (2) | `7-8` | 15:20–17:00 | G310 | `ai-2026a`, `civil-2026a`, `business-2026a`, `cs-2026a` | `ref:v1:section:006815c6eddba07f37c6` | LIVE |
| `ref:v1:session:16a99ae7d5907931183282ff` | `2026-autumn` | Chinese Language | Thursday (3) | `1-4` | 8:20–12:00 | N106 | `chinese-elementary-2026a` | `ref:v1:section:ca3eee001d167c63c508` | LIVE |
| `ref:v1:session:5d31d953b95f2919513cfc02` | `2026-autumn` | Chinese Language | Friday (4) | `1-4` | 8:20–12:00 | N107 | `chinese-intermediate-2026a` | `ref:v1:section:d1d486f9e2d28b85932f` | LIVE |
| `ref:v1:session:0bc1bda9e05274fcb0ceab09` | `2026-autumn` | Introduction to the Major | Monday (0) | `5-6` | 13:30–15:10 | G410 | `business-2026a` | `ref:v1:section:81922c31678aaac0cb02` | LIVE |
| `ref:v1:session:4cf90e145a8d6861af425307` | `2026-autumn` | Introduction to the Major | Tuesday (1) | `5-6` | 13:30–15:10 | G315 | `civil-2026a` | `ref:v1:section:0d226101ebc3e831f8cc` | LIVE |
| `ref:v1:session:d44b66449e101da3f54ad4a7` | `2026-autumn` | Introduction to the Major | Wednesday (2) | `5-6` | 13:30–15:10 | G309 | `ai-2026a` | `ref:v1:section:083707aa1428c6e8bbfc` | LIVE |
| `ref:v1:session:29185750f40e2cbaa8d2aa81` | `2026-autumn` | Introduction to the Major (Group 1) | Monday (0) | `5-6` | 13:30–15:10 | G315 | `cs-2026a` | `ref:v1:section:3c722ac84007113ae7a7` | LIVE |
| `ref:v1:session:e556990e39890e5ccd3022fa` | `2026-autumn` | Introduction to the Major (Group 2) | Wednesday (2) | `5-6` | 13:30–15:10 | G315 | `cs-2026a` | `ref:v1:section:0f469177db9393732656` | LIVE |
| `ref:v1:session:31601d1a13a2063603647916` | `2026-spring` | Architectural Mechanics (International) | Monday (0) | `5-8` | 13:30–17:00 | N301 | `civil-engineering-2026s` | `ref:v1:section:f55345e90e5648c85bbe` | LIVE |
| `ref:v1:session:0ce6a8afb255707986c3a18c` | `2026-spring` | Architectural Mechanics (International) | Tuesday (1) | `5-8` | 13:30–17:00 | N301 | `civil-engineering-2026s` | `ref:v1:section:f55345e90e5648c85bbe` | LIVE |
| `ref:v1:session:ca129375d061093a2c4c3186` | `2026-spring` | Chinese, Major 1-2 (International) | Monday (0) | `5-8` | 13:30–17:00 | N106 | `chinese-lit-2026s` | `ref:v1:section:ec8ba49b25d82bc7a34e` | LIVE |
| `ref:v1:session:2b4e24eb82a5cda452ba53eb` | `2026-spring` | Chinese, Major 1-2 (International) | Tuesday (1) | `5-8` | 13:30–17:00 | N106 | `chinese-lit-2026s` | `ref:v1:section:ec8ba49b25d82bc7a34e` | LIVE |
| `ref:v1:session:ab55bffdd9969f1351d20bbf` | `2026-spring` | Chinese, Major 1-2 (International) | Wednesday (2) | `5-6` | 13:30–15:10 | N106 | `chinese-lit-2026s` | `ref:v1:section:ec8ba49b25d82bc7a34e` | LIVE |
| `ref:v1:session:06e2fd515e7ff4e3d71859a4` | `2026-spring` | Chinese, Major 1-2 (International) | Wednesday (2) | `1-4` | 8:20–12:00 | N106 | `civil-engineering-2026s`, `ai-2026s`, `cs-2026s`, `business-2026s` | `ref:v1:section:ecfbfb8b0649fe4fb9ea` | LIVE |
| `ref:v1:session:0371d9bc06906d1852d7125d` | `2026-spring` | Civil Engineering Drawing (International) | Wednesday (2) | `5-8` | 13:30–17:00 | N301 | `civil-engineering-2026s` | `ref:v1:section:96d3623b2f2522083701` | LIVE |
| `ref:v1:session:7e3a6b57675748f82f675f4e` | `2026-spring` | Civil Engineering Drawing (International) | Thursday (3) | `1-4` | 8:20–12:00 | N301 | `civil-engineering-2026s` | `ref:v1:section:96d3623b2f2522083701` | LIVE |
| `ref:v1:session:f68a19bd68577d3db459788e` | `2026-spring` | Digital Electronic Technology | Tuesday (1) | `3-4` | 10:20–12:00 | N302 | `cs-2026s` | `ref:v1:section:276c1eca28c0bf95889f` | LIVE |
| `ref:v1:session:63924db740ab72bc38abbc0a` | `2026-spring` | Digital Electronic Technology | Thursday (3) | `3-4` | 10:20–12:00 | N302 | `cs-2026s` | `ref:v1:section:276c1eca28c0bf95889f` | LIVE |
| `ref:v1:session:fdb31147cda5892c177b6446` | `2026-spring` | Discrete Mathematics (International) | Wednesday (2) | `5-6` | 13:30–15:10 | N105 | `cs-2026s` | `ref:v1:section:4d6558ba9649b3b9c743` | LIVE |
| `ref:v1:session:9da3dbe88fbae3a97cd76af7` | `2026-spring` | Discrete Mathematics (International) | Friday (4) | `5-6` | 13:30–15:10 | N105 | `cs-2026s` | `ref:v1:section:4d6558ba9649b3b9c743` | LIVE |
| `ref:v1:session:678448e9f8f234340735451e` | `2026-spring` | Fundamentals of Programming (International) | Tuesday (1) | `5-8` | 13:30–17:00 | N103 | `cs-2026s` | `ref:v1:section:6c0ec4dd7daafe325d13` | LIVE |
| `ref:v1:session:6242f9a1ca5efdf851fdd4d5` | `2026-spring` | Human Resource Management (International) | Tuesday (1) | `5-6` | 13:30–15:10 | N104 | `business-2026s` | `ref:v1:section:4fb87df7bf87e94de6a9` | LIVE |
| `ref:v1:session:3effb33db7b783a686c85d58` | `2026-spring` | Human Resource Management (International) | Tuesday (1) | `7` | 15:20–16:05 | N104 | `business-2026s` | `ref:v1:section:4fb87df7bf87e94de6a9` | LIVE |
| `ref:v1:session:87621ec913666b8f13b49ae7` | `2026-spring` | Management (International) | Monday (0) | `5-6` | 13:30–15:10 | N104 | `business-2026s` | `ref:v1:section:4c6835e32af575f4d12c` | LIVE |
| `ref:v1:session:1945cdca7c0f4ae68053b9f4` | `2026-spring` | MATHS (A2) (International) | Friday (4) | `1-4` | 8:20–12:00 | N106 | `civil-engineering-2026s`, `ai-2026s`, `cs-2026s`, `business-2026s` | `ref:v1:section:f5b5ecfb8ca150a82568` | LIVE |
| `ref:v1:session:bdd808c77ef75918a691fb23` | `2026-spring` | Prompt Engineering (International) | Tuesday (1) | `3-4` | 10:20–12:00 | N103 | `ai-2026s` | `ref:v1:section:423235516af30c85b346` | LIVE |
| `ref:v1:session:4c01cd967de970e04304c7d5` | `2026-spring` | Prompt Engineering (International) | Thursday (3) | `3-4` | 10:20–12:00 | N103 | `ai-2026s` | `ref:v1:section:423235516af30c85b346` | LIVE |
| `ref:v1:session:e7e6a341042a887bdb8c46b3` | `2026-spring` | Python Programming (International) | Monday (0) | `5-6` | 13:30–15:10 | N302 | `ai-2026s` | `ref:v1:section:db0fad16f1abbd622b3f` | LIVE |
| `ref:v1:session:fcb5b5b7dc1ae8ae13fafe58` | `2026-spring` | Python Programming (International) | Tuesday (1) | `5-6` | 13:30–15:10 | N302 | `ai-2026s` | `ref:v1:section:db0fad16f1abbd622b3f` | LIVE |
| `ref:v1:session:97aab53f7e75852088924975` | `2026-spring` | University Physics A 1 (International) | Thursday (3) | `5-8` | 13:30–17:00 | N107 | `civil-engineering-2026s`, `ai-2026s`, `cs-2026s` | `ref:v1:section:17bfebc7714fdef97beb` | LIVE |

**Counts:** 52 sessions; 48 live; 4 held. All 76 raw rows are accounted for (52 unique sessions plus 24 merged cross-program rows).

---

## 8. Shared-delivery validation

Each row below is a shared **session identity**, not a section. The structural test is: same semester, course, day, clock interval and room, with the exact offering set. Nine shared session identities collapse into seven canonical sections. The final institutional sign-off is still required before any join row is committed.

| # | Period | Course | Day / slot | Offering IDs | Proposed section | Result |
|---|---|---|---|---|---|---|
| 1 | `2026-autumn` | Chinese Language | Monday / `1-2` | `ai-2026a`, `civil-2026a`, `business-2026a`, `cs-2026a` | `ref:v1:section:006815c6eddba07f37c6` | PASS — one shared section; pending sign-off |
| 2 | `2026-autumn` | Chinese Language | Wednesday / `7-8` | `ai-2026a`, `civil-2026a`, `business-2026a`, `cs-2026a` | `ref:v1:section:006815c6eddba07f37c6` | PASS — one shared section; pending sign-off |
| 3 | `2026-autumn` | Advanced Mathematics (A) 1 | Thursday / `5-8` | `ai-2026a`, `civil-2026a`, `business-2026a`, `cs-2026a` | `ref:v1:section:866b54b20860e34c43b2` | PASS — one shared section; pending sign-off |
| 4 | `2026-spring` | Chinese, Major 1-2 (International) | Wednesday / `1-4` | `civil-engineering-2026s`, `ai-2026s`, `cs-2026s`, `business-2026s` | `ref:v1:section:ecfbfb8b0649fe4fb9ea` | PASS — one shared section; pending sign-off |
| 5 | `2026-spring` | University Physics A 1 (International) | Thursday / `5-8` | `civil-engineering-2026s`, `ai-2026s`, `cs-2026s` | `ref:v1:section:17bfebc7714fdef97beb` | PASS — one shared section; pending sign-off |
| 6 | `2026-spring` | MATHS (A2) (International) | Friday / `1-4` | `civil-engineering-2026s`, `ai-2026s`, `cs-2026s`, `business-2026s` | `ref:v1:section:f5b5ecfb8ca150a82568` | PASS — one shared section; pending sign-off |
| 7 | `2025-autumn` | Chinese, Major 2-1 (International) | Wednesday / `1-2` | `ai-2025a`, `cs-2025a`, `business-2025a`, `robotics-2025a` | `ref:v1:section:feeccdd0c056db240de2` | PASS — one shared section; pending sign-off |
| 8 | `2025-autumn` | Chinese, Major 2-1 (International) | Thursday / `3-4` | `ai-2025a`, `cs-2025a`, `business-2025a`, `robotics-2025a` | `ref:v1:section:feeccdd0c056db240de2` | PASS — one shared section; pending sign-off |
| 9 | `2025-autumn` | Prompt Engineering (International) | Thursday / `5-8` | `ai-2025a`, `robotics-2025a` | `ref:v1:section:c4489c8850dfd91fbca5` | PASS — one shared section; pending sign-off |

**Counts:** 9 shared session identities; 7 canonical shared sections; 0 cross-semester groups; 24 raw rows merged into these identities.

---

## 9. Held N103 conflicts

| Period | Day | Time | Room | Course A | Course B | Status |
|---|---|---|---|---|---|---|
| `2025-autumn` | Monday | 10:20–12:00 | N103 | AI Ethics (International) (`ai-2025a`) | AI Thinking and Ethics (International) (`robotics-2025a`) | **HELD** — no merge; no confirmed booking |
| `2025-autumn` | Wednesday | 10:20–12:00 | N103 | AI Ethics (International) (`ai-2025a`) | AI Thinking and Ethics (International) (`robotics-2025a`) | **HELD** — no merge; no confirmed booking |

These are four unique weekly session rows across two derived sections. They remain in `academic_import_rows` with an unresolved-conflict status. They are not represented as confirmed timetable entries.

---

## 10. Complete source coverage

| Source item | Count | Target |
|---|---:|---|
| Semesters | 3 | `academic_periods` (only after dates and period code approval) |
| Program offerings | 15 | `program_offerings` |
| Distinct course labels | 26 | `courses` |
| Rooms | 11 | `classrooms` |
| Derived sections | 33 | `class_sections` (31 live, 2 held) |
| Section-offering links | 51 | `class_section_program_offerings` (49 live, 2 held) |
| Unique weekly sessions | 52 | `timetable_entries` (48 live, 4 held) |
| Raw schedule rows accounted for | 76 | import staging; 24 merged duplicates |
| Shared-delivery session identities | 9 | collapse into 7 canonical sections after validation |
| N103 room-conflict groups | 2 | held for institutional confirmation |

**No existing enrollment, attendance, assessment, grade or academic-history row is part of this mapping.**

