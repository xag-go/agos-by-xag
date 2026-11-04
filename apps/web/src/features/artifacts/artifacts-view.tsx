"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import type { Artifact, Artifacts } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Markdown } from "@/shared/ui/markdown";
import { PageHeader } from "@/shared/ui/page-header";
import { promoteArtifact, reviewArtifact } from "./actions";
import { HtmlPreview } from "./html-preview";
import { dateTime } from "@/shared/format";

const KINDS: Record<Artifact["kind"], string> = {
  image: "Image",
  pdf: "PDF",
  html: "HTML",
  md: "Markdown",
  other: "File",
};

const when = (seconds: number) =>
  seconds ? dateTime(new Date(seconds * 1000)) : "";

const size = (n: number) =>
  n >= 1_000_000
    ? `${(n / 1_000_000).toFixed(1)} MB`
    : n >= 1000
      ? `${String(Math.round(n / 1000))} kB`
      : `${String(n)} B`;

/**
 * Every work product of the workspace in one place: the cards' files (Hermes's
 * attachments) and the cards' documents, with a preview, the owner's review
 * (approved / needs work) and, for a markdown file, Promote to document.
 */
export function ArtifactsView({
  workspaceId,
  page,
}: {
  workspaceId: string;
  page: Artifacts;
}) {
  const [kind, setKind] = useState<"" | Artifact["kind"]>("");
  const [card, setCard] = useState("");
  const [member, setMember] = useState("");
  const [review, setReview] = useState<"" | "none" | "approved" | "needs_work">(
    "",
  );
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const cards = [...new Set(page.items.map((i) => i.card))].sort();
  const members = [
    ...new Set(page.items.map((i) => i.member).filter(Boolean)),
  ].sort();
  const shown = page.items.filter(
    (i) =>
      (!kind || i.kind === kind) &&
      (!card || i.card === card) &&
      (!member || i.member === member) &&
      (!review ||
        (review === "none" ? i.review === "" : i.review === review)) &&
      (!q ||
        `${i.name} ${i.cardTitle} ${i.card}`
          .toLowerCase()
          .includes(q.toLowerCase())),
  );
  const opened = page.items.find((i) => i.ref === open) ?? null;
  return (
    <div className="flex flex-col gap-6" data-fill>
      <PageHeader
        title="Artifacts"
        description="Every file and document the team produced on its cards, in one gallery. Review each one; a markdown file can become a card document with its own revisions."
      />
      {page.note && (
        <p className="rounded-xl bg-attention/40 px-3 py-2 text-sm">
          {page.note}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="Search"
          placeholder="Search by name or card"
          value={q}
          onChange={(e) => {
            setQ(e.currentTarget.value);
          }}
          className="max-w-xs"
        />
        <Select
          aria-label="Type"
          value={kind}
          onChange={(e) => {
            setKind(e.currentTarget.value as "" | Artifact["kind"]);
          }}
        >
          <option value="">Every type</option>
          {Object.entries(KINDS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Card"
          value={card}
          onChange={(e) => {
            setCard(e.currentTarget.value);
          }}
        >
          <option value="">Every card</option>
          {cards.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Member"
          value={member}
          onChange={(e) => {
            setMember(e.currentTarget.value);
          }}
        >
          <option value="">Everyone</option>
          {members.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Review"
          value={review}
          onChange={(e) => {
            setReview(e.currentTarget.value as typeof review);
          }}
        >
          <option value="">Any review</option>
          <option value="none">Not reviewed</option>
          <option value="approved">Approved</option>
          <option value="needs_work">Needs work</option>
        </Select>
        <span className="text-sm text-ink-3">
          {shown.length} of {page.items.length}
        </span>
      </div>
      {page.items.length === 0 ? (
        <p className="text-sm text-ink-3">
          Nothing yet: files a member attaches to a card and the cards&apos;
          documents show here.
        </p>
      ) : (
        <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
          <ul className="flex flex-col gap-2">
            {shown.map((i) => (
              <li key={i.ref}>
                <button
                  type="button"
                  onClick={() => {
                    setOpen(i.ref);
                  }}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left",
                    open === i.ref
                      ? "border-ink bg-sunken"
                      : "border-line hover:border-line-strong",
                  )}
                >
                  <span className="w-16 shrink-0 rounded-md bg-sunken px-1.5 py-0.5 text-center text-11 font-medium text-ink-2">
                    {KINDS[i.kind]}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink">
                      {i.name}
                    </span>
                    <span className="block truncate text-xs text-ink-3">
                      {i.cardTitle || i.card}
                      {i.member && ` · ${i.member}`}
                      {i.at > 0 && ` · ${when(i.at)}`}
                      {i.source === "document" && ` · v${String(i.revision)}`}
                    </span>
                  </span>
                  {i.review && <ReviewBadge state={i.review} />}
                </button>
              </li>
            ))}
            {shown.length === 0 && (
              <li className="text-sm text-ink-3">
                Nothing matches these filters.
              </li>
            )}
          </ul>
          <div className="min-h-0">
            {opened ? (
              <ArtifactPanel
                key={opened.ref}
                workspaceId={workspaceId}
                item={opened}
              />
            ) : (
              <p className="text-sm text-ink-3">Pick an artifact to see it.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ReviewBadge({ state }: { state: Artifact["review"] }) {
  if (!state) return null;
  return (
    <span
      className={cn(
        "shrink-0 rounded-md px-1.5 py-0.5 text-11 font-medium",
        state === "approved"
          ? "bg-success/15 text-success"
          : "bg-attention text-attention-ink",
      )}
    >
      {state === "approved" ? "Approved" : "Needs work"}
    </span>
  );
}

function ArtifactPanel({
  workspaceId,
  item,
}: {
  workspaceId: string;
  item: Artifact;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [said, setSaid] = useState<string | null>(null);
  const [note, setNote] = useState(item.reviewNote);
  const [state, setState] = useState(item.review);
  const file =
    item.attachmentId === null
      ? null
      : `/api/w/${encodeURIComponent(workspaceId)}/kanban/${encodeURIComponent(item.card)}/files/${String(item.attachmentId)}`;
  const cardHref = `/w/${encodeURIComponent(workspaceId)}/kanban?card=${encodeURIComponent(item.card)}`;
  const docHref = `${cardHref}&doc=${encodeURIComponent(item.key)}`;
  const label = "text-11 font-medium tracking-caps text-ink-3 uppercase";
  const setReview = (next: Artifact["review"]) => {
    const value = state === next ? "" : next;
    setState(value);
    start(async () => {
      setError(
        (await reviewArtifact(workspaceId, item.ref, value, note)).error,
      );
    });
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-display text-lg font-semibold">
            {item.name}
          </h2>
          <p className="text-xs text-ink-3">
            {KINDS[item.kind]}
            {item.size > 0 && ` · ${size(item.size)}`}
            {item.member && ` · ${item.member}`}
            {item.at > 0 && ` · ${when(item.at)}`}
            {" · "}
            <Link href={cardHref} className="underline hover:text-ink">
              {item.cardTitle || item.card}
            </Link>
            {item.source === "document" && (
              <>
                {" · "}
                <Link href={docHref} className="underline hover:text-ink">
                  open the document (v{String(item.revision)})
                </Link>
              </>
            )}
          </p>
        </div>
        {file && (
          <a href={file} download={item.name} className="text-sm underline">
            Download
          </a>
        )}
      </div>
      <section className="flex flex-col gap-2">
        <p className={label}>Review</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant={state === "approved" ? "primary" : undefined}
            disabled={busy}
            onClick={() => {
              setReview("approved");
            }}
          >
            Approved
          </Button>
          <Button
            type="button"
            variant={state === "needs_work" ? "danger" : undefined}
            disabled={busy}
            onClick={() => {
              setReview("needs_work");
            }}
          >
            Needs work
          </Button>
          <Input
            aria-label="Review note"
            placeholder="A note with it (optional)"
            value={note}
            onChange={(e) => {
              setNote(e.currentTarget.value);
            }}
            onBlur={() => {
              if (state && note !== item.reviewNote)
                start(async () => {
                  setError(
                    (await reviewArtifact(workspaceId, item.ref, state, note))
                      .error,
                  );
                });
            }}
            className="min-w-48 flex-1"
          />
          {item.source === "attachment" &&
            item.kind === "md" &&
            item.attachmentId !== null && (
              <Button
                type="button"
                disabled={busy}
                onClick={() => {
                  start(async () => {
                    const r = await promoteArtifact(
                      workspaceId,
                      item.card,
                      item.attachmentId ?? 0,
                    );
                    setError(r.error);
                    if (!r.error && r.key)
                      setSaid(
                        `Now document ${r.key}.md of card ${item.card} (v1).`,
                      );
                  });
                }}
              >
                Promote to document
              </Button>
            )}
        </div>
        <FormStatus error={error} />
        {said && <p className="text-sm text-ink-2">{said}</p>}
      </section>
      <Preview workspaceId={workspaceId} item={item} file={file} />
    </div>
  );
}

/** Images inline, markdown rendered, a PDF by the browser, HTML walled off. */
function Preview({
  workspaceId,
  item,
  file,
}: {
  workspaceId: string;
  item: Artifact;
  file: string | null;
}) {
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const wantsText =
    item.source === "attachment" &&
    (item.kind === "md" || item.kind === "html");
  useEffect(() => {
    if (!wantsText || !file) return;
    let gone = false;
    void fetch(file, { cache: "no-store" })
      .then((r) =>
        r.ok ? r.text() : Promise.reject(new Error(String(r.status))),
      )
      .then((t) => {
        if (!gone) setText(t);
      })
      .catch(() => {
        if (!gone) setFailed(true);
      });
    return () => {
      gone = true;
    };
  }, [file, wantsText]);
  if (item.source === "document")
    return (
      <p className="text-sm text-ink-3">
        A card document: open it from the card to read, edit, comment and
        restore.{" "}
        <Link
          href={`/w/${encodeURIComponent(workspaceId)}/kanban?card=${encodeURIComponent(item.card)}&doc=${encodeURIComponent(item.key)}`}
          className="underline hover:text-ink"
        >
          Open {item.name}
        </Link>
      </p>
    );
  if (!file) return null;
  if (item.kind === "image")
    return (
      // eslint-disable-next-line @next/next/no-img-element -- a file of the owner's own core, any size
      <img
        src={file}
        alt={item.name}
        className="max-h-[70dvh] max-w-full rounded-xl border border-line object-contain"
      />
    );
  if (item.kind === "pdf")
    return (
      <iframe
        title={item.name}
        src={file}
        className="h-[70dvh] w-full rounded-xl border border-line"
      />
    );
  if (failed)
    return (
      <p className="text-sm text-danger">This file couldn&apos;t be read.</p>
    );
  if (text === null && wantsText)
    return <p className="text-sm text-ink-3">Opening…</p>;
  if (item.kind === "html" && text !== null)
    return <HtmlPreview html={text} title={item.name} />;
  if (item.kind === "md" && text !== null)
    return (
      <div className="rounded-xl border border-line px-4 py-3 text-sm">
        <Markdown text={text} />
      </div>
    );
  return (
    <p className="text-sm text-ink-3">
      No preview for this type:{" "}
      <a href={file} download={item.name} className="underline">
        download it
      </a>
      .
    </p>
  );
}
