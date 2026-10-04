#!/usr/bin/env bash
# Verify Maestro + jq are installed and on PATH. Print install commands and exit non-zero if not.
set -euo pipefail

# Auto-augment PATH for common Maestro / Android SDK locations (non-interactive shells skip .zshrc).
[[ -d "$HOME/.maestro/bin" ]] && export PATH="$PATH:$HOME/.maestro/bin"
[[ -d "$HOME/Library/Android/sdk/platform-tools" ]] && export PATH="$PATH:$HOME/Library/Android/sdk/platform-tools"
[[ -d "$HOME/Library/Android/sdk/emulator" ]] && export PATH="$PATH:$HOME/Library/Android/sdk/emulator"

missing=0

if ! command -v maestro >/dev/null 2>&1; then
  echo "❌ maestro CLI not found on PATH."
  echo "   Install:  curl -Ls \"https://get.maestro.mobile.dev\" | bash"
  echo "   Then add: export PATH=\"\$PATH:\$HOME/.maestro/bin\""
  missing=1
else
  echo "✅ maestro: $(maestro --version 2>/dev/null | head -1 || echo 'installed')"
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "❌ jq not found on PATH."
  echo "   Install:  brew install jq"
  missing=1
else
  echo "✅ jq:      $(jq --version)"
fi

if ! command -v xcrun >/dev/null 2>&1; then
  echo "⚠️  xcrun not found — iOS Simulator runs will be unavailable."
  echo "   Install Xcode from the Mac App Store, then: xcode-select --install"
fi

if ! command -v adb >/dev/null 2>&1; then
  echo "⚠️  adb not found — Android Emulator runs will be unavailable."
  echo "   Install Android Studio, then add platform-tools to PATH."
fi

if [[ $missing -ne 0 ]]; then
  echo ""
  echo "Install the missing tools above, then re-run the skill."
  exit 1
fi

echo ""
echo "All required tools present."
exit 0
