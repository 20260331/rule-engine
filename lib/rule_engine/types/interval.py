#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  rule_engine/types/interval.py
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

import datetime
import decimal
from typing import Any, Iterator

from .. import errors

__all__ = ('AtomicInterval', 'Interval')

class AtomicInterval(object):
    """
    A single, non-empty, continuous interval between two endpoints. Either endpoint may be :py:data:`None` to
    indicate that the interval is unbounded on that side. Whether or not a finite endpoint is included in the
    interval is controlled by its corresponding closed flag.

    Instances are immutable and the closed flag of an unbounded side is always normalized to :py:data:`True`.
    Direct construction assumes the bounds describe a non-empty interval; use the :func:`_atomic` factory to have
    empty pieces (e.g. ``(1, 1)`` or ``(2, 1)``) represented by :py:data:`None`.

    .. versionadded:: 5.1.0
    """
    __slots__ = ('left', 'left_closed', 'right', 'right_closed')
    left: Any
    left_closed: bool
    right: Any
    right_closed: bool
    def __init__(
            self,
            left: Any = None,
            right: Any = None,
            *,
            left_closed: bool = True,
            right_closed: bool = False
    ) -> None:
        left, right = self._coerce_endpoints(left, right)
        self.left = left
        # the inclusivity of an unbounded side is meaningless; normalize to True so equivalent intervals compare
        # equal regardless of the flags that were originally provided
        self.left_closed = True if left is None else bool(left_closed)
        self.right = right
        self.right_closed = True if right is None else bool(right_closed)

    @staticmethod
    def _coerce_endpoints(left: Any, right: Any) -> tuple[Any, Any]:
        from .coercion import coerce_value
        if left is not None:
            left = coerce_value(left)
        if right is not None:
            right = coerce_value(right)
        for endpoint in (left, right):
            if endpoint is None:
                continue
            if isinstance(endpoint, decimal.Decimal):
                if not endpoint.is_finite():
                    # NaN is unordered and would break every comparison; an explicit infinity is expressed by
                    # omitting the endpoint (None) for an unbounded side
                    raise ValueError('interval endpoints must be finite (omit the endpoint for an unbounded side)')
            elif not isinstance(endpoint, (datetime.datetime, datetime.timedelta)):
                raise TypeError(
                        'interval endpoints must be numeric, datetime or timedelta values, not ' + type(endpoint).__name__
                )
        return left, right

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AtomicInterval):
            return NotImplemented
        return all((
                self.left == other.left,
                self.left_closed == other.left_closed,
                self.right == other.right,
                self.right_closed == other.right_closed,
        ))

    def __hash__(self) -> int:
        return hash((self.left, self.left_closed, self.right, self.right_closed))

    def __repr__(self) -> str:
        left = '' if self.left is None else str(self.left)
        right = '' if self.right is None else str(self.right)
        return '{0}{1}..{2}{3}'.format(
                '[' if self.left_closed else '(',
                left,
                right,
                ']' if self.right_closed else ')'
        )

    @property
    def domain_type_name(self) -> str | None:
        """The name of the endpoint data type, or :py:data:`None` when the interval is unbounded on both sides."""
        endpoint = self.left if self.left is not None else self.right
        if endpoint is None:
            return None
        if isinstance(endpoint, decimal.Decimal):
            return 'FLOAT'
        if isinstance(endpoint, datetime.datetime):
            return 'DATETIME'
        if isinstance(endpoint, datetime.timedelta):
            return 'TIMEDELTA'
        return None

    def contains(self, value: Any) -> bool:
        if self.left is not None:
            if type(value) is not type(self.left):
                raise errors.EvaluationError('data type mismatch')
            if value < self.left or (value == self.left and not self.left_closed):
                return False
        if self.right is not None:
            if type(value) is not type(self.right):
                raise errors.EvaluationError('data type mismatch')
            if value > self.right or (value == self.right and not self.right_closed):
                return False
        return True

    def overlaps(self, other: 'AtomicInterval') -> bool:
        return self.intersection(other) is not None

    def touches(self, other: 'AtomicInterval') -> bool:
        """Whether the two intervals are adjacent with no gap between them, i.e. the meeting point belongs to one."""
        if self.right is not None and other.left is not None and self.right == other.left:
            return self.right_closed or other.left_closed
        return False

    def intersection(self, other: 'AtomicInterval') -> 'AtomicInterval | None':
        # select the greater lower bound; when tied the point is included only when both sides include it
        if self.left is None:
            left, left_closed = other.left, other.left_closed
        elif other.left is None:
            left, left_closed = self.left, self.left_closed
        elif self.left > other.left:
            left, left_closed = self.left, self.left_closed
        elif self.left < other.left:
            left, left_closed = other.left, other.left_closed
        else:
            left, left_closed = self.left, self.left_closed and other.left_closed
        # select the lesser upper bound; when tied the point is included only when both sides include it
        if self.right is None:
            right, right_closed = other.right, other.right_closed
        elif other.right is None:
            right, right_closed = self.right, self.right_closed
        elif self.right < other.right:
            right, right_closed = self.right, self.right_closed
        elif self.right > other.right:
            right, right_closed = other.right, other.right_closed
        else:
            right, right_closed = self.right, self.right_closed and other.right_closed
        return _atomic(left, right, left_closed=left_closed, right_closed=right_closed)

    def union(self, other: 'AtomicInterval') -> 'Interval':
        return Interval.from_atoms(_merge_atoms((self, other)))

    def difference(self, other: 'AtomicInterval') -> 'Interval':
        return Interval.from_atoms(_subtract_atoms(self, other))

def _atomic(
        left: Any = None,
        right: Any = None,
        *,
        left_closed: bool = True,
        right_closed: bool = False
) -> AtomicInterval | None:
    """Construct an :py:class:`AtomicInterval`, returning :py:data:`None` when the bounds describe no point."""
    atom = AtomicInterval(left, right, left_closed=left_closed, right_closed=right_closed)
    if atom.left is not None and atom.right is not None:
        if atom.left > atom.right:
            return None
        if atom.left == atom.right and not (atom.left_closed and atom.right_closed):
            return None
    return atom

class Interval(object):
    """
    A continuous interval value backed by one or more disjoint, non-adjacent :py:class:`AtomicInterval` pieces. A
    literal interval (e.g. ``[1..10)``) contains a single atom while the algebraic operations
    (:py:meth:`intersection`, :py:meth:`union`, :py:meth:`difference`) are free to produce values spanning multiple
    pieces (e.g. ``[1..10) - [3..5)`` is both ``[1..3)`` and ``[5..10)``).

    Endpoints are ordered values of a single domain which must be either :py:attr:`~.DataType.FLOAT`,
    :py:attr:`~.DataType.DATETIME` or :py:attr:`~.DataType.TIMEDELTA`. :py:data:`None` endpoints denote unbounded
    sides. An interval with no atoms is the empty interval: it contains no values, compares equal to every other
    empty interval and acts as the identity for :py:meth:`union` and as the absorbing value for
    :py:meth:`intersection` and :py:meth:`difference`.

    .. versionadded:: 5.1.0
    """
    __slots__ = ('atoms',)
    atoms: tuple[AtomicInterval, ...]
    def __init__(
            self,
            left: Any = None,
            right: Any = None,
            *,
            left_closed: bool = True,
            right_closed: bool = False
    ) -> None:
        atom = _atomic(left, right, left_closed=left_closed, right_closed=right_closed)
        self.atoms = () if atom is None else (atom,)

    @classmethod
    def from_atoms(cls, atoms: Iterator[AtomicInterval] | tuple[AtomicInterval, ...] | list[AtomicInterval]) -> 'Interval':
        interval = object.__new__(cls)
        interval.atoms = tuple(_merge_atoms(atoms))
        return interval

    def __and__(self, other: object) -> 'Interval':
        if not isinstance(other, Interval):
            return NotImplemented
        return self.intersection(other)

    def __bool__(self) -> bool:
        return bool(self.atoms)

    def __contains__(self, value: Any) -> bool:
        if value is None:
            # mirror Python's containers where None membership is a normal (false) check rather than a type error
            return False
        if not self.atoms:
            return False
        domain = self.atoms[0].domain_type_name
        value = _coerce_domain_value(value, domain)
        if value is None:
            raise errors.EvaluationError('data type mismatch')
        return any(atom.contains(value) for atom in self.atoms)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Interval):
            return NotImplemented
        return self.atoms == other.atoms

    def __hash__(self) -> int:
        return hash(self.atoms)

    def __iter__(self) -> Iterator[AtomicInterval]:
        return iter(self.atoms)

    def __len__(self) -> int:
        return len(self.atoms)

    def __or__(self, other: object) -> 'Interval':
        if not isinstance(other, Interval):
            return NotImplemented
        return self.union(other)

    def __repr__(self) -> str:
        if not self.atoms:
            return 'empty interval'
        return ' | '.join(repr(atom) for atom in self.atoms)

    def __sub__(self, other: object) -> 'Interval':
        if not isinstance(other, Interval):
            return NotImplemented
        return self.difference(other)

    def __xor__(self, other: object) -> 'Interval':
        if not isinstance(other, Interval):
            return NotImplemented
        return self.symmetric_difference(other)

    @property
    def domain_type_name(self) -> str | None:
        """The name of the endpoint data type, or :py:data:`None` for an empty / fully unbounded value."""
        for atom in self.atoms:
            name = atom.domain_type_name
            if name is not None:
                return name
        return None

    @property
    def is_empty(self) -> bool:
        return not self.atoms

    def difference(self, other: 'Interval') -> 'Interval':
        """Return the part of this interval that is not part of *other*."""
        if not isinstance(other, Interval):
            raise TypeError('can only subtract an interval from an interval')
        if not self.atoms or not other.atoms:
            return self if not other.atoms else Interval.from_atoms(())
        _assert_same_domain(self, other)
        remaining: list[AtomicInterval] = list(self.atoms)
        for subtrahend in other.atoms:
            pieces: list[AtomicInterval] = []
            for piece in remaining:
                pieces.extend(_subtract_atoms(piece, subtrahend))
            remaining = pieces
            if not remaining:
                break
        return Interval.from_atoms(remaining)

    def intersection(self, other: 'Interval') -> 'Interval':
        """Return the interval covering the values that are part of both intervals."""
        if not isinstance(other, Interval):
            raise TypeError('can only intersect an interval with an interval')
        if not self.atoms or not other.atoms:
            return Interval.from_atoms(())
        _assert_same_domain(self, other)
        atoms: list[AtomicInterval] = []
        for left in self.atoms:
            for right in other.atoms:
                atom = left.intersection(right)
                if atom is not None:
                    atoms.append(atom)
        return Interval.from_atoms(atoms)

    def symmetric_difference(self, other: 'Interval') -> 'Interval':
        """Return the values that are part of exactly one of the two intervals."""
        return self.union(other).difference(self.intersection(other))

    def union(self, other: 'Interval') -> 'Interval':
        """Return the interval covering all values from both intervals."""
        if not isinstance(other, Interval):
            raise TypeError('can only union an interval with an interval')
        if not other.atoms:
            return self
        if not self.atoms:
            return other
        _assert_same_domain(self, other)
        return Interval.from_atoms(_merge_atoms(self.atoms + other.atoms))

def _is_domain_value(value: Any, domain: str | None) -> bool:
    if domain == 'FLOAT':
        return isinstance(value, decimal.Decimal)
    if domain == 'DATETIME':
        return isinstance(value, datetime.datetime)
    if domain == 'TIMEDELTA':
        return isinstance(value, datetime.timedelta)
    # a fully unbounded interval provides no static domain; accept any otherwise valid endpoint value
    return isinstance(value, (decimal.Decimal, datetime.datetime, datetime.timedelta))

def _coerce_domain_value(value: Any, domain: str | None) -> Any:
    """Coerce a candidate membership value to its native representation, returning :py:data:`None` on mismatch."""
    from .coercion import coerce_value
    if domain == 'FLOAT':
        if isinstance(value, bool) or not isinstance(value, (decimal.Decimal, float, int)):
            return None
        return coerce_value(value)
    if domain == 'DATETIME':
        if not isinstance(value, (datetime.date, datetime.datetime)):
            return None
        return coerce_value(value)
    if domain == 'TIMEDELTA':
        return value if isinstance(value, datetime.timedelta) else None
    coerced = coerce_value(value, verify_type=False)
    return coerced if _is_domain_value(coerced, domain) else None

def _assert_same_domain(left: Interval, right: Interval) -> None:
    left_name = left.domain_type_name
    right_name = right.domain_type_name
    if left_name is not None and right_name is not None and left_name != right_name:
        raise errors.EvaluationError('data type mismatch')

def _sort_key(atom: AtomicInterval) -> tuple[Any, int, Any, int]:
    # unbounded (-infinity) sides sort first; for equal lower values the closed side sorts first so that merging
    # preserves the inclusive flag
    return (
            atom.left is not None,
            atom.left,
            0 if atom.left_closed else 1,
            0 if atom.right_closed else 1,
    )

def _merge_atoms(atoms: Iterator[AtomicInterval] | tuple[AtomicInterval, ...] | list[AtomicInterval]) -> list[AtomicInterval]:
    """Sort *atoms* and merge any that overlap or meet at a mutually included point."""
    ordered = sorted(atoms, key=_sort_key)
    merged: list[AtomicInterval] = []
    for atom in ordered:
        if not merged:
            merged.append(atom)
            continue
        previous = merged[-1]
        if previous.intersection(atom) is not None or previous.touches(atom):
            right, right_closed = previous.right, previous.right_closed
            if atom.right is None:
                right, right_closed = None, True
            elif right is not None:
                if atom.right > right or (atom.right == right and atom.right_closed):
                    right, right_closed = atom.right, atom.right_closed
            replacement = _atomic(
                    previous.left,
                    right,
                    left_closed=previous.left_closed,
                    right_closed=right_closed
            )
            if replacement is None:
                continue
            merged[-1] = replacement
        else:
            merged.append(atom)
    return merged

def _subtract_atoms(piece: AtomicInterval, subtrahend: AtomicInterval) -> list[AtomicInterval]:
    if piece.intersection(subtrahend) is None:
        return [piece]
    results: list[AtomicInterval] = []
    # left remnant, ending where the subtrahend begins; the boundary point is kept when the subtrahend excludes it.
    # a subtrahend that is unbounded on the left leaves no remnant on that side
    if subtrahend.left is not None:
        left_remnant = _atomic(
                piece.left,
                subtrahend.left,
                left_closed=piece.left_closed,
                right_closed=not subtrahend.left_closed
        )
        if left_remnant is not None:
            results.append(left_remnant)
    # right remnant, beginning where the subtrahend ends; the boundary point is kept when the subtrahend excludes it.
    # a subtrahend that is unbounded on the right leaves no remnant on that side
    if subtrahend.right is not None:
        right_remnant = _atomic(
                subtrahend.right,
                piece.right,
                left_closed=not subtrahend.right_closed,
                right_closed=piece.right_closed
        )
        if right_remnant is not None:
            results.append(right_remnant)
    return results
