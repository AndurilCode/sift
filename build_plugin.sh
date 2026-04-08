#!/usr/bin/env bash
# Build the sift plugin: bundles the analyzer into a .pyz zipapp
# and copies it into the plugin skill directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$SCRIPT_DIR/skills/usage-analysis"
BUILD_DIR="$SCRIPT_DIR/.build"

echo "Building sift plugin..."

# Clean
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/app"

# Copy source modules into app package
cp "$SCRIPT_DIR/main.py" "$BUILD_DIR/app/__main__.py"
cp "$SCRIPT_DIR/report.py" "$BUILD_DIR/app/"
cp "$SCRIPT_DIR/dashboard.py" "$BUILD_DIR/app/"
cp "$SCRIPT_DIR/export_json.py" "$BUILD_DIR/app/"
cp -r "$SCRIPT_DIR/sources" "$BUILD_DIR/app/"
cp -r "$SCRIPT_DIR/metrics" "$BUILD_DIR/app/"

# Create zipapp
python3 -m zipapp "$BUILD_DIR/app" \
    --output "$SKILL_DIR/analyzer.pyz" \
    --python "/usr/bin/env python3"

# Clean build dir
rm -rf "$BUILD_DIR"

SIZE=$(du -h "$SKILL_DIR/analyzer.pyz" | cut -f1)

# Bump patch version in plugin.json and marketplace.json
PLUGIN_JSON="$SCRIPT_DIR/.claude-plugin/plugin.json"
MARKET_JSON="$SCRIPT_DIR/.claude-plugin/marketplace.json"

OLD_VER=$(python3 -c "import json; print(json.load(open('$PLUGIN_JSON'))['version'])")
IFS='.' read -r MAJOR MINOR PATCH <<< "$OLD_VER"
NEW_VER="$MAJOR.$MINOR.$((PATCH + 1))"

python3 -c "
import json
for path in ['$PLUGIN_JSON', '$MARKET_JSON']:
    with open(path) as f: d = json.load(f)
    if 'version' in d: d['version'] = '$NEW_VER'
    for p in d.get('plugins', []):
        if 'version' in p: p['version'] = '$NEW_VER'
    with open(path, 'w') as f: json.dump(d, f, indent=2); f.write('\n')
"

echo "Built: $SKILL_DIR/analyzer.pyz ($SIZE) — v$NEW_VER"

# Auto-configure git hooks on first build
HOOKS_PATH=$(git -C "$SCRIPT_DIR" config --local core.hooksPath 2>/dev/null || true)
if [ "$HOOKS_PATH" != "hooks" ]; then
    git -C "$SCRIPT_DIR" config --local core.hooksPath hooks
    echo "Configured git hooks (core.hooksPath=hooks)"
fi
