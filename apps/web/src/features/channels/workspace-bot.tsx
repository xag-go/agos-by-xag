"use client";

import { useRouter } from "next/navigation";
import {
  type TransitionStartFunction,
  useEffect,
  useMemo,
  useState,
  useTransition,
} from "react";
import { renderSVG } from "uqr";
import type { BotSetup, ChannelConnection } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import { Field, Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import {
  addConnection,
  approvePerson,
  deleteConnection,
  linkTelegramAccount,
  removePerson,
  setBotReactions,
  startBotSetup,
} from "./actions";
import { getStatus } from "@/shared/get-status";
import { Lamp } from "./lamp";

/**
 * A workspace's own Telegram bot, like Hermes: scan a QR code and tap
 * "Create bot" in Telegram (no BotFather, nothing to copy), or paste a token.
 * The bot's private chat with you is this workspace's Co-Founder chat.
 */
export function WorkspaceBot({
  workspaceId,
  workspaceName,
  bots,
  startWithQr = false,
}: {
  workspaceId: string;
  workspaceName: string;
  bots: ChannelConnection[];
  /** Right after creating the workspace: the QR code shows at once. */
  startWithQr?: boolean;
}) {
  const [mode, setMode] = useState<"idle" | "qr" | "token">(
    startWithQr && bots.length === 0 ? "qr" : "idle",
  );
  return (
    <div className="flex flex-col gap-3">
      {bots.length > 0 && (
        <ul className="flex flex-col gap-2">
          {bots.map((b) => (
            <BotRow key={b.id} bot={b} />
          ))}
        </ul>
      )}
      {mode === "qr" && (
        <QrSetup
          workspaceId={workspaceId}
          botName={workspaceName}
          onDone={() => {
            setMode("idle");
          }}
        />
      )}
      {mode === "token" && (
        <TokenSetup
          workspaceId={workspaceId}
          botName={workspaceName}
          onDone={() => {
            setMode("idle");
          }}
        />
      )}
      {mode === "idle" && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant={bots.length ? "secondary" : "primary"}
            onClick={() => {
              setMode("qr");
            }}
          >
            {bots.length ? "Add another bot" : "Create a bot with a QR code"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setMode("token");
            }}
          >
            I have a bot token
          </Button>
        </div>
      )}
    </div>
  );
}

function BotRow({ bot: b }: { bot: ChannelConnection }) {
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const { dialog, confirm } = useAsk();
  const linked = b.allowed.length > 0;
  const username = b.identity.replace(/^@/, "");
  return (
    <li className="flex flex-col gap-2 rounded-xl border border-line px-3 py-2 text-sm">
      {dialog}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Lamp status={b.status} reason={b.statusReason} />
        <span className="font-medium">{b.identity || b.name}</span>
        <span className={linked ? "text-ink-3" : "font-medium text-danger"}>
          {linked
            ? "Talks to the Co-Founder · only your account can write to it"
            : "Not linked to your Telegram account yet: it answers nobody"}
        </span>
        <span className="ml-auto flex items-center gap-3">
          <button
            type="button"
            disabled={busy}
            className="text-accent hover:underline"
            onClick={() => {
              setError(null);
              start(async () => {
                const r = await linkTelegramAccount(b.id);
                if (r.error || !r.link) setError(r.error ?? "No link.");
                else setLink(r.link);
              });
            }}
          >
            {linked ? "Link another account" : "Link my Telegram account"}
          </button>
          {username && linked && (
            <a
              href={`https://t.me/${username}`}
              target="_blank"
              rel="noreferrer"
              className="text-accent hover:underline"
            >
              Open in Telegram
            </a>
          )}
          <button
            type="button"
            disabled={busy}
            className="text-danger hover:underline"
            onClick={() => {
              void (async () => {
                const ok = await confirm({
                  title: `Disconnect “${b.identity || b.name}” from this workspace?`,
                  body: "The bot stops reading and sending here at once. Your chats and messages stay in AGOS. You can connect a bot again any time (the same one with its token, or a new one).",
                  confirmLabel: "Disconnect",
                  danger: true,
                });
                if (!ok) return;
                setError(null);
                start(async () => {
                  const r = await deleteConnection(b.id);
                  if (r.error) setError(r.error);
                });
              })();
            }}
          >
            Disconnect
          </button>
        </span>
      </div>
      <label className="flex items-center gap-2 text-ink-2">
        <input
          type="checkbox"
          checked={b.reactions}
          disabled={busy}
          onChange={(e) => {
            const reactions = e.target.checked;
            setError(null);
            start(async () => {
              const r = await setBotReactions(b.id, {
                name: b.name,
                enabled: b.enabled,
                reactions,
              });
              if (r.error) setError(r.error);
            });
          }}
        />
        React 👀 / ✅ / ❌ on your messages while it works (the
        telegram.reactions setting)
      </label>
      <People
        bot={b}
        busy={busy}
        onError={setError}
        start={start}
        confirm={confirm}
      />
      <FormStatus error={error} />
      {link && <ClaimLink link={link} />}
    </li>
  );
}

/** Who the bot listens to, and who asked (Hermes's allowlist and DM pairing). */
function People({
  bot: b,
  busy,
  onError,
  start,
  confirm,
}: {
  bot: ChannelConnection;
  busy: boolean;
  onError: (message: string | null) => void;
  start: TransitionStartFunction;
  confirm: ReturnType<typeof useAsk>["confirm"];
}) {
  if (b.pending.length === 0 && b.people.length === 0) return null;
  const who = (p: { id: string; name?: string }) =>
    p.name ? `${p.name} (${p.id})` : p.id;
  return (
    <ul className="flex flex-col gap-1 text-xs">
      {b.pending.map((p) => (
        <li key={p.requestId} className="flex flex-wrap items-center gap-x-3">
          <span className="font-medium text-ink">{who(p)}</span>
          <span className="text-ink-3">
            wrote to the bot and waits for your yes
          </span>
          <button
            type="button"
            disabled={busy}
            className="ml-auto text-accent hover:underline"
            onClick={() => {
              onError(null);
              start(async () => {
                const r = await approvePerson(b.id, p.requestId);
                if (r.error) onError(r.error);
              });
            }}
          >
            Approve
          </button>
        </li>
      ))}
      {b.people.map((p) => (
        <li key={p.id} className="flex flex-wrap items-center gap-x-3">
          <span className="text-ink-2">{who(p)}</span>
          <span className="text-ink-3">can write to the bot</span>
          <button
            type="button"
            disabled={busy}
            className="ml-auto text-danger hover:underline"
            onClick={() => {
              void (async () => {
                const ok = await confirm({
                  title: `Remove ${who(p)}?`,
                  body: "The bot stops listening to this account at once. They can write to it again and ask; you approve it here.",
                  confirmLabel: "Remove",
                  danger: true,
                });
                if (!ok) return;
                onError(null);
                start(async () => {
                  const r = await removePerson(b.id, p.id);
                  if (r.error) onError(r.error);
                });
              })();
            }}
          >
            Remove
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Scan or open: writing to the bot asks Hermes for a pairing code; the request
 * shows above for his Approve (the page looks again every few seconds). */
function ClaimLink({ link }: { link: string }) {
  const svg = useMemo(() => renderSVG(link, { border: 2 }), [link]);
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => {
      // A hidden tab re-renders nothing (like the Kanban's LiveRefresh).
      if (document.visibilityState === "visible") router.refresh();
    }, 4000);
    return () => {
      clearInterval(timer);
    };
  }, [router]);
  return (
    <div className="flex flex-wrap items-center gap-4 border-t border-line pt-3">
      <div
        role="img"
        aria-label="QR code to link your Telegram account"
        className="size-32 shrink-0 overflow-hidden rounded-lg bg-white"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      <div className="flex flex-col gap-1 text-ink-2">
        <p>
          Scan it with your phone, or{" "}
          <a
            href={link}
            target="_blank"
            rel="noreferrer"
            className="text-accent hover:underline"
          >
            open the link
          </a>
          , then tap <span className="font-medium text-ink">Start</span> in
          Telegram.
        </p>
        <p className="text-xs text-ink-3">
          The bot answers with a pairing code and your account shows here: tap
          Approve. A request lasts an hour. Only accounts you approve can write
          to the bot.
        </p>
      </div>
    </div>
  );
}

function QrSetup({
  workspaceId,
  botName,
  onDone,
}: {
  workspaceId: string;
  botName: string;
  onDone: () => void;
}) {
  const [setup, setSetup] = useState<BotSetup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  // One pairing per open panel.
  useEffect(() => {
    let cancelled = false;
    void startBotSetup(workspaceId, botName).then((r) => {
      if (cancelled) return;
      if (r.error || !r.setup) setError(r.error ?? "The QR code didn't load.");
      else setSetup(r.setup);
    });
    return () => {
      cancelled = true;
    };
  }, [workspaceId, botName]);

  // Waits for "Create bot" in Telegram; the core saves and links the bot.
  const id = setup?.id;
  const waiting = setup?.status === "waiting";
  useEffect(() => {
    if (!id || !waiting) return;
    const timer = setInterval(() => {
      void getStatus<BotSetup | null>(
        `/api/channels/telegram/setup/${encodeURIComponent(id)}`,
      ).then((next) => {
        if (!next) return;
        setSetup(next);
        if (next.status === "saved") router.refresh(); // the new bot shows
      });
    }, 2500);
    return () => {
      clearInterval(timer);
    };
  }, [id, waiting, router]);

  const link = setup?.link ?? "";
  const svg = useMemo(
    () => (link ? renderSVG(link, { border: 2 }) : ""),
    [link],
  );

  if (error || setup?.status === "error" || setup?.status === "expired")
    return (
      <div className="flex flex-col gap-2 rounded-xl border border-line p-4">
        <FormStatus error={error ?? setup?.error ?? "Something went wrong."} />
        <Button type="button" className="self-start" onClick={onDone}>
          Close
        </Button>
      </div>
    );
  if (setup?.status === "saved")
    return (
      <div className="flex flex-col gap-2 rounded-xl border border-line p-4">
        <p className="text-sm">
          <span className="font-medium">
            @{setup.botUsername || "your bot"}
          </span>{" "}
          is ready. Write to it in Telegram: the Co-Founder of this workspace
          answers, and Kanban notifications arrive there.
        </p>
        <Button type="button" className="self-start" onClick={onDone}>
          Done
        </Button>
      </div>
    );
  return (
    <div className="flex flex-wrap items-start gap-5 rounded-xl border border-line p-4">
      <div
        aria-label="QR code to create the bot"
        role="img"
        className="size-44 shrink-0 overflow-hidden rounded-lg bg-white"
        // Generated locally from the Telegram link (no outside image).
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      <div className="flex min-w-56 flex-1 flex-col gap-2 text-sm">
        <p className="font-medium">Create the bot in Telegram</p>
        <ol className="list-decimal pl-5 text-ink-2">
          <li>Scan this code with your phone (or open the link).</li>
          <li>
            Tap <span className="font-medium">Create bot</span> in Telegram.
          </li>
          <li>Come back here: it connects by itself.</li>
        </ol>
        {setup?.link ? (
          <a
            href={setup.link}
            target="_blank"
            rel="noreferrer"
            className="text-accent hover:underline"
          >
            Open the link in Telegram
          </a>
        ) : (
          <p className="text-ink-3">Loading the code…</p>
        )}
        {setup && (
          <p className="text-xs text-ink-3">
            Waiting for Telegram… The bot belongs to your Telegram account; only
            you can write to it.
          </p>
        )}
        <Button
          type="button"
          variant="ghost"
          className="self-start"
          onClick={onDone}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}

function TokenSetup({
  workspaceId,
  botName,
  onDone,
}: {
  workspaceId: string;
  botName: string;
  onDone: () => void;
}) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-line p-4">
      <Field
        label="Bot token"
        hint="From @BotFather in Telegram (/newbot). It's stored encrypted and never shown again."
      >
        <Input
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => {
            setToken(e.target.value);
          }}
          placeholder="123456789:ABC…"
        />
      </Field>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="primary"
          disabled={busy || !token.trim()}
          onClick={() => {
            setError(null);
            start(async () => {
              const r = await addConnection({
                kind: "telegram",
                name: botName,
                secret: token,
                allowed: "",
                workspaceId,
              });
              if (r.error) setError(r.error);
              else onDone();
            });
          }}
        >
          {busy ? "Connecting…" : "Connect"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <FormStatus error={error} />
      </div>
      <p className="text-xs text-ink-3">
        After connecting, tap “Link my Telegram account” on the bot: you open it
        in Telegram, tap Start, and that private chat becomes this
        workspace&apos;s Co-Founder chat.
      </p>
    </div>
  );
}
