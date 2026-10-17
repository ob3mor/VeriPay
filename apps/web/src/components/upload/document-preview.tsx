"use client";

import { useEffect, useState } from "react";
import { FileText } from "lucide-react";

import { formatBytes } from "@/components/upload/upload-client";

export interface DocumentPreviewProps {
  file: File;
  /** Fixed height class for the preview box (default h-80). */
  className?: string;
}

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || /\.pdf$/i.test(file.name);
}

function isImage(file: File): boolean {
  return file.type.startsWith("image/") || /\.(png|jpe?g)$/i.test(file.name);
}

/**
 * Local preview of the selected file BEFORE upload: images render inline,
 * PDFs in an <iframe> (every mainstream browser ships a built-in viewer; a
 * browser without one shows its own download affordance — honest fallback).
 *
 * The preview shows the local File via an object URL — it is NOT the stored
 * document; the caption says so to avoid any "already ingested" confusion.
 * Object URLs are created in an effect (never during prerender) and revoked
 * on change/unmount so the blob does not leak for the tab's lifetime.
 */
export function DocumentPreview({ file, className }: DocumentPreviewProps) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  if (!objectUrl) return null;

  const caption = `${file.name} · ${formatBytes(file.size)} — local preview, not yet stored in VeriPay`;

  if (isPdf(file)) {
    return (
      <figure className={className}>
        <iframe
          src={objectUrl}
          title={`Preview of ${file.name}`}
          className="h-80 w-full rounded-md border bg-background"
        />
        <figcaption className="mt-2 text-xs text-muted-foreground">{caption}</figcaption>
      </figure>
    );
  }

  if (isImage(file)) {
    return (
      <figure className={className}>
        {/* eslint-disable-next-line @next/next/no-img-element -- local blob URL, not a remote asset */}
        <img
          src={objectUrl}
          alt={`Preview of ${file.name}`}
          className="mx-auto max-h-80 w-auto max-w-full rounded-md border bg-background"
        />
        <figcaption className="mt-2 text-xs text-muted-foreground">{caption}</figcaption>
      </figure>
    );
  }

  // Validation rejects anything else before this renders; kept for safety.
  return (
    <figure className={className}>
      <div className="flex items-center gap-3 rounded-md border bg-muted/30 px-4 py-6">
        <FileText aria-hidden="true" className="h-8 w-8 text-muted-foreground" />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
          <p className="text-xs text-muted-foreground">{formatBytes(file.size)}</p>
        </div>
      </div>
      <figcaption className="mt-2 text-xs text-muted-foreground">{caption}</figcaption>
    </figure>
  );
}
