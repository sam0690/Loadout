"use client";

import { useMedia, watchUrl } from "@/lib/media";
import { PlanIcon } from "./ui/icons";
import { cn } from "./ui/cn";

/**
 * The source photos are full-colour gym shots with loud walls. Grayscale and a little
 * darker, they sit under the UI as backdrop instead of fighting the one volt accent --
 * the monochrome-photo look every athletic brand uses, for the same reason.
 */
const PHOTO = "absolute inset-0 size-full object-cover grayscale contrast-[1.1] brightness-[0.8]";

/**
 * Start and end position, cross-faded on a loop so the pair reads as the movement.
 * Decorative (alt="") because the exercise name is always beside it. Renders nothing
 * without media: an empty frame would be a hole in the screen.
 */
export function Frames({ slug, className }: { slug: string; className?: string }) {
  const media = useMedia(slug);
  if (!media || media.frames.length === 0) return null;
  const [first, second] = media.frames;
  return (
    <div className={cn("relative overflow-hidden rounded-card bg-raised", className)}>
      <img src={first} alt="" decoding="async" className={PHOTO} />
      {second && (
        <img
          src={second}
          alt=""
          decoding="async"
          // Resting opacity 0: when reduced motion cuts the animation short, this is
          // what remains, so the start position stands still.
          className={cn(PHOTO, "opacity-0 animate-[frames_2.4s_ease-in-out_infinite]")}
        />
      )}
      {/* Fades the photo's bottom edge into the card, so text below sits on ground. */}
      <div className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-surface to-transparent" />
    </div>
  );
}

/** First frame at row size, or the plan glyph when there is no photo. */
export function Thumb({ slug }: { slug: string }) {
  const media = useMedia(slug);
  const src = media?.frames[0];
  return (
    <span className="relative flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-control bg-raised text-ink-faint">
      {src ? (
        // Eager on purpose: Today's thumbnails are what put a session's photos in the
        // service worker cache before the gym, so a lazy one never fetched is one
        // missing offline.
        <img src={src} alt="" decoding="async" className={PHOTO} />
      ) : (
        <PlanIcon className="size-5" />
      )}
    </span>
  );
}

/**
 * The steps behind a closed disclosure, and a video search one tap out. Native
 * <details>: keyboard, screen reader and no-JS behaviour come free.
 */
export function HowTo({ slug, name }: { slug: string; name: string }) {
  const media = useMedia(slug);
  const steps = media?.steps ?? [];
  const watch = (
    <a
      href={watchUrl(name)}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-[0.875rem] text-ink-muted underline underline-offset-4 hover:text-ink"
    >
      Watch how ↗
    </a>
  );

  if (steps.length === 0) return <div>{watch}</div>;
  return (
    <details className="group rounded-control bg-surface px-4 py-3">
      <summary className="label flex cursor-pointer list-none items-center justify-between [&::-webkit-details-marker]:hidden">
        How to
        <span className="transition-transform duration-200 group-open:rotate-45" aria-hidden="true">
          +
        </span>
      </summary>
      <ol className="mt-3 list-decimal space-y-2 pl-5 text-[0.875rem] leading-relaxed text-ink-muted">
        {steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
      <div className="mt-3">{watch}</div>
    </details>
  );
}
