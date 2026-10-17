"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, Users } from "lucide-react";

import { FormDialog } from "@/components/form-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMe } from "@/hooks/use-session";
import { createContact, listContacts } from "@/lib/api";

import { fieldError, mutationMessage } from "./screen-helpers";

export interface ContactsPanelProps {
  vendorId: string;
}

/**
 * Authorized vendor contacts. These are the people a verifier would call back
 * during independent bank-account verification (R5) — the panel copy says so,
 * because that is what makes the contacts operationally meaningful.
 */
export function ContactsPanel({ vendorId }: ContactsPanelProps) {
  const me = useMe();
  const role = me.data?.user.role;
  const canContribute = role === "org_admin" || role === "finance_officer" || role === "reviewer";

  const contactsQuery = useQuery({
    queryKey: ["contacts", vendorId],
    queryFn: async () => (await listContacts(vendorId)).items,
  });
  const contacts = contactsQuery.data ?? [];

  const [createOpen, setCreateOpen] = useState(false);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            <Users className="h-4 w-4 text-muted-foreground" />
            Authorized contacts
          </span>
          {canContribute ? (
            <Button variant="outline" size="sm" onClick={() => setCreateOpen(true)}>
              <Plus />
              Add contact…
            </Button>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {contactsQuery.isError ? (
          <ErrorState
            error={contactsQuery.error}
            title="Could not load contacts"
            onRetry={() => void contactsQuery.refetch()}
          />
        ) : contactsQuery.isPending ? (
          <div className="h-16 animate-pulse rounded bg-muted" role="status" aria-label="Loading contacts" />
        ) : contacts.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No authorized contacts on file"
            description="Add the people authorized to speak for this vendor — bank-account verification callbacks go to these contacts, which is what makes the verification independent (R5)."
          />
        ) : (
          <ul className="space-y-3">
            {contacts.map((contact) => (
              <li key={contact.id} className="rounded-md border p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      {contact.full_name}
                      {contact.is_primary ? (
                        <span className="ml-2 rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                          Primary
                        </span>
                      ) : null}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {contact.role_title ?? "Role not recorded"}
                    </p>
                    <p className="mt-0.5 text-sm">
                      <a href={`mailto:${contact.email}`} className="text-primary hover:underline">
                        {contact.email}
                      </a>
                      {contact.phone ? <span className="text-muted-foreground"> · {contact.phone}</span> : null}
                    </p>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}

        <CreateContactDialog vendorId={vendorId} open={createOpen} onClose={() => setCreateOpen(false)} />
      </CardContent>
    </Card>
  );
}

function CreateContactDialog({
  vendorId,
  open,
  onClose,
}: {
  vendorId: string;
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [fullName, setFullName] = useState("");
  const [roleTitle, setRoleTitle] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [isPrimary, setIsPrimary] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createContact(vendorId, {
        full_name: fullName.trim(),
        email: email.trim(),
        role_title: roleTitle.trim() ? roleTitle.trim() : null,
        phone: phone.trim() ? phone.trim() : null,
        is_primary: isPrimary,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["contacts", vendorId] });
      close();
    },
  });

  const submit = () => {
    setLocalError(null);
    if (fullName.trim().length === 0) {
      setLocalError("The contact's name is required.");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setLocalError("Enter a valid email address.");
      return;
    }
    mutation.mutate();
  };

  const close = () => {
    mutation.reset();
    setLocalError(null);
    setFullName("");
    setRoleTitle("");
    setEmail("");
    setPhone("");
    setIsPrimary(false);
    onClose();
  };

  return (
    <FormDialog
      open={open}
      title="Add authorized contact"
      description="A person authorized to represent this vendor. Verification callbacks (R5) should go to known contacts like these."
      confirmLabel="Add contact"
      busy={mutation.isPending}
      onConfirm={submit}
      onCancel={close}
    >
      <div className="space-y-1.5">
        <Label htmlFor="contact-name">Full name *</Label>
        <Input id="contact-name" value={fullName} onChange={(event) => setFullName(event.target.value)} autoComplete="off" />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="contact-role">Role / title</Label>
        <Input id="contact-role" value={roleTitle} onChange={(event) => setRoleTitle(event.target.value)} autoComplete="off" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="contact-email">Email *</Label>
          <Input
            id="contact-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="off"
          />
          {fieldError(mutation.error, "email") ? (
            <p className="text-xs text-destructive">{fieldError(mutation.error, "email")}</p>
          ) : null}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="contact-phone">Phone</Label>
          <Input id="contact-phone" value={phone} onChange={(event) => setPhone(event.target.value)} autoComplete="off" />
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={isPrimary}
          onChange={(event) => setIsPrimary(event.target.checked)}
          className="h-4 w-4 rounded border-input"
        />
        Primary contact
      </label>
      {localError ? <p className="text-sm text-destructive">{localError}</p> : null}
      {mutation.isError && !fieldError(mutation.error, "email") ? (
        <p className="text-sm text-destructive">
          {mutationMessage(mutation.error, "The contact could not be added.")}
        </p>
      ) : null}
      {mutation.isSuccess ? (
        <p className="flex items-center gap-1.5 text-sm text-success-foreground">
          <Check className="h-4 w-4" />
          Contact added.
        </p>
      ) : null}
    </FormDialog>
  );
}
