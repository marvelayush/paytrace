"use client";

import { CircleAlert, Eye, EyeOff, LoaderCircle } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { safeNextPath, useCurrentUser, useLogin } from "@/lib/auth";

const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

const DEMO_ACCOUNTS = [
  { label: "Finance executive", email: "finance@paytrace.demo", note: "Full access" },
  { label: "Co-founder", email: "founder@paytrace.demo", note: "Read-only" },
];

function errorMessage(error: ApiError): string {
  if (error.status === 401) return "That email and password don't match. Check both and try again.";
  return error.message;
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  const login = useLogin();
  const currentUser = useCurrentUser();

  // Already signed in (e.g. opened /login in a second tab): go straight in.
  useEffect(() => {
    if (currentUser.data) router.replace(nextPath);
  }, [currentUser.data, nextPath, router]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (login.isPending) return;
    login.mutate(
      { email: email.trim(), password },
      { onSuccess: () => router.replace(nextPath) },
    );
  }

  function fillDemoAccount(demoEmail: string) {
    setEmail(demoEmail);
    login.reset();
    passwordRef.current?.focus();
  }

  const isBusy = login.isPending || login.isSuccess;
  const error = login.error;

  return (
    <div className="space-y-4">
      <form
        onSubmit={handleSubmit}
        className="space-y-5 rounded-xl border bg-card p-6 shadow-[0_1px_2px_rgba(16,24,40,0.04)]"
        aria-describedby={error ? "login-error" : undefined}
      >
        {error && (
          <Alert variant="destructive" id="login-error" role="alert" className="border-loss/20 bg-loss-soft">
            <CircleAlert />
            <AlertDescription className="text-loss">{errorMessage(error)}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-2">
          <Label htmlFor="email">Work email</Label>
          <Input
            id="email"
            name="email"
            type="email"
            inputMode="email"
            autoComplete="username"
            autoFocus
            required
            placeholder="you@company.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={isBusy}
            aria-invalid={error?.status === 401 || undefined}
            className="h-10"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <div className="relative">
            <Input
              ref={passwordRef}
              id="password"
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={isBusy}
              aria-invalid={error?.status === 401 || undefined}
              className="h-10 pr-10"
            />
            <button
              type="button"
              onClick={() => setShowPassword((shown) => !shown)}
              className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
            >
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
        </div>

        <Button type="submit" className="h-10 w-full" disabled={isBusy || !email || !password}>
          {isBusy ? (
            <>
              <LoaderCircle className="animate-spin" aria-hidden />
              Signing in…
            </>
          ) : (
            "Sign in"
          )}
        </Button>
      </form>

      {DEMO_MODE && (
        <section aria-labelledby="demo-heading" className="rounded-xl border border-dashed bg-card/60 p-4">
          <h2 id="demo-heading" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Demo accounts
          </h2>
          <ul className="mt-3 space-y-1">
            {DEMO_ACCOUNTS.map((account) => (
              <li key={account.email}>
                <button
                  type="button"
                  onClick={() => fillDemoAccount(account.email)}
                  disabled={isBusy}
                  className="flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left text-sm outline-none hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
                >
                  <span className="min-w-0">
                    <span className="block font-medium">{account.label}</span>
                    <span className="block truncate text-muted-foreground">{account.email}</span>
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">{account.note}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-3 px-2.5 text-xs text-muted-foreground">
            Pick an account to fill the email. Passwords are in the deployment notes.
          </p>
        </section>
      )}
    </div>
  );
}
