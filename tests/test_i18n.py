import string

import pytest

from exprand import i18n


def fields(text):
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)


def test_every_language_has_strings():
    assert i18n.STRINGS.keys() == set(i18n.LANGUAGES)


@pytest.mark.parametrize("language", [code for code in i18n.LANGUAGES if code != "en"])
def test_every_language_has_the_same_keys_and_placeholders_as_english(language):
    en, other = i18n.STRINGS["en"], i18n.STRINGS[language]
    assert en.keys() == other.keys()
    for key in en:
        assert fields(en[key]) == fields(other[key]), key


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
        ("es", "pt_BR.UTF-8", "es"),
        ("", "es_AR.UTF-8", "es"),
        ("", "", "en"),
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
