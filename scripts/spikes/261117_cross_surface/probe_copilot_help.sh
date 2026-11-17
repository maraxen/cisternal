#!/usr/bin/env bash
S=/home/marielle/scratch/qg-261112-findings/probe_copilot
mkdir -p $S/home
export HOME=$S/home COPILOT_HOME=$S/home/.copilot XDG_CONFIG_HOME=$S/home/.config
CP="bun /home/marielle/.bun/install/global/node_modules/@github/copilot/npm-loader.js"
echo "=== copilot --help (commands)"; $CP --help 2>&1 | rg -i 'plugin|mcp|config|inspect|validate|list' | head -20
echo "=== copilot plugin --help"; $CP plugin --help 2>&1 | head -25
echo "=== copilot mcp --help"; $CP mcp --help 2>&1 | head -20
