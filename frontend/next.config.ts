import type { NextConfig } from "next";

/**
 * Where the Next server proxies upstream services.
 * Same machine (npm on host): API http://127.0.0.1:8000, runtime http://127.0.0.1:7860
 * Docker Compose frontend service: API http://api:8000, runtime http://runtime:7860
 *
 * The browser always calls same-origin /api/v1 and ws(s)://…/agent/…, so the
 * public hostname that forwards port 3000 needs no separate API or runtime URL.
 */
const allowedDevOrigins = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((h) => h.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {
  allowedDevOrigins,
  // The backend's /campaign collection route requires a trailing slash and
  // 307-redirects to it using its own host (not the Next proxy origin) when
  // hit without one — that cross-origin redirect drops the Authorization
  // header, which looks like the user got logged out. Next's default
  // trailing-slash redirect would strip the slash from `/api/v1/campaign/`
  // before the rewrite ever runs, so this must stay off.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    const apiProxyTarget = (
      process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000"
    ).replace(/\/$/, "");
    const runtimeProxyTarget = (
      process.env.RUNTIME_PROXY_TARGET ?? "http://127.0.0.1:7860"
    ).replace(/\/$/, "");
    return [
      {
        source: "/api/v1/campaign/",
        destination: `${apiProxyTarget}/api/v1/campaign/`,
      },
      {
        source: "/api/v1/:path*",
        destination: `${apiProxyTarget}/api/v1/:path*`,
      },
      {
        source: "/agent/:orgId/:agentId",
        destination: `${runtimeProxyTarget}/agent/:orgId/:agentId`,
      },
    ];
  },
};

export default nextConfig;
