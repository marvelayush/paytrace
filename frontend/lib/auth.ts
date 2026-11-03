"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";

export type Role = "finance_exec" | "cofounder";

export type User = {
  id: number;
  email: string;
  name: string;
  role: Role;
};

export const ROLE_LABELS: Record<Role, string> = {
  finance_exec: "Finance executive",
  cofounder: "Co-founder",
};

const ME_KEY = ["auth", "me"] as const;

/** The signed-in user. A 401 means "not signed in" and is not retried. */
export function useCurrentUser() {
  return useQuery<User, ApiError>({
    queryKey: ME_KEY,
    queryFn: () => apiFetch<User>("/auth/me"),
    staleTime: 5 * 60_000,
  });
}

/**
 * Co-founders are read-only (A2). The UI hides controls they cannot use;
 * the API enforces the same rule independently.
 */
export function canEdit(user: User | undefined): boolean {
  return user?.role === "finance_exec";
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation<User, ApiError, { email: string; password: string }>({
    mutationFn: (credentials) =>
      apiFetch<User>("/auth/login", { method: "POST", body: JSON.stringify(credentials) }),
    onSuccess: (user) => queryClient.setQueryData(ME_KEY, user),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError>({
    mutationFn: () => apiFetch<void>("/auth/logout", { method: "POST" }),
    onSettled: () => queryClient.clear(),
  });
}

/** Only allow same-site relative paths as a post-login destination (no open redirects). */
export function safeNextPath(next: string | null): string {
  if (next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")) return next;
  return "/";
}
