# Runbook: a workspace's agents don't answer (Hermes gateway down)

Each workspace runs one Hermes gateway: Hermes's own systemd user service,
under the AGOS user. If it is down, that workspace's chats, Kanban dispatcher,
automations and Telegram stop. Other workspaces keep working.

## Symptoms

- Messages in one workspace get no answer; cards stay in Ready.
- `agos status` shows fewer `gateways running` than active workspaces.
- **Settings → Health** shows the workspace's engine as not running.

## 1. Look

```bash
agos status                         # gateways running (one per active workspace)
agos logs <workspace id>            # that workspace's Hermes logs
```

As the AGOS user, list the gateway units and their state:

```bash
sudo -iu agos
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user list-units --all 'hermes-gateway*'
journalctl --user -u <unit name> -n 100
```

## 2. Check the obvious first

- **A model provider.** Settings → Models: is a provider connected and
  working? An expired sign-in looks like "agents don't answer".
- **Usage limits.** Settings → Usage & limits: a "pause at" limit pauses every
  workspace on purpose (Hermes's own pause).
- **A paused or archived workspace.** Archived workspaces don't run.

## 3. Start it

Hermes's own service restarts a gateway after a crash. A gateway that was
stopped stays stopped: AGOS doesn't watch the gateways. Start it yourself:

```bash
systemctl --user start <unit name>
systemctl --user is-active <unit name>
```

## 4. Common causes

| The gateway log says                                  | Do this                                                                                                                                    |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `already owns profile` / another gateway runs         | Two gateways for one root. Stop both, wait for them to exit, start one.                                                                    |
| `Hermes contract broken: <name>`                      | The installed Hermes doesn't match this AGOS. Put Hermes back on the pinned commit ([hermes-upgrade.md](../hermes-upgrade.md), section 3). |
| `this kernel has no Landlock`                         | The kernel can't wall the gateway, so it refuses to run. Use an Ubuntu kernel.                                                             |
| Docker errors (`Cannot connect to the Docker daemon`) | `sudo systemctl start docker`, then start the gateway.                                                                                     |
| A missing plugin or dependency after an upgrade       | Prepare the home again: [hermes-upgrade.md](../hermes-upgrade.md), step 2d.                                                                |

## 5. Still down

Run Hermes's own checks for that root and keep the output for a report:

```bash
HERMES_HOME=~/agos-data/hermes/agos-<workspace id> HERMES_RUNTIME_DIR=~/.hermes/tools \
  ~/.local/bin/hermes doctor
```

**Settings → Health** shows the same `status` and `doctor` for every workspace.
