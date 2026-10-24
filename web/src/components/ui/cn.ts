/** Join class names, dropping the falsy ones. Small enough not to justify a dependency. */
export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
