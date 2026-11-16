#!/usr/bin/env bash
# Probe P2 (offline, scratch HOME): an Antigravity plugin whose MCP env has an UNDECLARED ${X} placeholder (no `variables`).
# Does it install enabled? Does `agy plugin validate` flag it? (Runtime expansion needs a live session: docs-only.)
set -u
S=/home/marielle/scratch/qg-261112-findings/probe_agy2
rm -rf $S; mkdir -p $S/home $S/plug_undeclared
cat > $S/plug_undeclared/plugin.json <<'JSON'
{"name":"plugundeclared","description":"probe plugin","version":"1.0.0"}
JSON
cat > $S/plug_undeclared/mcp_config.json <<'JSON'
{"mcpServers":{"srv":{"command":"echo","args":["hi"],"env":{"CISTERNAL_PLUGIN_OPTION_PROBE_SHADOW":"${CISTERNAL_PLUGIN_OPTION_PROBE_SHADOW}"}}}}
JSON
export HOME=$S/home XDG_CONFIG_HOME=$S/home/.config
echo "=== validate"; agy plugin validate $S/plug_undeclared --json 2>&1 | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps(d["findings"], indent=1))'
echo "=== install"; agy plugin install $S/plug_undeclared 2>&1 | tail -4
echo "=== list"; agy plugin list --json 2>&1 | python3 -c 'import json,sys; [print(p["name"], "enabled=", p["enabled"]) for p in json.load(sys.stdin)]'
