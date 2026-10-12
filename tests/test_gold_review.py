from legal_radar.gold_review import review_all, review_entry

ENTRY = {
    "id": "d1",
    "edges": [
        {"type": "DEFINES", "target": "a"},
        {"type": "APPLIES_TO", "target": "b"},
        {"type": "RELATES_TO", "target": "c"},
    ],
}


def scripted(answers):
    queue = iter(answers)
    return lambda entry, edge: next(queue)


def test_each_edge_is_marked_accepted_corrected_or_added_and_rejections_are_kept():
    decide = scripted(
        [
            ENTRY["edges"][0],  # accepted as proposed
            {"type": "DEFINES", "target": "b"},  # corrected
            None,  # rejected
            {"type": "EXCEPTS", "target": "d"},  # added
            None,  # nothing more to add
        ]
    )

    result = review_entry(ENTRY, decide)

    assert result["edges"] == [
        {"type": "DEFINES", "target": "a", "review": "accepted"},
        {
            "type": "DEFINES",
            "target": "b",
            "review": "corrected",
            "was": {"type": "APPLIES_TO", "target": "b"},
        },
        {"type": "EXCEPTS", "target": "d", "review": "added"},
    ]
    assert result["rejected"] == [{"type": "RELATES_TO", "target": "c"}]


def test_a_confirmed_negative_stays_an_explicit_empty_list():
    result = review_entry({"id": "d2", "edges": []}, scripted([None]))

    assert result == {"id": "d2", "edges": []}


def test_review_resumes_without_asking_again_and_saves_after_each_entry():
    saved = []
    done = [{"id": "d1", "edges": []}]

    result = review_all(
        [ENTRY, {"id": "d2", "edges": []}], done, scripted([None]), lambda r: saved.append(len(r))
    )

    assert [e["id"] for e in result] == ["d1", "d2"]
    assert saved == [2]


def test_adding_the_same_edge_twice_keeps_one():
    added = {"type": "DEFINES", "target": "a"}

    result = review_entry({"id": "d3", "edges": []}, scripted([added, added, None]))

    assert result["edges"] == [{**added, "review": "added"}]
