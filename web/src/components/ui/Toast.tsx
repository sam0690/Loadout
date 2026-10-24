"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { cn } from "./cn";
import { CheckIcon } from "./icons";

/**
 * Transient confirmation, bottom-anchored so it never covers the primary control.
 *
 * This exists because writes used to succeed silently: `enqueue` resolved, nothing on
 * screen changed, and the user had no way to tell a saved set from a dropped one. It
 * is not a modal and never blocks — the gym rule about dismissable-with-a-thumb applies
 * here too, so these dismiss themselves.
 */
type Tone = "ok" | "error";
interface Toast {
  id: number;
  message: string;
  tone: Tone;
}

const DURATION = { ok: 2200, error: 5000 } as const;

const ToastContext = createContext<((message: string, tone?: Tone) => void) | null>(null);

export function useToast() {
  const show = useContext(ToastContext);
  if (!show) throw new Error("useToast must be used inside <ToastProvider>");
  return show;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const show = useCallback((message: string, tone: Tone = "ok") => {
    setToasts((prev) => [...prev, { id: Date.now() + Math.random(), message, tone }]);
  }, []);

  const value = useMemo(() => show, [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Polite, not assertive: a confirmed set must not interrupt whatever a screen
          reader is already saying mid-workout. */}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"
      >
        {toasts.map((toast) => (
          <Item
            key={toast.id}
            toast={toast}
            onDone={() =>
              setToasts((prev) => prev.filter((t) => t.id !== toast.id))
            }
          />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function Item({ toast, onDone }: { toast: Toast; onDone: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDone, DURATION[toast.tone]);
    return () => clearTimeout(timer);
  }, [onDone, toast.tone]);

  return (
    <div
      className={cn(
        "flex max-w-sm items-center gap-2.5 rounded-control border px-3.5 py-2.5",
        "text-[0.875rem] shadow-lg shadow-black/40 motion-safe:animate-[toast-in_180ms_cubic-bezier(0.22,1,0.36,1)]",
        toast.tone === "error"
          ? "border-danger/40 bg-danger-quiet text-ink"
          : "border-line bg-raised text-ink",
      )}
    >
      {toast.tone === "ok" && <CheckIcon className="size-4 shrink-0 text-accent" />}
      <span>{toast.message}</span>
    </div>
  );
}
