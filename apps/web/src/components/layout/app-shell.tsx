"use client";

import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  BarChart3,
  ChevronDown,
  Home,
  LogOut,
  Moon,
  Search,
  Settings as SettingsIcon,
  Sun,
  UserRound,
  Users,
} from "lucide-react";
import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { AuthGuard } from "@/components/auth/auth-guard";
import { CommandMenu } from "@/components/layout/command-menu";
import { NotificationBell } from "@/components/layout/notification-bell";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { ThemeSwitcher } from "@/components/layout/theme-switcher";
import { useTheme } from "@/components/theme/theme-provider";
import { ScuMark } from "@/components/brand/scu-mark";
import { NAV_SECTIONS } from "@/lib/navigation";

interface AppShellProps {
  children: ReactNode;
  className?: string;
}

/**
 * Rail destinations. Every other permitted module lives in the "More" menu, so
 * the rail stays readable at laptop widths while nothing becomes unreachable.
 */
const PRIMARY_TABS = new Set([
  "dashboard",
  "myProfile",
  "students",
  "academics",
  "housing",
  "immigration",
  "announcements",
  "reports",
  "settings",
]);

/** Broadcast consumed by the command menu so the dock can open it. */
export const COMMAND_OPEN_EVENT = "scu:command-open";

/**
 * Application chrome, built on the Solvik UI kit.
 *
 * A sticky top rail carries the institution, a sliding-pill tab strip of every
 * permitted module, and the session tools; a floating dock repeats the most
 * used destinations. Visibility is UX only — the backend still authorizes each
 * request, so hiding a tab is never treated as access control.
 */
export function AppShell({ children, className }: AppShellProps) {
  const t = useTranslations("navigation");
  const tCommon = useTranslations("common");
  const tTheme = useTranslations("theme");
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout, hasPermission } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();

  const trackRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef(new Map<string, HTMLAnchorElement>());
  const [pill, setPill] = useState({ offset: 0, width: 0, ready: false });

  const roles = useMemo(() => user?.roles.map((role) => role.name) ?? [], [user]);

  const items = useMemo(
    () =>
      NAV_SECTIONS.flatMap((section) => section.items).filter(
        (item) =>
          item.href &&
          !item.comingSoon &&
          (!item.permission || hasPermission(item.permission)) &&
          !item.hiddenForRoles?.some((role) => roles.includes(role)) &&
          (!item.visibleForRoles || item.visibleForRoles.some((role) => roles.includes(role))),
      ),
    [hasPermission, roles],
  );

  const isCurrent = (href: string) =>
    href === "/app" ? pathname === "/app" : pathname === href || pathname.startsWith(`${href}/`);

  const activeHref = items.find((item) => isCurrent(item.href as string))?.href ?? null;
  const primaryItems = items.filter((item) => PRIMARY_TABS.has(item.labelKey));
  const moreItems = items.filter((item) => !PRIMARY_TABS.has(item.labelKey));
  const moreActive = moreItems.some((item) => isCurrent(item.href as string));

  // Measure the active tab so the pill slides between destinations exactly as
  // it does in the reference portal. Re-measured on route, resize and fonts.
  useLayoutEffect(() => {
    const measure = () => {
      const track = trackRef.current;
      const active = activeHref ? tabRefs.current.get(activeHref) : null;
      if (!track || !active) {
        setPill((current) => ({ ...current, ready: false }));
        return;
      }
      const trackRect = track.getBoundingClientRect();
      const rect = active.getBoundingClientRect();
      const rtl = document.documentElement.dir === "rtl";
      setPill({
        offset: rtl ? -(trackRect.right - rect.right) : rect.left - trackRect.left,
        width: rect.width,
        ready: true,
      });

      // With every permitted module in the rail, the active tab can sit outside
      // the visible strip. Bring it back into view without scrolling the page.
      const viewport = track.parentElement;
      if (viewport) {
        const left = rect.left - viewport.getBoundingClientRect().left;
        if (left < 0) viewport.scrollLeft += left - 12;
        else if (left + rect.width > viewport.clientWidth) {
          viewport.scrollLeft += left + rect.width - viewport.clientWidth + 12;
        }
      }
    };

    measure();
    window.addEventListener("resize", measure);
    document.fonts?.ready.then(measure).catch(() => {});
    return () => window.removeEventListener("resize", measure);
  }, [activeHref, items.length]);

  const initials = user?.full_name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  const handleLogout = async () => {
    await logout();
    router.replace("/login");
  };

  const dockLinks = [
    {
      href: "/app/students",
      label: t("students"),
      Icon: Users,
      visible: hasPermission("student.view") && !roles.includes("STUDENT"),
    },
    { href: "/app/housing", label: t("housing"), Icon: Home, visible: hasPermission("housing.view_all") },
    { href: "/app/reports", label: t("reports"), Icon: BarChart3, visible: hasPermission("reports.view") },
  ].filter((item) => item.visible);

  return (
    <AuthGuard>
      <div className="scu-shell">
        <div className="scu-backdrop" aria-hidden="true">
          <span className="scu-backdrop__glow scu-backdrop__glow--one" />
          <span className="scu-backdrop__glow scu-backdrop__glow--two" />
          <span className="scu-backdrop__grain" />
        </div>

        <header className="scu-top motion-drop">
          <Link href="/app" className="scu-brand" aria-label={tCommon("appName")}>
            <span className="scu-brand__mark">
              <ScuMark className="h-8 w-8" />
            </span>
            <span className="scu-brand__text">
              <span className="scu-brand__name">{tCommon("appShortName")}</span>
              <span className="scu-brand__sub">{tCommon("universityName")}</span>
            </span>
          </Link>

          <nav className="scu-tabs" aria-label={t("mainNav")}>
            <span className="scu-tabs__viewport">
              <div className="scu-tabs__track" ref={trackRef}>
                <span
                  className={cn("scu-tabs__pill", pill.ready && "is-ready")}
                  style={
                    {
                      transform: `translateX(${pill.offset}px)`,
                      width: pill.width,
                    } as CSSProperties
                  }
                  aria-hidden="true"
                />
                {primaryItems.map((item) => {
                  const href = item.href as string;
                  const active = activeHref === href;
                  return (
                    <Link
                      key={item.labelKey}
                      href={href}
                      ref={(node: HTMLAnchorElement | null) => {
                        if (node) tabRefs.current.set(href, node);
                        else tabRefs.current.delete(href);
                      }}
                      aria-current={active ? "page" : undefined}
                      className={cn("scu-tab", active && "is-active")}
                    >
                      {t(item.labelKey)}
                    </Link>
                  );
                })}

                {moreItems.length > 0 && (
                  <DropdownMenu.Root>
                    <DropdownMenu.Trigger asChild>
                      <button
                        type="button"
                        className={cn("scu-tab", moreActive && "is-active")}
                        aria-label={t("more")}
                      >
                        {t("more")}
                        <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    </DropdownMenu.Trigger>
                    <DropdownMenu.Portal>
                      <DropdownMenu.Content align="end" sideOffset={10} className="scu-pop">
                        {moreItems.map((item) => (
                          <DropdownMenu.Item key={item.labelKey} asChild>
                            <Link href={item.href as string} className="scu-pop__item">
                              <item.icon className="h-4 w-4" aria-hidden="true" />
                              {t(item.labelKey)}
                            </Link>
                          </DropdownMenu.Item>
                        ))}
                      </DropdownMenu.Content>
                    </DropdownMenu.Portal>
                  </DropdownMenu.Root>
                )}
              </div>
            </span>
          </nav>

          <div className="scu-tools">
            <CommandMenu />
            <NotificationBell />
            <span className="scu-lang hidden sm:block">
              <LanguageSwitcher className="w-[7.4rem]" />
            </span>
            <ThemeSwitcher className="scu-icon" />

            {user && (
              <DropdownMenu.Root>
                <DropdownMenu.Trigger asChild>
                  <button type="button" className="scu-me" aria-label={user.full_name}>
                    {initials || <UserRound className="h-4 w-4" />}
                  </button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content align="end" sideOffset={10} className="scu-pop">
                    <div className="scu-pop__head">
                      <strong>{user.full_name}</strong>
                      <span dir="ltr">{user.email}</span>
                    </div>
                    <DropdownMenu.Separator className="scu-pop__sep" />
                    <DropdownMenu.Item asChild>
                      <Link href="/app/settings" className="scu-pop__item">
                        <SettingsIcon className="h-4 w-4" aria-hidden="true" />
                        {t("settings")}
                      </Link>
                    </DropdownMenu.Item>
                    <DropdownMenu.Item
                      className="scu-pop__item scu-pop__item--danger"
                      onSelect={() => void handleLogout()}
                    >
                      <LogOut className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
                      {t("signOut")}
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
            )}
          </div>
        </header>

        <nav className="scu-dock" aria-label={t("quickActions")}>
          <button
            type="button"
            className="scu-dock__btn"
            aria-label={t("search")}
            onClick={() => window.dispatchEvent(new Event(COMMAND_OPEN_EVENT))}
          >
            <Search className="h-[18px] w-[18px]" aria-hidden="true" />
            <span className="scu-dock__tip">{t("search")}</span>
          </button>

          {dockLinks.map(({ href, label, Icon }) => (
            <Link key={href} href={href} className="scu-dock__btn" aria-label={label}>
              <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
              <span className="scu-dock__tip">{label}</span>
            </Link>
          ))}

          <span className="scu-dock__sep" />

          <Link href="/app/notifications" className="scu-dock__btn" aria-label={t("notifications")}>
            <svg
              className="h-[18px] w-[18px]"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.7 21a2 2 0 0 1-3.4 0" />
            </svg>
            <span className="scu-dock__tip">{t("notifications")}</span>
          </Link>

          <button
            type="button"
            className="scu-dock__btn"
            aria-label={tTheme("label")}
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          >
            {resolvedTheme === "dark" ? (
              <Sun className="h-[18px] w-[18px]" aria-hidden="true" />
            ) : (
              <Moon className="h-[18px] w-[18px]" aria-hidden="true" />
            )}
            <span className="scu-dock__tip">{tTheme("label")}</span>
          </button>

          <Link href="/app/settings" className="scu-dock__btn" aria-label={t("settings")}>
            <SettingsIcon className="h-[18px] w-[18px]" aria-hidden="true" />
            <span className="scu-dock__tip">{t("settings")}</span>
          </Link>
        </nav>

        <main id="main" className="scu-main">
          <div key={pathname} className={cn("motion-page", className)}>
            {children}
          </div>
        </main>
      </div>
    </AuthGuard>
  );
}
