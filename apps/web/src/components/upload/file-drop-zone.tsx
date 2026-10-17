"use client";

import { useCallback, useRef, useState } from "react";
import { CloudUpload } from "lucide-react";

import { cn } from "@/lib/utils";

export interface FileDropZoneProps {
  /** Called with the first accepted file (multiple selection is not needed). */
  onFileSelected: (file: File) => void;
  /** Disables interaction (e.g. while an upload is in flight). */
  disabled?: boolean;
  /** Rendered under the main hint — e.g. the allowed types / size ceiling. */
  hint?: string;
  className?: string;
}

/**
 * Drag-and-drop + click-to-browse file picker.
 *
 * Implementation notes:
 * - The visible zone is a real <button>, so keyboard focus and Enter/Space
 *   activation work without extra handlers; the <input type="file"> stays
 *   visually hidden.
 * - A dragenter/dragleave counter (not a boolean) avoids the flicker caused
 *   by child elements re-firing dragleave while the pointer stays inside.
 * - Drop and change handlers only *select* the file — validation and upload
 *   live in the upload workflow, keeping this component dumb.
 */
export function FileDropZone({ onFileSelected, disabled = false, hint, className }: FileDropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [isDragOver, setIsDragOver] = useState(false);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (file) onFileSelected(file);
    },
    [onFileSelected]
  );

  return (
    <div className={className}>
      <input
        ref={inputRef}
        type="file"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
        onChange={(event) => {
          handleFiles(event.target.files);
          // Allow re-selecting the same file after a failed validation.
          event.target.value = "";
        }}
      />
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        onDragEnter={(event) => {
          event.preventDefault();
          dragDepth.current += 1;
          if (!disabled) setIsDragOver(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (dragDepth.current === 0) setIsDragOver(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          dragDepth.current = 0;
          setIsDragOver(false);
          if (!disabled) handleFiles(event.dataTransfer.files);
        }}
        aria-label="Choose a file to upload, or drop it here"
        className={cn(
          "flex w-full flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          isDragOver
            ? "border-primary bg-primary/5"
            : "border-border bg-muted/30 hover:border-primary/40 hover:bg-muted/50",
          disabled && "pointer-events-none opacity-50"
        )}
      >
        <span
          aria-hidden="true"
          className="flex h-12 w-12 items-center justify-center rounded-full bg-muted"
        >
          <CloudUpload className="h-6 w-6 text-muted-foreground" />
        </span>
        <span className="text-sm font-medium text-foreground">
          Drop the document here, or <span className="text-primary">browse</span>
        </span>
        {hint && <span className="max-w-sm text-xs text-muted-foreground">{hint}</span>}
      </button>
    </div>
  );
}
