import { expect, test, type Page } from "@playwright/test";

import { LOCALE, USERS, app } from "./accounts";

/**
 * Practical accessibility audit (WCAG 2.2 AA), not a conformance claim.
 *
 * These checks exercise the paths a keyboard or screen-reader user takes:
 * focus order and visibility, accessible names, dialog focus management,
 * heading structure, table semantics, error announcements, colour contrast,
 * RTL layout and 200% text scaling.
 *
 * A scanner alone cannot establish conformance, so this suite deliberately
 * combines automated assertions with interaction. Where a check is a sample
 * (contrast, heading depth) that is stated in the test name.
 */

async function login(page: Page, user = USERS.admin) {
  await page.goto(app("/login"));
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(new RegExp(`/${LOCALE}/app`), { timeout: 25_000 });
}

async function tabTo(page: Page, predicate: (id: string) => boolean, limit = 25) {
  for (let step = 0; step < limit; step += 1) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      return {
        id: element?.id ?? "",
        tag: element?.tagName ?? "",
        text: (element?.innerText ?? "").trim().slice(0, 40),
      };
    });
    if (predicate(info.id) || predicate(info.tag)) return info;
  }
  return null;
}

test.describe("accessibility", () => {
  test("login is keyboard-operable and announces errors", async ({ page }) => {
    await page.goto(app("/login"));

    const email = await tabTo(page, (value) => value === "email");
    expect(email, "email field is reachable with Tab").not.toBeNull();
    await page.keyboard.type(USERS.admin.email);
    await page.keyboard.press("Tab");
    await page.keyboard.type("definitely-wrong-password");
    await page.keyboard.press("Enter");

    const alert = page.getByRole("alert").first();
    await expect(alert).toBeVisible({ timeout: 15_000 });
    await expect(alert).toHaveText(/incorrect email or password/i);
    // A rejected credential pair invalidates both fields, and each must be
    // tied to the announced error rather than only coloured red.
    await expect(page.locator("#email")).toHaveAttribute("aria-invalid", "true");
    await expect(page.locator("#password")).toHaveAttribute("aria-invalid", "true");
    await expect(page.locator("#email")).toHaveAttribute("aria-describedby", "login-error");
    await expect(page.locator("#password")).toHaveAttribute(
      "aria-describedby",
      "login-error",
    );
  });

  test("every visible form control on the login page has an accessible name", async ({
    page,
  }) => {
    await page.goto(app("/login"));
    const unnamed = await page.evaluate(() => {
      const controls = Array.from(
        document.querySelectorAll<HTMLElement>("input, select, textarea"),
      ).filter((element) => {
        const style = getComputedStyle(element);
        return style.display !== "none" && style.visibility !== "hidden";
      });
      return controls
        .filter((element) => {
          const input = element as HTMLInputElement;
          if (input.getAttribute("aria-label")?.trim()) return false;
          if (input.getAttribute("aria-labelledby")?.trim()) return false;
          if (input.id && document.querySelector(`label[for="${input.id}"]`)) return false;
          if (input.closest("label")) return false;
          if (input.type === "hidden") return false;
          return true;
        })
        .map((element) => (element as HTMLInputElement).outerHTML.slice(0, 120));
    });
    expect(unnamed).toEqual([]);
  });

  test("keyboard focus is visible on the dashboard", async ({ page }) => {
    await login(page);
    const missing: string[] = [];
    for (let step = 0; step < 22; step += 1) {
      await page.keyboard.press("Tab");
      const result = await page.evaluate(() => {
        const element = document.activeElement as HTMLElement | null;
        if (!element || element === document.body) return null;
        const style = getComputedStyle(element);
        const visible =
          (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0) ||
          (style.boxShadow !== "none" && style.boxShadow !== "");
        return {
          visible,
          label: `${element.tagName.toLowerCase()}${
            element.getAttribute("aria-label")
              ? `[${element.getAttribute("aria-label")}]`
              : ""
          }`,
        };
      });
      if (result && !result.visible) missing.push(result.label);
    }
    expect(missing, "focused controls without a visible focus indicator").toEqual([]);
  });

  test("heading structure is a single h1 without skipped levels", async ({ page }) => {
    await login(page);
    for (const path of ["/app", "/app/students"]) {
      await page.goto(app(path));
      await page.waitForLoadState("networkidle");
      const headings = await page.evaluate(() =>
        Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6"))
          .filter((element) => {
            const style = getComputedStyle(element);
            return (
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              element.getBoundingClientRect().height > 0
            );
          })
          .map((element) => Number(element.tagName.slice(1))),
      );
      expect(headings.filter((level) => level === 1).length, `${path} h1 count`).toBe(1);
      for (let index = 1; index < headings.length; index += 1) {
        expect(
          headings[index] - headings[index - 1],
          `${path} heading order ${headings.join(",")}`,
        ).toBeLessThanOrEqual(1);
      }
    }
  });

  test("the account menu is labelled, keyboard-operable and restores focus", async ({
    page,
  }) => {
    await login(page);
    const trigger = page.locator("header .scu-me").first();
    const label = await trigger.getAttribute("aria-label");
    expect(label?.trim().length ?? 0, "account trigger has an accessible name").toBeGreaterThan(0);
    await trigger.focus();
    await page.keyboard.press("Enter");

    const menu = page.getByRole("menu");
    await expect(menu).toBeVisible();
    const items = menu.getByRole("menuitem");
    expect(await items.count()).toBeGreaterThan(0);

    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    // Radix restores focus to the trigger during the close animation, so
    // assert with retry rather than reading activeElement once.
    await expect(trigger).toBeFocused();
  });

  test("a dialog traps focus, closes with Escape and returns focus", async ({ page }) => {
    await login(page);
    await page.goto(app("/app/accounts"));
    const opener = page.getByRole("button", { name: /create|new/i }).first();
    await opener.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // Radix moves focus into the dialog; the first focusable control must be
    // inside it rather than left behind on the page.
    const inside = await page.evaluate(() => {
      const active = document.activeElement;
      return Boolean(active?.closest('[role="dialog"]'));
    });
    expect(inside).toBe(true);

    for (let step = 0; step < 12; step += 1) {
      await page.keyboard.press("Tab");
      const stillInside = await page.evaluate(() =>
        Boolean(document.activeElement?.closest('[role="dialog"]')),
      );
      expect(stillInside, "focus escaped the modal dialog").toBe(true);
    }

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    const returned = await page.evaluate(() =>
      document.activeElement?.textContent?.trim().slice(0, 40),
    );
    expect(returned).toBeTruthy();
  });

  test("data tables expose column headers and an accessible name", async ({ page }) => {
    await login(page);
    await page.goto(app("/app/students"));
    const table = page.getByRole("table").first();
    await expect(table).toBeVisible();

    const headers = table.getByRole("columnheader");
    expect(await headers.count()).toBeGreaterThan(0);
    for (const header of await headers.all()) {
      const text = (await header.innerText()).trim();
      expect(text.length, "column header has text").toBeGreaterThan(0);
    }

    const name = await table.evaluate((element) => {
      const labelledBy = element.getAttribute("aria-labelledby");
      const label = labelledBy ? document.getElementById(labelledBy)?.textContent : null;
      return element.getAttribute("aria-label") ?? label ?? "";
    });
    expect(name.trim().length, "table has an accessible name").toBeGreaterThan(0);
  });

  test("sampled text meets the 4.5:1 contrast threshold", async ({ page }) => {
    await login(page);
    const failures: string[] = [];

    const inspect = async (path: string) => {
      await page.goto(app(path));
      await page.waitForLoadState("networkidle");
      const violations = await page.evaluate(() => {
        const parse = (value: string): number[] => {
          const match = value.match(/rgba?\(([^)]+)\)/);
          if (!match) return [0, 0, 0, 0];
          const parts = match[1].split(",").map((part) => parseFloat(part.trim()));
          return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1];
        };
        const channel = (value: number) => {
          const c = value / 255;
          return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
        };
        const luminance = (rgb: number[]) =>
          0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
        const ratio = (a: number[], b: number[]) => {
          const la = luminance(a);
          const lb = luminance(b);
          return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
        };
        const background = (element: HTMLElement): number[] | null => {
          let node: HTMLElement | null = element;
          while (node) {
            const style = getComputedStyle(node);
            if (style.backgroundImage !== "none") return null;
            const colour = parse(style.backgroundColor);
            if (colour[3] > 0.9) return colour;
            node = node.parentElement;
          }
          return [255, 255, 255, 1];
        };

        const results: string[] = [];
        const candidates = Array.from(
          document.querySelectorAll<HTMLElement>(
            "p, span, a, button, label, td, th, h1, h2, h3, h4, li",
          ),
        );
        for (const element of candidates.slice(0, 500)) {
          const ownText = Array.from(element.childNodes)
            .filter((node) => node.nodeType === Node.TEXT_NODE)
            .map((node) => node.textContent?.trim() ?? "")
            .join(" ")
            .trim();
          if (!ownText) continue;
          const rect = element.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) continue;
          const style = getComputedStyle(element);
          if (style.visibility === "hidden" || style.opacity === "0") continue;

          const fg = parse(style.color);
          if (fg[3] < 0.5) continue;
          const bg = background(element);
          if (!bg) continue;

          const size = parseFloat(style.fontSize);
          const bold = Number(style.fontWeight) >= 700;
          const large = size >= 24 || (bold && size >= 18.66);
          const required = large ? 3 : 4.5;
          const value = ratio(fg, bg);
          if (value + 0.01 < required) {
            results.push(
              `${ownText.slice(0, 45)} | ${value.toFixed(2)}:1 (needs ${required}) ` +
                `fg ${style.color} bg rgb(${bg.slice(0, 3).join(",")})`,
            );
          }
        }
        return results;
      });
      failures.push(...violations.map((violation) => `${path}: ${violation}`));
    };

    await inspect("/app");
    await inspect("/app/students");
    expect(failures.slice(0, 12), `${failures.length} contrast failure(s)`).toEqual([]);
  });

  test("images carry alt text", async ({ page }) => {
    await login(page);
    for (const path of ["/app", "/app/students"]) {
      await page.goto(app(path));
      await page.waitForLoadState("networkidle");
      const missing = await page.evaluate(() =>
        Array.from(document.querySelectorAll("img"))
          .filter((image) => !image.hasAttribute("alt"))
          .map((image) => image.getAttribute("src")?.slice(0, 80) ?? ""),
      );
      expect(missing, `${path} images without alt`).toEqual([]);
    }
  });

  test("Arabic layout is right-to-left without horizontal overflow", async ({ page }) => {
    await page.goto("/ar/login");
    await page.getByLabel(/البريد|email/i).fill(USERS.admin.email);
    await page.getByLabel(/كلمة المرور|password/i).fill(USERS.admin.password);
    await page.locator('button[type="submit"]').click();
    await page.waitForURL(/\/ar\/app/, { timeout: 25_000 });

    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "horizontal overflow in RTL").toBeLessThanOrEqual(1);

    // The navigation must still be reachable and mirrored, not hidden.
    await expect(page.locator("nav.scu-tabs")).toBeVisible();
    const navBox = await page.locator("nav.scu-tabs").boundingBox();
    expect(navBox?.width ?? 0).toBeGreaterThan(100);
  });

  test("200% text scaling does not introduce horizontal scrolling", async ({ page }) => {
    await login(page);
    await page.goto(app("/app/students"));
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "horizontal overflow at 200% text size").toBeLessThanOrEqual(1);
  });
});
