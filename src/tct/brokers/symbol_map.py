"""Traduce el simbolo canonico al nombre que usa cada broker.

OJO: en Windows con MT5 conectado esta tabla es solo un RESPALDO. El camino
principal es `MT5NativeBroker._resolver_contra_broker()`, que le pregunta a la
terminal que simbolos existen de verdad. Una tabla escrita a mano envejece mal
y nunca cubre a todos los brokers; preguntar es exacto.

El grupo dice "GOLD", el parser lo normaliza a "XAUUSD", pero el broker puede
llamarlo "XAUUSD.r", "XAUUSD_m" o "GOLD". Este modulo es el unico lugar donde
vive esa traduccion.

Adaptado de `app/brokers/mt5_symbol_map.py` de tradingalertaIA, cambiando el
eje: alla mapeaba Yahoo Finance -> MT5, aca mapea simbolo canonico -> broker.
"""

from __future__ import annotations

# Sufijo que agrega cada broker a los simbolos. El perfil se elige con
# MT5_BROKER_PROFILE en el .env.
_BROKER_SUFFIXES: dict[str, str] = {
    "default": "",
    "icmarkets": "",
    "metaquotes": "",
    "pepperstone": "",
    "exness": "m",       # XAUUSDm
    "fbs": "",
    "roboforex": ".r",   # XAUUSD.r
    "icmarkets_raw": ".raw",
    "fxpro": "",
    "tickmill": "",
}

# Excepciones que no se resuelven con un sufijo: el broker directamente usa
# otro nombre para el instrumento.
_BROKER_OVERRIDES: dict[str, dict[str, str]] = {
    "default": {},
    "icmarkets": {
        "NAS100": "US100",
        "US500": "US500",
        "GER40": "DE40",
        "USOIL": "XTIUSD",
        "UKOIL": "XBRUSD",
    },
    "pepperstone": {
        "NAS100": "NAS100",
        "US30": "US30",
        "GER40": "GER40",
        "USOIL": "XTIUSD",
    },
    "exness": {
        "NAS100": "USTEC",
        "US500": "USTEC500",
        "USOIL": "USOIL",
    },
    "metaquotes": {
        "NAS100": "NAS100",
        "US30": "US30",
    },
}


def to_broker_symbol(symbol: str, broker_profile: str = "default") -> str:
    """Simbolo canonico -> simbolo del broker.

    Si el perfil no se conoce, se devuelve el simbolo tal cual: es preferible
    que el broker rechace un nombre a que el bot opere el instrumento equivocado.
    """
    if not symbol:
        return symbol

    canonical = symbol.strip().upper()
    profile = (broker_profile or "default").strip().lower()

    override = _BROKER_OVERRIDES.get(profile, {}).get(canonical)
    if override:
        return override

    return canonical + _BROKER_SUFFIXES.get(profile, "")


def from_broker_symbol(broker_symbol: str, broker_profile: str = "default") -> str:
    """Inverso: sirve para reconciliar posiciones que devuelve el broker."""
    if not broker_symbol:
        return broker_symbol

    raw = broker_symbol.strip().upper()
    profile = (broker_profile or "default").strip().lower()

    for canonical, mapped in _BROKER_OVERRIDES.get(profile, {}).items():
        if mapped.upper() == raw:
            return canonical

    suffix = _BROKER_SUFFIXES.get(profile, "")
    if suffix and raw.endswith(suffix.upper()):
        return raw[: -len(suffix)]
    return raw


def supported_profiles() -> list[str]:
    return sorted(_BROKER_SUFFIXES)
