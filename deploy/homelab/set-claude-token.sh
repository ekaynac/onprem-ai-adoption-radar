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
extractor="$(mktemp)"
trap 'rm -f "$log" "$extractor"' EXIT

echo "1/4  Opening 'claude setup-token' — approve in the browser, then return here."
# A 1000-column pseudo-terminal keeps the token on one line: when the real
# window wrapped it, two characters were lost at the wrap (owner's Mac,
# 2026-09-30: 52+52+9 = 113 of 115 chars, every join rejected with 401).
script -q "$log" /bin/sh -c 'stty cols 1000 2>/dev/null; exec claude setup-token'

echo "2/4  Extracting the token from the recorded output…"
# Candidates, shortest first: the token may be wrapped over several lines, and
# text printed right after it may start on the very next line, so every
# line-boundary prefix of 90-140 chars is a candidate. Anthropic decides.
# Written to a file first: macOS /bin/bash 3.2 mis-parses a heredoc inside
# $(...) when its body contains an apostrophe ("unexpected EOF").
cat > "$extractor" <<'PY'
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
# The renderer breaks the token wherever the terminal width falls: sometimes
# a newline, sometimes a plain space (both seen on the owner's Mac on
# 2026-09-30), and prose may follow the last piece. So collect the
# whitespace-separated chunks after the start and offer every prefix join;
# the container check decides which one Anthropic accepts.
text = " ".join(line.strip().strip(BORDER) for line in lines[:6])
segments = []
for chunk in text.split():
    if not re.fullmatch(r"[A-Za-z0-9_-]+", chunk):
        break
    segments.append(chunk)
    if len(segments) == 8:
        break
joined = ["".join(segments[:n]) for n in range(1, len(segments) + 1)]
good = [c for c in joined if c.startswith("sk-ant-oat01-") and 90 <= len(c) <= 140]
if not good:
    # Diagnose without leaking: letters and digits masked as x.
    masked = [re.sub(r"[A-Za-z0-9]", "x", line)[:120] for line in lines[:4]]
    sys.exit("no plausible token (90-140 chars) in the setup-token output.\n"
             f"segment lengths: {[len(s) for s in segments]}\n"
             "masked lines after the token start:\n  " + "\n  ".join(repr(m) for m in masked))
print("\n".join(good))
PY
candidates="$(python3 "$extractor" "$log")"

echo "3/4  Checking each candidate from ct-radar itself (where it will be used)…"
# Checked inside the container, as the radar user: the Mac's own Claude login,
# hooks and settings cannot interfere. The candidate travels on ssh stdin.
# shellcheck disable=SC2016  # $t must expand in the container, not here
check_script='read -r t; cd /tmp; echo OK | CLAUDE_CODE_OAUTH_TOKEN=$t HOME=/opt/radar claude -p --output-format json --model haiku --strict-mcp-config --no-session-persistence 2>&1'
token=""
while IFS= read -r candidate; do
  # shellcheck disable=SC2029  # CTID and check_script are meant to expand locally
  reply="$(printf '%s\n' "$candidate" | ssh "$HOST" "LC_ALL=C pct exec ${CTID} -- runuser -u radar -- sh -c '${check_script}'" || true)"
  verdict="$(python3 -c '
import json, re, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except ValueError:
    print("non-JSON reply: " + re.sub(r"[A-Za-z0-9_-]{20,}", "<masked>", raw)[:200])
    sys.exit(0)
if data.get("is_error"):
    reason = data.get("terminal_reason") or data.get("subtype") or "error"
    print(reason + ": " + str(data.get("result", ""))[:160])
else:
    print("ok")
' "$reply")"
  echo "     candidate (${#candidate} chars): ${verdict}"
  if [ "$verdict" = "ok" ]; then
    token="$candidate"
    break
  fi
done <<<"$candidates"
if [ -z "$token" ]; then
  echo "No candidate was accepted; nothing was changed on ct-radar." >&2
  exit 1
fi

echo "4/4  Writing it to ct-radar (${HOST}, CT ${CTID})…"
# The remote side keeps /etc/radar/env's inode (and so root:radar 0640) by
# rewriting it with `cat >`, and builds the new copy under umask 077.
# shellcheck disable=SC2029  # CTID is meant to expand locally
printf '%s' "$token" | ssh "$HOST" "LC_ALL=C pct exec ${CTID} -- sh -c '
umask 077
t=\$(cat)
case \$t in sk-ant-oat01-*) ;; *) echo token-format-invalid >&2; exit 1;; esac
grep -v ^CLAUDE_CODE_OAUTH_TOKEN= /etc/radar/env > /root/env.new
echo CLAUDE_CODE_OAUTH_TOKEN=\$t >> /root/env.new
cat /root/env.new > /etc/radar/env
rm -f /root/env.new
stat -c \"%U:%G %a\" /etc/radar/env'"
echo "Done: ct-radar has a valid Claude token."
