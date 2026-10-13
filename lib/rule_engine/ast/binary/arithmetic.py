#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  rule_engine/ast/binary/arithmetic.py
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

import datetime
import functools
import operator
from typing import Any, Callable, TypeGuard

from ... import errors
from ...types import DataType, coerce_value, is_numeric
from ...types import _DataTypeDef, _QuantityDataTypeDef
from ...types.quantity import Quantity

from ..base import _assert_is_bytes, _assert_is_natural_number, _assert_is_numeric, _assert_is_string, _assert_not_nullable, _is_reduced
from .base import BinaryExpressionBase

def _is_quantity_type(dt: _DataTypeDef) -> TypeGuard[_QuantityDataTypeDef]:
    return DataType.is_type(dt, DataType.QUANTITY)

def _quantity_dimension(dt: _DataTypeDef) -> str | None:
    return dt.dimension if _is_quantity_type(dt) else None

def _assert_quantities_compatible(dt1: _DataTypeDef, dt2: _DataTypeDef) -> None:
    # raise a clear error as soon as a concrete dimension mismatch is known statically; the dimension-less QUANTITY
    # sentinel represents an unknown dimension and is left for evaluation-time validation
    dim1, dim2 = _quantity_dimension(dt1), _quantity_dimension(dt2)
    if dim1 is not None and dim2 is not None and dim1 != dim2:
        raise errors.DimensionMismatchError(dim1, dim2)

def _quantity_result_type(dt1: _DataTypeDef, dt2: _DataTypeDef) -> _DataTypeDef:
    dim = _quantity_dimension(dt1) or _quantity_dimension(dt2)
    return DataType.QUANTITY if dim is None else DataType.QUANTITY(dim)

class AddExpression(BinaryExpressionBase):
    """A class for representing addition expressions from the grammar text."""
    compatible_types: tuple[_DataTypeDef, ...] = (DataType.BYTES, DataType.FLOAT, DataType.STRING, DataType.DATETIME, DataType.TIMEDELTA, DataType.QUANTITY)
    result_type: _DataTypeDef = DataType.UNDEFINED

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(AddExpression, self).__init__(*args, **kwargs)
        _assert_not_nullable(self.left.result_type, role="left operand of '+'")
        _assert_not_nullable(self.right.result_type, role="right operand of '+'")
        if self.left.result_type != DataType.UNDEFINED and self.right.result_type != DataType.UNDEFINED:
            if _is_quantity_type(self.left.result_type) or _is_quantity_type(self.right.result_type):
                if not (_is_quantity_type(self.left.result_type) and _is_quantity_type(self.right.result_type)):
                    raise errors.EvaluationError('data type mismatch (a quantity can only be added to a quantity)')
                _assert_quantities_compatible(self.left.result_type, self.right.result_type)
                self.result_type = _quantity_result_type(self.left.result_type, self.right.result_type)
            elif self.left.result_type == DataType.DATETIME:
                if self.right.result_type != DataType.TIMEDELTA:
                    raise errors.EvaluationError('data type mismatch')
                self.result_type = self.left.result_type
            elif self.left.result_type == DataType.TIMEDELTA:
                if self.right.result_type not in (DataType.DATETIME, DataType.TIMEDELTA):
                    raise errors.EvaluationError('data type mismatch')
                self.result_type = self.right.result_type
            elif self.left.result_type != self.right.result_type:
                raise errors.EvaluationError('data type mismatch')
            else:
                self.result_type = self.left.result_type

    def _op_add(self, thing: Any) -> Any:
        left_value = self.left.evaluate(thing)
        right_value = self.right.evaluate(thing)
        if isinstance(left_value, Quantity) or isinstance(right_value, Quantity):
            if not isinstance(left_value, Quantity) or not isinstance(right_value, Quantity):
                raise errors.EvaluationError('data type mismatch (not a quantity value)')
            # the Quantity value type enforces compatible dimensions and performs the unit conversion
            return left_value + right_value
        if isinstance(left_value, datetime.datetime):
            if not isinstance(right_value, datetime.timedelta):
                raise errors.EvaluationError('data type mismatch (not a timedelta value)')
        elif isinstance(left_value, datetime.timedelta):
            if not isinstance(right_value, (datetime.timedelta, datetime.datetime)):
                raise errors.EvaluationError('data type mismatch (not a datetime or timedelta value)')
        elif isinstance(left_value, bytes) or isinstance(right_value, bytes):
            _assert_is_bytes(left_value, right_value)
        elif isinstance(left_value, str) or isinstance(right_value, str):
            _assert_is_string(left_value, right_value)
        else:
            _assert_is_numeric(left_value, right_value)
        return operator.add(left_value, right_value)

class SubtractExpression(BinaryExpressionBase):
    """
    A class for representing subtraction expressions from the grammar text.

    .. versionadded:: 3.5.0
    """
    compatible_types: tuple[_DataTypeDef, ...] = (DataType.FLOAT, DataType.DATETIME, DataType.TIMEDELTA, DataType.QUANTITY)
    result_type: _DataTypeDef = DataType.UNDEFINED

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(SubtractExpression, self).__init__(*args, **kwargs)
        _assert_not_nullable(self.left.result_type, role="left operand of '-'")
        _assert_not_nullable(self.right.result_type, role="right operand of '-'")
        if self.left.result_type != DataType.UNDEFINED and self.right.result_type != DataType.UNDEFINED:
            if _is_quantity_type(self.left.result_type) or _is_quantity_type(self.right.result_type):
                if not (_is_quantity_type(self.left.result_type) and _is_quantity_type(self.right.result_type)):
                    raise errors.EvaluationError('data type mismatch (a quantity can only be subtracted from a quantity)')
                _assert_quantities_compatible(self.left.result_type, self.right.result_type)
                self.result_type = _quantity_result_type(self.left.result_type, self.right.result_type)
            elif self.left.result_type == DataType.DATETIME:
                if self.right.result_type == DataType.DATETIME:
                    self.result_type = DataType.TIMEDELTA
                elif self.right.result_type == DataType.TIMEDELTA:
                    self.result_type = DataType.DATETIME
                else:
                    raise errors.EvaluationError('data type mismatch')
            elif self.left.result_type == DataType.TIMEDELTA:
                if self.right.result_type != DataType.TIMEDELTA:
                    raise errors.EvaluationError('data type mismatch')
                self.result_type = self.left.result_type
            elif self.left.result_type != self.right.result_type:
                raise errors.EvaluationError('data type mismatch')
            else:
                self.result_type = self.left.result_type

    def _op_sub(self, thing: Any) -> Any:
        left_value = self.left.evaluate(thing)
        right_value = self.right.evaluate(thing)
        if isinstance(left_value, Quantity) or isinstance(right_value, Quantity):
            if not isinstance(left_value, Quantity) or not isinstance(right_value, Quantity):
                raise errors.EvaluationError('data type mismatch (not a quantity value)')
            # the Quantity value type enforces compatible dimensions and performs the unit conversion
            return left_value - right_value
        if isinstance(left_value, datetime.datetime):
            if not isinstance(right_value, (datetime.datetime, datetime.timedelta)):
                raise errors.EvaluationError('data type mismatch (not a datetime or timedelta value)')
        elif isinstance(left_value, datetime.timedelta):
            if not isinstance(right_value, datetime.timedelta):
                raise errors.EvaluationError('data type mismatch (not a timedelta value)')
        else:
            _assert_is_numeric(left_value, right_value)
        return operator.sub(left_value, right_value)

class ArithmeticExpression(BinaryExpressionBase):
    """A class for representing arithmetic expressions from the grammar text such as multiplication and division."""
    compatible_types: tuple[_DataTypeDef, ...] = (DataType.FLOAT, DataType.QUANTITY)
    result_type: _DataTypeDef = DataType.FLOAT
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(ArithmeticExpression, self).__init__(*args, **kwargs)
        _assert_not_nullable(self.left.result_type, role='left arithmetic operand')
        _assert_not_nullable(self.right.result_type, role='right arithmetic operand')
        left_type, right_type = self.left.result_type, self.right.result_type
        if left_type != DataType.UNDEFINED and right_type != DataType.UNDEFINED:
            left_is_quantity = _is_quantity_type(left_type)
            right_is_quantity = _is_quantity_type(right_type)
            if left_is_quantity or right_is_quantity:
                if left_is_quantity and right_is_quantity:
                    _assert_quantities_compatible(left_type, right_type)
                    if self.type in ('tdiv', 'fdiv'):
                        # the ratio of two quantities is dimensionless
                        self.result_type = DataType.FLOAT
                    elif self.type == 'mod':
                        self.result_type = _quantity_result_type(left_type, right_type)
                    else:
                        raise errors.EvaluationError('data type mismatch (two quantities can not be multiplied or exponentiated)')
                elif left_is_quantity:
                    if right_type != DataType.FLOAT:
                        raise errors.EvaluationError('data type mismatch (a quantity can only be combined with a number)')
                    if self.type == 'pow':
                        raise errors.EvaluationError('data type mismatch (a quantity can not be exponentiated)')
                    self.result_type = _quantity_result_type(left_type, right_type)
                else:
                    if self.type != 'mul':
                        raise errors.EvaluationError('data type mismatch (a quantity may only be scaled by multiplication)')
                    self.result_type = _quantity_result_type(left_type, right_type)

    def __op_arithmetic(self, op: Callable[[Any, Any], Any], thing: Any) -> Any:
        left_value = self.left.evaluate(thing)
        right_value = self.right.evaluate(thing)
        try:
            if isinstance(left_value, Quantity) or isinstance(right_value, Quantity):
                result = self.__op_arithmetic_quantity(op, left_value, right_value)
            else:
                _assert_is_numeric(left_value)
                _assert_is_numeric(right_value)
                result = op(left_value, right_value)
        except ZeroDivisionError:
            raise errors.ArithmeticError('arithmetic error: division by zero') from None
        except ArithmeticError:
            raise errors.ArithmeticError('arithmetic error') from None
        return result

    def __op_arithmetic_quantity(self, op: Callable[[Any, Any], Any], left_value: Any, right_value: Any) -> Any:
        if isinstance(left_value, Quantity) and isinstance(right_value, Quantity):
            if op in (operator.mul, operator.pow):
                raise errors.EvaluationError('data type mismatch (two quantities can not be multiplied or exponentiated)')
            left_value._check_compatible(right_value)
            right_value = right_value.to(left_value.unit)
            if op in (operator.truediv, operator.floordiv):
                # the ratio of two quantities is a dimensionless number
                return op(left_value.value, right_value.value)
            # modulo keeps the unit of the left operand
            return Quantity(op(left_value.value, right_value.value), left_value.unit)
        elif isinstance(left_value, Quantity):
            if op is operator.pow:
                raise errors.EvaluationError('data type mismatch (a quantity can not be exponentiated)')
            if not is_numeric(right_value):
                raise errors.EvaluationError('data type mismatch (not a numeric value)')
            if op is operator.mul:
                return left_value.scale(right_value)
            return Quantity(op(left_value.value, right_value), left_value.unit)
        else:
            if op is not operator.mul or not is_numeric(left_value):
                raise errors.EvaluationError('data type mismatch (a quantity may only be scaled by multiplication)')
            return right_value.scale(left_value)

    _op_fdiv = functools.partialmethod(__op_arithmetic, operator.floordiv)
    _op_tdiv = functools.partialmethod(__op_arithmetic, operator.truediv)
    _op_mod  = functools.partialmethod(__op_arithmetic, operator.mod)
    _op_mul  = functools.partialmethod(__op_arithmetic, operator.mul)
    _op_pow  = functools.partialmethod(__op_arithmetic, operator.pow)

class BitwiseExpression(BinaryExpressionBase):
    """
    A class for representing bitwise arithmetic expressions from the grammar text such as XOR and shifting operations.
    """
    compatible_types: tuple[_DataTypeDef, ...] = (DataType.FLOAT, DataType.SET)
    result_type: _DataTypeDef = DataType.UNDEFINED
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(BitwiseExpression, self).__init__(*args, **kwargs)
        _assert_not_nullable(self.left.result_type, role='left bitwise operand')
        _assert_not_nullable(self.right.result_type, role='right bitwise operand')
        # don't use DataType.is_compatible, because for sets the member type isn't important
        if self.left.result_type != DataType.UNDEFINED and self.right.result_type != DataType.UNDEFINED:
            if self.left.result_type.__class__ != self.right.result_type.__class__:
                raise errors.EvaluationError('data type mismatch')
        if self.left.result_type == DataType.FLOAT:
            if _is_reduced(self.left):
                _assert_is_natural_number(self.left.evaluate(None))
            self.result_type = DataType.FLOAT
        if self.right.result_type == DataType.FLOAT:
            if _is_reduced(self.right):
                _assert_is_natural_number(self.right.evaluate(None))
            self.result_type = DataType.FLOAT
        if DataType.is_type(self.left.result_type, DataType.SET) or DataType.is_type(self.right.result_type, DataType.SET):
            self.result_type = DataType.SET  # this discards the member type info

    def _op_bitwise(self, op: Callable[[Any, Any], Any], thing: Any) -> Any:
        left = self.left.evaluate(thing)
        if DataType.from_value(left) == DataType.FLOAT:
            return self._op_bitwise_float(op, thing, left)
        elif DataType.is_type(DataType.from_value(left), DataType.SET):
            return self._op_bitwise_set(op, thing, left)
        raise errors.EvaluationError('data type mismatch')

    def _op_bitwise_float(self, op: Callable[[Any, Any], Any], thing: Any, left: Any) -> Any:
        _assert_is_natural_number(left)
        right = self.right.evaluate(thing)
        _assert_is_natural_number(right)
        return coerce_value(op(int(left), int(right)))

    def _op_bitwise_set(self, op: Callable[[Any, Any], Any], thing: Any, left: Any) -> Any:
        right = self.right.evaluate(thing)
        if not DataType.is_compatible(DataType.from_value(right), DataType.SET):
            raise errors.EvaluationError('data type mismatch')
        return op(left, right)

    _op_bwand = functools.partialmethod(_op_bitwise, operator.and_)
    _op_bwor  = functools.partialmethod(_op_bitwise, operator.or_)
    _op_bwxor = functools.partialmethod(_op_bitwise, operator.xor)

class BitwiseShiftExpression(BitwiseExpression):
    compatible_types: tuple[_DataTypeDef, ...] = (DataType.FLOAT,)
    result_type: _DataTypeDef = DataType.FLOAT
    def _op_bitwise_shift(self, *args: Any, **kwargs: Any) -> Any:
        return self._op_bitwise(*args, **kwargs)
    _op_bwlsh = functools.partialmethod(_op_bitwise_shift, operator.lshift)
    _op_bwrsh = functools.partialmethod(_op_bitwise_shift, operator.rshift)
