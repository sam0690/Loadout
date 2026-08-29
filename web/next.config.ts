import type { NextConfig } from "next";

const config: NextConfig = {
  // The logger has to work with no network at all, so the client bundle is the product.
  reactStrictMode: true,
};

export default config;
