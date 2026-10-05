"""Heuristic ranking of specialised Smart nodes for a prompt."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence


_CODE_RE = re.compile(
    r"```|def |class |import |function |typescript|python|rustc|compile error",
    re.I,
)
_IMAGE_RE = re.compile(r"\.(png|jpe?g|gif|webp|bmp|tiff)\b|image|photo|picture|vision", re.I)
_VERIFY_RE = re.compile(r"\b(verify|proof|trace|legal|contract|entail)\b", re.I)


def infer_needed_capabilities(prompt: str, attachments: Sequence[str] | None = None) -> List[str]:
    """Return capability tags that fit this prompt and attachments.

    Args:
        prompt: User text.
        attachments: File names or MIME hints.

    Returns:
        Ordered capability list (at least ``generic``).
    """
    names = " ".join(attachments or [])
    blob = f"{prompt}\n{names}"
    needed: List[str] = []
    if any(_IMAGE_RE.search(n or "") for n in (attachments or [])) or (
        _IMAGE_RE.search(prompt or "") and any(
            (n or "").lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
            for n in (attachments or [])
        )
    ):
        needed.append("vision")
    if _CODE_RE.search(blob or ""):
        needed.append("coding")
    if _VERIFY_RE.search(prompt or ""):
        needed.append("verifier")
    if not needed:
        needed.append("generic")
    return needed


def rank_nodes(
    nodes: List[Dict[str, Any]],
    prompt: str,
    attachments: Sequence[str] | None = None,
) -> List[Dict[str, Any]]:
    """Copy nodes with ``suitability`` scores (higher is a better match).

    Args:
        nodes: Smart node dicts with ``capabilities``.
        prompt: User text.
        attachments: File names.

    Returns:
        Nodes sorted by suitability desc, then price_per_query asc.
    """
    needed = infer_needed_capabilities(prompt, attachments)
    ranked = []
    for node in nodes:
        caps = node.get("capabilities") or ["generic"]
        if isinstance(caps, str):
            caps = [c.strip() for c in caps.split(",") if c.strip()]
        score = 0.0
        for tag in needed:
            if tag in caps:
                score += 3.0
        if "generic" in caps:
            score += 0.5
        if node.get("banned"):
            score -= 10.0
        price = float(node.get("price_per_query") or 0)
        reputation = float(node.get("reputation") or node.get("score") or 0)
        score += min(reputation, 100) / 200.0
        item = dict(node)
        item["suitability"] = round(score, 3)
        item["recommended_for"] = needed
        item["_price"] = price
        ranked.append(item)
    ranked.sort(key=lambda n: (-n["suitability"], n["_price"]))
    for item in ranked:
        item.pop("_price", None)
    return ranked
