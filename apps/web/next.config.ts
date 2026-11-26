import createNextIntlPlugin from "next-intl/plugin";
import type { NextConfig } from "next";

// next-intl v4 takes exactly one argument: the path to the request config.
// Messages are resolved by src/i18n/request.ts, which imports the JSON message
// catalogues statically so they are bundled into the build output.
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  output: "standalone",
  // The clone lives inside a larger workspace that has its own lockfile at the
  // root. Without pinning the tracing root Next walks up to that lockfile and
  // resolves the app against the wrong workspace.
  outputFileTracingRoot: process.cwd(),
};

export default withNextIntl(nextConfig);
