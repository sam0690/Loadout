/**
 * The icon set. Authored rather than pulled from a library, because the app needs
 * eight glyphs and a library is a dependency plus a bundle for 400 more.
 *
 * One 20×20 grid, one 1.75 stroke, round caps and joins throughout. Consistency across
 * the set matters more than any individual glyph — a mixed-weight icon set is the
 * fastest way to make a considered interface look assembled.
 */
type Props = { className?: string };

function Glyph({ className, children }: Props & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className ?? "size-5"}
    >
      {children}
    </svg>
  );
}

/** A loaded bar, seen end-on. The plan is the week's prescriptions. */
export function PlanIcon(p: Props) {
  return (
    <Glyph {...p}>
      <path d="M3 8v4M6 6.5v7M14 6.5v7M17 8v4M6 10h8" />
    </Glyph>
  );
}

export function HistoryIcon(p: Props) {
  return (
    <Glyph {...p}>
      <path d="M3.5 10a6.5 6.5 0 1 0 1.9-4.6" />
      <path d="M3 3v3.5h3.5M10 6.5V10l2.5 1.5" />
    </Glyph>
  );
}

export function SettingsIcon(p: Props) {
  return (
    <Glyph {...p}>
      <circle cx="10" cy="10" r="2.5" />
      <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4" />
    </Glyph>
  );
}

export function BackIcon(p: Props) {
  return (
    <Glyph {...p}>
      <path d="M12 4l-6 6 6 6" />
    </Glyph>
  );
}

export function CheckIcon(p: Props) {
  return (
    <Glyph {...p}>
      <path d="M4 10.5l4 4 8-9" />
    </Glyph>
  );
}

export function UndoIcon(p: Props) {
  return (
    <Glyph {...p}>
      <path d="M3 6.5h8a4.5 4.5 0 0 1 0 9H7" />
      <path d="M6 3.5l-3 3 3 3" />
    </Glyph>
  );
}

export function TimerIcon(p: Props) {
  return (
    <Glyph {...p}>
      <circle cx="10" cy="11" r="6.5" />
      <path d="M10 8v3M8 2.5h4" />
    </Glyph>
  );
}

export function SwapIcon(p: Props) {
  return (
    <Glyph {...p}>
      <path d="M3 7h11l-3-3M17 13H6l3 3" />
    </Glyph>
  );
}

export function OfflineIcon(p: Props) {
  return (
    <Glyph {...p}>
      <path d="M10 15.5h.01M6.2 12.3a5.5 5.5 0 0 1 7.6 0M3 9.2a10 10 0 0 1 14 0" />
      <path d="M3 3l14 14" />
    </Glyph>
  );
}
