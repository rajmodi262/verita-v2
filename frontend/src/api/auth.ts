import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { ApiError, request, setCsrfToken } from "./client";

export const roleSchema = z.enum(["analyst", "mlro", "validator", "reviewer"]);
export type Role = z.infer<typeof roleSchema>;

export const userSchema = z.object({
  id: z.number(),
  username: z.string(),
  role: roleSchema,
});
export type User = z.infer<typeof userSchema>;

const loginResponseSchema = z.object({
  user: userSchema,
  csrf_token: z.string(),
  expires_at: z.string(),
});

export const ROLE_LABELS: Record<Role, string> = {
  analyst: "Analyst",
  mlro: "MLRO",
  validator: "Model validator",
  reviewer: "Reviewer",
};

export const meQueryKey = ["me"] as const;

/** The signed-in user, or null when there is no session. Other errors propagate. */
export async function fetchMe(signal?: AbortSignal): Promise<User | null> {
  try {
    return await request("/me", { schema: userSchema, signal });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function useMe() {
  return useQuery({
    queryKey: meQueryKey,
    queryFn: ({ signal }) => fetchMe(signal),
    retry: false,
    staleTime: 60_000,
  });
}

export interface Credentials {
  username: string;
  password: string;
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (credentials: Credentials) =>
      request("/auth/login", { method: "POST", body: credentials, schema: loginResponseSchema }),
    onSuccess: (data) => {
      setCsrfToken(data.csrf_token);
      client.setQueryData(meQueryKey, data.user);
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request("/auth/logout", { method: "POST", schema: z.undefined() }),
    onSettled: () => {
      setCsrfToken(null);
      client.setQueryData(meQueryKey, null);
      void client.invalidateQueries();
    },
  });
}
