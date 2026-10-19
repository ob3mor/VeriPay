import Image from "next/image";
import Link from "next/link";

import { cn } from "@/lib/utils";

export interface AppLogoProps {
  /**
   * lockup (default) — the cropped shield mark beside a typed "VeriPay"
   * wordmark: crisp at every small size (the full lockup PNG's navy-outlined
   * letters go ghostly below ~40px on dark grounds).
   * full — the owner's complete lockup PNG alone, for large placements
   * (the auth screens' 44px hero slot).
   * mark — the cropped shield mark alone, for tight slots (mobile top bar).
   */
  variant?: "lockup" | "full" | "mark";
  size?: "xs" | "sm" | "md" | "lg";
  /** Render as a link to the landing page (headers). Pass false inside pages that are already the target. */
  href?: string | false;
  className?: string;
}

const MARK_SIZES = {
  xs: 20,
  sm: 22,
  md: 26,
  lg: 40,
} as const;

const WORDMARK_SIZES = {
  xs: "text-sm",
  sm: "text-sm",
  md: "text-base",
  lg: "text-xl",
} as const;

const FULL_SIZES = {
  lg: 44,
} as const;

/**
 * VeriPay brand rendering. All assets are the owner's supplied PNGs (crops of
 * apps/web/public/logo.png, transparent background) — no plate or white box
 * behind them anywhere. The typed wordmark accompanies the mark in the
 * default lockup so the brand reads crisply at UI sizes on the dark bench.
 *
 * Unoptimized next/image per the static-export config (next.config.ts).
 * Accessibility: the image is decorative; the link (or the sr-only span) is
 * named "VeriPay".
 */
export function AppLogo({
  size = "md",
  variant = "lockup",
  href = "/",
  className,
}: AppLogoProps) {
  const classes = cn("inline-flex items-center", className);

  if (variant === "full") {
    const height = FULL_SIZES[size as keyof typeof FULL_SIZES] ?? FULL_SIZES.lg;
    const content = (
      <Image
        src="/logo.png"
        alt=""
        width={Math.round(height * (1217 / 372))}
        height={height}
        priority
        className="object-contain"
      />
    );
    if (href === false) {
      return (
        <span className={classes}>
          {content}
          <span className="sr-only">VeriPay</span>
        </span>
      );
    }
    return (
      <Link href={href} aria-label="VeriPay" className={cn(classes, focusRing(href))}>
        {content}
      </Link>
    );
  }

  if (variant === "mark") {
    const box = MARK_SIZES[size];
    const content = (
      <Image
        src="/logo-mark.png"
        alt=""
        width={Math.round(box * (380 / 372))}
        height={box}
        priority
        className="object-contain"
      />
    );
    if (href === false) {
      return (
        <span className={classes}>
          {content}
          <span className="sr-only">VeriPay</span>
        </span>
      );
    }
    return (
      <Link href={href} aria-label="VeriPay" className={cn(classes, focusRing(href))}>
        {content}
      </Link>
    );
  }

  // Default: mark + typed wordmark.
  const box = MARK_SIZES[size];
  const lockupClasses = cn("inline-flex items-center gap-2", className);
  const content = (
    <>
      <Image
        src="/logo-mark.png"
        alt=""
        width={Math.round(box * (380 / 372))}
        height={box}
        priority
        className="object-contain"
      />
      <span
        className={cn(
          "font-semibold tracking-tight text-foreground",
          WORDMARK_SIZES[size]
        )}
      >
        VeriPay
      </span>
    </>
  );
  if (href === false) {
    return (
      <span className={lockupClasses}>
        {content}
        <span className="sr-only">VeriPay</span>
      </span>
    );
  }
  return (
    <Link href={href} aria-label="VeriPay" className={cn(lockupClasses, focusRing(href))}>
      {content}
    </Link>
  );
}

function focusRing(href: string | false): string {
  return href === false
    ? ""
    : "rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";
}
