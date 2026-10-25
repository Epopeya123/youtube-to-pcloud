# yt2pcloud: YouTube → phone → pCloud

Share a YouTube (or YouTube Music) link to **Termux** on the phone and:

1. the audio downloads with its cover art, as `.m4a` (YouTube's own AAC audio, not re-encoded);
2. Termux asks **"Upload to pCloud /My Music? [y/N]"**. Enter or `n` keeps it on the phone only;
3. if you say yes, it uploads and shows your pCloud playlists to pick one, several (`1,3`), a new one (`n`), or none (Enter).

The same file is never uploaded twice: if it is already in the folder, that copy is used.

## New phone (or first install)

1. Install **Termux from F-Droid** (<https://f-droid.org/packages/com.termux/>); this setup was built and tested with
   that version, not the Google Play one.
2. Let Termux open from the share menu: Android Settings → Apps → Termux → **Display over other apps** (Samsung calls
   it **Appear on top**) → allow.
3. Open Termux and run:

   ```bash
   pkg install -y git
   git clone https://github.com/Epopeya123/youtube-to-pcloud ~/youtube-to-pcloud
   bash ~/youtube-to-pcloud/yt2pcloud/install.sh
   ```

4. During the install, allow Termux to access your files when Android asks.
5. Log in to pCloud when asked: email, password, then the two-factor code (authenticator app or SMS) if your account
   uses one. pCloud then trusts the phone, so a later login may skip the code.
6. Test it: in YouTube, tap **Share → Termux**. The audio downloads, then Termux asks whether to upload it.

The installer:

- installs `python`, `ffmpeg`, `nodejs`, `yt-dlp[default]` (or plain `yt-dlp` and `yt-dlp-ejs` if that fails to
  build) and `mutagen`;
- puts the share script in `~/bin/termux-url-opener`, keeping the old one as `termux-url-opener.bak`;
- keeps downloading into whatever folder your previous script used, otherwise `Internal storage > Music`;
- logs you in to pCloud once. It uses pCloud's digest login, so your password never leaves the phone and is
  not saved. Only a login token is kept, in `~/.config/yt2pcloud/pcloud.json`. Two-factor codes (SMS or app)
  are asked for if your account uses them.

**Update** later with:

```bash
git -C ~/youtube-to-pcloud pull && bash ~/youtube-to-pcloud/yt2pcloud/install.sh
```

## If something goes wrong

- **"pCloud did not accept that email and password"**: usually a typo. Try again with
  `python3 ~/youtube-to-pcloud/yt2pcloud/pcloud.py login`.
- **Every download fails**, for example with `HTTP Error 403`: YouTube changed something and yt-dlp needs updating.
  Run the update command above.
- **"Sign in to confirm you're not a bot"**: YouTube distrusts the current network for a while. Try later, or switch
  between Wi-Fi and mobile data.
- **Anything else**: copy what Termux printed and paste it to Claude.

## New computer (so Claude can download and upload for you)

On a computer, Claude can do what the share script does ("add this video to my Chill playlist"). Once per computer:

1. Install Python 3, ffmpeg, Node.js and yt-dlp. On Windows:

   ```bash
   winget install Python.Python.3.13
   winget install Gyan.FFmpeg
   winget install OpenJS.NodeJS
   pip install -U "yt-dlp[default]"
   ```

   On macOS: `brew install python ffmpeg node yt-dlp`.
2. Clone this repository and log in once (each computer keeps its own login token):

   ```bash
   git clone https://github.com/Epopeya123/youtube-to-pcloud
   python youtube-to-pcloud/yt2pcloud/pcloud.py login
   ```

Then a video goes to pCloud like this, with the same yt-dlp options as the phone:

```bash
yt-dlp --js-runtimes node --no-playlist -f "bestaudio[ext=m4a]/bestaudio/best" -x --audio-format m4a \
    --embed-thumbnail --add-metadata -o "%(title)s.%(ext)s" "URL"
python youtube-to-pcloud/yt2pcloud/pcloud.py send "Title.m4a" -p "Chill"
```

The computer route has not been tried end to end yet; the phone route has.

## Commands

`pcloud.py` works on its own too, in Termux or on a computer (Python 3, nothing to install):

```bash
python3 pcloud.py send "Song.m4a" -p "Chill"   # upload and add to a playlist, no questions
python3 pcloud.py ask "Song.m4a"               # the same questions the share script asks
python3 pcloud.py playlists                    # your playlists
python3 pcloud.py folder "/My Music"           # change where uploads go
python3 pcloud.py login / whoami / logout
```

`send` is what Claude runs when you ask it to "upload this to pCloud and add it to my Chill playlist"
on a computer that has this repo.

## Settings

`~/.config/yt2pcloud/settings.sh` (phone only):

```bash
DOWNLOAD_DIR="$HOME/storage/shared/Music"     # where downloads are saved
YT2PCLOUD_HOME="/data/data/com.termux/files/home/youtube-to-pcloud/yt2pcloud"
```

## How it talks to pCloud

Plain HTTPS calls to pCloud's public API ([docs.pcloud.com](https://docs.pcloud.com)):
`getdigest` + `userinfo` to log in (two-factor accounts go through pCloud's own `login` and `tfa_login`, see
`CLAUDE.md`), `createfolderifnotexists`, `stat` and `uploadfile` to upload,
and `collection_list` / `collection_linkfiles` / `collection_create` for playlists (pCloud calls playlists
"collections", type 1). Accounts live in the EU (`eapi.pcloud.com`) or the US (`api.pcloud.com`); the
login tries the EU first and follows pCloud's "wrong region" answer (error 2321) if needed.

## Tests

```bash
python3 -m unittest discover -s yt2pcloud/tests -v
```

They run against a fake pCloud (`tests/mock_pcloud.py`): login in both regions, two-factor, expired
tokens, duplicate uploads, playlists, the real share script with yt-dlp downloading from a local web
server, and the installer with fake `pkg`/`pip`. They do not touch a real pCloud account.
