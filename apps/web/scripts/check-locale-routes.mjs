#!/usr/bin/env node
/**
 * Locale route verification against the *built* application.
 *
 * `pnpm build` proves the app compiles; it does not prove that a route actually
 * answers. This script starts the production server that `next build` produced
 * and asks each of the five supported locales for its login page, checking the
 * three things a broken i18n wiring changes:
 *
 *   1. the route answers 200 instead of 404/500;
 *   2. `<html lang>` is the locale that was requested;
 *   3. `<html dir>` is `rtl` for Arabic and `ltr` for the rest.
 *
 * It runs against the standalone server when one was produced (next.config.ts
 * sets `output: "standalone"`), and falls back to `next start` otherwise, so it
 * works with either build shape.
 *
 * Usage:  pnpm check:locales        (after `pnpm build`)
 */
import { spawn } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const appDir = join(here, "..");
const PORT = Number(process.env.LOCALE_CHECK_PORT || 4321);
const ORIGIN = `http://127.0.0.1:${PORT}`;

/** The five locales the product supports; Arabic is the RTL one. */
const EXPECTED = [
  { code: "en", dir: "ltr" },
  { code: "zh", dir: "ltr" },
  { code: "fr", dir: "ltr" },
  { code: "ru", dir: "ltr" },
  { code: "ar", dir: "rtl" },
];

const catalogues = readdirSync(join(appDir, "messages"))
  .filter((file) => file.endsWith(".json"))
  .map((file) => file.replace(/\.json$/, ""))
  .sort();

const expectedCodes = EXPECTED.map((locale) => locale.code).sort();
if (catalogues.join(",") !== expectedCodes.join(",")) {
  console.error(
    `Message catalogues (${catalogues.join(", ")}) do not match the supported ` +
      `locales (${expectedCodes.join(", ")}).`,
  );
  process.exit(1);
}

const standalone = join(appDir, ".next", "standalone", "server.js");
if (!existsSync(join(appDir, ".next"))) {
  console.error("No build found. Run `pnpm build` before `pnpm check:locales`.");
  process.exit(1);
}

const child = existsSync(standalone)
  ? spawn(process.execPath, [standalone], {
      cwd: join(appDir, ".next", "standalone"),
      env: { ...process.env, PORT: String(PORT), HOSTNAME: "127.0.0.1" },
      stdio: ["ignore", "pipe", "pipe"],
    })
  : spawn(
      process.execPath,
      [join(appDir, "node_modules", "next", "dist", "bin", "next"), "start", "-p", String(PORT), "-H", "127.0.0.1"],
      { cwd: appDir, env: process.env, stdio: ["ignore", "pipe", "pipe"] },
    );

let serverLog = "";
child.stdout.on("data", (chunk) => (serverLog += chunk));
child.stderr.on("data", (chunk) => (serverLog += chunk));

let stopping = false;
function stop(code) {
  if (stopping) return;
  stopping = true;
  child.kill("SIGTERM");
  // Do not let a wedged server hold the CI job open.
  setTimeout(() => child.kill("SIGKILL"), 5000).unref?.();
  process.exit(code);
}
process.on("SIGINT", () => stop(130));
process.on("SIGTERM", () => stop(143));

async function waitForServer(attempts = 90) {
  for (let i = 0; i < attempts; i += 1) {
    if (child.exitCode !== null) {
      throw new Error(`server exited early (${child.exitCode})\n${serverLog}`);
    }
    try {
      const response = await fetch(`${ORIGIN}/en/login`, { redirect: "manual" });
      if (response.status < 500) return;
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`server did not answer on ${ORIGIN}\n${serverLog}`);
}

/** Pull an attribute out of the served HTML without a DOM dependency. */
function attribute(html, name) {
  const match = new RegExp(`<html[^>]*\\b${name}="([^"]*)"`, "i").exec(html);
  return match ? match[1] : null;
}

const problems = [];

try {
  await waitForServer();

  for (const locale of EXPECTED) {
    const url = `${ORIGIN}/${locale.code}/login`;
    const response = await fetch(url, { redirect: "manual" });
    if (response.status !== 200) {
      problems.push(`${locale.code}: /${locale.code}/login answered ${response.status}`);
      continue;
    }

    const html = await response.text();
    const lang = attribute(html, "lang");
    const dir = attribute(html, "dir");

    if (lang !== locale.code) {
      problems.push(`${locale.code}: <html lang="${lang}"> should be "${locale.code}"`);
    }
    if (dir !== locale.dir) {
      problems.push(`${locale.code}: <html dir="${dir}"> should be "${locale.dir}"`);
    }
    // A raw key path means the catalogue did not load for that locale.
    if (/\b(?:navigation|errors|common\.actions)\.[a-zA-Z]/.test(html)) {
      problems.push(`${locale.code}: a raw translation key was rendered`);
    }
    if (problems.length === 0) {
      console.log(`ok ${locale.code}: 200, lang=${lang}, dir=${dir}`);
    }
  }
} catch (error) {
  problems.push(String(error.message ?? error));
}

if (problems.length > 0) {
  console.error("\nLocale route verification FAILED:");
  for (const problem of problems) console.error(`  - ${problem}`);
  if (serverLog) console.error(`\nserver output:\n${serverLog}`);
  stop(1);
} else {
  console.log(`\nAll ${EXPECTED.length} locale routes answered correctly (Arabic RTL verified).`);
  stop(0);
}
