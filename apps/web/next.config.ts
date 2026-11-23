import createNextIntlPlugin from "next-intl/plugin";
import type { NextConfig } from "next";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  output: "standalone",
  // The clone lives inside a larger workspace that has its own lockfile at the
  // root. Without pinning the tracing root Next walks up to that lockfile and
  // resolves the app against the wrong workspace.
  outputFileTracingRoot: process.cwd(),
};

export default withNextIntl(nextConfig);
