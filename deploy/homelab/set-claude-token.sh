#!/usr/bin/env bash
# Put a fresh Claude subscription token on ct-radar without copy/paste.
#
# Run on the owner's Mac, in a normal terminal (it needs the browser login):
#   bash deploy/homelab/set-claude-token.sh
#
# 1. runs `claude setup-token` (browser approval, token valid for one year),
#    recording the terminal so the token never has to be selected by hand;
# 2. extracts the token, re-joining lines the terminal wrapped;
# 3. checks it against Anthropic with one tiny `claude -p` call;
# 4. only then replaces CLAUDE_CODE_OAUTH_TOKEN in ct-radar's /etc/radar/env
#    over SSH stdin, keeping the file's root:radar 0640 permissions.
# The token is never printed. Re-run yearly (the watchdog/journal will show
# "Failed to authenticate" in the digest log when it expires).
set -euo pipefail

HOST="${RADAR_HOST:-root@100.75.17.74}"
CTID="${RADAR_CTID:-105}"

log="$(mktemp)"
trap 'rm -f "$log"' EXIT

echo "1/4  Opening 'claude setup-token' — approve in the browser, then return here."
script -q "$log" claude setup-token

echo "2/4  Extracting the token from the recorded output…"
# Candidates, longest first: the token may be wrapped over several lines, and
# text printed right after it may start on the very next line, so every
# line-boundary prefix of 90-140 chars is a candidate. Anthropic decides.
candidates="$(python3 - "$log" <<'PY'
import re
import sys

raw = open(sys.argv[1], "rb").read().decode("utf-8", "ignore")
raw = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw)  # ANSI CSI sequences
raw = re.sub(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)", "", raw)  # OSC sequences
start = raw.rfind("sk-ant-oat01-")
if start < 0:
    sys.exit("no sk-ant-oat01- token found in the setup-token output")
# setup-token draws the token inside a box: borders (│ ┃ ╭ ─ ...) and padding
# sit around every wrapped line, so strip them before reading the token run.
BORDER = "".join(chr(c) for c in range(0x2500, 0x2580)) + "|"
lines = raw[start:].replace("\r", "").split("\n")
segments = []
for line in lines:
    core = line.strip().strip(BORDER).strip()
    match = re.fullmatch(r"[A-Za-z0-9_-]+", core)
    if not match:  # blank line or prose: the token ended on an earlier line
        break
    segments.append(core)
joined = ["".join(segments[:n]) for n in range(len(segments), 0, -1)]
good = [c for c in joined if c.startswith("sk-ant-oat01-") and 90 <= len(c) <= 140]
if not good:
    # Diagnose without leaking: letters and digits masked as x.
    masked = [re.sub(r"[A-Za-z0-9]", "x", line)[:120] for line in lines[:4]]
    sys.exit("no plausible token (90-140 chars) in the setup-token output.\n"
             f"segment lengths: {[len(s) for s in segments]}\n"
             "masked lines after the token start:\n  " + "\n  ".join(repr(m) for m in masked))
print("\n".join(good))
PY
)"

echo "3/4  Checking the token with Anthropic…"
token=""
while IFS= read -r candidate; do
  check="$(CLAUDE_CODE_OAUTH_TOKEN="$candidate" claude -p --output-format json --tools "" \
    --strict-mcp-config --no-session-persistence --model haiku <<<'Yalnızca OK yaz.' || true)"
  if python3 -c 'import json,sys; d=json.loads(sys.argv[1]); sys.exit(1 if d.get("is_error") else 0)' "$check" 2>/dev/null; then
    token="$candidate"
    break
  fi
done <<<"$candidates"
if [ -z "$token" ]; then
  echo "Anthropic rejected every candidate; nothing was changed on ct-radar. Run this script again." >&2
  exit 1
fi

echo "4/4  Writing it to ct-radar (${HOST}, CT ${CTID})…"
# The remote side keeps /etc/radar/env's inode (and so root:radar 0640) by
# rewriting it with `cat >`, and builds the new copy under umask 077.
# shellcheck disable=SC2029  # CTID is meant to expand locally
printf '%s' "$token" | ssh "$HOST" "pct exec ${CTID} -- sh -c '
umask 077
t=\$(cat)
case \$t in sk-ant-oat01-*) ;; *) echo token-format-invalid >&2; exit 1;; esac
grep -v ^CLAUDE_CODE_OAUTH_TOKEN= /etc/radar/env > /root/env.new
echo CLAUDE_CODE_OAUTH_TOKEN=\$t >> /root/env.new
cat /root/env.new > /etc/radar/env
rm -f /root/env.new
stat -c \"%U:%G %a\" /etc/radar/env'"
echo "Done: ct-radar has a valid Claude token."
