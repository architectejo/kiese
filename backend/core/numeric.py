"""
Analyse numerique stricte PARTAGEE (BUG-1015 a 1019).

Une seule regle canonique pour toutes les entrees de quantite de production,
voie REST comme voie push de synchronisation :

* acceptes : `int` Python (pas `bool`), `float` entier (7.0), `Decimal` fini,
  et chaine ASCII apres retrait des SEULS espaces ASCII, de la forme
  `[-+]?[0-9]+(\\.0+)?` (entier) ou `[-+]?[0-9]+(\\.[0-9]+)?` (decimal) ;
* refuses : bool, None, exposants (`7E0`, `1e3`), soulignes (`1_0`), chiffres
  non ASCII, espaces non ASCII (NBSP, U+3000, U+2007...), listes/dicts,
  decimales non nulles pour un entier, chaines vides ou > 32 caracteres,
  `NaN` / `Infinity`.

Les fonctions levent `NumericError` (sous-classe de `ValueError`, message
francais, attribut `reason` : `invalid`, `too_small`, `too_big`, `places`).
"""
import re
from decimal import Decimal, InvalidOperation

ASCII_SPACES = ' \t\n\r\x0b\x0c'
MAX_TEXT_LENGTH = 32
_INT_RE = re.compile(r'[-+]?[0-9]+(?:\.0+)?')
_DEC_RE = re.compile(r'[-+]?[0-9]+(?:\.[0-9]+)?')
_HUGE = Decimal(10) ** 40


class NumericError(ValueError):
    def __init__(self, message, reason='invalid'):
        super().__init__(message)
        self.reason = reason


def _canonical_text(value, label):
    """Forme textuelle sans exposant de `value`, ou NumericError."""
    bad = NumericError(f"« {label} » invalide : nombre en chiffres 0-9 attendu.", 'invalid')
    if value is None or isinstance(value, bool):
        raise bad
    if isinstance(value, int):
        if value.bit_length() > 140:
            raise NumericError(f"« {label} » hors plage.", 'too_big' if value > 0 else 'too_small')
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float('inf'), float('-inf')):
            raise bad
        if abs(value) >= 1e30:
            raise NumericError(f"« {label} » hors plage.", 'too_big' if value > 0 else 'too_small')
        return format(Decimal(repr(value)), 'f')
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise bad
        if value.adjusted() > 40 or value.as_tuple().exponent < -60:
            raise NumericError(f"« {label} » hors plage.", 'too_big' if value > 0 else 'too_small')
        return format(value, 'f')
    if isinstance(value, str):
        text = value.strip(ASCII_SPACES)
        if not text or len(text) > MAX_TEXT_LENGTH:
            raise bad
        return text
    raise bad


def parse_ascii_int(value, *, minimum=None, maximum=None, allow_negative=True, label='valeur'):
    """Entier strict (regle canonique). Renvoie un `int` ou leve NumericError."""
    text = _canonical_text(value, label)
    if not _INT_RE.fullmatch(text):
        raise NumericError(f"« {label} » invalide : nombre entier en chiffres 0-9 attendu.", 'invalid')
    number = int(Decimal(text))
    if not allow_negative and number < 0:
        raise NumericError(f"« {label} » ne peut pas être négatif.", 'too_small')
    if minimum is not None and number < minimum:
        raise NumericError(f"« {label} » ne peut pas être inférieur à {minimum}.", 'too_small')
    if maximum is not None and number > maximum:
        raise NumericError(f"« {label} » ne peut pas dépasser {maximum}.", 'too_big')
    return number


def parse_ascii_decimal(value, *, places, minimum=None, maximum=None, max_digits=None, label='valeur'):
    """
    Decimal strict (regle canonique) a `places` decimales au plus, SANS arrondi
    silencieux. Renvoie un `Decimal` quantifie ou leve NumericError.
    """
    text = _canonical_text(value, label)
    if not _DEC_RE.fullmatch(text):
        raise NumericError(f"« {label} » invalide : nombre en chiffres 0-9 attendu.", 'invalid')
    try:
        number = Decimal(text)
        quantized = number.quantize(Decimal(1).scaleb(-places))
    except InvalidOperation:
        raise NumericError(f"« {label} » invalide ou hors plage.", 'invalid')
    if quantized != number:
        raise NumericError(f"« {label} » : {places} décimale(s) au maximum.", 'places')
    if quantized == 0:
        quantized = quantized.copy_abs()  # « -0 » devient 0
    if minimum is not None and quantized < minimum:
        raise NumericError(f"« {label} » ne peut pas être inférieur à {minimum}.", 'too_small')
    if maximum is not None and quantized > maximum:
        raise NumericError(f"« {label} » ne peut pas dépasser {maximum}.", 'too_big')
    if max_digits is not None and len(quantized.as_tuple().digits) > max_digits:
        raise NumericError(f"« {label} » invalide ou hors plage.", 'too_big')
    return quantized
