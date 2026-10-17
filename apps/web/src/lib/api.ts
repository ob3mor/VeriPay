/**
 * Typed fetch wrapper for the VeriPay REST API (docs/API.md).
 *
 * Design rules for the static export:
 * - The base URL comes from NEXT_PUBLIC_API_BASE_URL and is NOT required at
 *   build time: when unset it falls back to http://localhost:8000, so a pure
 *   static preview always builds and renders.
 * - docs/API.md §1: every v1 endpoint lives under /api/v1. Both common base
 *   forms — with or without the /api/v1 suffix (the repo-root .env.example
 *   uses the suffixed form) — are normalized here, never double-appended.
 *   Callers pass endpoint paths only, e.g. "/auth/me".
 * - Errors: every non-2xx response uses the versioned envelope (docs/API.md
 *   §2) and is parsed into ApiError; `message` is safe to render. Fetch
 *   rejections (API unreachable / offline) become ApiNetworkError. UI code
 *   must branch on these instead of crashing — the static pages render even
 *   with no backend running.
 */
import type {
  ApiErrorBody,
  ApiErrorResponse,
  LogoutResponse,
  MeResponse,
  RefreshResponse,
  RegisterRequest,
  RegisterResponse,
  TokenResponse,
} from "@veripay/api-contracts";
import { clearAccessToken, getAccessToken, getCsrfToken, setAccessToken as setAccessTokenInternal } from "./auth";

/** Used when NEXT_PUBLIC_API_BASE_URL is not set at build time. */
export const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** Normalized API root (origin + /api/v1), for display in offline hints. */
export function getApiRoot(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
  const base = raw.replace(/\/+$/, "");
  return /\/api\/v1$/i.test(base) ? base : `${base}/api/v1`;
}

/** Non-2xx parsed from the docs/API.md §2 envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorBody["code"];
  readonly details?: ApiErrorBody["details"];
  readonly requestId?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
    this.requestId = body.request_id;
  }

  /** field → first message, from `validation_error` details (docs/API.md §2). */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const detail of this.details ?? []) {
      if (detail.field) out[detail.field] ??= detail.message;
    }
    return out;
  }
}

/** fetch() itself rejected — the API is unreachable (offline / wrong port). */
export class ApiNetworkError extends Error {
  constructor(options?: { cause?: unknown }) {
    super("Could not reach the VeriPay API.", options ? { cause: options.cause } : undefined);
    this.name = "ApiNetworkError";
  }
}

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function performFetch<T>(path: string, init?: RequestInit): Promise<Response> {
  const url = `${getApiRoot()}${path.startsWith("/") ? path : `/${path}`}`;

  const headers = new Headers(init?.headers);
  const token = getAccessToken();
  // Never clobber an explicitly provided Authorization header.
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  // CSRF double-submit: mutating requests authenticated by the session cookie
  // must echo the readable csrf cookie (Bearer requests are exempt — the
  // backend enforces the rule, the client just always complies).
  const method = (init?.method ?? "GET").toUpperCase();
  if (MUTATING_METHODS.has(method) && !headers.has("X-CSRF-Token")) {
    const csrf = getCsrfToken();
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  try {
    // credentials: the httpOnly session cookie IS the durable session — it
    // must travel on every call, same-origin locally and via the SWA proxy.
    return await fetch(url, { ...init, headers, credentials: "include" });
  } catch (cause) {
    // fetch only rejects on network-level failures — the API is unreachable.
    throw new ApiNetworkError({ cause });
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let parsed: unknown;
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined; // HTML error page / proxy noise — handled below
    }
  }

  if (!response.ok) {
    const envelope = parsed as ApiErrorResponse | undefined;
    const body =
      envelope && typeof envelope === "object" && envelope.error && typeof envelope.error === "object"
        ? envelope.error
        : undefined;
    if (body && typeof body.code === "string" && typeof body.message === "string") {
      throw new ApiError(response.status, body);
    }
    // Non-enveloped failure (gateway page, empty body…). Keep the envelope
    // contract: message stays user-safe; body snippets land in details.
    throw new ApiError(response.status, {
      code: "internal",
      message: `The API returned an unexpected response (HTTP ${response.status}).`,
      request_id: "",
      details: text ? [{ message: `Response body: ${text.slice(0, 200)}` }] : undefined,
    });
  }

  // A 2xx with an empty/non-JSON body would otherwise resolve `undefined`
  // typed as T — every caller expects a JSON contract body, so fail loudly.
  if (parsed === undefined) {
    throw new ApiError(response.status, {
      code: "internal",
      message: "The API returned a 2xx response with an empty or non-JSON body.",
      request_id: "",
    });
  }
  return parsed as T;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await performFetch<T>(path, init);
  if (response.status === 401 && getAccessToken() && !path.startsWith("/auth/")) {
    // The in-memory Bearer token expired. One transparent refresh attempt;
    // on success the original request is retried with the fresh token.
    try {
      const refreshed = await parseResponse<RefreshResponse>(
        await performFetch("/auth/refresh", { method: "POST" })
      );
      setAccessTokenInternal(refreshed.access_token);
      const retry = await performFetch<T>(path, init);
      return await parseResponse<T>(retry);
    } catch {
      clearAccessToken();
      throw await parseResponse<T>(response);
    }
  }
  return await parseResponse<T>(response);
}

// ---------------------------------------------------------------------------
// Endpoint helpers — docs/API.md §4 (Phase 1 surface)
// ---------------------------------------------------------------------------

/**
 * POST /auth/login — OAuth2 password form: `username` carries the email so
 * FastAPI's "Authorize" button works out of the box (docs/API.md §4).
 */
export async function loginRequest(email: string, password: string): Promise<TokenResponse> {
  const form = new URLSearchParams({ username: email, password });
  return apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
}

/** POST /auth/register — creates a new organization and its first user (owner). */
export async function registerRequest(input: RegisterRequest): Promise<RegisterResponse> {
  return apiFetch<RegisterResponse>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

/** GET /auth/me — requires auth; the Bearer token is attached automatically. */
export async function fetchMe(): Promise<MeResponse> {
  return apiFetch<MeResponse>("/auth/me");
}

/**
 * POST /auth/logout — requires auth; revokes the presented access token
 * server-side so a signed-out (or stolen) token is rejected even though its
 * 8-hour JWT expiry has not passed. Fire-and-forget on the client: the local
 * session must be cleared even when the API is unreachable.
 */
export async function logoutRequest(): Promise<LogoutResponse> {
  return apiFetch<LogoutResponse>("/auth/logout", { method: "POST" });
}
