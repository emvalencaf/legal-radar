"""Human review of a proposed gold set (#67): every provision gets a decision, none is skipped.

The proposal is an LLM's; the reviewer accepts, corrects or rejects each proposed edge and may add
the ones it missed. Each kept edge records how it got there (`accepted`, `corrected` or `added`) so
anchoring bias can be audited afterwards; rejected proposals are kept under `rejected`.
"""

from collections.abc import Callable, Sequence

ACCEPTED, CORRECTED, ADDED = "accepted", "corrected", "added"


def review_entry(entry: dict, decide: Callable[[dict, dict], dict | None]) -> dict:
    """Review one `{id, edges, note?}` entry.

    `decide(entry, edge)` returns the edge to keep (the same one to accept, another to correct) or
    `None` to reject; `decide(entry, {})` is called until it returns `None` to collect added edges.
    """
    kept, rejected = [], []
    for edge in entry["edges"]:
        answer = decide(entry, edge)
        if answer is None:
            rejected.append(edge)
        else:
            review = ACCEPTED if _key(answer) == _key(edge) else CORRECTED
            kept.append(
                {**answer, "review": review, **({"was": edge} if review == CORRECTED else {})}
            )
    while (added := decide(entry, {})) is not None:
        if _key(added) not in {_key(k) for k in kept}:  # the same edge twice is one edge
            kept.append({**added, "review": ADDED})
    result = {"id": entry["id"], "edges": kept}
    if rejected:
        result["rejected"] = rejected
    return result


def review_all(
    entries: Sequence[dict],
    done: Sequence[dict],
    decide: Callable[[dict, dict], dict | None],
    save: Callable[[list[dict]], None],
) -> list[dict]:
    """Review the entries not in `done` in order, saving after each so a run can be resumed."""
    reviewed = list(done)
    seen = {e["id"] for e in reviewed}
    for entry in entries:
        if entry["id"] in seen:
            continue
        reviewed.append(review_entry(entry, decide))
        save(reviewed)
    return reviewed


def assemble(order: Sequence[str], reviewed: Sequence[dict]) -> list[dict]:
    """The reviewed entries in proposal order; refuses while any dispositivo is unreviewed."""
    by_id = {e["id"]: e for e in reviewed}
    missing = [id_ for id_ in order if id_ not in by_id]
    if missing:
        raise ValueError(f"{len(missing)} dispositivos not reviewed yet, first: {missing[0]}")
    return [by_id[id_] for id_ in order]


def _key(edge: dict) -> tuple:
    return edge["type"], edge.get("source"), edge.get("target")
