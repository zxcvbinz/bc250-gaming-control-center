"""Lingue dell'interfaccia.

Il testo sorgente è l'italiano: T("Limite FPS") ritorna la traduzione nella lingua attuale,
o l'italiano se manca. Per aggiungere una lingua: un file lang_xx.py con un dict XX
{"testo italiano": "traduzione"} e una voce in LANGS.
"""
import importlib

LANGS = [("it", "Italiano"), ("en", "English")]
SOURCE = "it"

_lang = SOURCE
_tables = {}


def _table(code):
    if code == SOURCE:
        return None
    if code not in _tables:
        try:
            mod = importlib.import_module(f".lang_{code}", __package__)
            _tables[code] = getattr(mod, code.upper(), {})
        except ImportError:
            _tables[code] = {}
    return _tables[code]


def set_lang(code):
    global _lang
    _lang = code if code in dict(LANGS) else SOURCE


def get_lang():
    return _lang


def T(text, **kw):
    """Traduce `text` (italiano) nella lingua attuale, poi .format(**kw) se servono valori."""
    tab = _table(_lang)
    out = tab.get(text, text) if tab else text
    if not kw:
        return out
    try:
        return out.format(**kw)
    except (KeyError, IndexError, ValueError):
        return text.format(**kw)   # traduzione sbagliata: meglio l'italiano che un errore


def _init():
    # import qui dentro: common non importa i18n, niente cicli
    try:
        from . import common
        set_lang(common.load_config().get("language", SOURCE))
    except Exception:
        pass


_init()
