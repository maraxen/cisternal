#!/usr/bin/env bash
# Probe P3 control: same plugin but with the documented string `command` + `args` form. Does `mcp list` show it?
set -u
S=/home/marielle/scratch/qg-261112-findings/probe_copilot
rm -rf $S/home $S/plug_str; mkdir -p $S/home $S/plug_str
cat > $S/plug_str/plugin.json <<'JSON'
{"name":"cprobestr","version":"1.0.0","description":"probe","mcpServers":{"srvstr":{"command":"echo","args":["hi"],"env":{"CISTERNAL_TELEMETRY_SHADOW":"${CISTERNAL_TELEMETRY_SHADOW:-}"}}}}
JSON
cat > $S/plug_str/.mcp.json <<'JSON'
{"mcpServers":{"srvstr":{"command":"echo","args":["hi"],"env":{"CISTERNAL_TELEMETRY_SHADOW":"${CISTERNAL_TELEMETRY_SHADOW:-}"}}}}
JSON
export HOME=$S/home COPILOT_HOME=$S/home/.copilot XDG_CONFIG_HOME=$S/home/.config
CP="bun /home/marielle/.bun/install/global/node_modules/@github/copilot/npm-loader.js"
timeout 90 $CP plugin install $S/plug_str 2>&1 | head -2
echo "=== mcp list (string command + args)"; timeout 60 $CP mcp list 2>&1 | tail -12
echo "=== mcp get srvstr (no variable exported)"; timeout 60 $CP mcp get srvstr 2>&1 | tail -15
echo "=== mcp get srvstr with CISTERNAL_TELEMETRY_SHADOW=off exported"
CISTERNAL_TELEMETRY_SHADOW=off timeout 60 $CP mcp get srvstr 2>&1 | tail -15
