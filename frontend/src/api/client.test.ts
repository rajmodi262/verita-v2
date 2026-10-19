import { z } from "zod";

import { json, mockApi, problem } from "../test/utils";

import { ApiError, CSRF_HEADER, currentCsrfToken, request, setCsrfToken } from "./client";

const schema = z.object({ ok: z.boolean() });

afterEach(() => {
  setCsrfToken(null);
});

it("returns the parsed body on success", async () => {
  mockApi({ "GET /thing": () => json({ ok: true }) });
  await expect(request("/thing", { schema })).resolves.toEqual({ ok: true });
});

it("sends the CSRF token on mutations but not on reads", async () => {
  setCsrfToken("tok-123");
  const { calls } = mockApi({
    "POST /thing": () => json({ ok: true }),
    "GET /thing": () => json({ ok: true }),
  });
  await request("/thing", { method: "POST", body: { a: 1 }, schema });
  await request("/thing", { schema });
  const post = calls[0]!.init.headers as Record<string, string>;
  const get = calls[1]!.init.headers as Record<string, string>;
  expect(post[CSRF_HEADER]).toBe("tok-123");
  expect(post["Content-Type"]).toBe("application/json");
  expect(get[CSRF_HEADER]).toBeUndefined();
  expect(calls[0]!.init.credentials).toBe("same-origin");
});

it("falls back to the CSRF cookie after a reload", () => {
  document.cookie = "verita_csrf=from-cookie; path=/";
  expect(currentCsrfToken()).toBe("from-cookie");
  setCsrfToken("in-memory");
  expect(currentCsrfToken()).toBe("in-memory");
});

it("turns problem+json into an ApiError with the server's fields", async () => {
  mockApi({
    "POST /auth/login": () =>
      problem(422, "validation-error", "Request validation failed", {
        errors: [{ loc: ["body", "password"], msg: "Field required" }],
      }),
  });
  const error = await request("/auth/login", { method: "POST", body: {}, schema }).catch(
    (e: unknown) => e,
  );
  expect(error).toBeInstanceOf(ApiError);
  const apiError = error as ApiError;
  expect(apiError.status).toBe(422);
  expect(apiError.slug).toBe("validation-error");
  expect(apiError.requestId).toBe("req-1");
  expect(apiError.fieldErrors?.[0]?.loc).toEqual(["body", "password"]);
});

it("handles error bodies that are not problem+json", async () => {
  mockApi({ "GET /thing": () => new Response("<html>bad gateway</html>", { status: 502 }) });
  await expect(request("/thing", { schema })).rejects.toMatchObject({
    status: 502,
    type: "http-error",
  });
});

it("reports a network failure as status 0", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
  );
  await expect(request("/thing", { schema })).rejects.toMatchObject({
    status: 0,
    type: "network-error",
  });
});

it("rethrows aborts untouched", async () => {
  const abort = new DOMException("aborted", "AbortError");
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(abort)),
  );
  await expect(request("/thing", { schema })).rejects.toBe(abort);
});

it("fails loudly when the response breaks the contract", async () => {
  mockApi({ "GET /thing": () => json({ ok: "yes" }) });
  await expect(request("/thing", { schema })).rejects.toMatchObject({
    type: "contract-error",
  });
});

it("accepts 204 No Content", async () => {
  mockApi({ "POST /auth/logout": () => new Response(null, { status: 204 }) });
  await expect(
    request("/auth/logout", { method: "POST", schema: z.undefined() }),
  ).resolves.toBeUndefined();
});

it("slug falls back to the whole type when it has no path", () => {
  const error = new ApiError({ status: 500, type: "plain", title: "x" });
  expect(error.slug).toBe("plain");
  expect(error.name).toBe("ApiError");
});
