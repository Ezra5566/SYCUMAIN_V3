"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Theme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";
export type Accent = "institution" | "sky" | "teal" | "violet" | "amber" | "rose";

const STORAGE_KEY = "scu-theme";
const ACCENT_KEY = "scu-accent";

export const ACCENTS: Accent[] = [
  "institution",
  "sky",
  "teal",
  "violet",
  "amber",
  "rose",
];

interface ThemeContextValue {
  theme: Theme;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: Theme) => void;
  accent: Accent;
  setAccent: (accent: Accent) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function isTheme(value: string | null): value is Theme {
  return value === "light" || value === "dark" || value === "system";
}

export function isAccent(value: string | null): value is Accent {
  return ACCENTS.includes(value as Accent);
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function applyAccent(accent: Accent) {
  document.documentElement.dataset.accent = accent;
}

/**
 * Appearance controller.
 *
 * Two independent device preferences are owned here: the light/dark theme and
 * the accent palette. Both are applied to <html> by the inline head script
 * before paint, so a reload never flashes the wrong colours, and both are local
 * to the device — appearance is not personal data that belongs in the account
 * record. Accent choice is a data attribute rather than inline styles so every
 * token-derived surface (buttons, links, focus rings, charts) follows at once.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("dark");
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("dark");
  const [accent, setAccentState] = useState<Accent>("institution");

  const apply = useCallback((nextTheme: Theme) => {
    const resolved = nextTheme === "system" ? systemTheme() : nextTheme;
    const root = document.documentElement;
    root.classList.toggle("dark", resolved === "dark");
    root.dataset.theme = nextTheme;
    root.style.colorScheme = resolved;
    setResolvedTheme(resolved);
  }, []);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    const initial: Theme = isTheme(stored) ? stored : "dark";
    setThemeState(initial);
    apply(initial);

    const storedAccent = window.localStorage.getItem(ACCENT_KEY);
    const initialAccent: Accent = isAccent(storedAccent) ? storedAccent : "institution";
    setAccentState(initialAccent);
    applyAccent(initialAccent);
  }, [apply]);

  useEffect(() => {
    if (theme !== "system") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply("system");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [theme, apply]);

  const setTheme = useCallback(
    (nextTheme: Theme) => {
      window.localStorage.setItem(STORAGE_KEY, nextTheme);
      setThemeState(nextTheme);
      apply(nextTheme);
    },
    [apply],
  );

  const setAccent = useCallback((nextAccent: Accent) => {
    window.localStorage.setItem(ACCENT_KEY, nextAccent);
    setAccentState(nextAccent);
    applyAccent(nextAccent);
  }, []);

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme, accent, setAccent }),
    [theme, resolvedTheme, setTheme, accent, setAccent],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used inside ThemeProvider");
  }
  return context;
}
