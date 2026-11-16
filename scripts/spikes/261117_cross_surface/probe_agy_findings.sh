#!/usr/bin/env bash
S=/home/marielle/scratch/qg-261112-findings/probe_agy
export HOME=$S/home XDG_CONFIG_HOME=$S/home/.config
agy plugin validate $S/plug_vars --json 2>&1 | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps(d["findings"], indent=1))'
echo "--- installed plugin state files:"
cat $S/home/.gemini/config/import_manifest.json 2>/dev/null | head -20
echo "--- does enabling in the CLI work without values?"
agy plugin enable plugvars 2>&1 | tail -3
agy plugin list --json 2>&1 | python3 -c 'import json,sys; [print(p["name"], p["enabled"]) for p in json.load(sys.stdin)]'
