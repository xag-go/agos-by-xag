# Security

AGOS runs autonomous agents on a machine that holds the owner's data and keys.
We take reports seriously and thank everyone who reports responsibly.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub: open the
[repository](https://github.com/xag-go/agos-by-xag)'s **Security** tab, then
**Report a vulnerability**. Include:

- what is affected (component, version from `agos version`);
- how to reproduce it, step by step;
- what an attacker could do with it.

What to expect:

- we aim to answer within **5 working days**;
- and to give a first assessment (accepted or not, and how severe) within **10 working
  days**;
- a fix in a new release, published together with an advisory that credits you
  (unless you prefer not to be named).

Please give us a reasonable time to fix the problem before you talk about it in
public.

## In scope

The things that matter most:

- **Escaping a workspace**: an agent, a skill, a web page or a message that
  makes one workspace's agents read or write another workspace's files, chats,
  keys or memory.
- **Escaping the sandbox**: an agent tool that reaches the host, the Docker
  socket, AGOS's data folder or another sandbox.
- **Reaching AGOS from outside**: any way to use AGOS from a device that is
  neither this machine nor the owner's Tailscale (host header tricks, DNS
  rebinding, cross-site requests).
- **Leaking secrets**: keys or tokens sent to the browser, written to a log or
  a backup, or placed in a model's context or a sandbox.
- **Bypassing approvals**: a risky action (delete, send, pay, install) that runs
  without the owner's approval when the owner asked to be asked.
- **Prompt injection that acts**: text in a web page, email, file or webhook
  that makes an agent change AGOS (folders, connectors, automations, team).
- **Backups**: reading a backup without its password, or a restore that writes
  outside AGOS's folders.
- **The installer and the `agos` command**: privilege escalation, unsafe
  defaults.

Out of scope: problems in Hermes Agent itself (report them to
[Hermes Agent](https://github.com/NousResearch/hermes-agent)), in model
providers or in other upstream projects, unless AGOS makes them worse; attacks
that need root on the machine or physical access; a machine the owner exposed to
the internet against the install guide.

## How AGOS is protected

The security model (network, web access, workspace isolation, credentials,
egress, approvals) is in [ARCHITECTURE.md §8](ARCHITECTURE.md#8-security-model).

## Supported versions

Only the latest stable release gets security fixes, as a new patch release
(`vX.Y.Z+1`, [docs/releases.md](docs/releases.md)); betas and the `main` branch get
them when they move on. Update with `agos update` (or Settings → General → Update
AGOS). Every release is signed: the installer and `agos update` refuse one whose
signature does not match.
