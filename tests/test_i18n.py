from komuzik.i18n import has_key, reload_messages, t
from komuzik.help_pages import USER_SLUGS, ADMIN_SLUGS


def test_t_returns_start():
    assert "Komuzik" in t("start") or "YouTube" in t("start")
    assert t("privacy").startswith("📄")


def test_t_format():
    # use a key that exists; format with unused kwargs is fine
    text = t("errors.no_access")
    assert text == "Нет доступа."


def test_missing_key_returns_key():
    assert t("this.key.does.not.exist") == "this.key.does.not.exist"


def test_wave1_keys_present():
    required = [
        "start",
        "privacy",
        "info.body",
        "info.github_url",
        "info.button_source",
        "errors.download_unavailable",
        "errors.pm_unavailable",
        "errors.tiktok",
        "errors.twitter",
        "errors.pinterest",
        "errors.no_access",
        "help.toc",
        "help.admin_toc",
        "help.buttons.back",
        "help.buttons.for_admin",
    ]
    for slug in USER_SLUGS:
        required.append(f"help.pages.{slug}")
        required.append(f"help.buttons.{slug}")
    for slug in ADMIN_SLUGS:
        required.append(f"help.admin_pages.{slug}")
        required.append(f"help.buttons.{slug}")
    missing = [k for k in required if not has_key(k)]
    assert missing == []


def test_reload_messages_roundtrip(tmp_path):
    path = tmp_path / "messages.yaml"
    path.write_text("hello: world\nnested:\n  x: '{name}!'\n", encoding="utf-8")
    reload_messages(str(path))
    assert t("hello") == "world"
    assert t("nested.x", name="A") == "A!"
    # restore project file for other tests
    reload_messages()
