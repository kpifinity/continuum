from ski_memory import bridge, kg, memgraph
from ski_memory.config import Config
from ski_memory.store import Store


def seeded(tmp_path):
    s = Store(Config(home=tmp_path))
    # same entity (Lake Louise) across two providers
    bridge.ingest_pasted(s, "You: Tell me about Lake Louise.\nClaude: Lake Louise in Alberta is stunning.", "A")
    bridge.ingest_pasted(s, "You: Lake Louise again?\nChatGPT: Lake Louise is a top spot.", "B")
    kg.build_all(s)
    return s


def test_graph_merges_entities_across_conversations(tmp_path):
    s = seeded(tmp_path)
    g = memgraph.build_global_graph(s)
    banff = next((n for n in g["nodes"] if "Lake Louise" in n["label"]), None)
    assert banff is not None
    assert banff["importance"] >= 2  # mentioned in both conversations


def test_node_detail_provenance(tmp_path):
    s = seeded(tmp_path)
    g = memgraph.build_global_graph(s)
    nid = next(n["id"] for n in g["nodes"] if "Lake Louise" in n["label"])
    d = memgraph.node_detail(s, nid)
    assert len(d["conversations"]) >= 2


def test_edits_apply_and_ledger_stays_valid(tmp_path):
    s = seeded(tmp_path)
    g = memgraph.build_global_graph(s)
    nid = next(n["id"] for n in g["nodes"] if "Lake Louise" in n["label"])
    memgraph.edit(s, nid, "rename", "Banff Park")
    memgraph.edit(s, nid, "pin", True)
    memgraph.edit(s, nid, "fact", "1981 split-level nearby.")
    d = memgraph.node_detail(s, nid)
    assert d["label"] == "Banff Park" and d["pinned"] and d["facts"] == ["1981 split-level nearby."]
    memgraph.edit(s, nid, "hide", True)
    g2 = memgraph.build_global_graph(s)
    assert not any(n["id"] == nid for n in g2["nodes"])
    ok, err = s.ledger.verify()
    assert ok, err


def test_merge_redirects(tmp_path):
    s = seeded(tmp_path)
    g = memgraph.build_global_graph(s)
    ids = [n["id"] for n in g["nodes"] if n["type"] == "entity"]
    if len(ids) >= 2:
        memgraph.edit(s, ids[0], "merge", ids[1])
        g2 = memgraph.build_global_graph(s)
        assert not any(n["id"] == ids[0] for n in g2["nodes"])
    ok, _ = s.ledger.verify()
    assert ok


def test_unknown_op_rejected(tmp_path):
    s = Store(Config(home=tmp_path))
    import pytest
    with pytest.raises(ValueError):
        memgraph.edit(s, "x", "explode", None)
