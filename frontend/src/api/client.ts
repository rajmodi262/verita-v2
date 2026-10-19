/**
 * Typed HTTP client for the Verita API.
 *
 * - Same-origin requests to /api/v1 (Vite proxies in dev; the host proxies in production).
 * - Mutations carry the session's CSRF token in X-CSRF-Token.
 * - Errors are RFC 9457 problem+json; they surface as ApiError with the server's fields.
 * - Every response body is validated against a Zod schema, so a contract drift fails loudly
 *   instead of rendering garbage.
 */
import { z } from "zod";

export const API_PREFIX = "/api/v1";
export const CSRF_COOKIE = "verita_csrf";
export const CSRF_HEADER = "X-CSRF-Token";

const problemSchema = z.object({
  type: z.string(),
  title: z.string(),
  status: z.number(),
  detail: z.string().optional(),
  request_id: z.string().optional(),
  errors: z.array(z.object({ loc: z.array(z.string()), msg: z.string() })).optional(),
});

export type FieldError = z.infer<typeof problemSchema>["errors"];

export class ApiError extends Error {
  readonly status: number;
  readonly type: string;
  readonly detail: string | undefined;
  readonly requestId: string | undefined;
  readonly fieldErrors: FieldError;

  constructor(init: {
    status: number;
    type: string;
    title: string;
    detail?: string | undefined;
    requestId?: string | undefined;
    fieldErrors?: FieldError;
  }) {
    super(init.title);
    this.name = "ApiError";
    this.status = init.status;
    this.type = init.type;
    this.detail = init.detail;
    this.requestId = init.requestId;
    this.fieldErrors = init.fieldErrors;
  }

  /** The stable problem slug, e.g. "invalid-credentials". */
  get slug(): string {
    return this.type.split("/").pop() ?? this.type;
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

function readCookie(name: string): string | null {
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

/** In memory after login; falls back to the cookie so a page reload keeps working. */
export function currentCsrfToken(): string | null {
  return csrfToken ?? readCookie(CSRF_COOKIE);
}

type Method = "GET" | "POST" | "PUT" | "DELETE";

export interface RequestOptions<T> {
  method?: Method;
  body?: unknown;
  schema: z.ZodType<T>;
  signal?: AbortSignal | undefined;
}

export async function request<T>(path: string, options: RequestOptions<T>): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const token = currentCsrfToken();
    if (token) headers[CSRF_HEADER] = token;
  }

  let response: Response;
  try {
    response = await fetch(API_PREFIX + path, {
      method,
      headers,
      credentials: "same-origin",
      body: options.body === undefined ? null : JSON.stringify(options.body),
      signal: options.signal ?? null,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError({
      status: 0,
      type: "network-error",
      title: "Can't reach the Verita API",
      detail: "Check that the backend is running.",
    });
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return options.schema.parse(undefined);

  const parsed = options.schema.safeParse(await response.json());
  if (!parsed.success) {
    throw new ApiError({
      status: response.status,
      type: "contract-error",
      title: "Unexpected response from the server",
      detail: parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "),
    });
  }
  return parsed.data;
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const problem = problemSchema.safeParse(body);
  if (problem.success) {
    return new ApiError({
      status: response.status,
      type: problem.data.type,
      title: problem.data.title,
      detail: problem.data.detail,
      requestId: problem.data.request_id,
      fieldErrors: problem.data.errors,
    });
  }
  return new ApiError({
    status: response.status,
    type: "http-error",
    title: `Request failed (${String(response.status)})`,
  });
}
