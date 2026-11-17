#!/usr/bin/env bash
# Probe (offline, scratch HOME, no credentials): does an Antigravity plugin whose mcp_config.json declares
# mcpServers.<s>.variables install ENABLED or DISABLED, and does `agy plugin validate` accept it?
set -u
S=/home/marielle/scratch/qg-261112-findings/probe_agy
rm -rf $S; mkdir -p $S/home $S/plug_vars/.claude-plugin $S/plug_novars
real_before=$(ls -A ~/.gemini/config/plugins 2>/dev/null | md5sum | cut -c1-8)
mk() {  # dir, with_vars
  d=$1
  cat > $d/plugin.json <<'JSON'
{"name":"__NAME__","description":"probe plugin"}
JSON
  sed -i "s/__NAME__/$(basename $d | tr -d _)/" $d/plugin.json
  if [ "$2" = vars ]; then
    cat > $d/mcp_config.json <<'JSON'
{"mcpServers":{"srv":{"command":"echo","args":["hi"],"env":{"CISTERNAL_PLUGIN_OPTION_PROBE_SHADOW":"${CISTERNAL_PLUGIN_OPTION_PROBE_SHADOW}"},
 "variables":[{"name":"CISTERNAL_PLUGIN_OPTION_PROBE_SHADOW","title":"Shadow records","description":"Type inherit, on or off."}]}}}
JSON
  else
    cat > $d/mcp_config.json <<'JSON'
{"mcpServers":{"srv":{"command":"echo","args":["hi"],"env":{}}}}
JSON
  fi
}
rm -rf $S/plug_vars; mkdir -p $S/plug_vars; mk $S/plug_vars vars
mk $S/plug_novars novars
export HOME=$S/home XDG_CONFIG_HOME=$S/home/.config
echo "=== validate (with variables)"; agy plugin validate $S/plug_vars --json 2>&1 | head -20
echo "=== install both (scratch HOME)"
agy plugin install $S/plug_vars 2>&1 | tail -4
agy plugin install $S/plug_novars 2>&1 | tail -4
echo "=== list --json"; agy plugin list --json 2>&1 | head -40
echo "=== real ~/.gemini plugins dir unchanged?"
unset HOME XDG_CONFIG_HOME
[ "$real_before" = "$(ls -A /home/marielle/.gemini/config/plugins 2>/dev/null | md5sum | cut -c1-8)" ] && echo UNCHANGED || echo CHANGED
find $S/home -maxdepth 6 -type f | head -20
