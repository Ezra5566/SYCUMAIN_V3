/**
 * Deterministic test accounts for the isolated browser suite.
 *
 * The addresses are the documented synthetic seed accounts created by
 * `apps/api/app/seed.py`; the password is the seeded one unless
 * `E2E_PASSWORD` overrides it. No real person's data is involved.
 *
 * `E2E_API_URL` must point at the isolated stack (port 8001) when the suite runs
 * through `scripts/e2e.sh`. The defaults match that stack, not development, so a
 * direct `pnpm test:e2e` against the wrong port fails loudly instead of quietly
 * mutating the wrong database.
 */

export type E2eRole = "admin" | "management" | "teacher" | "student";

export interface E2eAccount {
  email: string;
  password: string;
}

const PASSWORD = process.env.E2E_PASSWORD ?? "password123";

export const USERS: Record<E2eRole, E2eAccount> = {
  admin: { email: process.env.E2E_ADMIN_EMAIL ?? "admin@school.portal", password: PASSWORD },
  management: {
    email: process.env.E2E_MANAGEMENT_EMAIL ?? "management@school.portal",
    password: PASSWORD,
  },
  teacher: { email: process.env.E2E_TEACHER_EMAIL ?? "teacher@school.portal", password: PASSWORD },
  student: { email: process.env.E2E_STUDENT_EMAIL ?? "student@school.portal", password: PASSWORD },
};

/** Convenience aliases used by the existing specs. */
export const ADMIN = USERS.admin;
export const TEACHER = USERS.teacher;

/** Isolated API base; port 8001 belongs to the test stack. */
export const API_BASE = process.env.E2E_API_URL ?? "http://localhost:8001";

/** Locale every spec except the i18n one runs in. */
export const LOCALE = "en";
export const app = (path: string) => `/${LOCALE}${path}`;
