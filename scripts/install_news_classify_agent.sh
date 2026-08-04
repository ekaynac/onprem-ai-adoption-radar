#!/usr/bin/env bash
# Install (or reinstall) the local news-classification launchd agent.
#
# Copies news_classify_local.sh to ~/Library/Application Support/onprem-radar/
# and loads the launchd agent (every 2h + at load). Re-run after editing
# the script or the plist template — the agent runs the installed copy,
# not the repo checkout.
#
# Remove with:
#   launchctl bootout "gui/$(id -u)/com.megabilisim.onpremradar.news-classify"
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
label="com.megabilisim.onpremradar.news-classify"
app_dir="$HOME/Library/Application Support/onprem-radar"
agents_dir="$HOME/Library/LaunchAgents"
plist_target="$agents_dir/$label.plist"

mkdir -p "$app_dir" "$agents_dir" "$HOME/Library/Logs"
install -m 0755 "$script_dir/news_classify_local.sh" "$app_dir/news_classify_local.sh"
sed "s|__HOME__|$HOME|g" "$script_dir/launchd/$label.plist" > "$plist_target"

launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist_target"
launchctl print "gui/$(id -u)/$label" | grep -E "state|interval" | head -3

echo "Installed. Logs: ~/Library/Logs/onprem-radar-news-classify.log"
