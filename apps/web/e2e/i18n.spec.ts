import { expect, test, type Page } from "@playwright/test";

import { ADMIN } from "./accounts";

/**
 * Multilingual + RTL behaviour.
 *
 * These run against the real stack so they exercise the same message loading,
 * cookie handling and `dir` switching that users get. The aim is to fail loudly
 * on the two failure modes that matter:
 *   1. A locale renders a raw key path instead of a translation.
 *   2. Arabic renders as an LTR document with Arabic words in it.
 */

/** Per-locale expectations: a word that must appear and must be translated. */
const LOCALES = [
  {
    code: "en",
    dir: "ltr",
    // Login page heading area
    expect: /Sign in|Sign in to your account|Enter your institutional/i,
    navWord: "Dashboard",
  },
  {
    code: "zh",
    dir: "ltr",
    expect: /登录|请输入学校统一账户信息/,
    navWord: "工作台",
  },
  {
    code: "fr",
    dir: "ltr",
    expect: /Connexion|Connectez-vous|Saisissez vos identifiants/i,
    navWord: "Tableau de bord",
  },
  {
    code: "ar",
    dir: "rtl",
    expect: /تسجيل الدخول|أدخل بيانات الدخول/,
    navWord: "لوحة المعلومات",
  },
  {
    code: "ru",
    dir: "ltr",
    expect: /Войти|Введите учётные данные/,
    navWord: "Панель управления",
  },
] as const;

/**
 * Key paths that must never reach the screen. If message loading breaks, the
 * fallback renders the namespace-qualified key, so these are a direct signal.
 */
const LEAKED_KEYS = [
  "navigation.students",
  "navigation.dashboard",
  "auth.signIn",
  "auth.email",
  "common.actions.save",
  "students.title",
  "housing.title",
  "errors.generic",
  "locale.label",
];

function trackPageHealth(page: Page) {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    const text = message.text();
    // React logs hydration mismatches as errors; treat them as failures.
    if (message.type() === "error" && /hydrat/i.test(text)) {
      failures.push(`hydration: ${text}`);
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 500) {
      failures.push(`http ${response.status()}: ${response.url()}`);
    }
  });
  return failures;
}

async function expectNoLeakedKeys(page: Page) {
  const body = await page.locator("body").innerText();
  for (const key of LEAKED_KEYS) {
    expect(body, `raw translation key "${key}" was rendered`).not.toContain(key);
  }
}

async function signIn(page: Page, locale: string) {
  await page.goto(`/${locale}/login`);
  await page.getByLabel(/email|邮箱|Adresse|البريد|Эл\. почта/i).fill(ADMIN.email);
  await page.getByLabel(/password|密码|Mot de passe|كلمة المرور|Пароль/i).fill(ADMIN.password);
  await page.getByRole("button").filter({ hasText: /sign in|登录|se connecter|تسجيل الدخول|Войти/i }).click();
  await page.waitForURL(new RegExp(`/${locale}/app`), { timeout: 25_000 });
}

test.describe("localized rendering", () => {
  for (const locale of LOCALES) {
    test(`${locale.code}: login renders translated with dir=${locale.dir}`, async ({ page }) => {
      const failures = trackPageHealth(page);
      await page.goto(`/${locale.code}/login`);
      await page.waitForLoadState("networkidle");

      await expect(page.locator("html")).toHaveAttribute("lang", locale.code);
      await expect(page.locator("html")).toHaveAttribute("dir", locale.dir);
      await expect(page.locator("body")).toContainText(locale.expect);
      await expectNoLeakedKeys(page);
      expect(failures).toEqual([]);
    });

    test(`${locale.code}: dashboard renders translated`, async ({ page }) => {
      const failures = trackPageHealth(page);
      await signIn(page, locale.code);

      const nav = page.getByRole("navigation", { name: /.+/ }).first();
      await expect(nav).toContainText(locale.navWord);
      await expectNoLeakedKeys(page);
      expect(failures).toEqual([]);
    });
  }
});

test.describe("RTL layout", () => {
  test("arabic renders a genuine RTL document", async ({ page }) => {
    await signIn(page, "ar");

    // The document is RTL…
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");

    // …and the layout actually follows, rather than being an LTR skin. The V3
    // shell is a top rail, not the V1 sidebar, so the check is that its
    // end-side controls mirror: in RTL the account menu resolves to the left
    // half of the header, where "end" is.
    const account = page.locator("header .scu-me").first();
    await expect(account).toBeVisible();

    const box = await account.boundingBox();
    const viewport = page.viewportSize();
    expect(box).not.toBeNull();
    expect(viewport).not.toBeNull();
    if (box && viewport) {
      expect(box.x + box.width / 2).toBeLessThan(viewport.width / 2);
    }

    // The main landmark is still present and laid out.
    const mainBox = await page.locator("main").first().boundingBox();
    expect(mainBox).not.toBeNull();
    if (mainBox) expect(mainBox.width).toBeGreaterThan(0);
  });

  test("arabic student profile keeps tables usable", async ({ page }) => {
    await signIn(page, "ar");
    await page.goto("/ar/app/students");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    // A table on an RTL page must not be mirrored into nonsense: it should
    // still be present and readable rather than clipped to zero width.
    const table = page.locator("table").first();
    await expect(table).toBeVisible();
    const box = await table.boundingBox();
    expect(box).not.toBeNull();
    if (box) expect(box.width).toBeGreaterThan(200);
  });
});

test.describe("language switching", () => {
  test("switcher changes locale and stays on the same page", async ({ page }) => {
    const failures = trackPageHealth(page);
    await signIn(page, "en");
    await page.goto("/en/app/students");
    await page.waitForLoadState("networkidle");

    const switcher = page.getByLabel(/change language|切换语言|changer de langue|تغيير اللغة/i).first();
    await switcher.selectOption("zh");

    // Same page, new locale.
    await page.waitForURL(/\/zh\/app\/students/, { timeout: 25_000 });
    await expect(page.locator("html")).toHaveAttribute("lang", "zh");
    await expectNoLeakedKeys(page);
    expect(failures).toEqual([]);
  });

  test("locale choice persists to a bare root visit", async ({ page, context }) => {
    await page.goto("/ar/login");
    await page.waitForLoadState("networkidle");

    // The cookie set by visiting a prefixed URL should drive the bare root.
    const cookies = await context.cookies();
    expect(cookies.some((cookie) => cookie.name === "NEXT_LOCALE")).toBe(true);

    await page.goto("/");
    await page.waitForURL(/\/ar(\/|$)/, { timeout: 25_000 });
  });

  test("unknown locale prefix does not produce a blank page", async ({ page }) => {
    const response = await page.goto("/de/app/students");
    await page.waitForLoadState("domcontentloaded");
    // Middleware rewrites it into a known locale rather than 404-ing the app shell.
    expect(response?.status()).toBeLessThan(500);
    // `domcontentloaded` can fire before the app shell paints, so wait for
    // any rendered text instead of sampling the body once.
    await expect(page.locator("body")).toContainText(/\S/);
    const body = await page.locator("body").innerText();
    expect(body.trim().length).toBeGreaterThan(0);
  });
});
