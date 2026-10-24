#!/usr/bin/env python3
"""Upload songs to pCloud and add them to your pCloud playlists.

    python3 pcloud.py login                    log in once (saves a token, never your password)
    python3 pcloud.py ask FILE...              ask whether to upload, then which playlist
    python3 pcloud.py send FILE... [-p NAME]   upload without questions, optionally into playlist NAME
    python3 pcloud.py playlists                list your playlists
    python3 pcloud.py folder [PATH]            show or change the upload folder (default: /My Music)
    python3 pcloud.py whoami                   check the saved login
    python3 pcloud.py logout                   forget the saved login

Standard library only, so it runs as-is in Termux, on Windows and on macOS.
"""

import argparse
import getpass
import hashlib
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

CONFIG_FILE = os.environ.get("YT2PCLOUD_CONFIG") or os.path.join(
    os.path.expanduser("~"), ".config", "yt2pcloud", "pcloud.json"
)
DEFAULT_FOLDER = "/My Music"

# Each pCloud account lives in one region, EU or US, and only that region's
# API host accepts it. Try the EU host first; a wrong guess is answered with
# error 2321, which names the right host.
HOSTS = [h for h in os.environ.get("YT2PCLOUD_HOSTS", "eapi.pcloud.com,api.pcloud.com").split(",") if h]
SCHEME = os.environ.get("YT2PCLOUD_SCHEME", "https")
TOKEN_LIFETIME = 365 * 24 * 3600  # one year, the same as pCloud's own Python SDK asks for
DEVICE = "yt2pcloud"
OS_ID = {"win32": 5, "darwin": 6}.get(sys.platform, 7)  # pCloud's own client: 5 Windows, 6 macOS, 7 Linux

LOGIN_EXPIRED = {1000, 2000, 2094, 2095}  # "log in required/failed", "invalid token"
LOGIN_FAILED = 2000
TWO_FACTOR_NEEDED = 2297
WRONG_REGION = 2321
NETWORK = -1


class PCloudError(Exception):
    def __init__(self, result, message, response=None):
        super().__init__(message)
        self.result = result
        self.response = response or {}


# --- HTTP ---------------------------------------------------------------------

def _call(host, method, params=None, upload=None, timeout=120):
    """Call a pCloud API method and return its JSON. Raises PCloudError."""
    url = f"{SCHEME}://{host}/{method}"
    params = {k: v for k, v in (params or {}).items() if v is not None}
    if upload is None:
        request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params))
    else:
        body, content_type = _multipart(params, upload)
        request = urllib.request.Request(url, data=body, headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise PCloudError(NETWORK, f"Could not reach pCloud ({reason}). Check the internet connection.")
    except ValueError:
        raise PCloudError(NETWORK, f"pCloud sent an unreadable answer to {method}.")
    if data.get("result", 0) != 0:
        raise PCloudError(data["result"], data.get("error", f"error {data['result']}"), data)
    return data


def _multipart(fields, path):
    """Build a multipart/form-data body: the fields first, then the file."""
    boundary = uuid.uuid4().hex
    filename = os.path.basename(path)
    quoted = filename.replace('"', "%22").replace("\r", "%0D").replace("\n", "%0A")
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    chunks = []
    for key, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )
    chunks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{quoted}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode()
    )
    with open(path, "rb") as f:
        chunks.append(f.read())
    chunks.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


# --- Saved settings -------------------------------------------------------------

def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # the token is private
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    os.replace(tmp, CONFIG_FILE)


# --- Logging in -----------------------------------------------------------------

def _password_digest(email, password, digest):
    # pCloud's digest login: the password itself never leaves the device.
    email_hash = hashlib.sha1(email.lower().encode()).hexdigest()
    return hashlib.sha1((password + email_hash + digest).encode()).hexdigest()


def _ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        raise PCloudError(LOGIN_FAILED, "No answer could be read (is this running without a keyboard?).")


def _two_factor(host, email, password, deviceid, response):
    # userinfo answers 2297 without the token that tfa_login needs. pCloud's own
    # client logs in with the undocumented "login" method instead, which sends it.
    if not response.get("token"):
        digest = _call(host, "getdigest")["digest"]
        try:
            return _call(host, "login", {
                "getauth": 1, "username": email, "digest": digest,
                "passworddigest": _password_digest(email, password, digest),
                "authexpire": TOKEN_LIFETIME, "device": DEVICE, "deviceid": deviceid, "os": OS_ID,
            })
        except PCloudError as e:
            if e.result != TWO_FACTOR_NEEDED:
                raise
            response = e.response
    token = response.get("token")
    if not token:
        raise PCloudError(TWO_FACTOR_NEEDED, "pCloud asked for a two-factor code but sent no login token "
                                             f"(its answer had: {', '.join(sorted(response))}).")
    if response.get("tfatype") == 1:
        try:
            _call(host, "tfa_sendcodeviasms", {"token": token})
            print("pCloud sent you a login code by SMS.")
        except PCloudError as e:
            print(f"pCloud could not send the SMS ({e}).")
        prompt = "SMS code: "
    else:
        prompt = "Code from your authenticator app: "
    code = _ask(prompt).strip().replace(" ", "")
    return _call(host, "tfa_login", {
        "token": token, "code": code, "trustdevice": 1, "getauth": 1,
        "authexpire": TOKEN_LIFETIME, "device": DEVICE, "deviceid": deviceid, "os": OS_ID,
    })


def login(email=None, password=None):
    """Log in, save the token, and return (host, token)."""
    email = (email or _ask("pCloud email: ")).strip()
    if password is None:
        if sys.stdin.isatty():
            try:
                password = getpass.getpass("pCloud password (not shown): ")
            except EOFError:
                raise PCloudError(LOGIN_FAILED, "No password could be read.")
        else:  # piped in by a script or a test: there is no screen to hide it from
            password = _ask("pCloud password: ")

    deviceid = load_config().get("deviceid") or uuid.uuid4().hex  # the same id lets "trust this device" stick
    hosts, tried, last_error, rejected = list(HOSTS), set(), None, False
    while hosts:
        host = hosts.pop(0)
        if host in tried:
            continue
        tried.add(host)
        try:
            digest = _call(host, "getdigest")["digest"]
            result = _call(host, "userinfo", {
                "getauth": 1, "logout": 1, "username": email, "digest": digest,
                "passworddigest": _password_digest(email, password, digest),
                "authexpire": TOKEN_LIFETIME, "device": DEVICE,
            })
        except PCloudError as e:
            if e.result == WRONG_REGION:
                right_host = (e.response.get("location") or {}).get("api")
                if right_host:
                    hosts.insert(0, right_host)
                last_error = e
                continue
            if e.result == TWO_FACTOR_NEEDED:
                result = _two_factor(host, email, password, deviceid, e.response)
            elif e.result == LOGIN_FAILED:
                # wrong password, or an account in the other region: try the other host
                last_error, rejected = e, True
                continue
            else:
                raise
        config = load_config()
        config.update({"host": host, "auth": result["auth"], "email": email, "deviceid": deviceid})
        save_config(config)
        return host, result["auth"]
    if rejected:
        raise PCloudError(LOGIN_FAILED, "pCloud did not accept that email and password.")
    raise last_error or PCloudError(NETWORK, "No pCloud server answered.")


# --- The things we do with pCloud --------------------------------------------------

class PCloud:
    def __init__(self):
        config = load_config()
        self.host = config.get("host")
        self.auth = config.get("auth")
        self.folder = config.get("folder", DEFAULT_FOLDER)

    def call(self, method, params=None, upload=None):
        if not self.auth:
            print("You are not logged in to pCloud yet.")
            self.host, self.auth = login()
        try:
            return _call(self.host, method, {**(params or {}), "auth": self.auth}, upload)
        except PCloudError as e:
            if e.result not in LOGIN_EXPIRED:
                raise
            print("Your pCloud login has expired. Log in again.")
            self.host, self.auth = login()
            return _call(self.host, method, {**(params or {}), "auth": self.auth}, upload)

    def upload(self, path):
        """Upload path into the upload folder. Returns (fileid, uploaded_now)."""
        name = os.path.basename(path)
        size = os.path.getsize(path)
        folderid = self.call("createfolderifnotexists", {"path": self.folder})["metadata"]["folderid"]
        try:
            existing = self.call("stat", {"path": self.folder.rstrip("/") + "/" + name})["metadata"]
            if existing.get("size") == size:
                return existing["fileid"], False
        except PCloudError as e:
            if e.result == NETWORK or e.result in LOGIN_EXPIRED:
                raise
            # anything else means it is not there yet
        result = self.call("uploadfile", {
            "folderid": folderid, "nopartial": 1, "renameifexists": 1,
            "mtime": int(os.path.getmtime(path)),
        }, upload=path)
        return result["metadata"][0]["fileid"], True

    def playlists(self):
        collections = self.call("collection_list", {"type": 1}).get("collections", [])
        return [c for c in collections if not c.get("system") and c.get("ismine", True)]

    def add_to_playlist(self, playlist_id, fileids):
        result = self.call("collection_linkfiles", {
            "collectionid": playlist_id, "fileids": ",".join(str(f) for f in fileids),
        })
        return all(item.get("result", 0) == 0 for item in result.get("linkresult") or [])

    def create_playlist(self, name, fileids):
        self.call("collection_create", {
            "name": name, "type": 1, "fileids": ",".join(str(f) for f in fileids),
        })


# --- Commands ------------------------------------------------------------------------

def _upload_all(cloud, paths):
    fileids = []
    for path in paths:
        name = os.path.basename(path)
        print(f"Uploading {name} ...", flush=True)
        fileid, uploaded = cloud.upload(path)
        print("  done" if uploaded else f"  already in {cloud.folder}, using that copy")
        fileids.append(fileid)
    return fileids


def cmd_ask(cloud, paths):
    what = os.path.basename(paths[0]) if len(paths) == 1 else f"these {len(paths)} files"
    answer = _ask(f"\nUpload {what} to pCloud {cloud.folder}? [y/N] ").strip().lower()
    if answer not in ("y", "yes", "s", "si", "sí"):
        print("Not uploaded. The file stays on the phone.")
        return
    fileids = _upload_all(cloud, paths)

    playlists = cloud.playlists()
    print("\nAdd to a playlist?")
    for number, playlist in enumerate(playlists, 1):
        print(f"  {number}) {playlist['name']}")
    print("  n) New playlist")
    choice = _ask("Number (several: 1,3), n, or Enter for none: ").strip().lower()
    for part in [p for p in choice.replace(" ", "").split(",") if p]:
        if part == "n":
            name = _ask("Name of the new playlist: ").strip()
            if name:
                cloud.create_playlist(name, fileids)
                print(f"  created playlist {name}")
        elif part.isdigit() and 1 <= int(part) <= len(playlists):
            playlist = playlists[int(part) - 1]
            if cloud.add_to_playlist(playlist["id"], fileids):
                print(f"  added to {playlist['name']}")
            else:
                print(f"  could not add to {playlist['name']} (maybe it is already there)")
        else:
            print(f"  skipped '{part}': not in the list")


def cmd_send(cloud, paths, playlist_names):
    playlists = cloud.playlists() if playlist_names else []
    by_name = {p["name"].casefold(): p for p in playlists}
    missing = [n for n in playlist_names if n.casefold() not in by_name]
    if missing:
        names = ", ".join(p["name"] for p in playlists) or "none"
        raise PCloudError(0, f"No playlist called {', '.join(missing)}. Your playlists: {names}.")
    fileids = _upload_all(cloud, paths)
    for name in playlist_names:
        playlist = by_name[name.casefold()]
        ok = cloud.add_to_playlist(playlist["id"], fileids)
        print(f"  added to {playlist['name']}" if ok else f"  could not add to {playlist['name']}")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:  # song titles can have characters a Windows console cannot print
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Upload songs to pCloud and add them to playlists.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="log in once")
    sub.add_parser("logout", help="forget the saved login")
    sub.add_parser("whoami", help="check the saved login")
    sub.add_parser("playlists", help="list your playlists")
    folder = sub.add_parser("folder", help="show or change the upload folder")
    folder.add_argument("path", nargs="?")
    ask = sub.add_parser("ask", help="ask before uploading, then pick playlists")
    ask.add_argument("files", nargs="+")
    send = sub.add_parser("send", help="upload without questions")
    send.add_argument("files", nargs="+")
    send.add_argument("-p", "--playlist", action="append", default=[], help="playlist to add to (repeatable)")
    args = parser.parse_args(argv)

    try:
        if args.command in ("ask", "send"):
            missing = [f for f in args.files if not os.path.isfile(f)]
            if missing:
                raise PCloudError(0, f"File not found: {', '.join(missing)}")
        cloud = PCloud()
        if args.command == "login":
            host, _ = login()
            print(f"Logged in ({host}). Uploads go to {cloud.folder}.")
        elif args.command == "logout":
            if cloud.auth:
                try:
                    _call(cloud.host, "logout", {"auth": cloud.auth})
                except PCloudError:
                    pass
            config = load_config()
            config.pop("auth", None)
            save_config(config)
            print("Logged out.")
        elif args.command == "whoami":
            if not cloud.auth:
                raise PCloudError(LOGIN_FAILED, "Not logged in. Run: python3 pcloud.py login")
            info = _call(cloud.host, "userinfo", {"auth": cloud.auth})
            print(f"{info.get('email')} on {cloud.host}. Uploads go to {cloud.folder}.")
        elif args.command == "playlists":
            for playlist in cloud.playlists():
                print(f"{playlist['name']}  ({playlist.get('items', 0)} songs)")
        elif args.command == "folder":
            if args.path:
                path = "/" + args.path.strip("/")
                config = load_config()
                config["folder"] = path
                save_config(config)
                print(f"Uploads now go to {path}")
            else:
                print(cloud.folder)
        elif args.command == "ask":
            cmd_ask(cloud, args.files)
        elif args.command == "send":
            cmd_send(cloud, args.files, args.playlist)
    except PCloudError as e:
        print(f"pCloud: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
