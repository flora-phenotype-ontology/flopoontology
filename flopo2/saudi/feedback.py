"""Community review of atlas trait records: votes on whether an annotation is right.

    python -m flopo2.saudi.feedback serve --db feedback.sqlite [--port 7010]
    python -m flopo2.saudi.feedback export --db feedback.sqlite > votes.tsv

A small service next to the atlas (nginx proxies ``/feedback/`` to it; docs/atlas-deploy.md). It
uses the standard library only. Two kinds of vote are kept apart everywhere, in the table, in the
counts and in the export:

* ``anonymous``: no sign-in. The voter is a keyed hash of the client address (the address itself is
  not stored); one vote per record per address, and a daily limit per address.
* ``named``: the voter signed in with ORCID or GitHub and is stored as ``orcid:<iD>`` or
  ``github:<login>`` with the displayed name. Sign-in for a provider is offered only when its
  client ID and secret are configured.

A vote never changes the atlas data: it is a row in this database for the curator to read.

Environment: ``FEEDBACK_SECRET`` (signs sessions and keys the address hash; required),
``FEEDBACK_PUBLIC_BASE`` (the public address of the atlas, for sign-in redirects),
``GITHUB_CLIENT_ID``/``GITHUB_CLIENT_SECRET``, ``ORCID_CLIENT_ID``/``ORCID_CLIENT_SECRET``.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FB = "http://phenomebrowser.net/flopo/browse#"
RECORD = re.compile(r"^http://phenomebrowser\.net/flopo/[A-Za-z0-9._~/-]{1,200}$")
REASONS = {
    "wrong_part": "The plant part is wrong",
    "wrong_value": "The trait value is wrong",
    "wrong_number": "A number or unit is wrong",
    "wrong_taxon": "It is about another taxon",
    "not_in_text": "The text does not say this",
    "other": "Something else",
}
KINDS = ("named", "anonymous")
DAILY_LIMIT = {"anonymous": 200, "named": 2000}
COMMENT_LENGTH = 500
SESSION_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS votes (
  kind TEXT NOT NULL CHECK (kind IN ('named', 'anonymous')),
  voter TEXT NOT NULL,          -- 'orcid:<iD>' or 'github:<login>'; for anonymous a keyed hash of the address
  voter_name TEXT NOT NULL DEFAULT '',
  record TEXT NOT NULL,
  taxon TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  vote INTEGER NOT NULL CHECK (vote IN (1, -1)),
  reason TEXT NOT NULL DEFAULT '',
  comment TEXT NOT NULL DEFAULT '',
  release TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL,
  updated TEXT NOT NULL,
  PRIMARY KEY (kind, voter, record)
);
CREATE INDEX IF NOT EXISTS votes_taxon ON votes (taxon);
CREATE INDEX IF NOT EXISTS votes_voter_day ON votes (kind, voter, updated);
"""

PROVIDERS = {
    "github": {
        "label": "GitHub",
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "",
    },
    "orcid": {
        "label": "ORCID",
        "authorize": "https://orcid.org/oauth/authorize",
        "token": "https://orcid.org/oauth/token",
        "scope": "/authenticate",
    },
}


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.Lock()

    def vote(self, kind: str, voter: str, name: str, record: str, taxon: str, source: str, vote: int,
             reason: str, comment: str, release: str) -> str | None:
        """Store, replace or (vote 0) withdraw a vote. Returns an error message, or None."""

        stamp = now()
        with self.lock, self.db:
            if vote == 0:
                self.db.execute("DELETE FROM votes WHERE kind=? AND voter=? AND record=?", (kind, voter, record))
                return None
            day = self.db.execute("SELECT COUNT(*) FROM votes WHERE kind=? AND voter=? AND updated>=?",
                                  (kind, voter, stamp[:10])).fetchone()[0]
            if day >= DAILY_LIMIT[kind]:
                return "daily limit reached"
            self.db.execute(
                "INSERT INTO votes (kind, voter, voter_name, record, taxon, source, vote, reason, comment, release, created, updated)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (kind, voter, record) DO UPDATE SET"
                " vote=excluded.vote, reason=excluded.reason, comment=excluded.comment, release=excluded.release,"
                " voter_name=excluded.voter_name, updated=excluded.updated",
                (kind, voter, name, record, taxon, source, vote, reason, comment, release, stamp, stamp))
        return None

    def taxon_state(self, taxon: str, voters: dict[str, str]) -> dict:
        """Counts per record of a taxon, by kind, and the votes of the asking voter."""

        counts: dict[str, dict[str, list[int]]] = {}
        mine: dict[str, dict] = {}
        with self.lock:
            rows = self.db.execute("SELECT record, kind, voter, vote, reason FROM votes WHERE taxon=?", (taxon,)).fetchall()
        for record, kind, voter, vote, reason in rows:
            cell = counts.setdefault(record, {k: [0, 0] for k in KINDS})[kind]
            cell[0 if vote > 0 else 1] += 1
            if voters.get(kind) == voter:
                mine.setdefault(record, {})[kind] = {"vote": "up" if vote > 0 else "down", "reason": reason}
        return {"counts": counts, "mine": mine}

    def export(self, out) -> None:
        cursor = self.db.execute("SELECT * FROM votes ORDER BY updated")
        writer = csv.writer(out, delimiter="\t", lineterminator="\n")
        writer.writerow([c[0] for c in cursor.description])
        for row in cursor:
            writer.writerow([re.sub(r"\s+", " ", str(v)) for v in row])


class Signer:
    def __init__(self, secret: str):
        self.key = secret.encode()

    def sign(self, payload: dict) -> str:
        body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
        return body + "." + hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()

    def read(self, token: str | None) -> dict | None:
        try:
            body, mac = (token or "").rsplit(".", 1)
            if not hmac.compare_digest(mac, hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()):
                return None
            payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            return payload if payload.get("exp", 0) > time.time() else None
        except (ValueError, json.JSONDecodeError):
            return None

    def address(self, address: str) -> str:
        return "a:" + hmac.new(self.key, ("address:" + address).encode(), hashlib.sha256).hexdigest()[:24]


def fetch_json(url: str, data: dict | None = None, headers: dict | None = None, timeout: float = 20) -> dict:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers={"Accept": "application/json", "User-Agent": "flopo-atlas", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def lookup_record(endpoint: str, record: str) -> tuple[str, str] | None:
    """(taxon, source) of a trait record of the atlas, or None when there is no such record."""

    query = f"SELECT ?t ?s WHERE {{ <{record}> a <{FB}TraitRecord> ; <{FB}taxon> ?t ; <{FB}source> ?s }} LIMIT 1"
    result = fetch_json(endpoint + "?" + urllib.parse.urlencode({"query": query}),
                        headers={"Accept": "application/sparql-results+json"})
    rows = result["results"]["bindings"]
    return (rows[0]["t"]["value"], rows[0]["s"]["value"].rsplit("/", 1)[-1]) if rows else None


def identity(provider: str, config: dict, code: str, redirect_uri: str) -> tuple[str, str]:
    """Exchange a sign-in code for ('orcid:<iD>' or 'github:<login>', displayed name)."""

    spec = PROVIDERS[provider]
    token = fetch_json(spec["token"], {
        "client_id": config["id"], "client_secret": config["secret"], "code": code,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
    if provider == "orcid":
        if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", token.get("orcid", "")):
            raise ValueError("ORCID did not return an iD")
        return "orcid:" + token["orcid"], token.get("name") or token["orcid"]
    if not token.get("access_token"):
        raise ValueError("GitHub did not return a token")
    user = fetch_json("https://api.github.com/user", headers={"Authorization": "Bearer " + token["access_token"]})
    return "github:" + user["login"], user.get("name") or user["login"]


class App:
    """The service without the socket, so that tests can call it."""

    def __init__(self, store: Store, secret: str, public_base: str = "", providers: dict | None = None,
                 lookup=lookup_record, identify=identity):
        self.store, self.signer = store, Signer(secret)
        self.public_base = public_base.rstrip("/") + "/" if public_base else ""
        self.providers = providers or {}
        self.lookup, self.identify = lookup, identify
        self.known: dict[str, tuple[str, str]] = {}

    # ------------------------------------------------------------------ helpers
    def _session(self, cookies: dict) -> dict | None:
        session = self.signer.read(cookies.get("fs"))
        return session if session and session.get("id") else None

    def _base(self, headers: dict) -> str:
        """Public address of the atlas, with a trailing slash."""

        if self.public_base:
            return self.public_base
        return f"http://{headers.get('host', 'localhost')}{headers.get('x-forwarded-prefix', '')}/"

    def _voters(self, headers: dict, cookies: dict) -> dict[str, str]:
        voters = {"anonymous": self.signer.address(headers.get("x-atlas-client", "") or "unknown")}
        session = self._session(cookies)
        if session:
            voters["named"] = session["id"]
        return voters

    # ------------------------------------------------------------------ requests
    def handle(self, method: str, path: str, query: dict, headers: dict, cookies: dict, body: bytes):
        """Returns (status, headers, JSON-able body or None)."""

        if path == "/feedback/health":
            return 200, {}, {"ok": True}
        if path == "/feedback/state" and method == "GET":
            session = self._session(cookies)
            out = {
                "providers": [{"key": key, "label": PROVIDERS[key]["label"]} for key in PROVIDERS if key in self.providers],
                "signed_in": {"id": session["id"], "name": session.get("name", "")} if session else None,
                "reasons": REASONS,
            }
            taxon = query.get("taxon", "")
            if RECORD.match(taxon):
                out.update(self.store.taxon_state(taxon, self._voters(headers, cookies)))
            return 200, {"Cache-Control": "no-store"}, out
        if path == "/feedback/vote" and method == "POST":
            return self._vote(headers, cookies, body)
        if path == "/feedback/logout" and method == "POST":
            return 200, {"Set-Cookie": "fs=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"}, {"ok": True}
        match = re.fullmatch(r"/feedback/(login|callback)/([a-z]+)", path)
        if match and method == "GET" and match[2] in self.providers:
            return (self._login if match[1] == "login" else self._callback)(match[2], query, headers, cookies)
        return 404, {}, {"error": "not found"}

    def _vote(self, headers: dict, cookies: dict, body: bytes):
        # A form posted from another site cannot send JSON, and a script there cannot read the reply.
        if "application/json" not in headers.get("content-type", ""):
            return 415, {}, {"error": "send JSON"}
        try:
            data = json.loads(body)
            record, choice = str(data["record"]), str(data["vote"])
        except (ValueError, KeyError, TypeError):
            return 400, {}, {"error": "malformed request"}
        reason, comment = str(data.get("reason") or ""), str(data.get("comment") or "").strip()[:COMMENT_LENGTH]
        if not RECORD.match(record) or choice not in ("up", "down", "none") or (reason and reason not in REASONS):
            return 400, {}, {"error": "malformed request"}
        endpoint = headers.get("x-atlas-sparql", "")
        if record not in self.known:
            try:
                found = self.lookup(endpoint, record)
            except (OSError, ValueError, KeyError):
                return 503, {}, {"error": "the record could not be checked; try again"}
            if not found:
                return 404, {}, {"error": "no such trait record"}
            if len(self.known) > 200_000:
                self.known.clear()
            self.known[record] = found
        taxon, source = self.known[record]
        voters = self._voters(headers, cookies)
        kind = "named" if "named" in voters else "anonymous"
        session = self._session(cookies) or {}
        if choice != "down":
            reason = comment = ""
        error = self.store.vote(kind, voters[kind], session.get("name", ""), record, taxon, source,
                                {"up": 1, "down": -1, "none": 0}[choice], reason, comment, headers.get("x-atlas-release", ""))
        if error:
            return 429, {}, {"error": error}
        state = self.store.taxon_state(taxon, voters)
        return 200, {}, {"kind": kind, "counts": state["counts"].get(record, {k: [0, 0] for k in KINDS}),
                         "mine": state["mine"].get(record, {})}

    def _login(self, provider: str, query: dict, headers: dict, cookies: dict):
        back = query.get("return", "")
        if not re.fullmatch(r"#/[A-Za-z0-9._~/%?=&-]{0,300}", back):
            back = "#/"
        nonce = secrets.token_urlsafe(16)
        state = self.signer.sign({"n": nonce, "p": provider, "r": back, "exp": time.time() + 600})
        spec, base = PROVIDERS[provider], self._base(headers)
        params = {"client_id": self.providers[provider]["id"], "redirect_uri": f"{base}feedback/callback/{provider}",
                  "state": state, "response_type": "code"}
        if spec["scope"]:
            params["scope"] = spec["scope"]
        return 302, {"Location": spec["authorize"] + "?" + urllib.parse.urlencode(params),
                     "Set-Cookie": f"fn={nonce}; Path=/; Max-Age=600; HttpOnly; SameSite=Lax"}, None

    def _callback(self, provider: str, query: dict, headers: dict, cookies: dict):
        base = self._base(headers)
        state = self.signer.read(query.get("state"))
        if not state or state.get("p") != provider or not query.get("code") or state.get("n") != cookies.get("fn"):
            return 302, {"Location": base + "#/"}, None  # refused or stale: back to the atlas, not signed in
        try:
            voter, name = self.identify(provider, self.providers[provider], query["code"], f"{base}feedback/callback/{provider}")
        except (OSError, ValueError, KeyError) as exc:
            print(f"sign-in with {provider} failed: {exc}", file=sys.stderr)
            return 302, {"Location": base + state["r"]}, None
        session = self.signer.sign({"id": voter, "name": name[:80], "exp": time.time() + SESSION_DAYS * 86400})
        return 302, {"Location": base + state["r"],
                     "Set-Cookie": f"fs={session}; Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Lax"}, None


def serve(app: App, host: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _run(self, method: str) -> None:
            url = urllib.parse.urlsplit(self.path)
            query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            headers = {k.lower(): v for k, v in self.headers.items()}
            cookies = dict(part.strip().split("=", 1) for part in headers.get("cookie", "").split(";") if "=" in part)
            length = min(int(headers.get("content-length") or 0), 8192)
            body = self.rfile.read(length) if length else b""
            try:
                status, out_headers, payload = app.handle(method, url.path, query, headers, cookies, body)
            except Exception as exc:  # noqa: BLE001 - a broken request must not stop the service
                print(f"error on {method} {url.path}: {exc!r}", file=sys.stderr)
                status, out_headers, payload = 500, {}, {"error": "internal error"}
            data = json.dumps(payload).encode() if payload is not None else b""
            self.send_response(status)
            for key, value in out_headers.items():
                self.send_header(key, value)
            if payload is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            self._run("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._run("POST")

        def log_message(self, fmt: str, *args) -> None:  # no client addresses in the log
            pass

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["serve", "export"])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7010)
    args = parser.parse_args(argv)
    store = Store(str(args.db))
    if args.command == "export":
        store.export(sys.stdout)
        return
    secret = os.environ.get("FEEDBACK_SECRET", "")
    if len(secret) < 32:
        raise SystemExit("FEEDBACK_SECRET must be set (32 characters or more)")
    providers = {key: {"id": os.environ[f"{key.upper()}_CLIENT_ID"], "secret": os.environ[f"{key.upper()}_CLIENT_SECRET"]}
                 for key in PROVIDERS if os.environ.get(f"{key.upper()}_CLIENT_ID") and os.environ.get(f"{key.upper()}_CLIENT_SECRET")}
    print(f"feedback service on {args.host}:{args.port}; sign-in: {', '.join(providers) or 'none configured'}", file=sys.stderr)
    serve(App(store, secret, os.environ.get("FEEDBACK_PUBLIC_BASE", ""), providers), args.host, args.port)


if __name__ == "__main__":
    main()
