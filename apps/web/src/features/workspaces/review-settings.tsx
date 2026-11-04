"use client";

import { useState, useTransition } from "react";
import type { ReviewSettings } from "@/data/types";
import { saveReviewSettings } from "@/features/kanban/card-actions";
import { StagesEditor } from "@/features/kanban/card-review";
import { Button } from "@/shared/ui/button";
import { Field, Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { PanelSection } from "@/shared/ui/panel";

/** Workspace settings → Review: the stages every card goes through (a card may set
 * its own on its Review tab), how many rounds of changes before a card comes to
 * the owner, and whether cards with children need an accepted plan first. */
export function ReviewSettingsCard({
  workspaceId,
  settings,
}: {
  workspaceId: string;
  settings: ReviewSettings | null;
}) {
  const [stages, setStages] = useState<string[]>(settings?.stages ?? []);
  const [cap, setCap] = useState(String(settings?.cap ?? 3));
  const [planFirst, setPlanFirst] = useState(settings?.planFirst ?? false);
  const [planReviewer, setPlanReviewer] = useState(
    settings?.planReviewer ?? "owner",
  );
  const [busy, start] = useTransition();
  const [status, setStatus] = useState<{
    error: string | null;
    saved?: boolean;
  }>({
    error: null,
  });
  if (settings === null)
    return (
      <p className="text-sm text-ink-2">
        The review settings can&apos;t be read right now.
      </p>
    );
  const members = settings.members ?? [];
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <p className="text-sm text-ink-2">
        When a member finishes a card, it goes through these reviews in order:
        each reviewer approves (the next one takes it) or asks for changes (it
        goes back to the member). A reviewer who is the member itself is
        skipped. A stage that is yours waits in your Inbox.
      </p>
      <PanelSection
        aria-labelledby="review-stages-title"
        className="flex flex-col gap-4 p-5"
      >
        <h2
          id="review-stages-title"
          className="font-display text-base font-semibold"
        >
          Review stages
        </h2>
        <StagesEditor
          stages={stages}
          members={members}
          onChange={setStages}
          disabled={busy}
        />
        <Field
          label="Rounds of changes before a card comes to you"
          hint="After this many requests for changes, the card stops and waits for you."
        >
          <Input
            type="number"
            min={1}
            max={20}
            value={cap}
            disabled={busy}
            className="w-24"
            onChange={(e) => {
              setCap(e.currentTarget.value);
            }}
          />
        </Field>
      </PanelSection>
      <PanelSection
        aria-labelledby="review-plan-title"
        className="flex flex-col gap-4 p-5"
      >
        <h2
          id="review-plan-title"
          className="font-display text-base font-semibold"
        >
          Plan first
        </h2>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={planFirst}
            disabled={busy}
            onChange={(e) => {
              setPlanFirst(e.currentTarget.checked);
            }}
          />
          Big cards (cards with children) need an accepted plan before the work
          starts
        </label>
        <Field label="Who accepts plans">
          <Select
            value={planReviewer}
            disabled={busy}
            onChange={(e) => {
              setPlanReviewer(e.currentTarget.value);
            }}
          >
            <option value="owner">You (the owner)</option>
            <option value="lead">The member&apos;s lead</option>
            <option value="cofounder">The Co-Founder</option>
            {members
              .filter((m) => m.name !== "cofounder")
              .map((m) => (
                <option key={m.name} value={m.name}>
                  {m.title}
                </option>
              ))}
          </Select>
        </Field>
      </PanelSection>
      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => {
            start(async () => {
              setStatus(
                await saveReviewSettings(workspaceId, {
                  stages,
                  cap: Number(cap) || 3,
                  planFirst,
                  planReviewer,
                }),
              );
            });
          }}
        >
          Save
        </Button>
        <FormStatus error={status.error} saved={status.saved} />
      </div>
    </div>
  );
}
