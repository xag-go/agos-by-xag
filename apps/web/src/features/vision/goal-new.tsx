"use client";

import { useState } from "react";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { PlusIcon } from "@/shared/ui/icons";
import { addGoal, addProject, addResult } from "./actions";
import { useRun } from "./use-run";
import { escapeTo } from "./goal-keys";
import { type Kind, type Member } from "./goal-model";
import { sectionLabel, small } from "./goal-styles";
import { FormActions, KindFields } from "./goal-editor";
import { OwnerSelect } from "./goal-chips";

export function NewResult({
  workspaceId,
  goalId,
  className = "bg-sunken/60",
  onClose,
}: {
  workspaceId: string;
  goalId: number;
  className?: string;
  onClose: () => void;
}) {
  const [busy, error, run] = useRun();
  const [title, setTitle] = useState("");
  const [start, setStart] = useState("0");
  const [target, setTarget] = useState("");
  const [unit, setUnit] = useState("");
  const [dueOn, setDueOn] = useState("");
  return (
    <form
      aria-label="New key result"
      className={cn(
        "flex flex-wrap items-center gap-1.5 rounded-xl px-3 py-2.5",
        className,
      )}
      onKeyDown={escapeTo(onClose)}
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const r = await addResult(workspaceId, goalId, {
            title,
            start: Number(start) || 0,
            current: Number(start) || 0,
            target: target.trim() ? Number(target) : null,
            unit,
            dueOn,
          });
          if (!r.error) onClose();
          return r;
        });
      }}
    >
      <Input
        aria-label="What is measured"
        className={cn(small, "!w-auto min-w-40 flex-1")}
        value={title}
        maxLength={200}
        placeholder="What is measured (Followers)"
        autoFocus
        onChange={(e) => {
          setTitle(e.target.value);
        }}
      />
      <Input
        aria-label="Start"
        inputMode="decimal"
        placeholder="Start"
        className={cn(small, "!w-16 tabular-nums")}
        value={start}
        onChange={(e) => {
          setStart(e.target.value);
        }}
      />
      <Input
        aria-label="Target"
        inputMode="decimal"
        className={cn(small, "!w-20 tabular-nums")}
        value={target}
        placeholder="Target"
        onChange={(e) => {
          setTarget(e.target.value);
        }}
      />
      <Input
        aria-label="Unit"
        className={cn(small, "!w-20")}
        value={unit}
        maxLength={40}
        placeholder="Unit"
        onChange={(e) => {
          setUnit(e.target.value);
        }}
      />
      <Input
        type="date"
        aria-label="Due"
        className={cn(small, "!w-auto")}
        value={dueOn}
        onChange={(e) => {
          setDueOn(e.target.value);
        }}
      />
      <FormActions
        busy={busy}
        canAdd={Boolean(title.trim())}
        error={error}
        onClose={onClose}
      />
    </form>
  );
}

export function NewProject({
  workspaceId,
  goalId,
  members,
  onClose,
}: {
  workspaceId: string;
  goalId: number;
  members: Member[];
  onClose: () => void;
}) {
  const [busy, error, run] = useRun();
  const [title, setTitle] = useState("");
  const [owner, setOwner] = useState("");
  const [kind, setKind] = useState<Kind>("dated");
  const [startsOn, setStartsOn] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const [rhythm, setRhythm] = useState("");
  return (
    <form
      aria-label="New project"
      className="flex flex-wrap items-center gap-1.5 rounded-lg bg-sunken/60 px-2.5 py-2"
      onKeyDown={escapeTo(onClose)}
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const r = await addProject(workspaceId, goalId, {
            title,
            owner,
            projectKind: kind,
            startsOn: kind === "dated" ? startsOn : "",
            endsOn: kind === "dated" ? endsOn : "",
            rhythm: kind === "recurring" ? rhythm : "",
          });
          if (!r.error) onClose();
          return r;
        });
      }}
    >
      <Input
        aria-label="Project title"
        className={cn(small, "!w-auto min-w-40 flex-1")}
        value={title}
        maxLength={200}
        placeholder="Project (Weekly reels)"
        autoFocus
        onChange={(e) => {
          setTitle(e.target.value);
        }}
      />
      <OwnerSelect value={owner} members={members} onChange={setOwner} />
      <KindFields
        kind={kind}
        startsOn={startsOn}
        endsOn={endsOn}
        rhythm={rhythm}
        onChange={(patch) => {
          if (patch.projectKind) setKind(patch.projectKind);
          if (patch.startsOn !== undefined) setStartsOn(patch.startsOn);
          if (patch.endsOn !== undefined) setEndsOn(patch.endsOn);
          if (patch.rhythm !== undefined) setRhythm(patch.rhythm);
        }}
      />
      <FormActions
        busy={busy}
        canAdd={Boolean(title.trim())}
        error={error}
        onClose={onClose}
      />
    </form>
  );
}

export function NewGoal({
  workspaceId,
  members,
  onClose,
}: {
  workspaceId: string;
  members: Member[];
  onClose: () => void;
}) {
  const [busy, error, run] = useRun();
  const [title, setTitle] = useState("");
  const [owner, setOwner] = useState("");
  const [dueOn, setDueOn] = useState("");
  return (
    <form
      aria-label="New goal"
      className="vision-card flex flex-col gap-2 px-6 py-5"
      onKeyDown={escapeTo(onClose)}
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const r = await addGoal(workspaceId, { title, owner, dueOn });
          if (!r.error) onClose();
          return r;
        });
      }}
    >
      <p className={sectionLabel}>New goal</p>
      <Input
        aria-label="Goal title"
        value={title}
        maxLength={200}
        placeholder="Grow the audience to 10k"
        autoFocus
        onChange={(e) => {
          setTitle(e.target.value);
        }}
      />
      <p className="text-xs text-ink-3">
        2 to 4 goals, about three months each. The Co-Founder proposes them too.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <OwnerSelect value={owner} members={members} onChange={setOwner} />
        <Input
          type="date"
          aria-label="Due"
          className={cn(small, "!w-auto")}
          value={dueOn}
          onChange={(e) => {
            setDueOn(e.target.value);
          }}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          disabled={busy || !title.trim()}
        >
          <PlusIcon /> Add goal
        </Button>
        <Button variant="ghost" disabled={busy} onClick={onClose}>
          Cancel
        </Button>
        <FormStatus error={error} />
      </div>
    </form>
  );
}
