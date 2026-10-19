#!/usr/bin/env sh
# Puts `bioterminal` on your PATH by linking it into ~/.local/bin (or $BIN).
set -e

DIR=$(cd "$(dirname "$0")" && pwd)
BIN="${BIN:-$HOME/.local/bin}"

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
    echo "bioterminal needs Python 3.8 or newer (python3 --version)" >&2
    exit 1
fi

mkdir -p "$BIN"
chmod +x "$DIR/bioterminal.py"
ln -sf "$DIR/bioterminal.py" "$BIN/bioterminal"
echo "✦ linked $BIN/bioterminal -> $DIR/bioterminal.py"

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "  $BIN isn't on your PATH yet — add this to ~/.zshrc or ~/.bashrc:"
       echo "    export PATH=\"$BIN:\$PATH\"" ;;
esac

cat <<'EOF'

  Optional, for tmux users — add to ~/.tmux.conf, then run: tmux source ~/.tmux.conf

    set -ag terminal-overrides ",*:RGB"
    bind C display-popup -E -w 85% -h 80% -b rounded "bioterminal --pane '#{pane_id}'"

  Then press prefix + C anywhere to open bioterminal as a popup.
EOF
