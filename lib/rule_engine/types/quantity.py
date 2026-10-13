#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  rule_engine/types/quantity.py
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are
#  met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following disclaimer
#    in the documentation and/or other materials provided with the
#    distribution.
#  * Neither the name of the project nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
#  "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
#  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
#  A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
#  OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
#  SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
#  LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
#  DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
#  THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

from __future__ import annotations

import decimal
from typing import Any, Iterator, Union

from .. import errors

# supported physical dimensions; the names intentionally mirror the DataType convention (upper case)
DIMENSION_TIME = 'TIME'
DIMENSION_INFORMATION = 'INFORMATION'

class Unit(object):
    """
    A unit of measure belonging to a physical *dimension*. Units are related to the dimension's base unit through an
    exact decimal *factor* (``base_magnitude = value * factor``), so all conversions remain precise regardless of the
    active :py:class:`~decimal.Context`.

    .. versionadded:: 5.1.0
    """
    __slots__ = ('name', 'symbol', 'dimension', 'factor', 'is_base')
    name: str
    symbol: str
    dimension: str
    factor: decimal.Decimal
    is_base: bool
    def __init__(self, name: str, symbol: str, dimension: str, factor: decimal.Decimal, is_base: bool = False) -> None:
        self.name = name
        self.symbol = symbol
        self.dimension = dimension
        self.factor = decimal.Decimal(factor)
        self.is_base = is_base

    def __repr__(self) -> str:
        return "<Unit name={0!r} symbol={1!r} dimension={2} factor={3} >".format(
                self.name,
                self.symbol,
                self.dimension,
                self.factor
        )

def _unit(name: str, symbol: str, dimension: str, factor: Any, is_base: bool = False) -> Unit:
    return Unit(name, symbol, dimension, decimal.Decimal(factor), is_base=is_base)

# registry of all supported units, keyed by their case-sensitive symbol
UNITS: dict[str, Unit] = {}
# alternative spellings accepted by get_unit (e.g. from the parse_quantity builtin); literal syntax uses symbols only
UNIT_ALIASES: dict[str, str] = {}

def _register(unit: Unit, aliases: tuple[str, ...] = ()) -> None:
    UNITS[unit.symbol] = unit
    for alias in aliases:
        UNIT_ALIASES[alias] = unit.symbol

_register(_unit('second', 's', DIMENSION_TIME, 1, is_base=True), aliases=('second', 'seconds', 'sec', 'secs'))
_register(_unit('millisecond', 'ms', DIMENSION_TIME, '0.001'), aliases=('millisecond', 'milliseconds'))
_register(_unit('byte', 'B', DIMENSION_INFORMATION, 1, is_base=True), aliases=('byte', 'bytes'))
_register(_unit('kibibyte', 'KiB', DIMENSION_INFORMATION, 1024), aliases=('kibibyte', 'kibibytes'))

def get_unit(name: str) -> Unit:
    """
    Look up a :py:class:`Unit` by its case-sensitive symbol (e.g. ``s``, ``ms``, ``B``, ``KiB``) or one of its aliases
    (e.g. ``seconds``, ``bytes``).

    :param str name: The unit symbol or alias to look up.
    :return: The matching unit.
    :raises ValueError: If no unit is registered under *name*.

    .. versionadded:: 5.1.0
    """
    symbol = UNIT_ALIASES.get(name, name)
    try:
        return UNITS[symbol]
    except KeyError:
        raise ValueError("unknown unit: {0!r}".format(name)) from None

def iter_units(dimension: str) -> Iterator[Unit]:
    """Iterate over all registered units of the specified *dimension*."""
    for unit in UNITS.values():
        if unit.dimension == dimension:
            yield unit

def _to_decimal(value: Any) -> decimal.Decimal:
    if isinstance(value, decimal.Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return decimal.Decimal(value)
    if isinstance(value, float):
        return decimal.Decimal(repr(value))
    return decimal.Decimal(value)

class Quantity(object):
    """
    A precise, dimensioned quantity consisting of a :py:class:`~decimal.Decimal` magnitude and a :py:class:`Unit`.
    Quantities of the same dimension can be compared, converted and combined regardless of their unit, while mixing
    dimensions (e.g. a duration with an information size) raises :py:exc:`~rule_engine.errors.DimensionMismatchError`.

    Arithmetic honors the current :py:class:`~decimal.Context`, preserving the semantics of the engine's
    :py:attr:`~rule_engine.types.DataType.FLOAT` data type.

    .. versionadded:: 5.1.0
    """
    __slots__ = ('value', 'unit')
    value: decimal.Decimal
    unit: Unit
    def __init__(self, value: Any, unit: Union[Unit, str]) -> None:
        if not isinstance(unit, Unit):
            unit = get_unit(unit)
        self.value = _to_decimal(value)
        self.unit = unit

    def __repr__(self) -> str:
        return "<{0} {1} {2} >".format(self.__class__.__name__, self.value, self.unit.symbol)

    def __str__(self) -> str:
        return "{0} {1}".format(self.value, self.unit.symbol)

    @property
    def dimension(self) -> str:
        """The physical dimension of the quantity (e.g. ``TIME`` or ``INFORMATION``)."""
        return self.unit.dimension

    def base_magnitude(self) -> decimal.Decimal:
        """Return the magnitude expressed in the dimension's base unit (seconds for ``TIME``, bytes for ``INFORMATION``)."""
        return self.value * self.unit.factor

    def to(self, unit: Union[Unit, str]) -> 'Quantity':
        """
        Convert the quantity to another *unit* of the same dimension.

        :param unit: The target unit or its symbol.
        :return: A new quantity expressed in *unit*.
        :raises ~rule_engine.errors.DimensionMismatchError: If *unit* belongs to a different dimension.
        """
        if not isinstance(unit, Unit):
            unit = get_unit(unit)
        if unit.dimension != self.unit.dimension:
            raise errors.DimensionMismatchError(self.unit.dimension, unit.dimension)
        return Quantity(self.base_magnitude() / unit.factor, unit)

    def _check_compatible(self, other: 'Quantity') -> None:
        if not isinstance(other, Quantity):
            raise errors.EvaluationError('data type mismatch (not a quantity value)')
        if other.unit.dimension != self.unit.dimension:
            raise errors.DimensionMismatchError(self.unit.dimension, other.unit.dimension)

    def ratio(self, other: 'Quantity') -> decimal.Decimal:
        """Return the dimensionless ratio of two quantities of the same dimension (``self / other``)."""
        self._check_compatible(other)
        return self.base_magnitude() / other.base_magnitude()

    def scale(self, factor: decimal.Decimal) -> 'Quantity':
        """Return the quantity multiplied by a dimensionless *factor*, keeping the unit."""
        return Quantity(self.value * factor, self.unit)

    def __add__(self, other: Any) -> 'Quantity':
        if not isinstance(other, Quantity):
            return NotImplemented
        self._check_compatible(other)
        return Quantity(self.value + other.to(self.unit).value, self.unit)

    def __sub__(self, other: Any) -> 'Quantity':
        if not isinstance(other, Quantity):
            return NotImplemented
        self._check_compatible(other)
        return Quantity(self.value - other.to(self.unit).value, self.unit)

    def __neg__(self) -> 'Quantity':
        return Quantity(-self.value, self.unit)

    def __pos__(self) -> 'Quantity':
        return Quantity(+self.value, self.unit)

    def __abs__(self) -> 'Quantity':
        return Quantity(abs(self.value), self.unit)

    def __bool__(self) -> bool:
        return bool(self.value)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Quantity):
            return NotImplemented
        self._check_compatible(other)
        return self.base_magnitude() == other.base_magnitude()

    def __ne__(self, other: Any) -> bool:
        if not isinstance(other, Quantity):
            return NotImplemented
        self._check_compatible(other)
        return self.base_magnitude() != other.base_magnitude()

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Quantity):
            return NotImplemented
        self._check_compatible(other)
        return self.base_magnitude() < other.base_magnitude()

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, Quantity):
            return NotImplemented
        self._check_compatible(other)
        return self.base_magnitude() <= other.base_magnitude()

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Quantity):
            return NotImplemented
        self._check_compatible(other)
        return self.base_magnitude() > other.base_magnitude()

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, Quantity):
            return NotImplemented
        self._check_compatible(other)
        return self.base_magnitude() >= other.base_magnitude()

    def __hash__(self) -> int:
        return hash((self.unit.dimension, self.base_magnitude()))
