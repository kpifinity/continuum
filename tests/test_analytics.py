"""Analytics is anonymous and on-by-default (opt-out); disabling stops all sends."""
import time

from ski_memory import analytics


def _capture(monkeypatch):
    import json
    sent = []
    monkeypatch.setattr(analytics, "_post", lambda payload: sent.append(json.loads(payload.decode())))
    return sent


def test_default_is_on_opt_out(tmp_path, monkeypatch):
    sent = _capture(monkeypatch)
    state = analytics.public_state(tmp_path)
    assert state["consent"] is True  # on by default (opt-out)
    analytics.startup(tmp_path)
    time.sleep(0.2)
    assert len(sent) == 1 and sent[0]["event"] == "install"
    analytics.startup(tmp_path)  # already installed -> sends the day's heartbeat
    time.sleep(0.2)
    assert len(sent) == 2 and sent[1]["event"] == "heartbeat"
    analytics.startup(tmp_path)  # same day -> heartbeat throttled, nothing new
    time.sleep(0.1)
    assert len(sent) == 2


def test_disabling_stops_all_sends(tmp_path, monkeypatch):
    sent = _capture(monkeypatch)
    analytics.set_consent(tmp_path, False)
    analytics.startup(tmp_path)
    analytics.send(tmp_path, "install")
    analytics.heartbeat(tmp_path)
    time.sleep(0.1)
    assert sent == []


def test_install_ping_is_anonymous(tmp_path, monkeypatch):
    sent = _capture(monkeypatch)
    analytics.startup(tmp_path)
    time.sleep(0.2)
    assert len(sent) == 1
    p = sent[0]
    assert set(p.keys()) == {"install_id", "event", "app", "version", "os", "arch", "ts"}
    for forbidden in ("content", "title", "prompt", "messages", "fingerprint", "home", "email"):
        assert forbidden not in p


def test_re_enabling_sends_install(tmp_path, monkeypatch):
    sent = _capture(monkeypatch)
    analytics.set_consent(tmp_path, False)
    analytics.set_consent(tmp_path, True)
    time.sleep(0.2)
    assert any(e["event"] == "install" for e in sent)


def test_install_id_is_stable(tmp_path):
    a = analytics.load(tmp_path)["install_id"]
    b = analytics.load(tmp_path)["install_id"]
    assert a == b and len(a) == 32
