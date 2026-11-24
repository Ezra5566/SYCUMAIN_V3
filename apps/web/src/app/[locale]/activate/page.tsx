import { setRequestLocale } from "next-intl/server";
import { ActivateForm } from "@/components/auth/activate-form";

/**
 * Complete first-login activation.
 *
 * The single-use token rides in the query string and is read on the server, so
 * it never enters client-side routing state.
 */
export default async function ActivatePage({
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

  return <ActivateForm token={token} />;
}
