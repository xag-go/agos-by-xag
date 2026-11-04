# Proposal: let the operator minimize the Docker sandbox's capability bounding set

## What Hermes does today

`tools/environments/docker.py` starts every container with `--cap-drop ALL` plus
`--cap-add CHOWN, DAC_OVERRIDE, FOWNER` (`_BASE_SECURITY_ARGS`) and, when
`docker_run_as_host_user` is off, `--cap-add SETUID, SETGID`
(`_PRIVDROP_CAP_ARGS`, so a root-started init can drop privileges).

## The gap

For an image whose default user is already unprivileged (AGOS's `agos-sandbox:*`
runs as `agent`), those five caps sit unused in the bounding set (CapEff is 0, and
no-new-privileges keeps them unreachable). They cannot be removed from the
operator's side: Docker resolves `--cap-add X ... --cap-drop X` in the ADD's
favor (verified: CapBnd stayed 0xcb with drops appended via
`terminal.docker_extra_args`), so `docker_extra_args` can't minimize them.

## Proposal

A setting, default unchanged:

```yaml
terminal:
  docker_cap_add: [] # default: today's five (unchanged behavior)
```

When the operator sets it (even to `[]`), `_build_security_args` uses exactly that
list instead of `_BASE_SECURITY_ARGS`'s adds + `_PRIVDROP_CAP_ARGS`. Images that
start as root keep the default; hardened non-root images get a truly empty
bounding set.

## Why not in AGOS

Hermes is the engine (hard rule 1): AGOS must not fork the terminal backend, and
Docker's add-wins rule makes an args-level workaround impossible.
