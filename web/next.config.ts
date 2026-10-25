import type { NextConfig } from "next";

const config: NextConfig = {
  // The logger has to work with no network at all, so the client bundle is the product.
  reactStrictMode: true,
  // Old routes, for installed PWAs and bookmarks. Each points at its final home, never
  // at another redirect.
  async redirects() {
    return [
      { source: "/plan", destination: "/today", permanent: true },
      { source: "/history", destination: "/profile", permanent: true },
      { source: "/progress", destination: "/profile", permanent: true },
      { source: "/settings", destination: "/profile/settings", permanent: true },
      { source: "/log/:id", destination: "/workout?exercise=:id", permanent: true },
    ];
  },
};

export default config;
