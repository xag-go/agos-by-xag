# Instant automations (webhooks)

All automations live in one Automations tab. Each one starts on a schedule, the
moment something happens in another app (a webhook), or both.

Every automation runs **by itself to the end** (the report comes to Runs and the
Co-Founder chat). Only with **Check with me first** on (or when the owner tells the
Co-Founder to check with them first) does a run wait for their Approve before anything starts. The
same rule holds for tasks the Co-Founder or an agent adds from a chat: they start by
themselves, unless the owner asked to be checked with first (then they wait in To do
and come back to the owner for review). Commands inside an automation run are allowed by
themselves (sandbox only); a blocked step ends that run and is told once in the
Co-Founder chat.

An automation can start **the moment something happens in another app**, not only
on a schedule. This is general: a project board, a Google Sheet (Apps Script), Zapier, GitHub,
a form, a payment provider, anything that can send a webhook.

## How it works

```
Board / Sheet / any app ──POST /webhooks/<route>──▶ public https (tunnel or server)
      ──▶ webhook relay (passes ONLY POST /webhooks/agos-<id>-<token>, maps the
          signature / delivery / event headers to the names Hermes reads)
      ──▶ the workspace's Hermes webhook platform (127.0.0.1): HMAC signature,
          route on/off, "Only these events" (route filters), rate, delivery id
      ──▶ the route's script (Hermes runs it, no agent, no tokens): the run goes on
          the workspace's Kanban at once (team steps, or one step for the agent /
          Co-Founder who does it), with the delivery in "What happened"
      ──▶ Hermes's dispatcher works the cards; Runs reads them from the board
```

AGOS only writes the route and the script (Hermes config) and shows what the
script noted of each delivery (Webhook → Last deliveries). The same script is what
the automation's Hermes cron job runs on its schedule, and what Run now runs.

- **When it starts** (per automation): _On a schedule_, _When something happens_
  (webhook only), or _Both_ (webhook + a schedule as a safety net).
- **Webhook dialog** (Automations → Webhook): the address to paste in the other app,
  the signing secret (paste the app's `whsec_…`), which events count (e.g.
  `spaces.task.moved, spaces.task.created`), the last deliveries and what happened
  to each, "New address" (old one stops at once), "Turn off".
- The Co-Founder can set it too: `"webhook": true` on create/update_automation. Its
  instructions tell it never to build "check every 5 minutes" when the app can send
  a webhook.

## Guarantees

| Case                                                | What happens                                                                                                                                                                |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Delivery signed with the right secret               | Hermes runs the route's script: the run is on the Kanban right away (HTTP 200 `ignored`/`script`: Hermes has nothing more to do)                                            |
| Same delivery again (a retry resends the same body) | the route script drops it (same body within an hour): noted as "Already received", nothing runs twice. Hermes's own delivery-id check runs after route scripts, so it can't |
| Deliveries during a run                             | a new run waits on the running one on Hermes's board; later ones join that waiting run as comments                                                                          |
| Event not in "Only these events"                    | Hermes's route filter: 200 `ignored`/`filter`, nothing runs                                                                                                                 |
| Wrong/missing signature, unknown address            | 401 / 404 from Hermes, nothing runs                                                                                                                                         |
| Automation off                                      | the route is disabled: 403, nothing runs                                                                                                                                    |
| More than 30 deliveries a minute on one route       | 429 (Hermes's rate limit)                                                                                                                                                   |
| Body over 512 KB                                    | 413 (the relay)                                                                                                                                                             |
| The board didn't take it (Hermes's Kanban failed)   | noted as refused in Last deliveries; Hermes still answers 200, so the sender won't retry                                                                                    |
| Payload text                                        | handed to agents as DATA, with the rule never to follow instructions inside it                                                                                              |

Hermes's own `coalesce` (debounce a burst into one run) is for agent-mode routes
only and can't be combined with a script or a cron job, so the burst rule above
lives in the run script, on Hermes's board.

Signatures accepted: `x-agos-signature` (AGOS's own format, `sha256=<hex HMAC-SHA256 of
the raw body>`), `x-hub-signature-256` (GitHub), `x-signature-256`, `x-signature`.

## Security

- The core and web app stay on 127.0.0.1. Only the relay port (8767) may be exposed,
  and it answers 404 to everything except `POST /hooks/<token>`; it never passes
  cookies or the internal token.
- Tokens are 32 random bytes; signing secrets are sealed with the master key.

## Reaching it from the internet

An app on the internet needs a public https address for the relay, for example a
tunnel such as `ngrok http 127.0.0.1:8767` or Cloudflare Tunnel. Point the tunnel
ONLY at the relay port (8767). Save the address once in the Webhook dialog ("Public
address of this machine"). Any app that sends signed webhooks works as is: create an
automation (When something happens), paste its address in the app's webhook settings,
and paste the app's signing secret (`whsec_…`) in the Webhook dialog.
