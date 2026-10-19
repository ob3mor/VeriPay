"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FormAlert } from "@/components/form-alert";
import { loginRequest } from "@/lib/api";
import { setAccessToken } from "@/lib/auth";

/**
 * Sign-in — controlled form calling the REAL API (POST /api/v1/auth/login,
 * OAuth2 password form per docs/API.md §4). On success the server sets the
 * httpOnly session cookie (the durable session) and returns a short-lived
 * Bearer token that is kept IN MEMORY ONLY (src/lib/auth.ts — never
 * localStorage); the user is redirected to /dashboard.
 *
 * Failures render through <FormAlert> (src/components/form-alert.tsx), which
 * gives rate-limited attempts (429 `rate_limited` — per-IP throttle plus
 * per-IP+email lockout, apps/api/app/core/ratelimit.py) their own amber
 * "wait it out" treatment, keeps the no-enumeration credential message, and
 * degrades to an offline hint — the page never crashes when the backend is.
 */
export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const { access_token } = await loginRequest(email.trim(), password);
      setAccessToken(access_token);
      router.replace("/dashboard");
    } catch (err) {
      // Classification + rendering live in FormAlert. The credential-error
      // message is identical for unknown email and wrong password (no
      // account enumeration) and is safe to display — docs/API.md §2/§4.
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-display text-xl font-semibold">Welcome back</CardTitle>
        <CardDescription>Sign in to your VeriPay workspace.</CardDescription>
      </CardHeader>

      <form onSubmit={handleSubmit}>
        <CardContent className="space-y-4">
          {error ? <FormAlert error={error} fallbackTitle="Sign-in failed" /> : null}

          <div className="space-y-2">
            <Label htmlFor="email">Work email</Label>
            <Input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              placeholder="dana@acme.example"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              autoFocus
              disabled={submitting}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              disabled={submitting}
            />
          </div>
        </CardContent>

        <CardFooter className="flex flex-col gap-4 pt-6">
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? <LoaderCircle className="animate-spin" /> : null}
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
          <p className="text-sm text-muted-foreground">
            New to VeriPay?{" "}
            <Link
              href="/register"
              className="font-medium text-primary underline-offset-4 hover:text-accent hover:underline"
            >
              Create an account
            </Link>
          </p>
        </CardFooter>
      </form>
    </Card>
  );
}
