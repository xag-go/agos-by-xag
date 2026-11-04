"use client";

import { useEffect, useState, useTransition } from "react";
import type { ChannelConnection, ChatAddress } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import {
  addAddress,
  removeAddress,
  type TelegramPlace,
  telegramPlaces,
} from "./actions";
import { Lamp } from "./lamp";
import { MenuBackdrop } from "@/shared/ui/menu-backdrop";
import { Panel } from "@/shared/ui/panel";

/** A chat's "Where": web only, or also the workspace's Telegram chat / group / topic. */
export function ChatWhere({
  workspaceId,
  chatId,
  addresses,
  connections,
}: {
  workspaceId: string;
  chatId: number;
  addresses: ChatAddress[];
  connections: ChannelConnection[];
}) {
  const [open, setOpen] = useState(false);
  const worst = addresses.some((a) => a.status === "error")
    ? "error"
    : addresses.some((a) => a.status === "connecting")
      ? "connecting"
      : "connected";
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
        }}
        className="flex h-7 items-center gap-2 rounded-full border border-line px-2.5 text-xs text-ink-2 hover:border-line-strong"
        aria-expanded={open}
      >
        {addresses.length > 0 && (
          <Lamp
            status={worst}
            reason={addresses.find((a) => a.status === "error")?.statusReason}
          />
        )}
        {addresses.length === 0 ? "Web only" : "Web + Telegram"}
      </button>
      {open && (
        <>
          <MenuBackdrop
            label="Close"
            onClose={() => {
              setOpen(false);
            }}
          />
          <Panel className="absolute top-9 right-0 z-30 flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-3 p-4 shadow-popover">
            <p className="text-sm font-medium">Where this chat lives</p>
            <ul className="flex flex-col gap-2">
              <li className="text-sm text-ink-2">Web (always)</li>
              {addresses.map((a) => (
                <AddressRow
                  key={a.id}
                  workspaceId={workspaceId}
                  chatId={chatId}
                  address={a}
                />
              ))}
            </ul>
            {connections.length === 0 ? (
              <p className="text-xs text-ink-3">
                Connect this workspace&apos;s Telegram bot in its Settings →
                Channels first.
              </p>
            ) : (
              <>
                <PlacePicker workspaceId={workspaceId} chatId={chatId} />
                <details className="text-xs text-ink-3">
                  <summary className="cursor-pointer">
                    Type a group / topic id yourself
                  </summary>
                  <AddAddress
                    workspaceId={workspaceId}
                    chatId={chatId}
                    connections={connections}
                  />
                </details>
              </>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}

/**
 * Where in Telegram: the private chat with the bot, each group's General and each
 * topic its bot has seen (or a new topic), with what is linked to each now.
 */
function PlacePicker({
  workspaceId,
  chatId,
}: {
  workspaceId: string;
  chatId: number;
}) {
  const [data, setData] = useState<{
    connectionId: number | null;
    places: TelegramPlace[];
  } | null>(null);
  const [choice, setChoice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  useEffect(() => {
    let live = true;
    void telegramPlaces(workspaceId).then((d) => {
      if (live) setData(d);
    });
    return () => {
      live = false;
    };
  }, [workspaceId]);
  if (data === null) return <p className="text-xs text-ink-3">Looking…</p>;
  const groups = [
    ...new Set(data.places.filter((p) => p.group).map((p) => p.group)),
  ];
  const groupId = (name: string) =>
    data.places.find((p) => p.group === name)?.address.split(":")[0] ?? "";
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-ink-2">
        Link it to a place in Telegram. A group shows up here once you write in
        it (with the bot added as an admin); a topic, once you write in that
        topic.
      </p>
      <div className="flex items-center gap-2">
        <Select
          aria-label="Place in Telegram"
          className="min-w-0 flex-1"
          value={choice}
          onChange={(e) => {
            setChoice(e.target.value);
          }}
        >
          <option value="">Choose a place…</option>
          {data.places
            .filter((p) => !p.group)
            .map((p) => (
              <option key={p.address} value={p.address} disabled={!!p.linkedTo}>
                {p.label}
                {p.linkedTo ? ` — linked to ${p.linkedTo}` : ""}
              </option>
            ))}
          {groups.map((g) => (
            <optgroup key={g} label={g}>
              {data.places
                .filter((p) => p.group === g)
                .map((p) => (
                  <option
                    key={p.address}
                    value={p.address}
                    disabled={!!p.linkedTo}
                  >
                    {p.label}
                    {p.linkedTo ? ` — linked to ${p.linkedTo}` : ""}
                  </option>
                ))}
              <option value={`new:${groupId(g)}`}>
                ＋ New topic for this chat
              </option>
            </optgroup>
          ))}
        </Select>
        <Button
          variant="primary"
          className="h-9"
          disabled={busy || !choice || data.connectionId === null}
          onClick={() => {
            setError(null);
            start(async () => {
              const creating = choice.startsWith("new:");
              const r = await addAddress(workspaceId, chatId, {
                connectionId: data.connectionId ?? 0,
                address: creating ? "" : choice,
                createTopicIn: creating ? choice.slice(4) : "",
                notify: false,
              });
              if (r.error) setError(r.error);
              else setChoice("");
            });
          }}
        >
          {busy ? "Linking…" : "Link"}
        </Button>
      </div>
      <FormStatus error={error} className="text-xs" />
    </div>
  );
}

function AddressRow({
  workspaceId,
  chatId,
  address: a,
}: {
  workspaceId: string;
  chatId: number;
  address: ChatAddress;
}) {
  const [busy, start] = useTransition();
  return (
    <li className="flex items-center gap-2 text-sm">
      <Lamp status={a.status} reason={a.statusReason} />
      <span className="min-w-0 flex-1 truncate" title={a.address}>
        {a.connectionName} · {a.label || a.address}
      </span>
      <button
        type="button"
        disabled={busy}
        className="text-xs text-danger hover:underline"
        onClick={() => {
          start(async () => {
            await removeAddress(workspaceId, chatId, a.id);
          });
        }}
      >
        Remove
      </button>
    </li>
  );
}

function AddAddress({
  workspaceId,
  chatId,
  connections,
}: {
  workspaceId: string;
  chatId: number;
  connections: ChannelConnection[];
}) {
  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? 0);
  const [mode, setMode] = useState<"create" | "existing">("create");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const kind =
    connections.find((c) => c.id === connectionId)?.kind ?? "telegram";
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      <Select
        aria-label="Connection"
        value={connectionId}
        onChange={(e) => {
          setConnectionId(Number(e.target.value));
        }}
      >
        {connections.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name} (Telegram)
          </option>
        ))}
      </Select>
      <Select
        aria-label="How"
        value={mode}
        onChange={(e) => {
          setMode(e.target.value === "existing" ? "existing" : "create");
        }}
      >
        <option value="create">
          {kind === "telegram"
            ? "Create a topic in a group"
            : "Create a channel"}
        </option>
        <option value="existing">
          {kind === "telegram"
            ? "Use an existing group / topic"
            : "Use an existing channel"}
        </option>
      </Select>
      <Input
        value={value}
        placeholder={
          kind === "telegram"
            ? mode === "create"
              ? "Group id (forum), e.g. -1001234567890"
              : "Group id, or group:topic"
            : "Channel UUID"
        }
        onChange={(e) => {
          setValue(e.target.value);
        }}
      />
      <p className="text-xs text-ink-3">
        A Telegram group linked here also gets the Kanban&apos;s notifications
        (done, stopped, needs you), like the Co-Founder chat.
      </p>
      <div className="flex items-center gap-2">
        <Button
          className="h-8"
          disabled={
            busy ||
            (kind === "telegram" && !value.trim()) ||
            (mode === "existing" && !value.trim())
          }
          onClick={() => {
            setError(null);
            start(async () => {
              const r = await addAddress(workspaceId, chatId, {
                connectionId,
                address: mode === "existing" ? value : "",
                createTopicIn: mode === "create" ? value || "-" : "",
                notify: false,
              });
              if (r.error) setError(r.error);
              else setValue("");
            });
          }}
        >
          Add
        </Button>
        <FormStatus error={error} className="text-xs" />
      </div>
    </div>
  );
}
