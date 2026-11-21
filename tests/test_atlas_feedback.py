import io
import json

from flopo2.saudi.feedback import App, Store

REC = "http://phenomebrowser.net/flopo/flora-assertion/abc123"
TAXON = "http://phenomebrowser.net/flopo/taxon/ipni-1-1"
JSON = {"content-type": "application/json", "x-atlas-sparql": "http://q/", "x-atlas-release": "r1"}


def _app(tmp_path, **kwargs):
    lookup = lambda endpoint, record: (TAXON, "demo") if record == REC else None  # noqa: E731
    return App(Store(str(tmp_path / "f.sqlite")), "s" * 40, lookup=lookup, **kwargs)


def _vote(app, vote, address="1.1.1.1", cookies=None, **extra):
    body = json.dumps({"record": REC, "vote": vote, **extra}).encode()
    return app.handle("POST", "/feedback/vote", {}, {**JSON, "x-atlas-client": address}, cookies or {}, body)


def _state(app, address="1.1.1.1", cookies=None):
    return app.handle("GET", "/feedback/state", {"taxon": TAXON}, {"x-atlas-client": address}, cookies or {}, b"")[2]


def test_anonymous_votes_count_once_per_address_and_can_change(tmp_path):
    app = _app(tmp_path)
    assert _vote(app, "up")[2]["counts"] == {"named": [0, 0], "anonymous": [1, 0]}
    assert _vote(app, "up")[2]["counts"]["anonymous"] == [1, 0]  # the same address again: still one
    status, _, out = _vote(app, "down", reason="wrong_part", comment="it is the petal\n" + "x" * 900)
    assert status == 200 and out["counts"]["anonymous"] == [0, 1] and out["mine"]["anonymous"] == {"vote": "down", "reason": "wrong_part"}
    assert _vote(app, "up", address="2.2.2.2")[2]["counts"]["anonymous"] == [1, 1]
    assert _state(app, "3.3.3.3")["mine"] == {} and _state(app)["mine"][REC]["anonymous"]["vote"] == "down"
    assert _vote(app, "none")[2]["counts"]["anonymous"] == [1, 0]  # withdrawn
    out = io.StringIO()
    app.store.export(out)
    header, row = [line.split("\t") for line in out.getvalue().splitlines()]
    stored = dict(zip(header, row))
    assert stored["kind"] == "anonymous" and stored["taxon"] == TAXON and stored["source"] == "demo" and stored["release"] == "r1"
    assert "2.2.2.2" not in out.getvalue()  # the address is not stored


def test_named_votes_are_kept_apart_from_anonymous_ones(tmp_path):
    app = _app(tmp_path)
    session = {"fs": app.signer.sign({"id": "orcid:0000-0001-2345-6789", "name": "A Botanist", "exp": 9e12})}
    _vote(app, "up")  # anonymous, from the same address
    out = _vote(app, "down", cookies=session, reason="wrong_value")[2]
    assert out["kind"] == "named" and out["counts"] == {"named": [0, 1], "anonymous": [1, 0]}
    state = _state(app, cookies=session)
    assert state["signed_in"] == {"id": "orcid:0000-0001-2345-6789", "name": "A Botanist"}
    assert state["mine"][REC] == {"anonymous": {"vote": "up", "reason": ""}, "named": {"vote": "down", "reason": "wrong_value"}}
    forged = {"fs": session["fs"][:-1] + ("0" if session["fs"][-1] != "0" else "1")}
    assert _vote(app, "up", address="9.9.9.9", cookies=forged)[2]["kind"] == "anonymous"


def test_bad_requests_are_refused(tmp_path, monkeypatch):
    app = _app(tmp_path)
    other = json.dumps({"record": REC + "x", "vote": "up"}).encode()
    assert app.handle("POST", "/feedback/vote", {}, JSON, {}, other)[0] == 404  # not a record of the atlas
    assert _vote(app, "sideways")[0] == 400 and _vote(app, "down", reason="nonsense")[0] == 400
    form = {"content-type": "application/x-www-form-urlencoded"}
    assert app.handle("POST", "/feedback/vote", {}, form, {}, b"record=x")[0] == 415  # a form from another site
    monkeypatch.setitem(__import__("flopo2.saudi.feedback", fromlist=["x"]).DAILY_LIMIT, "anonymous", 1)
    assert _vote(app, "up")[0] == 200 and _vote(app, "down")[0] == 429


def test_sign_in_round_trip_and_refusals(tmp_path):
    seen = {}

    def identify(provider, config, code, redirect_uri):
        seen.update(provider=provider, code=code, redirect_uri=redirect_uri)
        return "github:someone", "Some One"

    app = _app(tmp_path, public_base="http://example.org/flopo", providers={"github": {"id": "cid", "secret": "x"}}, identify=identify)
    assert [p["key"] for p in _state(app)["providers"]] == ["github"]
    assert app.handle("GET", "/feedback/login/orcid", {}, {}, {}, b"")[0] == 404  # not configured
    status, headers, _ = app.handle("GET", "/feedback/login/github", {"return": "#/taxon/ipni-1-1"}, {}, {}, b"")
    assert status == 302 and "redirect_uri=http%3A%2F%2Fexample.org%2Fflopo%2Ffeedback%2Fcallback%2Fgithub" in headers["Location"]
    state = headers["Location"].split("state=")[1].split("&")[0]
    nonce = {"fn": headers["Set-Cookie"].split(";")[0].split("=", 1)[1]}
    # the state of one browser does not sign in another
    status, headers2, _ = app.handle("GET", "/feedback/callback/github", {"code": "c", "state": state}, {}, {"fn": "other"}, b"")
    assert status == 302 and "Set-Cookie" not in headers2 and not seen
    status, headers2, _ = app.handle("GET", "/feedback/callback/github", {"code": "c", "state": state}, {}, nonce, b"")
    assert headers2["Location"] == "http://example.org/flopo/#/taxon/ipni-1-1" and seen["code"] == "c"
    session = {"fs": headers2["Set-Cookie"].split(";")[0].split("=", 1)[1]}
    assert _state(app, cookies=session)["signed_in"]["id"] == "github:someone"
    status, headers3, _ = app.handle("GET", "/feedback/login/github", {"return": "http://evil.example/"}, {}, {}, b"")
    back = app.signer.read(headers3["Location"].split("state=")[1].split("&")[0])
    assert back["r"] == "#/"  # only pages of the atlas
