from komuzik.playlist import parse_exclusion_ops


def test_plus_list_includes_all_bare_numbers():
    current = {11, 12, 13, 14, 15, 16}
    result = parse_exclusion_ops("+11,13,15", 20, current)
    assert result == {12, 14, 16}


def test_minus_list_excludes_bare_numbers():
    result = parse_exclusion_ops("-1,3,8", 20, set())
    assert result == {1, 3, 8}


def test_mixed_signs_bare_inherits_last():
    current = {1, 2, 3, 4, 5}
    result = parse_exclusion_ops("+1,2,-4,5", 20, current)
    assert result == {3, 4, 5}


def test_range_with_bare_after_minus():
    result = parse_exclusion_ops("-1-3,5", 20, set())
    assert result == {1, 2, 3, 5}
