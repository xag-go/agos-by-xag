# User guide

A short tour of every screen. AGOS opens at **http://localhost:3000** (or the
address Settings → Access shows for your phone). Words in **bold** are defined
in the [glossary](glossary.md).

## First start

A fresh AGOS has no workspace. The home screen asks you to create one.

1. **Settings → Models**: connect at least one model provider (a subscription
   sign-in, an API key, or both). Agents can't answer without one.
2. **New workspace**: a name, a short description and a default model. AGOS
   makes the workspace's own Hermes, its Co-Founder and its sandbox.
3. Open the workspace and talk to its **Co-Founder**.

## The left rail

Each workspace is an icon on the rail. Click one to open it. Right-click (or
long-press on a phone) for its settings, archive and delete. **New workspace**
and **Settings** sit at the bottom.

## Inside a workspace

The tabs appear in the order you choose in **Settings → General**.

| Tab               | What it is for                                                                                                                                                                                           |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Dashboard**     | The workspace at a glance: what is running, what waits for you, usage this month, recent activity.                                                                                                       |
| **Office**        | A picture of the team at work: who is busy, on what card, and who is idle.                                                                                                                               |
| **Kanban**        | Every task as a **card** in Hermes's columns (Triage, To do, Ready, Running, Blocked, Review, Done). Drag cards, open one for its details, chat and documents. Save views and filter by label or member. |
| **Inbox**         | Everything that waits for your decision: hires, kits, questions from agents, memory or skill changes Hermes holds for you, approvals. Approve, reject or edit.                                           |
| **Sessions**      | Your chats with the Co-Founder or one agent. Several chats, each with its own context. Voice notes, files and pictures work here.                                                                        |
| **Team Chat**     | The team's direct messages and **groups** (**rooms**). In a group the Co-Founder directs who answers. You can step in at any time.                                                                       |
| **Hierarchy**     | The team: the Co-Founder at the top, each **member** with its role, who it reports to, its model, its kit and its work hours. Hire, edit or let go.                                                      |
| **Vision**        | The project's plan: the vision, goals and the rhythm (what happens each day and week), with progress read from the Kanban.                                                                               |
| **Status**        | Status cards: a short summary of one part of the project, kept up to date daily, weekly or when you ask.                                                                                                 |
| **Automations**   | Work that starts by itself: on a schedule, when something happens in another app (a webhook), or both. Run now, see past runs, turn off. Webhooks: [instant automations](guides/instant-automations.md). |
| **Documentation** | The team's playbooks (`playbooks/` in the workspace folder): how this project's work is done. The agents read them on every job.                                                                         |
| **Artifacts**     | Every file and document the team made on cards, with your reviews.                                                                                                                                       |
| **Screen**        | The workspace's virtual desktop, live, when an agent uses a browser or a desktop app.                                                                                                                    |
| **Log**           | What happened in this workspace, with filters: activity, errors and warnings, Hermes's own logs.                                                                                                         |
| **Search**        | One search over cards, chats, documents, files, the plan, the team and skills.                                                                                                                           |

## The Co-Founder

The Co-Founder is the workspace's lead agent. It can do anything you can do in
the app: create cards, hire members, write automations, change settings. Each
change shows as a card in the chat:

- most changes are done at once and have an **Undo** button;
- risky ones (deletes, imports, people, the Hermes update) wait for your
  **Approve**.

Ask it in plain words, in any language you like.

## Workspace settings

Open them from the workspace's right-click menu.

| Section               | What it is for                                                                                                                                                                            |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **General**           | Name, description, icon, default model, Telegram, the folders the agents may see (read only or read and write), commands that run without asking or never, goal mode, archive and delete. |
| **Identity & memory** | Who this workspace is (its identity text) and what Hermes remembers about it.                                                                                                             |
| **What I learned**    | What the team learned in this workspace, and this workspace's share of the Brain.                                                                                                         |
| **Work hours**        | The workspace's week: check-in and check-out per day (or off), on your clock, and who stays on today.                                                                                     |
| **Review**            | The review stages every card goes through, and how many rounds of changes before a card comes to you.                                                                                     |
| **Labels**            | The labels you put on cards.                                                                                                                                                              |
| **Channels**          | Where this workspace's chats also live: Telegram bots, groups and topics.                                                                                                                 |
| **Capabilities**      | The skills, tools and MCP servers this workspace may use.                                                                                                                                 |
| **Skills that grow**  | How many new skills agents may ask for per day, the Co-Founder's weekly skill review, and their log.                                                                                      |
| **Keys**              | Keys for this workspace's own tools and scripts. Keys belong here or in Settings → Models, never in a chat.                                                                               |
| **Connections**       | Outside apps (Google, GitHub, Composio…) this workspace signs in to with its own account.                                                                                                 |
| **Export / Import**   | Download the workspace as a readable bundle, or bring a bundle in (with a preview first).                                                                                                 |

## Settings (for every workspace)

| Section             | What it is for                                                                                                 |
| ------------------- | -------------------------------------------------------------------------------------------------------------- |
| **General**         | Theme, your name and timezone, tab order, voice notes, **Update AGOS**, **Hermes update**.                     |
| **My rules**        | Rules about you that every workspace follows: language, how to ask you, how to report.                         |
| **Brain**           | Ways of working the whole team learned, shared by every project. No project data goes in it.                   |
| **Models**          | Connect providers once for every workspace: subscription sign-in, API key, or both.                            |
| **Helper models**   | Which model does each side job (looking at pictures, summing up long chats…).                                  |
| **Connectors**      | Every app and MCP server in one list. Each workspace turns on what it needs and signs in with its own account. |
| **Tools**           | Every tool Hermes has.                                                                                         |
| **Hermes settings** | Every Hermes setting, with each workspace's value. A change here is written into every workspace's Hermes.     |
| **Health**          | Hermes's own `status` and `doctor` checks of every workspace's engine.                                         |
| **Errors**          | AGOS's own errors and each workspace's Hermes errors, grouped, with **Mark fixed** (and Undo).                 |
| **Usage & limits**  | Spending limits shared by every workspace: warn at, pause at.                                                  |
| **Access**          | Open AGOS from your phone or another computer over Tailscale (Activate, then scan the QR code).                |
| **Notifications**   | How each kind of event reaches you: in the app, by push on your phone, on Telegram, or not at all.             |
| **Server & backup** | Archived and trashed workspaces, backup password and schedule, Back up now, Test a restore, disk space.        |

## Phone

After **Settings → Access → Activate**, scan the QR code with your phone and
add AGOS to the home screen. It works like an app, with push notifications.
Only devices in your own Tailscale network can open it.

## When something looks wrong

- An agent doesn't answer: check **Settings → Models** and the workspace's
  **Log**.
- A workspace seems stuck: **Settings → Health** shows its engine's state.
- Nothing opens at all: see the [runbooks](runbooks/README.md).
