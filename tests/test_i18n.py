import string

import pytest

from exprand import i18n


def fields(text):
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)


def test_both_languages_have_the_same_keys_and_placeholders():
    en, pt = i18n.STRINGS["en"], i18n.STRINGS["pt"]
    assert en.keys() == pt.keys()
    for key in en:
        assert fields(en[key]) == fields(pt[key]), key


def test_every_string_formats_with_its_own_placeholders():
    for language in i18n.LANGUAGES:
        for key, text in i18n.STRINGS[language].items():
            values = {name: "x" for name in fields(text)}
            assert i18n.t(language, key, **values)


@pytest.mark.parametrize(
    "forced, lang_env, expected",
    [
        ("pt", "en_US.UTF-8", "pt"),
        ("en", "pt_BR.UTF-8", "en"),
        ("", "pt_BR.UTF-8", "pt"),
        ("", "en_US.UTF-8", "en"),
        ("fr", "", "en"),
    ],
)
def test_default_language_follows_the_override_then_the_locale(
    monkeypatch, forced, lang_env, expected
):
    monkeypatch.setenv("EXPRAND_LANG", forced)
    monkeypatch.setenv("LANG", lang_env)
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *a, **k: (None, None))
    assert i18n.default_language() == expected
