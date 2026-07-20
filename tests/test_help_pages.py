from komuzik.help_pages import (
    ADMIN_SLUGS,
    INFO_GITHUB_URL,
    INFO_TEXT,
    USER_SLUGS,
    admin_page_buttons,
    admin_page_text,
    admin_toc_buttons,
    admin_toc_text,
    resolve_help_callback,
    user_page_buttons,
    user_page_text,
    user_toc_buttons,
    user_toc_text,
)


def _button_data(rows) -> set[bytes]:
    out = set()
    for row in rows:
        for btn in row:
            data = getattr(btn, "data", None)
            if data is not None:
                out.add(data)
    return out


def test_user_toc_no_admin_button():
    data = _button_data(user_toc_buttons(is_admin=False))
    assert b"help_a_toc" not in data
    for slug in USER_SLUGS:
        assert f"help_u_{slug}".encode() in data


def test_user_toc_admin_button():
    data = _button_data(user_toc_buttons(is_admin=True))
    assert b"help_a_toc" in data


def test_pages_nonempty_and_callback_len():
    assert user_toc_text().strip()
    assert admin_toc_text().strip()
    for slug in USER_SLUGS:
        assert user_page_text(slug).strip()
        assert len(f"help_u_{slug}") <= 64
    for slug in ADMIN_SLUGS:
        assert admin_page_text(slug).strip()
        assert len(f"help_a_{slug}") <= 64


def test_key_commands_mentioned():
    cmds = user_page_text("commands")
    for cmd in ("/report", "/info", "/settings", "/search", "/stats", "/limits", "/privacy"):
        assert cmd in cmds
    assert "/admin" in admin_page_text("panel")
    assert "/ban" in admin_page_text("bans")
    assert "/setstorage" in admin_page_text("storage")
    assert "/post" in admin_page_text("post")


def test_info_constants():
    assert INFO_GITHUB_URL == "https://github.com/kotazzz/komuzik"
    assert "Kotaz" in INFO_TEXT
    assert "/report" in INFO_TEXT
    assert INFO_GITHUB_URL in INFO_TEXT


def test_resolve_callback():
    assert resolve_help_callback("help_toc") == ("user_toc", None)
    assert resolve_help_callback("help_a_toc") == ("admin_toc", None)
    assert resolve_help_callback("help_u_inline") == ("user_page", "inline")
    assert resolve_help_callback("help_a_limits") == ("admin_page", "limits")
    assert resolve_help_callback("help_u_nope") == ("unknown", None)


def test_back_buttons():
    assert b"help_toc" in _button_data(admin_toc_buttons())
    assert b"help_toc" in _button_data(user_page_buttons())
    assert b"help_a_toc" in _button_data(admin_page_buttons())
