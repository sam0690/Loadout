import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ServiceWorker } from "@/components/ServiceWorker";

export const metadata: Metadata = {
  title: "Loadout",
  description: "Training that fits the equipment you actually have.",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: "#0b0d10",
  // No zoom-on-tap delay, and no accidental pinch while logging a set with one thumb.
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="mx-auto min-h-dvh max-w-md antialiased">
        <ServiceWorker />
        {children}
      </body>
    </html>
  );
}
