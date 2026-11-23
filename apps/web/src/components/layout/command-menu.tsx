"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowRight, Search } from "lucide-react";
import { useRouter } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { NAV_SECTIONS } from "@/lib/navigation";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

/**
 * Permission-aware command menu.
 *
 * It only navigates to modules the current role can already open; the server
 * remains the authorization boundary. Keyboard handling is local and explicit
 * so Cmd/Ctrl+K never triggers a hidden browser conflict inside a form.
 */
export function CommandMenu() {
  const t = useTranslations("navigation");
  const { hasPermission, user } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const roles = user?.roles.map((role) => role.name) ?? [];
  const items = useMemo(
    () =>
      NAV_SECTIONS.flatMap((section) =>
        section.items.filter(
          (item) =>
            item.href &&
            !item.comingSoon &&
            (!item.permission || hasPermission(item.permission)) &&
            !item.hiddenForRoles?.some((role) => roles.includes(role)) &&
            (!item.visibleForRoles ||
              item.visibleForRoles.some((role) => roles.includes(role))),
        ),
      ).map((item) => ({
        ...item,
        label: t(item.labelKey),
        href: item.href as string,
      })),
    // `t` is stable for the active locale; roles and permissions close over the
    // current session and must participate in the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, user?.id, roles.join(","), hasPermission],
  );

  const normalized = query.trim().toLocaleLowerCase();
  const results = normalized
    ? items.filter((item) => item.label.toLocaleLowerCase().includes(normalized))
    : items;

  // The dock's search button is outside this component, so it opens the
  // palette through a window event rather than a shared context.
  useEffect(() => {
    const openPalette = () => setOpen(true);
    window.addEventListener("scu:command-open", openPalette);
    return () => window.removeEventListener("scu:command-open", openPalette);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!open) {
      setQuery("");
      return;
    }
    const timer = window.setTimeout(() => inputRef.current?.focus(), 40);
    return () => window.clearTimeout(timer);
  }, [open]);

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="scu-icon shrink-0 text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(true)}
        aria-label={t("search")}
        title={`${t("search")} (⌘K)`}
      >
        <Search className="h-[18px] w-[18px]" aria-hidden="true" />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="top-[15%] max-w-xl gap-0 overflow-hidden p-0 sm:rounded-xl">
          <DialogTitle className="sr-only">{t("commandTitle")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("commandDescription")}
          </DialogDescription>
          <div className="flex items-center gap-2 border-b border-border/80 px-3.5">
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <Input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && results[0]) {
                  event.preventDefault();
                  go(results[0].href);
                }
              }}
              placeholder={t("searchPlaceholder")}
              aria-label={t("searchPlaceholder")}
              className="h-12 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
            />
            <kbd className="scu-kbd hidden sm:inline-flex">
              ESC
            </kbd>
          </div>

          <div className="max-h-[min(26rem,60vh)] overflow-y-auto p-1.5">
            {results.length === 0 ? (
              <p className="px-3 py-8 text-center text-sm text-muted-foreground">
                {t("noResults")}
              </p>
            ) : (
              <ul className="motion-finder space-y-0.5">
                {results.map((item, index) => {
                  const Icon = item.icon;
                  return (
                    <li key={item.labelKey}>
                      <button
                        type="button"
                        onClick={() => go(item.href)}
                        className="group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-start transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/[0.08] text-primary">
                          <Icon className="h-4 w-4" aria-hidden="true" />
                        </span>
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">
                          {item.label}
                        </span>
                        {index === 0 && query && (
                          <kbd className="scu-kbd hidden sm:inline-flex">
                            ↵
                          </kbd>
                        )}
                        <ArrowRight
                          className="h-3.5 w-3.5 text-muted-foreground/50 rtl:rotate-180"
                          aria-hidden="true"
                        />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-border/80 bg-muted/25 px-4 py-2.5 text-[10px] text-muted-foreground">
            <span>{t("commandHint")}</span>
            <span className="flex items-center gap-1.5">
              <kbd className="scu-kbd">⌘K</kbd>
              {t("commandToggle")}
            </span>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
