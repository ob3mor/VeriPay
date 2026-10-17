"use client";

import { useCallback, useEffect, useId, useRef } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface FormDialogProps {
  /** Render nothing when closed; the <dialog> opens via showModal(). */
  open: boolean;
  title: string;
  /** Body text under the title — state what the action does and does NOT do. */
  description?: React.ReactNode;
  /** Form fields. Validation and submission stay with the parent. */
  children?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Destructive confirmations render the red confirm button (default true). */
  destructive?: boolean;
  /** Disables both buttons while the parent is submitting. */
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Accessible form dialog, dependency-free (no Radix in this scaffold).
 *
 * Built on the native <dialog> element (same conventions as
 * confirm-dialog.tsx): showModal() provides focus trapping, Escape handling
 * (routed to onCancel) and an inert background; initial focus lands on the
 * CANCEL button so a careless Enter cannot confirm a destructive action.
 * Unlike ConfirmDialog, the confirm button submits no form — the parent owns
 * the fields and decides what onConfirm does (validate, call the API, close).
 */
export function FormDialog({
  open,
  title,
  description,
  children,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  busy = false,
  onConfirm,
  onCancel,
}: FormDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  // useId (not Math.random) — stable across SSR/prerender and hydration.
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  // Native Escape triggers the `cancel` event before closing — route it to
  // the controlled onCancel so parent state stays the source of truth.
  const handleCancel = useCallback(
    (event: React.SyntheticEvent<HTMLDialogElement, Event>) => {
      event.preventDefault();
      if (!busy) onCancel();
    },
    [busy, onCancel]
  );

  // Focus the cancel button whenever the dialog opens.
  useEffect(() => {
    if (open) {
      const id = window.setTimeout(() => cancelRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  // While open, the page behind the dialog must not scroll.
  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      className="w-[min(34rem,calc(100vw-2rem))] rounded-lg border border-border bg-card p-6 text-card-foreground shadow-lg"
    >
      <h2 id={titleId} className="text-lg font-semibold">
        {title}
      </h2>
      {description && (
        <div id={descriptionId} className="mt-2 text-sm text-muted-foreground">
          {description}
        </div>
      )}
      {children && <div className="mt-4 space-y-4">{children}</div>}
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button ref={cancelRef} variant="outline" onClick={onCancel} disabled={busy}>
          {cancelLabel}
        </Button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className={cn(
            buttonVariants({ variant: destructive ? "destructive" : "default" }),
            "inline-flex h-10 items-center justify-center gap-2 whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium disabled:pointer-events-none disabled:opacity-50"
          )}
        >
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
