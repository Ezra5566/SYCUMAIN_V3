"use client";

import { useLocale } from "next-intl";
import { Toaster as SonnerToaster, toast } from "sonner";
import { isRtl } from "@/i18n/routing";
import { useTheme } from "@/components/theme/theme-provider";

export function Toaster() {
  const locale = useLocale();
  const { resolvedTheme } = useTheme();

  return (
    <SonnerToaster
      position={isRtl(locale) ? "bottom-left" : "bottom-right"}
      theme={resolvedTheme}
      richColors
      toastOptions={{ className: "scu-toast" }}
    />
  );
}

export { toast };
