#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  rule_engine/ast/literal.py
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

import collections
from typing import TYPE_CHECKING, Any, Iterable

from .. import errors
from ..parser.utilities import parse_datetime, parse_float, parse_timedelta
from ..types import DataType, coerce_value
from ..types import _DataTypeDef
from ..types.interval import Interval

from .base import (
        ExpressionBase,
        LiteralExpressionBase,
        _assert_not_nullable,
        _is_reduced,
        _iterable_member_value_type,
)

if TYPE_CHECKING:
    from ..engine.context import Context

# the scalar data types that are permitted as continuous interval endpoints
_interval_endpoint_types: tuple[_DataTypeDef, ...] = (DataType.DATETIME, DataType.TIMEDELTA, DataType.FLOAT)

def _interval_endpoint_value_type(endpoints: Iterable[Any]) -> _DataTypeDef:
    """Infer the endpoint type of an interval from its bound expressions, validating that they share a domain."""
    endpoint_types = set()
    for endpoint in endpoints:
        if endpoint is None:
            continue
        result_type = endpoint.result_type if isinstance(endpoint, ExpressionBase) else endpoint
        if result_type == DataType.UNDEFINED:
            continue
        if result_type not in _interval_endpoint_types:
            raise errors.EvaluationError('data type mismatch (interval endpoints must be float, datetime or timedelta values)')
        endpoint_types.add(result_type)
    if len(endpoint_types) > 1:
        raise errors.EvaluationError('data type mismatch (interval endpoints must be of the same type)')
    return endpoint_types.pop() if endpoint_types else DataType.UNDEFINED

################################################################################
# Literal Expressions
################################################################################
class _CollectionMixin(object):
    # these attributes are provided by the LiteralExpressionBase half of the subclasses
    result_type: _DataTypeDef
    value: Any
    def evaluate(self, thing: Any) -> Any:
        return self.result_type.python_type(member.evaluate(thing) for member in self.value)

    @property
    def is_reduced(self) -> bool:  # type: ignore[override]
        return _is_reduced(*self.value)

    def to_graphviz(self, digraph: Any, *args: Any, **kwargs: Any) -> None:
        super(_CollectionMixin, self).to_graphviz(digraph, *args, **kwargs)  # type: ignore[misc]
        for member in self.value:
            member.to_graphviz(digraph, *args, **kwargs)
            digraph.edge(str(id(self)), str(id(member)))

class ArrayExpression(_CollectionMixin, LiteralExpressionBase):  # type: ignore[override]
    """Literal array expressions containing 0 or more sub-expressions."""
    result_type: _DataTypeDef = DataType.ARRAY
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(ArrayExpression, self).__init__(*args, **kwargs)
        self.result_type = DataType.ARRAY(value_type=_iterable_member_value_type(self.value))

    @classmethod
    def build(cls, context: 'Context', value: Iterable[ExpressionBase]) -> 'ArrayExpression':  # type: ignore[override]
        return cls(context, [member.build() for member in value])

class BooleanExpression(LiteralExpressionBase):
    """Literal boolean expressions representing True or False."""
    result_type: _DataTypeDef = DataType.BOOLEAN

class BytesExpression(LiteralExpressionBase):
    """
    Literal bytes expressions representing a binary string. This expression type always evaluates to true when not empty.
    """
    result_type: _DataTypeDef = DataType.BYTES

class DatetimeExpression(LiteralExpressionBase):
    """
    Literal datetime expressions representing a specific point in time. This expression type always evaluates to true.
    """
    result_type: _DataTypeDef = DataType.DATETIME
    @classmethod
    def from_string(cls, context: 'Context', string: str) -> 'DatetimeExpression':
        dt = parse_datetime(string, default_timezone=context.default_timezone)
        return cls(context, dt)

class TimedeltaExpression(LiteralExpressionBase):
    """
    Literal timedelta expressions representing an offset from a specific point in time.

    .. versionadded:: 3.5.0
    """
    result_type: _DataTypeDef = DataType.TIMEDELTA
    @classmethod
    def from_string(cls, context: 'Context', string: str) -> 'TimedeltaExpression':
        return cls(context, parse_timedelta(string))

class FloatExpression(LiteralExpressionBase):
    """Literal float expressions representing numerical values."""
    result_type: _DataTypeDef = DataType.FLOAT
    def __init__(self, context: 'Context', value: Any, **kwargs: Any) -> None:
        value = coerce_value(value)
        super(FloatExpression, self).__init__(context, value, **kwargs)

    @classmethod
    def from_string(cls, context: 'Context', string: str) -> 'FloatExpression':
        return cls(context, parse_float(string))

class FunctionExpression(LiteralExpressionBase):
    """Literal mapping expression representing a function."""
    # there's no syntax for defining functions, but this is required by the parser when a method is referred to on a
    # literal value, e.g. `b"41".decode('utf-8')`
    result_type: _DataTypeDef = DataType.FUNCTION

class IntervalExpression(LiteralExpressionBase):
    """
    Literal continuous interval expressions such as ``[1..10)`` or ``[d"2020-01-01"..]``. The value may span one or
    more disjoint atoms when the expression is the reduced result of interval algebra (e.g. ``[1..10) - [3..5)``).

    .. versionadded:: 5.1.0
    """
    result_type: _DataTypeDef = DataType.INTERVAL
    def __init__(self, context: 'Context', value: Interval) -> None:
        super(IntervalExpression, self).__init__(context, value)
        self.result_type = DataType.from_value(value)

class IntervalBoundsExpression(ExpressionBase):
    """
    An interval literal whose endpoint expressions have not (yet) been reduced to literal values. This allows
    endpoints to reference symbols and built-ins such as ``[d"2020-01-01" .. $now]``. The expression reduces to an
    :py:class:`IntervalExpression` as soon as both endpoints are reduced literals.

    .. versionadded:: 5.1.0
    """
    __slots__ = ('left', 'right', 'left_closed', 'right_closed')
    left: ExpressionBase | None
    right: ExpressionBase | None
    left_closed: bool
    right_closed: bool
    def __init__(
            self,
            context: 'Context',
            *,
            left: ExpressionBase | None = None,
            right: ExpressionBase | None = None,
            left_closed: bool = True,
            right_closed: bool = False
    ) -> None:
        self.context = context
        for endpoint, role in ((left, 'left'), (right, 'right')):
            if endpoint is not None:
                _assert_not_nullable(endpoint.result_type, role='{} interval endpoint'.format(role))
        value_type = _interval_endpoint_value_type((left, right))
        self.result_type = DataType.INTERVAL(value_type)
        self.left = left
        self.right = right
        self.left_closed = bool(left_closed)
        self.right_closed = bool(right_closed)

    @classmethod
    def build(  # type: ignore[override]
            cls,
            context: 'Context',
            *,
            left: ExpressionBase | None = None,
            right: ExpressionBase | None = None,
            left_closed: bool = True,
            right_closed: bool = False
    ) -> ExpressionBase:
        left_built = left.build() if left is not None else None
        right_built = right.build() if right is not None else None
        assert left_built is None or isinstance(left_built, ExpressionBase)
        assert right_built is None or isinstance(right_built, ExpressionBase)
        reduced = cls(
                context,
                left=left_built,
                right=right_built,
                left_closed=left_closed,
                right_closed=right_closed
        ).reduce()
        assert isinstance(reduced, ExpressionBase)
        return reduced

    def __repr__(self) -> str:
        return "<{0} left={1!r} right={2!r} >".format(self.__class__.__name__, self.left, self.right)

    def evaluate(self, thing: Any) -> Interval:
        values: list[Any] = []
        for endpoint, role in ((self.left, 'left'), (self.right, 'right')):
            if endpoint is None:
                values.append(None)
                continue
            value = endpoint.evaluate(thing)
            if value is None:
                # an omitted endpoint is genuinely unbounded; a present expression that yields null is a type error
                raise errors.EvaluationError(
                        'data type mismatch ({} interval endpoint is null; omit the endpoint for an unbounded side)'.format(role)
                )
            value_type = DataType.from_value(value)
            if value_type not in _interval_endpoint_types:
                raise errors.EvaluationError('data type mismatch (interval endpoints must be float, datetime or timedelta values)')
            values.append(value)
        left_value, right_value = values
        if left_value is not None and right_value is not None and type(left_value) is not type(right_value):
            raise errors.EvaluationError('data type mismatch (interval endpoints must be of the same type)')
        try:
            return Interval(
                    left_value,
                    right_value,
                    left_closed=self.left_closed,
                    right_closed=self.right_closed
            )
        except (TypeError, ValueError) as error:
            raise errors.EvaluationError('data type mismatch ({})'.format(str(error))) from None

    def reduce(self) -> ExpressionBase:
        endpoints = tuple(endpoint for endpoint in (self.left, self.right) if endpoint is not None)
        if not _is_reduced(*endpoints):
            return self
        return IntervalExpression(self.context, self.evaluate(None))

    def to_graphviz(self, digraph: Any, *args: Any, **kwargs: Any) -> None:
        super(IntervalBoundsExpression, self).to_graphviz(digraph, *args, **kwargs)
        for endpoint, label in ((self.left, 'left'), (self.right, 'right')):
            if endpoint is not None:
                endpoint.to_graphviz(digraph, *args, **kwargs)
                digraph.edge(str(id(self)), str(id(endpoint)), label=label)

class MappingExpression(LiteralExpressionBase):
    """Literal mapping expression representing a set of associations between keys and values."""
    result_type: _DataTypeDef = DataType.MAPPING
    def __init__(self, context: 'Context', value: Any, **kwargs: Any) -> None:
        if isinstance(value, dict):
            value = tuple(value.items())
        super(MappingExpression, self).__init__(context, value, **kwargs)
        self.result_type = DataType.MAPPING(
                key_type=_iterable_member_value_type(key for key, _ in self.value),
                value_type=_iterable_member_value_type(value for _, value in self.value)
        )

    @classmethod
    def build(cls, context: 'Context', value: Any) -> 'MappingExpression':  # type: ignore[override]
        value = collections.OrderedDict(value)
        value = collections.OrderedDict((k.build(), v.build()) for k, v in value.items())
        return cls(context, value)

    def evaluate(self, thing: Any) -> Any:
        mapping: 'collections.OrderedDict[Any, Any]' = collections.OrderedDict()
        for key, value in self.value:
            key = key.evaluate(thing)
            key_type = DataType.from_value(key)
            if key_type.is_compound and not DataType.is_type(key_type, DataType.ARRAY):
                raise errors.EngineError("the {} data type may not be used for mapping keys".format(key_type.name))
            mapping[key] = value
        # defer value evaluation to avoid evaluating values of duplicate keys
        for key, value in mapping.items():
            mapping[key] = value.evaluate(thing)
        return mapping

    @property
    def is_reduced(self) -> bool:  # type: ignore[override]
        return all(_is_reduced(key, value) for key, value in self.value)

class NullExpression(LiteralExpressionBase):
    """Literal null expressions representing null values. This expression type always evaluates to false."""
    result_type: _DataTypeDef = DataType.NULL
    def __init__(self, context: 'Context', value: Any = None) -> None:
        # all of the literal expressions take a value
        if value is not None:
            raise TypeError('value must be None')
        super(NullExpression, self).__init__(context, value=None)

class SetExpression(_CollectionMixin, LiteralExpressionBase):  # type: ignore[override]
    """Literal set expressions containing 0 or more sub-expressions."""
    result_type: _DataTypeDef = DataType.SET
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(SetExpression, self).__init__(*args, **kwargs)
        self.result_type = DataType.SET(value_type=_iterable_member_value_type(self.value))

    @classmethod
    def build(cls, context: 'Context', value: Iterable[ExpressionBase]) -> 'SetExpression':  # type: ignore[override]
        built = set(member.build() for member in value)
        return cls(context, built)

class StringExpression(LiteralExpressionBase):
    """Literal string expressions representing an array of characters."""
    result_type: _DataTypeDef = DataType.STRING
