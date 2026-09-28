import leakguard

PROFILE = {"identity": {"names": ["Alice", "Alice Doe"], "emails": ["alice@corp.example"],
                        "hosts": {"box1": {"aliases": ["box1-lan"], "ssh": "ubuntu"}}},
           "publish_deny": ["acct-42", "x"], "publish_allow": ["ubuntu"]}


def test_needles():
    assert leakguard.needles(PROFILE) == sorted(
        ["alice", "alice doe", "alice@corp.example", "box1", "box1-lan", "acct-42"])


def test_needles_without_names():
    n = leakguard.needles(PROFILE, names=False)
    assert "alice" not in n and "alice@corp.example" in n


def test_empty_profile_has_no_needles():
    assert leakguard.needles({}) == []


def test_find_case_insensitive_with_line_numbers_and_allow_list():
    hits = leakguard.find({"a.py": "ok\nhost = 'BOX1'\n", "b.yml": "runs-on: ubuntu-latest\n"},
                          leakguard.needles(PROFILE))
    assert hits == ["a.py:2: box1"]
