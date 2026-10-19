import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import { ThemeProvider } from "../lib/theme";

function isClientError(error: unknown): boolean {
  return error instanceof ApiError && error.status >= 400 && error.status < 500;
}

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Client errors (4xx) won't fix themselves; retry only network and server failures.
        retry: (failureCount, error) => failureCount < 2 && !isClientError(error),
        refetchOnWindowFocus: false,
      },
    },
  });
}

export function Providers({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? makeQueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>{children}</ThemeProvider>
    </QueryClientProvider>
  );
}
