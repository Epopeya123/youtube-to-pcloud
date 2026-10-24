"""A small fake of the pCloud API, for testing pcloud.py without an account.

Two "regions" run on two local ports, like eapi.pcloud.com and api.pcloud.com.
The account lives in one of them. Behaviour follows docs.pcloud.com and
pCloud's own console client (2297 = two-factor needed, 2321 = wrong region).
"""

import email.parser
import email.policy
import hashlib
import json
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EMAIL = "nacho@example.com"
PASSWORD = "correct horse"
TFA_CODE = "123456"


class MockPCloud:
    def __init__(self, account_region="eu", tfa_type=None, wrong_region_error=2321):
        self.account_region = account_region
        self.tfa_type = tfa_type
        self.send_tfa_token = True
        self.wrong_region_error = wrong_region_error
        self.digests = set()
        self.tokens = set()
        self.calls = []
        self.folders = {"/": 0}
        self.next_id = 100
        self.files = {}  # fileid -> dict(name, size, folderid, data)
        self.collections = [
            {"id": 1, "name": "Chill", "type": "audio", "system": False, "ismine": True, "files": []},
            {"id": 2, "name": "Gym", "type": "audio", "system": False, "ismine": True, "files": []},
            {"id": 3, "name": "Most Listened", "type": "audio", "system": True, "ismine": True, "files": []},
        ]
        self.lock = threading.Lock()
        self.servers = {}
        for region in ("eu", "us"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler(region))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.servers[region] = server
        self.hosts = {r: f"127.0.0.1:{s.server_address[1]}" for r, s in self.servers.items()}

    def close(self):
        for server in self.servers.values():
            server.shutdown()
            server.server_close()

    # helpers for tests
    def expire_tokens(self):
        self.tokens.clear()

    def methods(self):
        return [m for _, m, _ in self.calls]

    def folder_path(self, folderid):
        return next(p for p, i in self.folders.items() if i == folderid)

    def files_in(self, path):
        folderid = self.folders.get(path)
        return {f["name"]: f for f in self.files.values() if f["folderid"] == folderid}

    def playlist(self, name):
        return next(c for c in self.collections if c["name"] == name)

    # the API
    def _handler(self, region):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, data):
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                params = dict(urllib.parse.parse_qsl(url.query))
                self._reply(mock.handle(region, url.path.strip("/"), params, None))

            def do_POST(self):
                url = urllib.parse.urlsplit(self.path)
                params = dict(urllib.parse.parse_qsl(url.query))
                body = self.rfile.read(int(self.headers["Content-Length"]))
                head = f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode()
                message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(head + body)
                upload = None
                for part in message.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    if part.get_filename() is not None:
                        upload = (part.get_filename(), part.get_payload(decode=True))
                    else:
                        params[name] = part.get_payload(decode=True).decode()
                self._reply(mock.handle(region, url.path.strip("/"), params, upload))

        return Handler

    def handle(self, region, method, params, upload):
        with self.lock:
            self.calls.append((region, method, params))
            return self._handle(region, method, params, upload)

    def _new_id(self):
        self.next_id += 1
        return self.next_id

    def _issue_token(self):
        token = secrets.token_hex(16)
        self.tokens.add(token)
        return {"result": 0, "auth": token, "email": EMAIL}

    def _handle(self, region, method, p, upload):
        if method == "getdigest":
            digest = secrets.token_hex(8)
            self.digests.add(digest)
            return {"result": 0, "digest": digest}

        if method in ("userinfo", "login") and "username" in p:
            if region != self.account_region:
                if self.wrong_region_error == 2321:
                    other = self.account_region
                    return {"result": 2321, "error": "This user is on another location.",
                            "location": {"id": 2 if other == "eu" else 1, "api": self.hosts[other],
                                         "binapi": "bin." + self.hosts[other]}}
                return {"result": 2000, "error": "Log in failed."}
            if p.get("digest") not in self.digests:
                return {"result": 2000, "error": "Log in failed."}
            email_hash = hashlib.sha1(p["username"].lower().encode()).hexdigest()
            expected = hashlib.sha1((PASSWORD + email_hash + p["digest"]).encode()).hexdigest()
            if p["username"].lower() != EMAIL or p.get("passworddigest") != expected:
                return {"result": 2000, "error": "Log in failed."}
            if self.tfa_type:
                # Like the real server: only "login", the method of pCloud's own client,
                # sends the token that tfa_login needs; userinfo leaves it out.
                answer = {"result": 2297, "error": "Two factor authentication required."}
                if method == "login" and self.send_tfa_token:
                    answer.update({"token": "tfa-token", "tfatype": self.tfa_type, "hasdevices": False})
                return answer
            return self._issue_token()

        if method == "tfa_sendcodeviasms":
            return {"result": 0}
        if method == "tfa_login":
            if p.get("token") == "tfa-token" and p.get("code") == TFA_CODE:
                return self._issue_token()
            return {"result": 2064, "error": "Invalid code."}

        # everything else needs a valid token, on the account's own region
        if "auth" not in p:
            return {"result": 1000, "error": "Log in required."}
        if p["auth"] not in self.tokens or region != self.account_region:
            return {"result": 2000, "error": "Log in failed."}

        if method == "userinfo":
            return {"result": 0, "email": EMAIL}
        if method == "logout":
            self.tokens.discard(p["auth"])
            return {"result": 0, "auth_deleted": True}
        if method == "createfolderifnotexists":
            path = "/" + p["path"].strip("/")
            if path not in self.folders:
                self.folders[path] = self._new_id()
            return {"result": 0, "metadata": {"folderid": self.folders[path], "isfolder": True,
                                              "name": path.rsplit("/", 1)[-1]}}
        if method == "stat":
            folder, _, name = p["path"].rpartition("/")
            match = self.files_in(folder or "/").get(name)
            if not match:
                return {"result": 2009, "error": "File not found."}
            return {"result": 0, "metadata": {"fileid": match["id"], "name": name, "size": match["size"]}}
        if method == "uploadfile":
            name, data = upload
            folderid = int(p["folderid"])
            existing = self.files_in(self.folder_path(folderid))
            if name in existing and p.get("renameifexists"):
                stem, dot, ext = name.rpartition(".")
                n = 1
                while f"{stem} ({n}).{ext}" in existing:
                    n += 1
                name = f"{stem} ({n}).{ext}"
            fileid = self._new_id()
            self.files[fileid] = {"id": fileid, "name": name, "size": len(data), "folderid": folderid,
                                  "data": data, "mtime": p.get("mtime")}
            meta = {"fileid": fileid, "name": name, "size": len(data), "parentfolderid": folderid}
            return {"result": 0, "fileids": [fileid], "metadata": [meta]}
        if method == "collection_list":
            cols = [{k: v for k, v in c.items() if k != "files"} | {"items": len(c["files"])}
                    for c in self.collections if p.get("type") in (None, "1")]
            return {"result": 0, "collections": cols}
        if method == "collection_linkfiles":
            col = next((c for c in self.collections if c["id"] == int(p["collectionid"])), None)
            if col is None:
                return {"result": 2055, "error": "Collection not found."}
            results = []
            for fileid in [int(f) for f in p["fileids"].split(",")]:
                if fileid in self.files:
                    col["files"].append(fileid)
                    results.append({"fileid": fileid, "result": 0})
                else:
                    results.append({"fileid": fileid, "result": 2009})
            return {"result": 0, "collection": {"id": col["id"], "name": col["name"]}, "linkresult": results}
        if method == "collection_create":
            files = [int(f) for f in p.get("fileids", "").split(",") if f]
            col = {"id": self._new_id(), "name": p["name"], "type": "audio", "system": False,
                   "ismine": True, "files": files}
            self.collections.append(col)
            return {"result": 0, "collection": {"id": col["id"], "name": col["name"]}}
        return {"result": 2003, "error": f"Unknown method {method} in the mock."}
