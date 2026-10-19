"use client";

import { useCallback, useEffect, useId, useRef } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ConfirmDialogProps {
  /** Render nothing when closed; the <dialog> opens via showModal(). */
  open: boolean;
  title: string;
  /** Body text — state the consequence plainly (what will happen, what it does NOT mean). */
  description: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Destructive confirmations render the red confirm button (default true). */
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Accessible confirmation dialog, dependency-free (no Radix in this scaffold).
 *
 * Built on the native <dialog> element: showModal() gives focus trapping,
 * Escape handling (mapped to onCancel) and inert background for free.
 * Accessibility wiring is explicit: aria-labelledby → the title,
 * aria-describedby → the description; initial focus lands on the CANCEL
 * button so a careless Enter can never confirm a destructive action.
 *
 * Honest by convention: use it for irreversible/human-only actions (verifying
 * a bank account, closing a case). The description should state what the
 * action does — e.g. "records your independent verification" — never imply a
 * payment or genuineness outcome.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = true,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
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
      onCancel();
    },
    [onCancel]
  );

  // Focus the cancel button whenever the dialog opens.
  useEffect(() => {
    if (open) {
      // Wait a frame so the dialog is actually displayed before focusing.
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
      aria-describedby={descriptionId}
      className="w-[min(28rem,calc(100vw-2rem))] rounded-lg border border-border bg-card p-6 text-card-foreground shadow-plate"
    >
      <h2 id={titleId} className="font-display text-lg font-semibold">
        {title}
      </h2>
      <div id={descriptionId} className="mt-2 text-sm text-muted-foreground">
        {description}
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button ref={cancelRef} variant="outline" onClick={onCancel}>
          {cancelLabel}
        </Button>
        <button
          type="button"
          onClick={onConfirm}
          className={cn(
            buttonVariants({ variant: destructive ? "destructive" : "default" }),
            "inline-flex h-10 items-center justify-center gap-2 whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium"
          )}
        >
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
