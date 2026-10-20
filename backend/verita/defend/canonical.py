"""RFC 8785 JSON Canonicalization Scheme (JCS).

Two parties that hash "the same" JSON must produce the same bytes. JCS fixes the three things
ordinary serialisers leave open:

* object members sorted by their names' UTF-16 code units (not by Python's code points);
* numbers in the ECMAScript ``Number.prototype.toString`` form (shortest round-trip digits,
  exponent only outside [1e-6, 1e21), no ``+`` on positive mantissas, ``-0`` → ``0``);
* strings with the minimal JSON escapes and everything else as raw UTF-8.

Only JSON values are accepted: ``dict`` (string keys), ``list``/``tuple``, ``str``, ``int``,
``float`` (finite), ``bool`` and ``None``. Anything else is a programming error, so it raises.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}
MAX_SAFE_INTEGER = 2**53 - 1
_LITERALS = {None: "null", True: "true", False: "false"}


class CanonicalizationError(ValueError):
    """The value cannot be represented in canonical JSON."""


def _string(value: str) -> str:
    out = ['"']
    for ch in value:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:  # noqa: PLR2004 - control characters
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _number(value: float) -> str:
    """ECMAScript Number::toString for a finite double (ECMA-262 §7.1.12.1)."""
    if not math.isfinite(value):
        msg = "NaN and Infinity are not JSON numbers"
        raise CanonicalizationError(msg)
    if value == 0:
        return "0"  # also -0
    if value < 0:
        return "-" + _number(-value)
    # repr() gives the shortest digits that round-trip (the same digits ECMAScript uses);
    # Decimal splits them into a digit string and a power of ten.
    _, raw_digits, exponent = Decimal(repr(value)).as_tuple()
    digits = "".join(map(str, raw_digits)).lstrip("0")
    stripped = digits.rstrip("0")
    point = len(digits) + int(exponent)  # value = 0.digits × 10^point
    digits = stripped
    k, n = len(digits), point
    if k <= n <= 21:  # noqa: PLR2004
        return digits + "0" * (n - k)
    if 0 < n <= 21:  # noqa: PLR2004
        return f"{digits[:n]}.{digits[n:]}"
    if -6 < n <= 0:  # noqa: PLR2004
        return "0." + "0" * (-n) + digits
    e = n - 1
    sign = "+" if e >= 0 else "-"
    head = digits[0] if k == 1 else f"{digits[0]}.{digits[1:]}"
    return f"{head}e{sign}{abs(e)}"


def _utf16_key(name: str) -> list[int]:
    data = name.encode("utf-16-be")
    return [int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data), 2)]


def _integer(value: int) -> str:
    """JSON numbers are IEEE-754 doubles (RFC 8785 §3.2.2.3). An integer is accepted only when
    a double holds it exactly; otherwise a reader would silently round it (2**53 + 1 → 2**53)
    and the two parties would hash different numbers."""
    if abs(value) <= MAX_SAFE_INTEGER:
        return str(value)
    try:
        spelled = _number(float(value))
    except OverflowError:
        spelled = ""
    if spelled != str(value) and float(spelled or "nan") != value:
        msg = f"integer {value} is not exactly representable as an IEEE-754 double"
        raise CanonicalizationError(msg)
    return spelled


def _emit(value: Any, out: list[str]) -> None:
    if value is None or isinstance(value, bool):  # bool before int: True is an int
        out.append(_LITERALS[value])
    elif isinstance(value, int):
        out.append(_integer(value))
    elif isinstance(value, float):
        out.append(_number(value))
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _emit(item, out)
        out.append("]")
    elif isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            msg = "object keys must be strings"
            raise CanonicalizationError(msg)
        out.append("{")
        for i, key in enumerate(sorted(value, key=_utf16_key)):
            if i:
                out.append(",")
            out.append(_string(key))
            out.append(":")
            _emit(value[key], out)
        out.append("}")
    else:
        msg = f"{type(value).__name__} is not a JSON value"
        raise CanonicalizationError(msg)


def canonicalize(value: Any) -> bytes:
    """The RFC 8785 canonical UTF-8 bytes of a JSON value."""
    out: list[str] = []
    _emit(value, out)
    return "".join(out).encode("utf-8")
