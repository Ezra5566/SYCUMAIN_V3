import { setRequestLocale } from "next-intl/server";
import { ResetPasswordForm } from "@/components/auth/reset-password-form";

/**
 * Complete a password reset.
 *
 * The token rides in the query string, so it is read here on the server and
 * handed to the form as a prop. Reading it via `useSearchParams` in a client
 * component would force a Suspense boundary for no benefit, and this also keeps
 * the token out of any client-side routing logic.
 */
export default async function ResetPasswordPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ token?: string | string[] }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const raw = query.token;
  const token = (Array.isArray(raw) ? raw[0] : raw) ?? "";

  return <ResetPasswordForm token={token} />;
}
