#!/usr/bin/env bash
# Adds StudyLapse to your app launcher (GNOME / KDE / etc.).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DIR" "$HOME/.local/share/applications"
cp "$ROOT/packaging/studylapse.svg" "$ICON_DIR/studylapse.svg"
sed "s|@ROOT@|$ROOT|g" "$ROOT/packaging/studylapse.desktop" > "$HOME/.local/share/applications/studylapse.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Installed. Look for 'StudyLapse' in your app launcher."
