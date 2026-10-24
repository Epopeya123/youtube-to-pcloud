#!/data/data/com.termux/files/usr/bin/bash
# One-time setup in Termux. Safe to run again: it is also how you update.
#   bash ~/youtube-to-pcloud/yt2pcloud/install.sh
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
CONF_DIR="$HOME/.config/yt2pcloud"
SETTINGS="$CONF_DIR/settings.sh"
OPENER="$HOME/bin/termux-url-opener"

echo "== Installing tools (skips what is already there)"
pkg install -y python ffmpeg nodejs
# yt-dlp[default] also pulls in C extensions that Termux has to compile, which fails
# without a compiler; then install the plain packages the old phone setup used.
pip install -U "yt-dlp[default]" mutagen || pip install -U yt-dlp yt-dlp-ejs mutagen

[ -d "$HOME/storage/shared" ] || termux-setup-storage

mkdir -p "$CONF_DIR" "$HOME/bin"

# Keep downloading into the folder the previous share script used, if any.
if [ ! -f "$SETTINGS" ]; then
    dir="Music"
    old="$(grep -o 'storage/shared/[^"]*' "$OPENER" 2>/dev/null | head -n 1 || true)"
    [ -n "$old" ] && dir="${old#storage/shared/}"
    # shellcheck disable=SC2016  # $HOME is meant to stay literal; it expands when the file is read
    printf 'DOWNLOAD_DIR="$HOME/storage/shared/%s"\n' "$dir" > "$SETTINGS"
fi
# Point the share script at this copy of the repo.
sed -i '/^YT2PCLOUD_HOME=/d' "$SETTINGS"
printf 'YT2PCLOUD_HOME="%s"\n' "$HERE" >> "$SETTINGS"

if [ -f "$OPENER" ] && ! cmp -s "$OPENER" "$HERE/termux-url-opener"; then
    cp "$OPENER" "$OPENER.bak"
    echo "== Previous share script saved as $OPENER.bak"
fi
cp "$HERE/termux-url-opener" "$OPENER"
chmod +x "$OPENER"

# shellcheck source=/dev/null
echo "== Downloads go to: $(. "$SETTINGS"; echo "$DOWNLOAD_DIR")"
if python3 "$HERE/pcloud.py" whoami >/dev/null 2>&1; then
    python3 "$HERE/pcloud.py" whoami
else
    echo "== Log in to pCloud once (your password is not saved, only a login token)"
    python3 "$HERE/pcloud.py" login
fi

echo
echo "All set. Share a YouTube link to Termux to try it."
