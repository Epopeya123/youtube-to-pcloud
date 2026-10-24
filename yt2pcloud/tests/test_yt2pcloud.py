"""Tests for yt2pcloud, against the fake pCloud in mock_pcloud.py.

    python3 -m unittest discover -s yt2pcloud/tests -v

The share-script test also needs yt-dlp and ffmpeg; it is skipped without them.
"""

import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

from mock_pcloud import EMAIL, PASSWORD, TFA_CODE, MockPCloud

HERE = os.path.dirname(os.path.abspath(__file__))
YT2PCLOUD = os.path.dirname(HERE)
PCLOUD_PY = os.path.join(YT2PCLOUD, "pcloud.py")
LOGIN = f"{EMAIL}\n{PASSWORD}\n"


class Base(unittest.TestCase):
    account_region = "eu"
    tfa_type = None
    wrong_region_error = 2321

    def setUp(self):
        self.mock = MockPCloud(self.account_region, self.tfa_type, self.wrong_region_error)
        self.addCleanup(self.mock.close)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.config = os.path.join(self.tmp, "config", "pcloud.json")
        self.env = dict(os.environ,
                        YT2PCLOUD_CONFIG=self.config,
                        YT2PCLOUD_SCHEME="http",
                        YT2PCLOUD_HOSTS=f"{self.mock.hosts['eu']},{self.mock.hosts['us']}",
                        HOME=self.tmp)

    def run_cli(self, *args, stdin=""):
        # piped stdin: pcloud.py reads the password with input(), as it does for any script
        return subprocess.run([sys.executable, PCLOUD_PY, *args], input=stdin, text=True,
                              capture_output=True, env=self.env, timeout=60, start_new_session=True)

    def saved(self):
        with open(self.config) as f:
            return json.load(f)

    def song(self, name="Song.m4a", data=b"fake audio " * 100):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def logged_in(self):
        r = self.run_cli("login", stdin=LOGIN)
        self.assertEqual(r.returncode, 0, r.stderr)


class LoginTests(Base):
    def test_login_saves_token_and_host(self):
        r = self.run_cli("login", stdin=LOGIN)
        self.assertEqual(r.returncode, 0, r.stderr)
        saved = self.saved()
        self.assertEqual(saved["host"], self.mock.hosts["eu"])
        self.assertIn(saved["auth"], self.mock.tokens)
        with open(self.config) as f:
            self.assertNotIn(PASSWORD, f.read())
        if os.name == "posix":  # Windows has no owner-only file mode
            self.assertEqual(oct(os.stat(self.config).st_mode & 0o777), "0o600")
        # the password itself never went over the wire
        sent = json.dumps([p for _, _, p in self.mock.calls])
        self.assertNotIn(PASSWORD, sent)

    def test_wrong_password(self):
        r = self.run_cli("login", stdin=f"{EMAIL}\nnope\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("did not accept that email and password", r.stderr)
        self.assertFalse(os.path.exists(self.config))


class UsAccountTests(Base):
    account_region = "us"

    def test_wrong_region_answer_redirects_to_the_right_host(self):
        r = self.run_cli("login", stdin=LOGIN)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.saved()["host"], self.mock.hosts["us"])
        self.assertEqual([c[0] for c in self.mock.calls if c[1] == "userinfo"], ["eu", "us"])


class UsAccountPlainRejectionTests(Base):
    account_region = "us"
    wrong_region_error = 2000  # in case pCloud just says "login failed" on the wrong host

    def test_falls_back_to_the_other_host(self):
        r = self.run_cli("login", stdin=LOGIN)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.saved()["host"], self.mock.hosts["us"])


class AuthenticatorTests(Base):
    tfa_type = 2

    def test_two_factor_with_app_code(self):
        r = self.run_cli("login", stdin=LOGIN + TFA_CODE + "\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("authenticator app", r.stdout)
        tfa = [p for _, m, p in self.mock.calls if m == "tfa_login"][0]
        self.assertEqual(tfa["trustdevice"], "1")
        self.assertNotIn("tfa_sendcodeviasms", self.mock.methods())

    def test_two_factor_wrong_code(self):
        r = self.run_cli("login", stdin=LOGIN + "000000\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Invalid code", r.stderr)


class SmsTests(Base):
    tfa_type = 1

    def test_two_factor_by_sms(self):
        r = self.run_cli("login", stdin=LOGIN + TFA_CODE + "\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tfa_sendcodeviasms", self.mock.methods())
        self.assertIn("SMS", r.stdout)


class UploadTests(Base):
    def setUp(self):
        super().setUp()
        self.logged_in()

    def test_ask_no_uploads_nothing(self):
        r = self.run_cli("ask", self.song(), stdin="\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("uploadfile", self.mock.methods())
        self.assertIn("stays on the phone", r.stdout)

    def test_ask_yes_uploads_to_my_music_and_adds_to_playlists(self):
        song = self.song("Transformers ⧸ Cello Cover.m4a")
        r = self.run_cli("ask", song, stdin="y\n1,n\nRoad trip\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        files = self.mock.files_in("/My Music")
        self.assertEqual(list(files), ["Transformers ⧸ Cello Cover.m4a"])
        fileid = files["Transformers ⧸ Cello Cover.m4a"]["id"]
        with open(song, "rb") as f:
            self.assertEqual(files["Transformers ⧸ Cello Cover.m4a"]["data"], f.read())
        self.assertEqual(self.mock.playlist("Chill")["files"], [fileid])
        self.assertEqual(self.mock.playlist("Road trip")["files"], [fileid])
        self.assertEqual(self.mock.playlist("Gym")["files"], [])
        self.assertNotIn("Most Listened", r.stdout)  # pCloud's own automatic playlists are hidden

    def test_ask_enter_means_no_playlist(self):
        r = self.run_cli("ask", self.song(), stdin="y\n\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.mock.files_in("/My Music")), 1)
        self.assertNotIn("collection_linkfiles", self.mock.methods())

    def test_same_file_twice_is_not_uploaded_twice(self):
        song = self.song()
        self.run_cli("ask", song, stdin="y\n\n")
        r = self.run_cli("ask", song, stdin="y\n2\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already in /My Music", r.stdout)
        self.assertEqual(self.mock.methods().count("uploadfile"), 1)
        self.assertEqual(len(self.mock.playlist("Gym")["files"]), 1)

    def test_different_file_with_same_name_is_kept_as_a_copy(self):
        self.run_cli("ask", self.song(data=b"one"), stdin="y\n\n")
        self.run_cli("ask", self.song(data=b"two two"), stdin="y\n\n")
        self.assertEqual(sorted(self.mock.files_in("/My Music")), ["Song (1).m4a", "Song.m4a"])

    def test_bad_playlist_choice_is_skipped(self):
        r = self.run_cli("ask", self.song(), stdin="y\n9,x\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("skipped '9'", r.stdout)
        self.assertIn("skipped 'x'", r.stdout)

    def test_expired_login_asks_again_and_carries_on(self):
        self.mock.expire_tokens()
        r = self.run_cli("ask", self.song(), stdin="y\n" + LOGIN + "1\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("expired", r.stdout)
        self.assertEqual(len(self.mock.playlist("Chill")["files"]), 1)

    def test_send_with_playlist_name_any_case(self):
        r = self.run_cli("send", self.song(), "-p", "gym")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.mock.playlist("Gym")["files"]), 1)

    def test_send_unknown_playlist_uploads_nothing_and_lists_names(self):
        r = self.run_cli("send", self.song(), "-p", "Nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Chill, Gym", r.stderr)
        self.assertNotIn("uploadfile", self.mock.methods())

    def test_several_files_one_question(self):
        a, b = self.song("A.m4a"), self.song("B.m4a")
        r = self.run_cli("ask", a, b, stdin="y\n1\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("these 2 files", r.stdout)
        self.assertEqual(len(self.mock.playlist("Chill")["files"]), 2)

    def test_folder_can_be_changed(self):
        r = self.run_cli("folder", "Music/From YouTube")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.run_cli("send", self.song())
        self.assertEqual(list(self.mock.files_in("/Music/From YouTube")), ["Song.m4a"])

    def test_playlists_and_whoami(self):
        r = self.run_cli("playlists")
        self.assertEqual(r.stdout.splitlines(), ["Chill  (0 songs)", "Gym  (0 songs)"])
        r = self.run_cli("whoami")
        self.assertIn(EMAIL, r.stdout)

    def test_missing_file(self):
        r = self.run_cli("send", os.path.join(self.tmp, "nothere.m4a"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("File not found", r.stderr)

    def test_logout(self):
        r = self.run_cli("logout")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("auth", self.saved())
        self.assertEqual(self.mock.tokens, set())


def _tools_present():
    return shutil.which("yt-dlp") and shutil.which("ffmpeg") and shutil.which("bash")


# The share script and installer are Termux (Linux) shell scripts.
TERMUX_LIKE = os.name == "posix"


@unittest.skipUnless(TERMUX_LIKE and _tools_present(), "needs Linux/macOS with yt-dlp, ffmpeg and bash")
class ShareScriptTests(Base):
    """Runs the real termux-url-opener: yt-dlp downloads from a local web server."""

    def setUp(self):
        super().setUp()
        self.logged_in()
        media = os.path.join(self.tmp, "www")
        os.makedirs(media)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                        "-c:a", "aac", os.path.join(media, "test_tone.m4a")], check=True)
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        handler = functools.partial(Quiet, directory=media)
        self.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.web.serve_forever, daemon=True).start()
        self.addCleanup(self.web.server_close)
        self.addCleanup(self.web.shutdown)
        self.url = f"http://127.0.0.1:{self.web.server_address[1]}/test_tone.m4a"
        self.downloads = os.path.join(self.tmp, "storage", "shared", "Podcasts")
        os.makedirs(os.path.join(self.tmp, ".config", "yt2pcloud"), exist_ok=True)
        with open(os.path.join(self.tmp, ".config", "yt2pcloud", "settings.sh"), "w") as f:
            f.write(f'DOWNLOAD_DIR="{self.downloads}"\nYT2PCLOUD_HOME="{YT2PCLOUD}"\n')

    def share(self, stdin):
        return subprocess.run(["bash", os.path.join(YT2PCLOUD, "termux-url-opener"), self.url],
                              input=stdin, text=True, capture_output=True, env=self.env, timeout=180,
                              start_new_session=True)

    def test_download_then_upload_and_playlist(self):
        r = self.share("y\n2\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(os.listdir(self.downloads), ["test_tone.m4a"])
        self.assertIn("Saved: test_tone.m4a", r.stdout)
        self.assertEqual(list(self.mock.files_in("/My Music")), ["test_tone.m4a"])
        self.assertEqual(len(self.mock.playlist("Gym")["files"]), 1)
        self.assertIn("Done. Press Enter to close.", r.stdout)

    def test_download_only(self):
        r = self.share("n\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(os.listdir(self.downloads), ["test_tone.m4a"])
        self.assertNotIn("uploadfile", self.mock.methods())

    def test_failed_download_says_so(self):
        self.url += ".missing"
        r = self.share("\n")
        self.assertIn("Download failed", r.stdout)
        self.assertNotIn("uploadfile", self.mock.methods())


@unittest.skipUnless(TERMUX_LIKE and shutil.which("bash"), "needs Linux/macOS with bash")
class InstallerTests(Base):
    """Runs install.sh with fake pkg/pip/termux-setup-storage."""

    def setUp(self):
        super().setUp()
        fake_bin = os.path.join(self.tmp, "fakebin")
        os.makedirs(fake_bin)
        for tool in ("pkg", "pip", "termux-setup-storage"):
            path = os.path.join(fake_bin, tool)
            with open(path, "w") as f:
                f.write(f'#!/bin/sh\necho "{tool} $*" >> "$HOME/fake-calls.log"\n')
            os.chmod(path, 0o755)
        os.makedirs(os.path.join(self.tmp, "storage", "shared"))
        self.env["PATH"] = fake_bin + os.pathsep + self.env["PATH"]
        self.opener = os.path.join(self.tmp, "bin", "termux-url-opener")

    def install(self, stdin=""):
        return subprocess.run(["bash", os.path.join(YT2PCLOUD, "install.sh")], input=stdin, text=True,
                              capture_output=True, env=self.env, timeout=60, start_new_session=True)

    def settings(self):
        with open(os.path.join(self.tmp, ".config", "yt2pcloud", "settings.sh")) as f:
            return f.read()

    def test_keeps_the_old_download_folder_and_backs_up_the_old_script(self):
        os.makedirs(os.path.dirname(self.opener))
        with open(self.opener, "w") as f:
            f.write('#!/bin/bash\nout="$HOME/storage/shared/Podcasts"\nyt-dlp "$1"\n')
        r = self.install(stdin=LOGIN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('DOWNLOAD_DIR="$HOME/storage/shared/Podcasts"', self.settings())
        self.assertIn(f'YT2PCLOUD_HOME="{YT2PCLOUD}"', self.settings())
        self.assertTrue(os.path.exists(self.opener + ".bak"))
        with open(self.opener) as f, open(os.path.join(YT2PCLOUD, "termux-url-opener")) as g:
            self.assertEqual(f.read(), g.read())
        self.assertTrue(os.access(self.opener, os.X_OK))
        self.assertIn(self.saved()["auth"], self.mock.tokens)
        with open(os.path.join(self.tmp, "fake-calls.log")) as f:
            calls = f.read()
        self.assertIn("pkg install -y python ffmpeg nodejs", calls)
        self.assertIn("pip install -U yt-dlp[default] mutagen", calls)

    def test_fresh_phone_defaults_to_music_and_rerun_skips_login(self):
        r = self.install(stdin=LOGIN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('DOWNLOAD_DIR="$HOME/storage/shared/Music"', self.settings())
        r = self.install(stdin="")  # already logged in: no questions
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(EMAIL, r.stdout)
        self.assertEqual(self.settings().count("YT2PCLOUD_HOME="), 1)
        self.assertFalse(os.path.exists(self.opener + ".bak"))

    def test_falls_back_to_plain_yt_dlp_when_the_default_extra_fails(self):
        with open(os.path.join(self.tmp, "fakebin", "pip"), "a") as f:
            f.write('case "$*" in *"[default]"*) exit 1 ;; esac\n')
        r = self.install(stdin=LOGIN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.tmp, "fake-calls.log")) as f:
            self.assertIn("pip install -U yt-dlp yt-dlp-ejs mutagen", f.read())


if __name__ == "__main__":
    unittest.main()
