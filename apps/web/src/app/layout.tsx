import type { Metadata } from "next";

import { QueryProvider } from "@/components/query-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: "VeriPay — AI-powered invoice & payment fraud prevention",
  description:
    "VeriPay cross-checks every invoice against your vendors, purchase orders and trusted bank accounts, and routes inconsistencies to human review. It never authorizes payments automatically and never declares an invoice genuine.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      {/*
        System font stack (no network fonts — the static export must build
        without fetching anything). QueryProvider wraps the whole tree so every
        page can use TanStack Query hooks.
      */}
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
