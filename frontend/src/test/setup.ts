import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { setCsrfToken } from "../api/client";

// Lazy routes and the debounced plan request need more than the 1 s default on a busy CI box.
configure({ asyncUtilTimeout: 4000 });

afterEach(() => {
  cleanup();
  setCsrfToken(null); // module state must not leak between tests
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.cookie.split(";").forEach((c) => {
    const name = c.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  });
  localStorage.clear();
});
