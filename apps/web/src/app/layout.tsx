import type { Metadata, Viewport } from "next";
import { Public_Sans, Source_Serif_4, Spline_Sans_Mono } from "next/font/google";

import { QueryProvider } from "@/components/query-provider";

import "./globals.css";

/*
 * Type voices of the "examiner's bench" world, self-hosted at build time by
 * next/font (no runtime fetch — static-export safe):
 *   Public Sans     — UI, body, labels (civic, audit-grade sans)
 *   Source Serif 4  — titles/page headers (charter authority)
 *   Spline Sans Mono — IDs, amounts, audit actions (measurement voice)
 */
const publicSans = Public_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const splineMono = Spline_Sans_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "VeriPay — AI-powered invoice & payment fraud prevention",
  description:
    "VeriPay cross-checks every invoice against your vendors, purchase orders and trusted bank accounts, and routes inconsistencies to human review. It never authorizes payments automatically and never declares an invoice genuine.",
  icons: {
    icon: "/logo.png",
    apple: "/logo.png",
  },
};

export const viewport: Viewport = {
  themeColor: "#091320",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      {/*
        QueryProvider wraps the whole tree so every page can use TanStack
        Query hooks. Font variables land on <body> so Tailwind's font-sans /
        font-display / font-mono utilities resolve everywhere.
      */}
      <body
        className={`${publicSans.variable} ${sourceSerif.variable} ${splineMono.variable} min-h-screen bg-background font-sans text-foreground antialiased`}
      >
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
