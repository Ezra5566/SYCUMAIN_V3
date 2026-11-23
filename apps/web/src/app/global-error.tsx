"use client";

import { useEffect } from "react";

/**
 * Last-resort error fallback.
 *
 * This component runs above the localized layout and therefore cannot use the
 * NextIntl provider. The small inline dictionary keeps the fallback readable in
 * every supported language without bundling user data or internal details.
 */
const COPY = {
  en: {
    title: "Something went wrong",
    body: "The portal could not finish loading. Try again; if the problem continues, contact the international office.",
    retry: "Try again",
    signIn: "Sign in",
  },
  zh: {
    title: "出现问题",
    body: "门户无法完成加载。请重试；若问题持续存在，请联系国际学院办公室。",
    retry: "重试",
    signIn: "登录",
  },
  fr: {
    title: "Un problème est survenu",
    body: "Le portail n’a pas pu terminer le chargement. Réessayez ; si le problème persiste, contactez le bureau international.",
    retry: "Réessayer",
    signIn: "Se connecter",
  },
  ar: {
    title: "حدث خطأ ما",
    body: "تعذّر على البوابة إكمال التحميل. حاول مرة أخرى؛ وإذا استمرت المشكلة فتواصل مع مكتب الطلاب الدوليين.",
    retry: "إعادة المحاولة",
    signIn: "تسجيل الدخول",
  },
  ru: {
    title: "Что-то пошло не так",
    body: "Портал не смог завершить загрузку. Повторите попытку; если проблема сохраняется, обратитесь в международный офис.",
    retry: "Повторить",
    signIn: "Войти",
  },
} as const;

type GlobalLocale = keyof typeof COPY;

function localeFromPath(): GlobalLocale {
  if (typeof window === "undefined") return "en";
  const first = window.location.pathname.split("/").filter(Boolean)[0];
  return first && first in COPY ? (first as GlobalLocale) : "en";
}

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const locale = localeFromPath();
  const copy = COPY[locale];
  const dir = locale === "ar" ? "rtl" : "ltr";

  useEffect(() => {
    if (process.env.NODE_ENV !== "production") {
      console.error("[ui] global error", error);
    }
  }, [error]);

  return (
    <html lang={locale} dir={dir} suppressHydrationWarning>
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#f4f7fa",
          color: "#111c2e",
          fontFamily:
            "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
        }}
      >
        <main
          style={{
            width: "min(28rem, calc(100% - 2rem))",
            padding: "2rem",
            borderRadius: "0.75rem",
            border: "1px solid #dbe3ed",
            background: "#ffffff",
            boxShadow: "0 12px 32px -16px rgba(18, 37, 63, 0.24)",
            textAlign: "center",
          }}
        >
          <h1 style={{ margin: 0, fontSize: "1.25rem" }}>{copy.title}</h1>
          <p
            style={{
              margin: "0.75rem 0 0",
              color: "#5f7188",
              fontSize: "0.875rem",
              lineHeight: 1.6,
            }}
          >
            {copy.body}
          </p>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              justifyContent: "center",
              gap: "0.5rem",
              marginTop: "1.5rem",
            }}
          >
            <button
              type="button"
              onClick={reset}
              style={{
                border: 0,
                borderRadius: "0.5rem",
                background: "#173b63",
                color: "#ffffff",
                padding: "0.625rem 1rem",
                cursor: "pointer",
                font: "inherit",
              }}
            >
              {copy.retry}
            </button>
            <a
              href={`/${locale}/login`}
              style={{
                borderRadius: "0.5rem",
                border: "1px solid #dbe3ed",
                color: "#173b63",
                padding: "0.625rem 1rem",
                textDecoration: "none",
                font: "inherit",
              }}
            >
              {copy.signIn}
            </a>
          </div>
        </main>
      </body>
    </html>
  );
}
