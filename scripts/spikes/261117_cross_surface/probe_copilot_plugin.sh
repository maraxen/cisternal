#!/usr/bin/env bash
# Probe P3 (offline, scratch HOME/COPILOT_HOME, no credentials): does Copilot CLI parse a plugin MCP server written the way
# cisternal's copilot exporter writes it (array `command`, `env` with ${NAME:-}) and what does `copilot mcp get` show?
set -u
S=/home/marielle/scratch/qg-261112-findings/probe_copilot
rm -rf $S/home $S/plug; mkdir -p $S/home $S/plug
cat > $S/plug/plugin.json <<'JSON'
{"name":"cprobe","version":"1.0.0","description":"probe","mcpServers":{"srv":{"command":["echo","hi"],"env":{"CISTERNAL_TELEMETRY_SHADOW":"${CISTERNAL_TELEMETRY_SHADOW:-}"}}}}
JSON
cat > $S/plug/.mcp.json <<'JSON'
{"mcpServers":{"srv":{"command":["echo","hi"],"env":{"CISTERNAL_TELEMETRY_SHADOW":"${CISTERNAL_TELEMETRY_SHADOW:-}"}}}}
JSON
export HOME=$S/home COPILOT_HOME=$S/home/.copilot XDG_CONFIG_HOME=$S/home/.config
CP="bun /home/marielle/.bun/install/global/node_modules/@github/copilot/npm-loader.js"
echo "=== plugin install (local dir)"; timeout 90 $CP plugin install $S/plug 2>&1 | tail -6
echo "=== plugin list"; timeout 60 $CP plugin list 2>&1 | tail -6
echo "=== mcp list"; timeout 60 $CP mcp list 2>&1 | tail -10
echo "=== mcp get srv"; timeout 60 $CP mcp get srv 2>&1 | tail -15
echo "=== mcp get srv with CISTERNAL_TELEMETRY_SHADOW=off exported"
CISTERNAL_TELEMETRY_SHADOW=off timeout 60 $CP mcp get srv 2>&1 | tail -15
echo "=== files created under scratch COPILOT_HOME:"; find $S/home -maxdepth 5 -type f | head -15
