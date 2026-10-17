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
import { ApiError, registerRequest } from "@/lib/api";
import { setAccessToken } from "@/lib/auth";

/**
 * Registration — controlled form calling the REAL API (POST /api/v1/auth/register,
 * docs/API.md §4). Creates a NEW organization and its first user (role
 * org_admin, apps/api/app/modules/auth/service.py); joining an existing org
 * arrives later with invites. On 201 the server sets the httpOnly session
 * cookie and the short-lived Bearer token is kept in memory only; the user
 * lands on /dashboard. Server validation (422 details) is mapped to per-field
 * errors; everything else renders through <FormAlert> — including the amber
 * rate-limit treatment for 429 `rate_limited` (registration is throttled per
 * IP, apps/api/app/api/v1/routes/auth.py). Never a crash.
 */
export default function RegisterPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<unknown>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    setFormError(null);
    setFieldErrors({});
    if (password !== confirmPassword) {
      setFieldErrors({ confirm_password: "Passwords do not match." });
      return;
    }

    setSubmitting(true);
    try {
      const response = await registerRequest({
        email: email.trim(),
        password,
        full_name: fullName.trim(),
        organization_name: organizationName.trim(),
      });
      setAccessToken(response.access_token);
      router.replace("/dashboard");
    } catch (err) {
      // 409 conflict: "email already registered". 422: per-field details.
      // 429 rate_limited: FormAlert renders the amber wait-it-out alert.
      setFormError(err);
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors);
    } finally {
      setSubmitting(false);
    }
  }

  function fieldError(field: string): string | undefined {
    return fieldErrors[field];
  }

  /**
   * A11y contract for per-field errors: every input points at its error/hint
   * paragraph via aria-describedby and carries aria-invalid, so screen readers
   * announce which field failed and why (the paragraphs alone are invisible
   * to them). The static password hint doubles as the describedby target when
   * the field has no error.
   */
  function describedBy(field: string, hintId?: string): string | undefined {
    const ids: string[] = [];
    if (fieldError(field)) ids.push(`${field}-error`);
    if (hintId) ids.push(hintId);
    return ids.length > 0 ? ids.join(" ") : undefined;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">Create your workspace</CardTitle>
        <CardDescription>
          Registers a new organization — you will be its first user (Organization Admin). Joining an
          existing organization arrives later with invites.
        </CardDescription>
      </CardHeader>

      <form onSubmit={handleSubmit}>
        <CardContent className="space-y-4">
          {formError ? <FormAlert error={formError} fallbackTitle="Registration failed" /> : null}

          <div className="space-y-2">
            <Label htmlFor="full_name">Full name</Label>
            <Input
              id="full_name"
              name="full_name"
              autoComplete="name"
              placeholder="Dana Reyes"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              required
              disabled={submitting}
              aria-invalid={fieldError("full_name") ? true : undefined}
              aria-describedby={describedBy("full_name")}
            />
            {fieldError("full_name") ? (
              <p id="full_name-error" className="text-sm text-destructive">
                {fieldError("full_name")}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="organization_name">Organization name</Label>
            <Input
              id="organization_name"
              name="organization_name"
              autoComplete="organization"
              placeholder="Acme GmbH"
              value={organizationName}
              onChange={(event) => setOrganizationName(event.target.value)}
              required
              disabled={submitting}
              aria-invalid={fieldError("organization_name") ? true : undefined}
              aria-describedby={describedBy("organization_name")}
            />
            {fieldError("organization_name") ? (
              <p id="organization_name-error" className="text-sm text-destructive">
                {fieldError("organization_name")}
              </p>
            ) : null}
          </div>

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
              disabled={submitting}
              aria-invalid={fieldError("email") ? true : undefined}
              aria-describedby={describedBy("email")}
            />
            {fieldError("email") ? (
              <p id="email-error" className="text-sm text-destructive">
                {fieldError("email")}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={8}
              disabled={submitting}
              aria-invalid={fieldError("password") ? true : undefined}
              aria-describedby={describedBy("password", "password-hint")}
            />
            {fieldError("password") ? (
              <p id="password-error" className="text-sm text-destructive">
                {fieldError("password")}
              </p>
            ) : (
              <p id="password-hint" className="text-xs text-muted-foreground">
                At least 8 characters.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="confirm_password">Confirm password</Label>
            <Input
              id="confirm_password"
              name="confirm_password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
              disabled={submitting}
              aria-invalid={fieldError("confirm_password") ? true : undefined}
              aria-describedby={describedBy("confirm_password")}
            />
            {fieldError("confirm_password") ? (
              <p id="confirm_password-error" className="text-sm text-destructive">
                {fieldError("confirm_password")}
              </p>
            ) : null}
          </div>
        </CardContent>

        <CardFooter className="flex flex-col gap-4 pt-6">
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? <LoaderCircle className="animate-spin" /> : null}
            {submitting ? "Creating workspace…" : "Create workspace"}
          </Button>
          <p className="text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="font-medium text-foreground underline-offset-4 hover:underline">
              Sign in
            </Link>
          </p>
        </CardFooter>
      </form>
    </Card>
  );
}
