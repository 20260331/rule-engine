#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  tests/quantity.py
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

import decimal
import unittest

import rule_engine
import rule_engine.ast as ast
import rule_engine.engine as engine
import rule_engine.errors as errors
import rule_engine.parser.utilities as parser_utilities
import rule_engine.types as types

__all__ = ('QuantityDataTypeTests', 'QuantityRuleTests', 'QuantityTests')

DataType = types.DataType
Quantity = types.Quantity

class QuantityTests(unittest.TestCase):
    def test_construct_and_lookup(self):
        self.assertEqual(Quantity(1, 's').unit.symbol, 's')
        self.assertEqual(Quantity(1, types.get_unit('ms')).unit.dimension, 'TIME')
        self.assertEqual(types.get_unit('seconds').symbol, 's')
        self.assertEqual(types.get_unit('bytes').symbol, 'B')
        self.assertEqual(types.get_unit('kibibytes').symbol, 'KiB')
        with self.assertRaises(ValueError):
            types.get_unit('parsec')
        with self.assertRaises(ValueError):
            Quantity(1, 'parsec')

    def test_dimension_and_conversion(self):
        self.assertEqual(Quantity(1, 's').dimension, 'TIME')
        self.assertEqual(Quantity(1, 'KiB').dimension, 'INFORMATION')
        self.assertEqual(Quantity(1, 's').to('ms'), Quantity(1000, 'ms'))
        self.assertEqual(Quantity(1000, 'ms').to('s'), Quantity(1, 's'))
        self.assertEqual(Quantity(1, 'KiB').to('B'), Quantity(1024, 'B'))
        self.assertEqual(Quantity(1, 'B').to('KiB'), Quantity(decimal.Decimal('0.0009765625'), 'KiB'))
        with self.assertRaises(errors.DimensionMismatchError):
            Quantity(1, 's').to('B')

    def test_conversion_is_exact_decimal(self):
        # quantities must keep the Decimal semantics of the FLOAT data type (no binary float artifacts)
        result = Quantity(decimal.Decimal('0.1'), 's') + Quantity(decimal.Decimal('0.2'), 's')
        self.assertEqual(result.value, decimal.Decimal('0.3'))
        self.assertEqual(Quantity(3, 'B').to('KiB').value * 1024, decimal.Decimal('3'))

    def test_comparison_across_units(self):
        self.assertTrue(Quantity(1, 's') == Quantity(1000, 'ms'))
        self.assertFalse(Quantity(2, 's') == Quantity(1000, 'ms'))
        self.assertTrue(Quantity(1, 'KiB') > Quantity(1023, 'B'))
        self.assertTrue(Quantity(500, 'ms') < Quantity(1, 's'))
        self.assertTrue(Quantity(1, 'KiB') >= Quantity(1024, 'B'))
        self.assertTrue(Quantity(1, 'B') <= Quantity(1, 'B'))
        self.assertFalse(Quantity(1, 'B') != Quantity(1, 'B'))
        with self.assertRaises(errors.DimensionMismatchError):
            Quantity(1, 's') < Quantity(1, 'B')
        with self.assertRaises(errors.DimensionMismatchError):
            Quantity(1, 's') == Quantity(1, 'B')

    def test_arithmetic(self):
        result = Quantity(500, 'ms') + Quantity('0.5', 's')
        self.assertEqual(result, Quantity(1, 's'))
        self.assertEqual(result.unit.symbol, 'ms')
        self.assertEqual(Quantity(1, 's') - Quantity(250, 'ms'), Quantity(decimal.Decimal('0.750'), 's'))
        self.assertEqual(-Quantity(5, 'B'), Quantity(-5, 'B'))
        self.assertEqual(Quantity(3, 's').scale(2), Quantity(6, 's'))
        self.assertEqual(Quantity(1, 'KiB').ratio(Quantity(512, 'B')), decimal.Decimal('2'))
        self.assertEqual(hash(Quantity(1, 's')), hash(Quantity(1000, 'ms')))
        self.assertTrue(Quantity(1, 's'))
        self.assertFalse(Quantity(0, 's'))
        with self.assertRaises(errors.DimensionMismatchError):
            Quantity(1, 's') + Quantity(1, 'B')
        with self.assertRaises(errors.DimensionMismatchError):
            Quantity(1, 'KiB') - Quantity(1, 'ms')

    def test_special_methods_and_registry(self):
        quantity = Quantity(-5, 'ms')
        self.assertEqual(str(Quantity(1, 's')), '1 s')
        self.assertEqual(repr(Quantity(1, 's')), '<Quantity 1 s >')
        self.assertEqual(+quantity, quantity)
        self.assertEqual(abs(quantity), Quantity(5, 'ms'))
        self.assertNotEqual(Quantity(1, 's'), Quantity(2, 's'))
        self.assertTrue(Quantity(1, 's') <= Quantity(1000, 'ms'))
        self.assertTrue(Quantity(1, 's') >= Quantity(1000, 'ms'))
        self.assertTrue(Quantity(1, 's') > Quantity(999, 'ms'))
        self.assertEqual({unit.symbol for unit in types.iter_units('TIME')}, {'s', 'ms'})
        self.assertEqual({unit.symbol for unit in types.iter_units('INFORMATION')}, {'B', 'KiB'})
        # incompatible operand types fall back to Python's reflected-operation protocol rather than raising
        self.assertIs(Quantity(1, 's').__eq__(1), NotImplemented)
        self.assertIs(Quantity(1, 's').__add__(1), NotImplemented)
        with self.assertRaises(errors.EvaluationError):
            Quantity(1, 's')._check_compatible(1)

    def test_parse_quantity(self):
        self.assertEqual(parser_utilities.parse_quantity('30s'), Quantity(30, 's'))
        self.assertEqual(parser_utilities.parse_quantity('500ms'), Quantity(500, 'ms'))
        self.assertEqual(parser_utilities.parse_quantity('1024B'), Quantity(1024, 'B'))
        self.assertEqual(parser_utilities.parse_quantity('1KiB'), Quantity(1, 'KiB'))
        self.assertEqual(parser_utilities.parse_quantity('1.5e3ms'), Quantity(1500, 'ms'))
        for invalid in ('', 's', '1', '1m', '1 x', '01s', '1kib'):
            with self.assertRaises(errors.QuantitySyntaxError, msg=invalid) as cm:
                parser_utilities.parse_quantity(invalid)
            self.assertEqual(cm.exception.value, invalid)

class QuantityDataTypeTests(unittest.TestCase):
    def test_data_type_from_value(self):
        self.assertEqual(DataType.from_value(Quantity(1, 's')), DataType.QUANTITY('TIME'))
        self.assertEqual(DataType.from_value(Quantity(1, 'B')), DataType.QUANTITY('INFORMATION'))
        self.assertEqual(DataType.from_type(Quantity), DataType.QUANTITY)
        self.assertTrue(DataType.is_type(DataType.QUANTITY('TIME'), DataType.QUANTITY))
        self.assertNotEqual(DataType.QUANTITY('TIME'), DataType.QUANTITY('INFORMATION'))
        self.assertEqual(DataType.QUANTITY('TIME'), DataType.QUANTITY('TIME'))
        self.assertNotEqual(DataType.QUANTITY('TIME'), DataType.FLOAT)

    def test_data_type_compatibility(self):
        self.assertTrue(DataType.is_compatible(DataType.QUANTITY('TIME'), DataType.QUANTITY('TIME')))
        self.assertFalse(DataType.is_compatible(DataType.QUANTITY('TIME'), DataType.QUANTITY('INFORMATION')))
        # the dimension-less sentinel represents an unknown dimension and is checked at evaluation time instead
        self.assertTrue(DataType.is_compatible(DataType.QUANTITY, DataType.QUANTITY('TIME')))
        self.assertTrue(DataType.is_compatible(DataType.QUANTITY('TIME'), DataType.QUANTITY))
        self.assertFalse(DataType.is_compatible(DataType.QUANTITY('TIME'), DataType.FLOAT))

    def test_data_type_coercion_and_members(self):
        quantity = Quantity(1, 's')
        self.assertIs(types.coerce_value(quantity), quantity)
        member_type = types.iterable_member_value_type((Quantity(1, 's'), Quantity(2, 'ms')))
        self.assertEqual(member_type, DataType.QUANTITY('TIME'))
        member_type = types.iterable_member_value_type((Quantity(1, 's'), Quantity(2, 'B')))
        self.assertIs(member_type, DataType.UNDEFINED)
        self.assertIn('QUANTITY', DataType)

class QuantityRuleTests(unittest.TestCase):
    def setUp(self):
        self.context = engine.Context()

    def _eval(self, rule, thing=None, context=None):
        return rule_engine.Rule(rule, context=context or self.context).evaluate(thing or {})

    def test_literal_equivalence(self):
        self.assertTrue(self._eval('1s == 1000ms'))
        self.assertTrue(self._eval('1KiB == 1024B'))
        self.assertFalse(self._eval('1s != 1000ms'))
        self.assertTrue(self._eval('1500ms > 1s'))
        self.assertTrue(self._eval('1023B < 1KiB'))
        self.assertTrue(self._eval('1000ms >= 1s'))
        self.assertTrue(self._eval('1KiB <= 1024B'))

    def test_literal_result_type(self):
        for rule, dimension in (('1s', 'TIME'), ('500ms', 'TIME'), ('1B', 'INFORMATION'), ('1KiB', 'INFORMATION')):
            statement = engine.Rule(rule).statement
            self.assertIsInstance(statement.expression, ast.QuantityExpression)
            self.assertEqual(statement.expression.result_type, DataType.QUANTITY(dimension))

    def test_arithmetic_results(self):
        self.assertEqual(self._eval('500ms + 500ms'), Quantity(1000, 'ms'))
        self.assertEqual(self._eval('1s - 250ms'), Quantity(decimal.Decimal('0.750'), 's'))
        self.assertEqual(self._eval('-250ms'), Quantity(-250, 'ms'))
        self.assertEqual(self._eval('2 * 30s'), Quantity(60, 's'))
        self.assertEqual(self._eval('30s * 2'), Quantity(60, 's'))
        self.assertEqual(self._eval('1KiB / 2'), Quantity(decimal.Decimal('0.5'), 'KiB'))
        self.assertEqual(self._eval('1500B // 1024'), Quantity(1, 'B'))
        self.assertEqual(self._eval('1500B % 1024'), Quantity(476, 'B'))
        self.assertEqual(self._eval('1000ms % 300ms'), Quantity(100, 'ms'))
        # floor division of a quantity by a number keeps the quantity's own unit
        self.assertEqual(self._eval('1500ms // 1000'), Quantity(1, 'ms'))
        # division of two quantities is a dimensionless FLOAT
        self.assertEqual(self._eval('1KiB / 512B'), decimal.Decimal('2'))
        self.assertEqual(self._eval('1s // 300ms'), decimal.Decimal('3'))
        self.assertNotIsInstance(self._eval('1KiB / 512B'), Quantity)
        # literal operations are reduced at parse time
        self.assertIsInstance(engine.Rule('1s + 2s').statement.expression, ast.QuantityExpression)
        self.assertIsInstance(engine.Rule('1KiB / 1B').statement.expression, ast.FloatExpression)

    def test_arithmetic_errors(self):
        with self.assertRaises(errors.ArithmeticError):
            self._eval('1s / 0')
        with self.assertRaises(errors.ArithmeticError):
            self._eval('1s % 0ms')
        with self.assertRaises(errors.EvaluationError):
            self._eval('1s ** 2')
        with self.assertRaises(errors.EvaluationError):
            self._eval('2 / 1s')
        with self.assertRaises(errors.EvaluationError):
            self._eval('1s * 1ms')
        # the same invalid combinations are also caught at evaluation time when the types are not statically known
        with self.assertRaises(errors.EvaluationError):
            self._eval('a * b', {'a': Quantity(1, 's'), 'b': Quantity(1, 's')})
        with self.assertRaises(errors.EvaluationError):
            self._eval('a ** b', {'a': Quantity(1, 's'), 'b': decimal.Decimal(2)})
        with self.assertRaises(errors.EvaluationError):
            self._eval('a / b', {'a': decimal.Decimal(2), 'b': Quantity(1, 's')})
        with self.assertRaises(errors.EvaluationError):
            self._eval('a * b', {'a': Quantity(1, 's'), 'b': 'not a number'})

    def test_symbol_comparison_and_evaluation_time_errors(self):
        # untyped symbols defer the dimension check to evaluation time
        self.assertTrue(self._eval('latency > 500ms', {'latency': Quantity(1, 's')}))
        self.assertTrue(self._eval('size == 1024B', {'size': Quantity(1, 'KiB')}))
        with self.assertRaises(errors.DimensionMismatchError):
            self._eval('a > b', {'a': Quantity(1, 's'), 'b': Quantity(1, 'B')})
        with self.assertRaises(errors.EvaluationError):
            self._eval('a == b', {'a': Quantity(1, 's'), 'b': decimal.Decimal(1)})
        with self.assertRaises(errors.EvaluationError):
            self._eval('a + b', {'a': Quantity(1, 's'), 'b': decimal.Decimal(1)})
        # scaling a quantity by a plain number (either operand order) is supported
        self.assertEqual(self._eval('a * b', {'a': Quantity(30, 's'), 'b': decimal.Decimal(2)}), Quantity(60, 's'))
        self.assertEqual(self._eval('a * b', {'a': decimal.Decimal(2), 'b': Quantity(30, 's')}), Quantity(60, 's'))

    def test_typed_context_compile_time_checks(self):
        context = engine.Context(type_resolver=rule_engine.type_resolver_from_dict({
                'latency': DataType.QUANTITY('TIME'),
                'size': DataType.QUANTITY('INFORMATION'),
        }))
        self.assertTrue(rule_engine.Rule('latency > 500ms', context=context).evaluate({'latency': Quantity('1.5', 's')}))
        for rule in ('latency > 1B', 'latency + size', 'size == latency', 'latency == 1'):
            with self.assertRaises(errors.EvaluationError, msg=rule):
                rule_engine.Rule(rule, context=context)

    def test_conversion_attributes(self):
        self.assertEqual(self._eval('1s.milliseconds'), decimal.Decimal('1000'))
        self.assertEqual(self._eval('1500ms.seconds'), decimal.Decimal('1.5'))
        self.assertEqual(self._eval('1KiB.bytes'), decimal.Decimal('1024'))
        self.assertEqual(self._eval('1536B.kibibytes'), decimal.Decimal('1.5'))
        self.assertEqual(self._eval('size.bytes', {'size': Quantity(2, 'KiB')}), decimal.Decimal('2048'))

    def test_parse_quantity_builtin(self):
        self.assertIsInstance(self._eval('$parse_quantity("30s")'), Quantity)
        self.assertTrue(self._eval('$parse_quantity("1KiB") == 1024B'))
        with self.assertRaises(errors.FunctionCallError):
            self._eval('$parse_quantity("invalid")')

    def test_containers_and_control_flow(self):
        self.assertEqual(self._eval('[1s, 2000ms]'), (Quantity(1, 's'), Quantity(2000, 'ms')))
        self.assertTrue(self._eval('1s in {1000ms, 2s}'))
        self.assertEqual(self._eval('{1000ms: "one second"}[1s]'), 'one second')
        self.assertEqual(self._eval('x > 0 ? 1s : 2s', {'x': 1}), Quantity(1, 's'))
        self.assertTrue(self._eval('1s and 2s'))
        self.assertFalse(self._eval('0s or 0B'))

    def test_null_comparisons(self):
        # equality with NULL mirrors the other data types and allows null-checking nullable quantities
        self.assertFalse(self._eval('1s == null'))
        self.assertTrue(self._eval('1s != null'))
        self.assertFalse(self._eval('null == 1s'))
        self.assertTrue(self._eval('null != 1s'))
        self.assertTrue(self._eval('null == null'))
        context = engine.Context(type_resolver=rule_engine.type_resolver_from_dict({
                'latency': DataType.NULLABLE(DataType.QUANTITY('TIME')),
        }))
        self.assertTrue(rule_engine.Rule('latency == null', context=context).evaluate({'latency': None}))
        self.assertFalse(rule_engine.Rule('latency == null', context=context).evaluate({'latency': Quantity(1, 's')}))
        for rule in ('1s > null', '1s < null', '1s >= null', '1s <= null'):
            with self.assertRaises(errors.EvaluationError, msg=rule):
                rule_engine.Rule(rule)

if __name__ == '__main__':
    unittest.main()
