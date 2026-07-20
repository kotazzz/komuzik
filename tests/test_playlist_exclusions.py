from komuzik.playlist import parse_exclusion_ops


def test_plus_list_includes_all_bare_numbers():
    current = {11, 12, 13, 14, 15, 16}
    result = parse_exclusion_ops("+11,13,15", 20, current)
    assert result == {12, 14, 16}


def test_plus_list_with_range():
    current = set(range(1, 21))
    result = parse_exclusion_ops("+11,13,15,18-20", 20, current)
    assert result == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 17}


def test_plus_list_odd_numbers():
    current = set(range(1, 21))
    result = parse_exclusion_ops("+11,13,15,17,19", 20, current)
    assert sorted(current - result) == [11, 13, 15, 17, 19]


def test_plus_short_list_with_range():
    current = set(range(1, 6))
    result = parse_exclusion_ops("+1,2,4-5", 20, current)
    assert result == {3}


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


def test_fullwidth_comma_and_plus():
    current = {11, 12, 13}
    result = parse_exclusion_ops("＋11，13", 20, current)
    assert result == {12}
