"""Telegram Copy Trading: lee senales de Telegram y las replica en MT5.

Escalera de riesgo (TRADING_MODE):
    AUTO                   -> por defecto. Elige segun las credenciales del
                              .env: MT5 demo si hay MetaApi, papel si no.
    PAPER_ONLY             -> solo registra, no manda nada. Funciona en macOS.
    PAPER_AND_METAAPI_DEMO -> registra y ejecuta en MT5 demo via MetaApi. macOS.
    PAPER_AND_MT5_DEMO     -> registra y ejecuta en MT5 demo local. SOLO Windows.
    LIVE                   -> dinero real. Necesita ademas ALLOW_LIVE_TRADING=true.
"""

__version__ = "0.5.0"
