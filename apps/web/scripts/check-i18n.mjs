#!/usr/bin/env node
/**
 * Translation integrity check.
 *
 * `en.json` is the reference catalog. Every other locale must contain exactly
 * the same key set — no missing keys (which would render a raw key path to a
 * student) and no orphaned keys (which are dead weight and hide typos).
 *
 * It also verifies that every ICU argument used in a translation exists in the
 * English source. A message like `Expires in {days} days` translated as
 * `{dana}` would otherwise throw `IntlError` at render time in production only.
 *
 * Finally it actually compiles every message. That is the only reliable way to
 * catch ICU quoting mistakes — for example the French `jusqu'au {date}`, where
 * the apostrophe makes ICU treat the placeholder as a literal string and render
 * `{date}` to the user. Compiling catches it here instead of in production.
 *
 * It also verifies the *dynamically composed* keys (see DYNAMIC_KEYS). Those
 * are invisible to source scanning because they are built from API enum values
 * at runtime, so a missing entry only surfaces when a user opens that screen.
 *
 * Finally it scans the source for literal `t("some.key")` calls and checks that
 * each one resolves. Key *parity* across locales cannot catch a key that no
 * locale defines: the call sites still agree with each other while every screen
 * renders the raw path `settings.profile.heading` to the user. Nor can it catch
 * a key that exists as a string where an object is expected, which is exactly
 * what happens when a placeholder scalar is later replaced by a group of keys.
 *
 * Run:  pnpm i18n:check
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import IntlMessageFormat from "intl-messageformat";

const here = dirname(fileURLToPath(import.meta.url));
const messagesDir = join(here, "..", "messages");
const srcDir = join(here, "..", "src");
const REFERENCE = "en";

/** Flatten nested catalog objects into dotted key paths. */
function flatten(obj, prefix = "") {
  const out = {};
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      Object.assign(out, flatten(value, path));
    } else {
      out[path] = value;
    }
  }
  return out;
}

/**
 * Extract ICU argument names from a message.
 *
 * Only braces at depth 0 are arguments. Inside `{count, plural, =0 {No students}
 * one {# student} other {# students}}` the outer brace is the argument `count`
 * and the branch bodies are nested one level deeper, so a naive regex would
 * wrongly report `No` and `student` as arguments. Tracking depth fixes that.
 */
function icuArgs(message) {
  if (typeof message !== "string") return new Set();

  const found = new Set();
  const ARG_START = /^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:[,}])/;

  let depth = 0;
  for (let i = 0; i < message.length; i += 1) {
    const char = message[i];

    if (char === "{") {
      if (depth === 0) {
        const match = ARG_START.exec(message.slice(i + 1));
        if (match) found.add(match[1]);
      }
      depth += 1;
    } else if (char === "}") {
      depth = Math.max(0, depth - 1);
    }
  }

  return found;
}

function loadCatalog(file) {
  const raw = readFileSync(join(messagesDir, file), "utf8");
  try {
    return flatten(JSON.parse(raw));
  } catch (error) {
    console.error(`  ✖ ${file} is not valid JSON: ${error.message}`);
    process.exit(1);
  }
}

/**
 * Compile a message and confirm every declared argument survives formatting.
 *
 * A placeholder that is present in the source but absent from the formatted
 * output was swallowed by ICU quoting (or another parsing subtlety).
 */
function compileProblems(locale, key, message) {
  const problems = [];
  const expected = icuArgs(message);
  const values = Object.fromEntries(
    [...expected].map((name) => [name, name === "count" ? 7 : "VALUE"]),
  );

  try {
    const compiled = new IntlMessageFormat(message, locale);
    const output = String(compiled.format(values));

    for (const arg of expected) {
      if (!output.includes(values[arg])) {
        problems.push(
          `${key}: argument {${arg}} is dropped when formatting ` +
            `(rendered: ${JSON.stringify(output)}) — check ICU quoting`,
        );
      }
    }
  } catch (error) {
    problems.push(`${key}: does not compile — ${error.message}`);
  }

  return problems;
}

/**
 * Keys the UI builds at runtime from API enum values.
 *
 * Each list mirrors a backend enum or a backend constant set. When the backend
 * gains a value, add it here and to every catalog; otherwise that screen will
 * render a raw enum token (or a key path) to the user.
 */
const DYNAMIC_KEYS = {
  "audit.actions": [
    "auth.login_succeeded",
    "auth.login_failed",
    "auth.logout",
    "auth.password_changed",
    "auth.sessions_revoked",
    "student.created",
    "student.updated",
    "student.archived",
    "student.status_changed",
    "account.created",
    "account.updated",
    "account.roles_changed",
    "account.activated",
    "account.deactivated",
    "account.password_reset",
    "account.sessions_revoked",
    "immigration.change_request.created",
    "immigration.change_request.approved",
    "immigration.change_request.rejected",
    "housing.assignment.created",
    "housing.assignment.transferred",
    "housing.assignment.updated",
    "housing.assignment.ended",
    "announcement.created",
    "announcement.updated",
    "announcement.published",
    "announcement.archived",
    "support.ticket.created",
    "support.ticket.updated",
    "document.uploaded",
    "document.downloaded",
    "document.archived",
    "document.deleted",
    "academic.enrollment.created",
    "academic.enrollment.dropped",
    "academic.attendance.updated",
    "academic.calendar.exception_created",
    "academic.calendar.exception_corrected",
    "academic.calendar.exception_voided",
    "academic.calendar.vacation_range_created",
    "academic.calendar.vacation_range_adjusted",
    "academic.calendar.vacation_range_cancelled",
    "academic.commencement.approved",
    "academic.commencement.corrected",
    "academic.grade.updated",
    "dormitory.absence.recorded",
    "dormitory.absence.corrected",
  ],
  // Mirrors the statuses app.services.immigration.calculate_document_status
  // returns. These are derived from expiry dates, so a value the catalog cannot
  // name silently falls back to humanized English in every other locale.
  "immigration.statusLabel": [
    "VALID",
    "EXPIRING_SOON",
    "URGENT",
    "EXPIRED",
    "NOT_PROVIDED",
  ],
  // Mirrors AnnouncementStatus / AnnouncementPriority / AnnouncementAudienceType
  "announcements.status": ["DRAFT", "SCHEDULED", "PUBLISHED", "ARCHIVED"],
  "announcements.priorities": ["LOW", "NORMAL", "HIGH", "URGENT"],
  "announcements.audiences": [
    "ALL",
    "STUDENTS",
    "TEACHERS",
    "STAFF",
    "MAJOR",
    "PROGRAM",
    "CLASS",
  ],
  // Mirrors SupportTicketStatus / SupportTicketPriority / SupportTicketCategory
  "support.status": [
    "OPEN",
    "IN_PROGRESS",
    "WAITING_FOR_STUDENT",
    "RESOLVED",
    "CLOSED",
  ],
  "support.priorities": ["LOW", "NORMAL", "HIGH", "URGENT"],
  "support.categories": [
    "VISA_IMMIGRATION",
    "HOUSING",
    "ACADEMIC",
    "FINANCE",
    "IT",
    "GENERAL",
  ],
  // Mirrors NotificationType exactly.
  "notifications.types": [
    "IMMIGRATION_CHANGE_SUBMITTED",
    "IMMIGRATION_CHANGE_APPROVED",
    "IMMIGRATION_CHANGE_REJECTED",
    "IMMIGRATION_DOCUMENT_UPLOADED",
    "HOUSING_ASSIGNMENT_CREATED",
    "HOUSING_ASSIGNMENT_TRANSFERRED",
    "HOUSING_ASSIGNMENT_ENDED",
    "SUPPORT_TICKET_CREATED",
    "SUPPORT_TICKET_REPLIED",
    "SUPPORT_TICKET_STATUS_CHANGED",
    "SUPPORT_TICKET_ASSIGNED",
    "ANNOUNCEMENT_PUBLISHED",
    "DOCUMENT_UPLOADED",
  ],
  // A UI convention, not a backend enum: `document_type` is a free string.
  "documents.types": [
    "PASSPORT",
    "VISA",
    "RESIDENCE_PERMIT",
    "PHOTO",
    "TRANSCRIPT",
    "OTHER",
  ],
  // Mirrors DocumentStatus.
  "documents.status": ["ACTIVE", "ARCHIVED", "DELETED"],
  // Sentences the notifications screen composes from NotificationType.
  "notifications.messages": [
    "immigrationSubmitted",
    "immigrationApproved",
    "immigrationRejected",
    "immigrationDocumentUploaded",
    "housingAssigned",
    "housingTransferred",
    "housingEnded",
    "supportCreated",
    "supportReplied",
    "supportStatusChanged",
    "supportAssigned",
    "announcementPublished",
    "documentUploaded",
  ],
  "reports.metrics": [
    "totalStudents",
    "activeStudents",
    "inactiveStudents",
    "graduated",
    "withdrawn",
    "suspended",
    "housedOnCampus",
    "offCampus",
    "totalCapacity",
    "occupiedBeds",
    "availableBeds",
    "outOfServiceRooms",
    "fullRooms",
    "missingInformation",
    "expiring30",
    "expiring90",
    "expired",
    "roomsAvailable",
    "roomsPartial",
    "totalEnrollments",
  ],
  "reports.sections": [
    "studentsByStatus",
    "studentsByProgram",
    "studentsByNationality",
    "immigrationExpiry",
    "housingOccupancy",
    "housingByBuilding",
    "enrollmentByPeriod",
    "teacherAssignments",
  ],
};

/** Recursively collect the source files that can contain translation calls. */
function sourceFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(full));
    } else if (/\.(tsx|ts)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

/**
 * Cross-check the API's error codes against the translation catalog.
 *
 * Codes are read from the FastAPI sources, in whichever form the backend uses
 * to raise them:
 *
 *   - the dict-literal form    {"code": "CONFLICT"}
 *   - the assignment form      code = "NOT_FOUND"
 *   - a typed rule exception   HousingRuleError("BED_OCCUPIED", ...)
 *
 * The third form is why CODE_CARRYING_CALLS exists: once a code travels as a
 * constructor argument, no generic pattern can tell it apart from an ordinary
 * uppercase string. Adding a new typed-error class therefore means adding it
 * here — otherwise its codes silently lose their messages.
 *
 * `missing` is fatal: the code reaches the frontend with no message.
 * `reserved` is not: catalog entries with no emitter are dead translations and
 * are surfaced as a count so drift stays visible without blocking the build.
 */
const CODE_CARRYING_CALLS = [
  "HousingRuleError",
  "AcademicRuleError",
  "CalendarError",
  "CommencementError",
  "AbsenceError",
  "DormitoryError",
  "ExaminationError",
];

/**
 * Mappings whose entries name an API error code as an all-caps literal.
 *
 * A fourth shape exists and is easy to miss: a reason -> response table, where
 * the code sits inside the tuple rather than in a `"code": ...` pair. Codes
 * built by deriving them from the key at runtime (e.g. `key.upper()`) are
 * invisible to every text-based check — which is exactly how a family of codes
 * once shipped with no message in any language. Listing the mapping here makes
 * its all-caps literals part of the contract.
 */
const CODE_CARRYING_MAPPINGS = ["_PLACEMENT_ERRORS", "_ADMISSION_ERRORS"];

function backendCodeProblems(reference) {
  const apiDir = join(here, "..", "..", "api", "app");
  const CALL = CODE_CARRYING_CALLS.join("|");
  const patterns = [
    /"code"\s*:\s*"([A-Z][A-Z0-9_]{2,})"/g,
    /\bcode\s*=\s*"([A-Z][A-Z0-9_]{2,})"/g,
    new RegExp(`\\b(?:${CALL})\\(\\s*"([A-Z][A-Z0-9_]{2,})"`, "g"),
  ];

  // An all-caps quoted literal is a code wherever it appears. Messages in these
  // tables are sentences, so the two cannot be confused.
  const mappingPattern = new RegExp(
    `(?:^|\\n)(?:${CODE_CARRYING_MAPPINGS.join("|")})\\s*:[\\s\\S]*?\\n\\}`,
    "g",
  );
  const literalPattern = /"([A-Z][A-Z0-9_]{2,})"/g;

  const emitted = new Set();
  for (const file of pythonFiles(apiDir)) {
    const text = readFileSync(file, "utf8");
    for (const pattern of patterns) {
      pattern.lastIndex = 0;
      for (const match of text.matchAll(pattern)) emitted.add(match[1]);
    }
    for (const block of text.matchAll(mappingPattern)) {
      for (const match of block[0].matchAll(literalPattern)) {
        emitted.add(match[1]);
      }
    }
  }

  // `reference` is the flattened catalog, so code messages appear as dotted
  // keys rather than a nested `errors.codes` object.
  const PREFIX = "errors.codes.";
  const catalog = new Set(
    Object.keys(reference)
      .filter((key) => key.startsWith(PREFIX))
      .map((key) => key.slice(PREFIX.length)),
  );

  return {
    emitted: emitted.size,
    missing: [...emitted].filter((c) => !catalog.has(c)).sort(),
    reserved: [...catalog].filter((c) => !emitted.has(c)).sort(),
  };
}

function pythonFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__pycache__") continue;
      out.push(...pythonFiles(full));
    } else if (entry.endsWith(".py")) {
      out.push(full);
    }
  }
  return out;
}

/**
 * Find literal translation calls whose key no catalog defines.
 *
 * A file may bind the same translator name (`t`) in several components with
 * different namespaces, so a key is accepted when it resolves in *any*
 * namespace used in that file. A genuinely missing key therefore still fails,
 * while a legitimate sibling namespace does not produce a false positive.
 *
 * Only literal first arguments are checked. Template-literal keys built from
 * API values cannot be resolved statically and are covered by DYNAMIC_KEYS.
 */
function literalKeyProblems(reference) {
  const problems = [];
  const CALL = /(?:^|[^\w.])(t[A-Z]\w*|t)\(\s*"([A-Za-z0-9_.\-]+)"\s*[,)]/g;
  const BINDING = /useTranslations\(\s*(?:"([^"]+)"\s*)?\)/g;

  for (const file of sourceFiles(srcDir)) {
    const source = readFileSync(file, "utf8");
    if (!source.includes("useTranslations")) continue;

    const namespaces = new Set();
    for (const match of source.matchAll(BINDING)) {
      namespaces.add(match[1] ?? "");
    }
    if (namespaces.size === 0) continue;

    for (const match of source.matchAll(CALL)) {
      const key = match[2];
      const resolved = [...namespaces].some((ns) =>
        ns ? reference[`${ns}.${key}`] !== undefined : reference[key] !== undefined,
      );
      if (!resolved) {
        problems.push(`${file.replace(`${srcDir}/`, "")}: ${key}`);
      }
    }
  }

  return problems;
}

/**
 * Confirm every runtime-composed key exists in every catalog.
 *
 * Catalogs are already flattened, so a dotted path is a direct lookup.
 * Returns a map of locale -> problems so the report stays grouped by locale.
 */
function dynamicKeyProblems(catalogs) {
  const byLocale = new Map();

  for (const [locale, catalog] of Object.entries(catalogs)) {
    const problems = [];
    for (const [namespace, values] of Object.entries(DYNAMIC_KEYS)) {
      for (const value of values) {
        const key = `${namespace}.${value}`;
        const resolved = catalog[key];
        if (typeof resolved !== "string" || resolved.trim() === "") {
          problems.push(key);
        }
      }
    }
    if (problems.length > 0) byLocale.set(locale, problems);
  }

  return byLocale;
}

const files = readdirSync(messagesDir).filter((f) => f.endsWith(".json"));
const referenceFile = `${REFERENCE}.json`;

if (!files.includes(referenceFile)) {
  console.error(`Reference catalog ${referenceFile} is missing.`);
  process.exit(1);
}

const reference = loadCatalog(referenceFile);
const referenceKeys = Object.keys(reference);
const locales = files.filter((f) => f !== referenceFile).map((f) => f.replace(/\.json$/, ""));

let failures = 0;

console.log(`Reference: ${referenceFile} (${referenceKeys.length} keys)\n`);

for (const locale of locales) {
  const catalog = loadCatalog(`${locale}.json`);
  const keys = Object.keys(catalog);
  const missing = referenceKeys.filter((k) => !(k in catalog));
  const extra = keys.filter((k) => !(k in reference));
  const empty = keys.filter(
    (k) => typeof catalog[k] !== "string" || catalog[k].trim() === "",
  );

  // Argument names must match the English source exactly.
  const argMismatches = [];
  for (const key of keys) {
    if (!(key in reference)) continue;
    const expected = icuArgs(reference[key]);
    const actual = icuArgs(catalog[key]);
    for (const arg of actual) {
      if (!expected.has(arg)) argMismatches.push(`${key}: unknown argument {${arg}}`);
    }
    for (const arg of expected) {
      if (!actual.has(arg)) argMismatches.push(`${key}: missing argument {${arg}}`);
    }
  }

  // Every message must actually compile and preserve its placeholders.
  const compileFailures = [];
  for (const key of keys) {
    if (typeof catalog[key] !== "string" || catalog[key].trim() === "") continue;
    compileFailures.push(...compileProblems(locale, key, catalog[key]));
  }

  const problems =
    missing.length +
    extra.length +
    empty.length +
    argMismatches.length +
    compileFailures.length;

  if (problems === 0) {
    console.log(`✔ ${locale}: ${keys.length} keys, no problems`);
    continue;
  }

  failures += problems;
  console.log(`✖ ${locale}: ${keys.length} keys`);
  for (const k of missing) console.log(`    missing key:  ${k}`);
  for (const k of extra) console.log(`    orphaned key: ${k}`);
  for (const k of empty) console.log(`    empty value:  ${k}`);
  for (const m of argMismatches) console.log(`    icu argument: ${m}`);
  for (const m of compileFailures) console.log(`    icu compile:  ${m}`);
}

// Runtime-composed keys (API enums) cannot be found by scanning source, so
// they are verified against an explicit manifest instead.
const allCatalogs = {
  [REFERENCE]: reference,
};
for (const locale of locales) allCatalogs[locale] = loadCatalog(`${locale}.json`);

const dynamicProblems = dynamicKeyProblems(allCatalogs);
if (dynamicProblems.size === 0) {
  const total = Object.values(DYNAMIC_KEYS).reduce((sum, v) => sum + v.length, 0);
  console.log(
    `\n✔ dynamic keys: ${total} runtime-composed keys resolve in all locales`,
  );
} else {
  for (const [locale, keys] of dynamicProblems) {
    failures += keys.length;
    console.log(`\n✖ ${locale}: ${keys.length} dynamic key problem(s)`);
    for (const key of keys) console.log(`    missing key: ${key}`);
  }
}

// Literal call sites are checked against the reference catalog: a missing key
// renders its own path to the user in every locale, so parity alone cannot see
// it.
const literalProblems = literalKeyProblems(reference);
if (literalProblems.length === 0) {
  console.log(
    "\n✔ literal keys: every source translation call resolves in the reference catalog",
  );
} else {
  failures += literalProblems.length;
  console.log(`\n✖ ${literalProblems.length} unresolved translation key(s)`);
  for (const problem of literalProblems) console.log(`    unknown key: ${problem}`);
}

// The API returns machine-readable codes and the frontend renders the sentence
// (see useErrorMessage). A code emitted by the backend but absent from the
// catalog therefore falls through to a generic status message — the user is
// told "something went wrong" instead of "that bed is already occupied". This
// is invisible to every other check here, because the key is looked up
// dynamically from the response body.
const codeProblems = backendCodeProblems(reference);
if (codeProblems.missing.length === 0) {
  console.log(
    `\n\u2714 error codes: all ${codeProblems.emitted} backend codes have a message`,
  );
} else {
  failures += codeProblems.missing.length;
  console.log(
    `\n\u2716 ${codeProblems.missing.length} backend error code(s) with no message`,
  );
  for (const code of codeProblems.missing) {
    console.log(`    no errors.codes.${code} — falls back to a generic message`);
  }
}

// Reported but not fatal: reserved for endpoints that currently collapse
// distinct failures into a generic CONFLICT, so the message is dead until that
// endpoint emits a specific code.
if (codeProblems.reserved.length > 0) {
  console.log(
    `\n  note: ${codeProblems.reserved.length} reserved code(s) not yet emitted by the API`,
  );
  console.log(`        ${codeProblems.reserved.join(", ")}`);
}

console.log("");
if (failures > 0) {
  console.error(`Translation check FAILED with ${failures} problem(s).`);
  process.exit(1);
}
console.log(`Translation check passed for ${locales.length + 1} locales.`);
