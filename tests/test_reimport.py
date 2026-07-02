from ski_memory import ingest
from ski_memory.config import Config
from ski_memory.store import Store

V1 = ('[{"uuid":"c-9","name":"Project chat","chat_messages":['
      '{"sender":"human","text":"Lets plan the launch."},'
      '{"sender":"assistant","text":"Sure, step one is the beta."}]}]')
V2 = ('[{"uuid":"c-9","name":"Project chat","chat_messages":['
      '{"sender":"human","text":"Lets plan the launch."},'
      '{"sender":"assistant","text":"Sure, step one is the beta."},'
      '{"sender":"human","text":"What is step two?"},'
      '{"sender":"assistant","text":"Step two is the launch post."}]}]')


def test_reimport_merges_new_messages(tmp_path):
    s = Store(Config(home=tmp_path))
    r1 = ingest.import_into_store(s, V1, "v1")
    assert r1["conversations_added"] == 1 and r1["messages_added"] == 2
    assert s.counts()["conversations"] == 1 and s.counts()["messages"] == 2

    r2 = ingest.import_into_store(s, V2, "v2")
    assert r2["conversations_added"] == 0
    assert r2["conversations_updated"] == 1
    assert r2["messages_added"] == 2
    assert s.counts()["conversations"] == 1   # no duplicate conversation
    assert s.counts()["messages"] == 4

    ok, err = s.ledger.verify()
    assert ok, err


def test_reimport_identical_is_idempotent(tmp_path):
    s = Store(Config(home=tmp_path))
    ingest.import_into_store(s, V2, "a")
    r = ingest.import_into_store(s, V2, "b")
    assert r["messages_added"] == 0 and r["conversations_updated"] == 0
    assert s.counts()["messages"] == 4


def test_generic_reimport_updates_same_conversation(tmp_path):
    s = Store(Config(home=tmp_path))
    g1 = '{"title":"Notes","messages":[{"role":"user","content":"start here"}]}'
    g2 = '{"title":"Notes","messages":[{"role":"user","content":"start here"},{"role":"assistant","content":"added later"}]}'
    ingest.import_into_store(s, g1, "g1")
    r = ingest.import_into_store(s, g2, "g2")
    assert r["conversations_added"] == 0 and r["messages_added"] == 1
    assert s.counts()["conversations"] == 1
