"use client";

import { useEffect, useState } from "react";

/** One exercise's photos and steps, from public/exercises/index.json (D32). */
export interface Media {
  source: string;
  frames: string[];
  /** Empty for a borrowed photo: the source's steps describe a different exercise. */
  steps: string[];
}

let index: Promise<Record<string, Media>> | null = null;

/**
 * The manifest, fetched once per page load and shared by every caller. A static file
 * rather than an API route: it is catalog content, identical for every user, and the
 * service worker keeps it for offline. A failed fetch is forgotten so the next caller
 * retries, and renders as "no media" meanwhile -- photos are never worth an error.
 */
function load(): Promise<Record<string, Media>> {
  index ??= fetch("/exercises/index.json")
    .then((r) => (r.ok ? (r.json() as Promise<Record<string, Media>>) : {}))
    .catch(() => {
      index = null;
      return {};
    });
  return index;
}

export function useMedia(slug: string): Media | null {
  const [media, setMedia] = useState<Media | null>(null);
  useEffect(() => {
    let live = true;
    void load().then((all) => live && setMedia(all[slug] ?? null));
    return () => {
      live = false;
    };
  }, [slug]);
  return media;
}

/** A search, not a chosen video: nothing to curate and no link to rot (D32). */
export const watchUrl = (name: string): string =>
  `https://www.youtube.com/results?search_query=${encodeURIComponent(`${name} exercise form`)}`;
