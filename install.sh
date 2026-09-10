#!/bin/bash
#
# chicken_and_egg — get a fresh Mac to the point where it can set itself up.
#
#   curl -fsSL https://raw.githubusercontent.com/markryall/chicken_and_egg/main/install.sh | bash
#
# Optionally name the runbook to continue with once the machine can
# authenticate, as owner/repo:
#
#   curl -fsSL .../install.sh | bash -s -- markryall/dotfiles-private
#
# It installs a small runner, fetches a public first-phase runbook, and hands
# over. Nothing here needs credentials — that is the whole point of the split.
#
# Prefer to read before running? Reasonable:
#
#   curl -fsSL .../install.sh -o /tmp/cae.sh && less /tmp/cae.sh && bash /tmp/cae.sh
#
set -euo pipefail

REPO="${CAE_REPO:-markryall/chicken_and_egg}"
BRANCH="${CAE_BRANCH:-main}"
RAW="https://raw.githubusercontent.com/$REPO/$BRANCH"
BIN="${CAE_BIN:-$HOME/.local/bin}"
WORK="${TMPDIR:-/tmp}/chicken_and_egg"

# The runbook to continue with after this phase. Reaches the runbook as the
# default of its first question, so passing it is a convenience and never a
# requirement.
export RUNBOOK_TARGET="${1:-}"

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31m==>\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "This bootstraps macOS. You are on $(uname -s)."

# Command Line Tools first: python3 and git both arrive with them, and on a
# fresh Mac /usr/bin/python3 is a stub that pops the installer rather than
# running anything.
if ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
  say "Installing the Command Line Tools — a dialog will open."
  /usr/bin/xcode-select --install >/dev/null 2>&1 || true
  warn "Finish that installer, then run this command again."
  exit 0
fi

PYTHON=/usr/bin/python3
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
  || die "Need python3 3.8+; $PYTHON is $("$PYTHON" -V 2>&1)"

say "Installing the runner to $BIN/runbook"
mkdir -p "$BIN"
curl -fsSL "$RAW/runbook.py" -o "$BIN/runbook.tmp"
head -1 "$BIN/runbook.tmp" | grep -q python \
  || die "That did not look like the runner — refusing to install it."
mv "$BIN/runbook.tmp" "$BIN/runbook"
chmod +x "$BIN/runbook"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) warn "$BIN is not on your PATH — the first runbook step fixes that." ;;
esac

say "Fetching the first-phase runbook"
mkdir -p "$WORK"
curl -fsSL "$RAW/runbooks/new-mac.md" -o "$WORK/new-mac.md"

# Piped into bash, this script *is* stdin, and by now that pipe is drained.
# The runner asks questions, so hand it the terminal rather than the husk of
# the pipe — otherwise every prompt reads EOF and the runbook looks like it
# aborts on the first step. The runner reopens /dev/tty itself as well; this
# covers the interactive steps it spawns, and says something useful when there
# is no terminal at all.
if [ ! -r /dev/tty ]; then
  warn "No terminal available, so the runner has nothing to ask. Run it yourself:"
  echo "    $BIN/runbook $WORK/new-mac.md"
  exit 0
fi

say "Here we go."
echo
exec "$PYTHON" "$BIN/runbook" "$WORK/new-mac.md" < /dev/tty
