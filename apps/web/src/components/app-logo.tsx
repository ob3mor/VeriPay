import Image from "next/image";
import Link from "next/link";

import { cn } from "@/lib/utils";

export interface AppLogoProps {
  /** Overall height in px; the mark is square, the wordmark scales with it. */
  size?: "sm" | "md" | "lg";
  /** Render as a link to the landing page (headers). Pass false inside pages that are already the target. */
  href?: string | false;
  /** Hide the "VeriPay" wordmark (icon-only, e.g. tight mobile slots). */
  wordmark?: boolean;
  className?: string;
}

const SIZES = {
  sm: { box: 28, text: "text-sm" },
  md: { box: 34, text: "text-base" },
  lg: { box: 40, text: "text-lg" },
} as const;

/**
 * VeriPay brand lockup: the owner's logo (apps/web/public/logo.png, copied
 * byte-exact from the owner's supplied file) + wordmark. Unoptimized
 * next/image per the static-export config (next.config.ts).
 *
 * Accessibility: the image is decorative; the wordmark (or aria-label when
 * wordmark is hidden) names the link "VeriPay".
 */
export function AppLogo({ size = "md", href = "/", wordmark = true, className }: AppLogoProps) {
  const { box, text } = SIZES[size];

  const content = (
    <>
      <Image
        src="/logo.png"
        alt=""
        width={box}
        height={box}
        priority
        className="rounded-md object-contain"
      />
      {wordmark && <span className={cn("font-semibold tracking-tight text-foreground", text)}>VeriPay</span>}
      {!wordmark && <span className="sr-only">VeriPay</span>}
    </>
  );

  const classes = cn("inline-flex items-center gap-2.5", className);

  if (href === false) {
    return <span className={classes}>{content}</span>;
  }
  return (
    <Link href={href} aria-label="VeriPay" className={cn(classes, "rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2")}>
      {content}
    </Link>
  );
}
