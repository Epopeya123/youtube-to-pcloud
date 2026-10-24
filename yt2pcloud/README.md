# yt2pcloud: YouTube → phone → pCloud

Share a YouTube (or YouTube Music) link to **Termux** on the phone and:

1. the audio downloads with its cover art, as `.m4a` (YouTube's own AAC audio, not re-encoded);
2. Termux asks **"Upload to pCloud /My Music? [y/N]"**. Enter or `n` keeps it on the phone only;
3. if you say yes, it uploads and shows your pCloud playlists to pick one, several (`1,3`), a new one (`n`), or none (Enter).

The same file is never uploaded twice: if it is already in the folder, that copy is used.

## Install on the phone (Termux)

```bash
pkg install -y git
git clone https://github.com/Epopeya123/youtube-to-pcloud ~/youtube-to-pcloud
bash ~/youtube-to-pcloud/yt2pcloud/install.sh
```

The installer:

- installs `python`, `ffmpeg`, `nodejs`, `yt-dlp[default]` and `mutagen`;
- puts the share script in `~/bin/termux-url-opener`, keeping the old one as `termux-url-opener.bak`;
- keeps downloading into whatever folder your previous script used, otherwise `Internal storage > Music`;
- logs you in to pCloud once. It uses pCloud's digest login, so your password never leaves the phone and is
  not saved. Only a login token is kept, in `~/.config/yt2pcloud/pcloud.json`. Two-factor codes (SMS or app)
  are asked for if your account uses them.

**Update** later with:

```bash
git -C ~/youtube-to-pcloud pull && bash ~/youtube-to-pcloud/yt2pcloud/install.sh
```

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
`getdigest` + `userinfo` to log in, `createfolderifnotexists`, `stat` and `uploadfile` to upload,
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
