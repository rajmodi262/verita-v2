import { QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { Providers } from "../app/providers";
import { routes } from "../app/router";

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": status >= 400 ? "application/problem+json" : "application/json" },
  });
}

export function problem(status: number, slug: string, title: string, extra = {}): Response {
  return json(
    { type: `https://verita.dev/problems/${slug}`, title, status, request_id: "req-1", ...extra },
    status,
  );
}

export type Handler = (init: RequestInit) => Response | Promise<Response>;

/** Stub fetch with "METHOD /path" → handler. Unknown routes fail the test loudly. */
export function mockApi(handlers: Record<string, Handler>) {
  const calls: { key: string; init: RequestInit }[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const key = `${init.method ?? "GET"} ${url.replace("/api/v1", "")}`;
    calls.push({ key, init });
    const handler = handlers[key];
    if (!handler) return Promise.reject(new Error(`unexpected request: ${key}`));
    return Promise.resolve(handler(init));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export const ANALYST = { id: 1, username: "priya", role: "analyst" } as const;

export function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <Providers client={client}>
      <RouterProvider router={router} />
    </Providers>,
  );
  return { ...view, router, client };
}
