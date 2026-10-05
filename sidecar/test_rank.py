"""Node ranking heuristics for Beez Desktop Two."""

from rank import infer_needed_capabilities, rank_nodes


def test_code_prompt_prefers_coding_node():
    needed = infer_needed_capabilities("```python\ndef foo():\n    pass\n```")
    assert "coding" in needed
    nodes = [
        {"node_id": "a", "capabilities": ["generic"], "price_per_query": 0.3, "reputation": 80},
        {"node_id": "b", "capabilities": ["coding", "generic"], "price_per_query": 1.5, "reputation": 80},
    ]
    ranked = rank_nodes(nodes, "fix this rustc compile error")
    assert ranked[0]["node_id"] == "b"
    assert ranked[0]["suitability"] > ranked[1]["suitability"]


def test_image_attachment_requests_vision():
    needed = infer_needed_capabilities("describe this", ["photo.png"])
    assert "vision" in needed
