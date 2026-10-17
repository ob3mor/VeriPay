/**
 * Upload client for POST /documents (multipart) with real browser progress
 * events, plus the client-side half of the backend's validation rules.
 *
 * Why XMLHttpRequest and not fetch: fetch() cannot report upload progress
 * without request streams; XHR's `progress` events on `upload` give honest
 * byte-level progress for the progress bar. Everything else mirrors
 * src/lib/api.ts conventions exactly (this file must not duplicate that
 * module's exports, only its behavior):
 * - Base URL via getApiRoot() (NEXT_PUBLIC_API_BASE_URL normalization).
 * - Auth: the in-memory Bearer token (lib/auth.ts — never web storage) and
 *   the httpOnly session cookie (withCredentials). Mutating request → the
 *   readable `veripay_csrf` cookie is echoed in X-CSRF-Token (ADR 0005).
 * - Errors: the docs/API.md §2 versioned envelope parsed into ApiError; fetch
 *   / network-level failures become ApiNetworkError; `message` is safe to
 *   render — the UI never invents a cause.
 *
 * Validation parity (apps/api/app/modules/documents/service.py):
 * - MIME allowlist + magic-byte signature pairs:
 *     application/pdf  → "%PDF-"
 *     image/png        → 89 50 4E 47 0D 0A 1A 0A
 *     image/jpeg       → FF D8 FF
 *   (a renamed .exe must not pass — the client sniffs bytes too, so users get
 *   the same rejection the server would give, before any network round-trip)
 * - Size ceiling: settings.upload_max_bytes default 10 MiB.
 */
import type { DocumentKind, ProcessedDocumentOut } from "@veripay/api-contracts";

import { ApiError, ApiNetworkError, getApiRoot } from "@/lib/api";
import { getAccessToken, getCsrfToken } from "@/lib/auth";

/** Mirrors apps/api/app/core/config.py `upload_max_bytes` (10 MiB). */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

/** Human-readable ceiling for validation messages. */
export const MAX_UPLOAD_BYTES_LABEL = "10 MB";

/** (declared MIME, magic prefix) pairs — must BOTH match, as on the server. */
const SIGNATURES: ReadonlyArray<readonly [string, string, number[]]> = [
  ["application/pdf", "PDF", [0x25, 0x50, 0x44, 0x46, 0x2d]], // "%PDF-"
  ["image/png", "PNG image", [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]],
  ["image/jpeg", "JPEG image", [0xff, 0xd8, 0xff]],
];

const ALLOWED_MIMES = new Set(SIGNATURES.map(([mime]) => mime));

const ALLOWED_EXTENSIONS = ".pdf, .png, .jpg, .jpeg";

/** Thrown when the user cancels an in-flight upload (AbortController). */
export class UploadAbortedError extends Error {
  constructor() {
    super("Upload cancelled.");
    this.name = "UploadAbortedError";
  }
}

function describeBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

export { describeBytes as formatBytes };

/**
 * Client-side validation mirroring the backend's rules so the user learns
 * about an invalid file before any bytes travel. Returns a human-readable
 * problem, or null when the file may be sent. Deliberately NOT a substitute
 * for the server checks — the API re-validates everything (this can only
 * reject earlier, never accept something the server would reject).
 */
export async function validateUploadFile(file: File): Promise<string | null> {
  if (file.size === 0) {
    return "This file is empty (0 bytes).";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `File is ${describeBytes(file.size)} — the limit is ${MAX_UPLOAD_BYTES_LABEL}.`;
  }

  const declared = file.type.toLowerCase();
  const byExtension = /\.(pdf|png|jpe?g)$/i.test(file.name);
  if (!ALLOWED_MIMES.has(declared) && !byExtension) {
    return `Unsupported file type. Allowed: PDF, PNG, JPEG (got ${
      declared || `no type reported for "${file.name}"`
    }).`;
  }

  // Magic-byte sniff of the first bytes — the same signatures the server
  // checks, so a renamed file fails here with the same message it would get
  // from the API ("content does not match its declared type").
  let header: Uint8Array;
  try {
    header = new Uint8Array(await file.slice(0, 8).arrayBuffer());
  } catch {
    return null; // cannot sniff (rare); let the server decide — no fake error
  }
  const matched = SIGNATURES.some(([, , magic]) =>
    magic.every((byte, index) => header[index] === byte)
  );
  if (!matched) {
    return "File content does not look like a PDF, PNG or JPEG (signature check failed).";
  }
  return null;
}

export interface UploadProgress {
  /** 0..100 when the browser can compute it; null while indeterminate. */
  percent: number | null;
  /** Bytes sent so far, when reported by the browser. */
  loaded?: number;
  total?: number;
}

export interface UploadWithProgressParams {
  file: File;
  kind?: DocumentKind;
  vendor_id?: string;
  onProgress?: (progress: UploadProgress) => void;
  /** AbortSignal from an AbortController — aborting rejects with UploadAbortedError. */
  signal?: AbortSignal;
}

/**
 * POST /documents with real upload progress. Resolves with the
 * ProcessedDocumentOut (processing runs inline server-side, so the returned
 * processing_status is usually already final; the upload page still polls
 * GET /documents/{id} — documents endpoints — to cover async backends).
 */
export function uploadDocumentWithProgress(
  params: UploadWithProgressParams
): Promise<ProcessedDocumentOut> {
  const { file, kind, vendor_id, onProgress, signal } = params;

  return new Promise<ProcessedDocumentOut>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${getApiRoot()}/documents`);
    xhr.withCredentials = true; // the httpOnly session cookie IS the session

    const token = getAccessToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    const csrf = getCsrfToken();
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);

    if (signal) {
      const onAbort = () => {
        xhr.abort();
      };
      signal.addEventListener("abort", onAbort, { once: true });
    }

    xhr.upload.onprogress = (event) => {
      onProgress?.({
        percent: event.lengthComputable
          ? Math.min(100, Math.round((event.loaded / event.total) * 100))
          : null,
        loaded: event.loaded,
        total: event.total,
      });
    };

    xhr.onload = () => {
      resolve(parseDocumentResponse(xhr.status, xhr.responseText));
    };
    xhr.onerror = () => {
      // Network-level failure only (DNS, refused connection, offline) —
      // HTTP error statuses go through onload instead.
      reject(new ApiNetworkError());
    };
    xhr.onabort = () => {
      reject(new UploadAbortedError());
    };
    xhr.ontimeout = () => {
      reject(new ApiNetworkError());
    };

    const form = new FormData();
    form.append("file", file, file.name);
    if (kind) form.append("kind", kind);
    if (vendor_id) form.append("vendor_id", vendor_id);
    xhr.send(form);
  });
}

/**
 * Parse a /documents response exactly like lib/api.ts parseResponse: 2xx
 * needs a JSON body; non-2xx must carry the docs/API.md §2 envelope — and
 * anything else becomes an honest "unexpected response" ApiError with the
 * body snippet in details, never a guessed cause.
 */
function parseDocumentResponse(status: number, bodyText: string): ProcessedDocumentOut {
  let parsed: unknown;
  if (bodyText.length > 0) {
    try {
      parsed = JSON.parse(bodyText);
    } catch {
      parsed = undefined;
    }
  }

  if (status < 200 || status >= 300) {
    const envelope = parsed as { error?: { code?: unknown; message?: unknown } } | undefined;
    const body = envelope?.error;
    if (body && typeof body.code === "string" && typeof body.message === "string") {
      throw new ApiError(status, body as ConstructorParameters<typeof ApiError>[1]);
    }
    throw new ApiError(status, {
      code: "internal",
      message: `The API returned an unexpected response (HTTP ${status}).`,
      request_id: "",
      details: bodyText ? [{ message: `Response body: ${bodyText.slice(0, 200)}` }] : undefined,
    });
  }

  if (parsed === undefined || typeof parsed !== "object") {
    throw new ApiError(status, {
      code: "internal",
      message: "The API returned a 2xx response with an empty or non-JSON body.",
      request_id: "",
    });
  }
  return parsed as ProcessedDocumentOut;
}
