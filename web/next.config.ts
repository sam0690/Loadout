import type { NextConfig } from "next";

const config: NextConfig = {
  // The logger has to work with no network at all, so the client bundle is the product.
  reactStrictMode: true,
  // The routes before the Today/Week/Progress split, for installed PWAs and bookmarks.
  async redirects() {
    return [
      { source: "/plan", destination: "/today", permanent: true },
      { source: "/history", destination: "/progress", permanent: true },
    ];
  },
};

export default config;
