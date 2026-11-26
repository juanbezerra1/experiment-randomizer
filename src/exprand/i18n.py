"""The few words the window shows, in English, Brazilian Portuguese and Spanish."""

from __future__ import annotations

import locale
import os

__all__ = ["LANGUAGES", "STRINGS", "default_language", "t"]

LANGUAGES = ("en", "pt", "es")

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "window_title": "Experiment randomizer",
        "protocol": "{arms} arms · {conditions} conditions · {rounds} rounds",
        "protocol_arms_only": "{arms} arms",
        "protocol_orders_only": "{conditions} conditions · {rounds} rounds",
        "session": "Session: {n}",
        "no_session": "Session: —",
        "arm_frame": "Arm",
        "arm_hidden": "(hidden)",
        "reveal_arm": "Reveal arm",
        "rounds_frame": "Order of the conditions in each round",
        "round": "Round {i}",
        "new_session": "New session",
        "confirm_new": (
            "Draw and log a new session?\nEvery draw is permanent and is never reused."
        ),
        "open_folder": "Open data folder",
        "folder_message": "The data are in:\n{path}",
        "verify": "Verify log",
        "verify_ok": "Log verified: {n} sessions, nothing altered.",
        "verify_bad": "Problems found:\n{problems}",
        "logged": "Recorded in the log (session {n}).",
        "ready": "Ready. Nothing is drawn until you press “New session”.",
        "error": "Error",
        "info": "Information",
    },
    "pt": {
        "window_title": "Sorteador do experimento",
        "protocol": "{arms} braços · {conditions} condições · {rounds} rodadas",
        "protocol_arms_only": "{arms} braços",
        "protocol_orders_only": "{conditions} condições · {rounds} rodadas",
        "session": "Sessão: {n}",
        "no_session": "Sessão: —",
        "arm_frame": "Braço",
        "arm_hidden": "(oculto)",
        "reveal_arm": "Revelar braço",
        "rounds_frame": "Ordem das condições em cada rodada",
        "round": "Rodada {i}",
        "new_session": "Nova sessão",
        "confirm_new": (
            "Sortear e registrar uma nova sessão?\n"
            "Todo sorteio é permanente e nunca é reaproveitado."
        ),
        "open_folder": "Abrir pasta dos dados",
        "folder_message": "Os dados estão em:\n{path}",
        "verify": "Verificar registro",
        "verify_ok": "Registro verificado: {n} sessões, nada foi alterado.",
        "verify_bad": "Problemas encontrados:\n{problems}",
        "logged": "Registrado no log (sessão {n}).",
        "ready": "Pronto. Nada é sorteado até você apertar “Nova sessão”.",
        "error": "Erro",
        "info": "Informação",
    },
    "es": {
        "window_title": "Aleatorizador del experimento",
        "protocol": "{arms} brazos · {conditions} condiciones · {rounds} rondas",
        "protocol_arms_only": "{arms} brazos",
        "protocol_orders_only": "{conditions} condiciones · {rounds} rondas",
        "session": "Sesión: {n}",
        "no_session": "Sesión: —",
        "arm_frame": "Brazo",
        "arm_hidden": "(oculto)",
        "reveal_arm": "Revelar brazo",
        "rounds_frame": "Orden de las condiciones en cada ronda",
        "round": "Ronda {i}",
        "new_session": "Nueva sesión",
        "confirm_new": (
            "¿Sortear y registrar una nueva sesión?\n"
            "Cada sorteo es permanente y nunca se reutiliza."
        ),
        "open_folder": "Abrir carpeta de datos",
        "folder_message": "Los datos están en:\n{path}",
        "verify": "Verificar registro",
        "verify_ok": "Registro verificado: {n} sesiones, nada fue alterado.",
        "verify_bad": "Problemas encontrados:\n{problems}",
        "logged": "Guardado en el registro (sesión {n}).",
        "ready": "Listo. No se sortea nada hasta que pulse “Nueva sesión”.",
        "error": "Error",
        "info": "Información",
    },
}


def default_language() -> str:
    """``EXPRAND_LANG`` if set, else the locale's language if it is one of ours, else English."""
    forced = os.environ.get("EXPRAND_LANG", "").lower()
    if forced in LANGUAGES:
        return forced
    try:
        name = locale.getlocale()[0] or os.environ.get("LANG", "")
    except ValueError:  # pragma: no cover - a locale string the platform cannot parse
        name = os.environ.get("LANG", "")
    return next((code for code in LANGUAGES if name.lower().startswith(code)), "en")


def t(language: str, key: str, **values: object) -> str:
    return STRINGS[language][key].format(**values)
