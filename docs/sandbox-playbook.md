# Sandbox Evaluation Playbook

A repeatable way to try a "Try This Week" tool **without exposing your machine
or data** to an unevaluated agent. The radar can generate a per-tool plan
(`radar sandbox --project "<name>"`, or the `sandbox_plan` MCP tool); this
document is the general method behind those plans.

## Principles

1. **Disposable by default.** Trial in a throwaway directory, container, or VM
   that you delete afterward. Assume the tool may write files, spawn processes,
   or phone home.
2. **Least privilege.** Start with no host mounts, no GPU, and network egress
   off (or allow-listed). Add capabilities one at a time, only after you have
   read what the tool does with them.
3. **No real secrets.** Use dummy API keys and synthetic data. Never point a
   first trial at production credentials, source repos, or customer data.
4. **Observe, then trust.** Watch what the tool reads, writes, and connects to
   before granting it terminal, file-write, browser, or persistent-agent
   access.

## Strategy by tool shape

The generator picks one of these from the card's tags:

| Strategy | When | Isolation |
| --- | --- | --- |
| `docker` | self-hosted / model-serving / single-binary | `docker run --rm --network none --memory 4g`, no mounts |
| `python-cli` | CLI / coding agent / open-source | throwaway `venv` or `uvx <pkg>` in `/tmp` |
| `node-cli` | npm / node / VS Code extension | `npx` with a local `npm_config_prefix` |
| `manual` | nothing packaged detected | read docs, run inside a VM/container first |

## Permission escalation ladder

Only climb one rung at a time, reverting if behavior looks wrong:

1. Offline, read-only, synthetic data.
2. Allow-listed network egress (the specific API it needs).
3. A single mounted scratch directory (never `$HOME` or a real repo).
4. Tool-specific permissions (terminal, file-write, browser) — one at a time.
5. GPU passthrough (`--gpus all`) only with a verified image source.

## Teardown

Always remove the container and scratch directory when done:

```bash
docker rm -f trial-<slug> 2>/dev/null || true
rm -rf /tmp/radar-trial-<slug>
```

## Recording the result

After a trial, feed the outcome back into the radar's decision: does it confirm
or contradict the tool's current ring? Note evidence (what worked, what it
accessed, friction) so the next scan's card reflects a real evaluation, not just
repository signals.
