import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ServiceWorker } from "@/components/ServiceWorker";
import { SyncProvider } from "@/components/Sync";
import { ToastProvider } from "@/components/ui/Toast";

export const metadata: Metadata = {
  title: "Loadout",
  description: "Training that fits the equipment you actually have.",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  // Matches --color-ground exactly. A theme colour that drifts from the body background
  // shows as a seam between the browser chrome and the page.
  themeColor: "#0d1013",
  width: "device-width",
  initialScale: 1,
  // No maximumScale. It was set to 1 to stop an accidental pinch mid-set, which also
  // took pinch-zoom away from everyone who relies on it -- a WCAG 1.4.4 failure for a
  // 300ms tap-delay win. `touch-action: manipulation` on buttons buys the same win
  // without the cost.
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      {/* No max-width here. Each surface decides its own measure: the logger stays a
          thumb's width at every breakpoint because that is its entire premise, while
          the plan and history earn real space on a laptop. */}
      <body className="min-h-dvh antialiased">
        <ServiceWorker />
        <SyncProvider>
          <ToastProvider>{children}</ToastProvider>
        </SyncProvider>
      </body>
    </html>
  );
}
