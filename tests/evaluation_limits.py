#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  tests/evaluation_limits.py
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

import operator
import pickle
import queue
import threading
import unittest

import rule_engine

__all__ = (
    'ASTStepLimitTests',
    'ContainerItemLimitTests',
    'EvaluationLimitContextTests',
    'EvaluationLimitResidueTests',
)

class _CountingIterator(object):
    """An iterator which counts fetched members and reports an exact remaining length hint."""
    def __init__(self, values, owner):
        self._iterator = iter(values)
        self._owner = owner

    def __iter__(self):
        return self

    def __next__(self):
        value = next(self._iterator)
        self._owner.fetched += 1
        return value

    def __length_hint__(self):
        return operator.length_hint(self._iterator, 0)

class _CountingSet(set):
    """
    A set which counts how many of its members the comprehension loop fetches. Member-type detection iterates the
    set before evaluation proper and is ignored (the first pass); only members pulled by the comprehension's own
    iteration loop (the second pass) are counted.
    """
    def __init__(self, values):
        super(_CountingSet, self).__init__(values)
        self.passes = 0
        self.fetched = 0

    def __iter__(self):
        self.passes += 1
        base_iterator = super(_CountingSet, self).__iter__()
        if self.passes == 1:
            return base_iterator
        return _CountingIterator(base_iterator, self)

class EvaluationLimitContextTests(unittest.TestCase):
    def test_context_limits_default(self):
        context = rule_engine.Context()
        self.assertIsNone(context.max_ast_steps)
        self.assertIsNone(context.max_container_items)

    def test_context_limits_stored(self):
        context = rule_engine.Context(max_ast_steps=10, max_container_items=20)
        self.assertEqual(context.max_ast_steps, 10)
        self.assertEqual(context.max_container_items, 20)

    def test_context_limit_validation(self):
        self.assertEqual(rule_engine.Context(max_ast_steps=1).max_ast_steps, 1)
        for bad_value in (0, -1):
            with self.assertRaises(ValueError):
                rule_engine.Context(max_ast_steps=bad_value)
            with self.assertRaises(ValueError):
                rule_engine.Context(max_container_items=bad_value)
        for bad_value in (1.5, '5', True, False):
            with self.assertRaises(TypeError):
                rule_engine.Context(max_ast_steps=bad_value)
            with self.assertRaises(TypeError):
                rule_engine.Context(max_container_items=bad_value)

    def test_context_limits_pickle(self):
        context = rule_engine.Context(max_ast_steps=10, max_container_items=20)
        restored = pickle.loads(pickle.dumps(context))
        self.assertEqual(restored.max_ast_steps, 10)
        self.assertEqual(restored.max_container_items, 20)

class ASTStepLimitTests(unittest.TestCase):
    def test_step_limit_allows_bounded_evaluation(self):
        # 'a + b' executes three AST nodes: the add expression and the two symbol expressions
        context = rule_engine.Context(max_ast_steps=3)
        rule = rule_engine.Rule('a + b', context=context)
        self.assertEqual(rule.evaluate({'a': 1, 'b': 2}), 3)

    def test_step_limit_stops_evaluation(self):
        context = rule_engine.Context(max_ast_steps=2)
        rule = rule_engine.Rule('a + b', context=context)
        with self.assertRaises(rule_engine.ASTStepLimitError) as cm:
            rule.evaluate({'a': 1, 'b': 2})
        error = cm.exception
        self.assertEqual(error.limit, 2)
        self.assertEqual(error.usage, 3)
        self.assertIsInstance(error, rule_engine.EvaluationLimitError)
        self.assertIsInstance(error, rule_engine.EvaluationError)
        self.assertIsInstance(error, rule_engine.EngineError)
        self.assertIn('AST step', str(error))
        self.assertIn('limit=2', repr(error))

    def test_step_limit_does_not_meter_parse_time_reduction(self):
        # '1 + 2' is folded into a single literal at parse time, so evaluation needs exactly one AST step
        context = rule_engine.Context(max_ast_steps=1)
        rule = rule_engine.Rule('1 + 2', context=context)
        self.assertEqual(rule.evaluate(None), 3)

    def test_step_limit_comprehension(self):
        context = rule_engine.Context(max_ast_steps=10)
        rule = rule_engine.Rule('[x * 2 for x in items]', context=context)
        with self.assertRaises(rule_engine.ASTStepLimitError):
            rule.evaluate({'items': tuple(range(100))})

    def test_step_limit_does_not_prefetch_input(self):
        context = rule_engine.Context(max_ast_steps=3)
        rule = rule_engine.Rule('[x for x in items]', context=context)
        items = _CountingSet(range(5))
        with self.assertRaises(rule_engine.ASTStepLimitError):
            rule.evaluate({'items': items})
        # the first element is fetched and processed, but the budget trips before the second one is pulled
        self.assertEqual(items.fetched, 1)

class ContainerItemLimitTests(unittest.TestCase):
    def test_item_limit_array_literal(self):
        context = rule_engine.Context(max_container_items=3)
        self.assertEqual(rule_engine.Rule('[1, 2, 3]', context=context).evaluate(None), (1, 2, 3))
        context = rule_engine.Context(max_container_items=2)
        rule = rule_engine.Rule('[1, 2, 3]', context=context)
        with self.assertRaises(rule_engine.ContainerItemLimitError) as cm:
            rule.evaluate(None)
        self.assertEqual(cm.exception.limit, 2)
        self.assertGreaterEqual(cm.exception.usage, 2)
        self.assertIn('container item', str(cm.exception))

    def test_item_limit_set_literal(self):
        context = rule_engine.Context(max_container_items=2)
        rule = rule_engine.Rule('{1, 2, 3}', context=context)
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule.evaluate(None)

    def test_item_limit_mapping_literal(self):
        context = rule_engine.Context(max_container_items=2)
        rule = rule_engine.Rule("{'a': 1, 'b': 2, 'c': 3}", context=context)
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule.evaluate(None)

    def test_item_limit_nested_containers(self):
        # the outer array holds 2 members and each inner array holds 2, for 6 items total
        rule_text = '[[1, 2], [3, 4]]'
        self.assertEqual(
                rule_engine.Rule(rule_text, context=rule_engine.Context(max_container_items=6)).evaluate(None),
                ((1, 2), (3, 4))
        )
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule_engine.Rule(rule_text, context=rule_engine.Context(max_container_items=5)).evaluate(None)

    def test_item_limit_dynamic_members(self):
        context = rule_engine.Context(max_container_items=2)
        rule = rule_engine.Rule('[a, b]', context=context)
        self.assertEqual(rule.evaluate({'a': 1, 'b': 2}), (1, 2))
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule_engine.Rule('[a, b, c]', context=rule_engine.Context(max_container_items=2)).evaluate(
                    {'a': 1, 'b': 2, 'c': 3}
            )

    def test_item_limit_comprehension(self):
        context = rule_engine.Context(max_container_items=5)
        rule = rule_engine.Rule('[x for x in items]', context=context)
        self.assertEqual(rule.evaluate({'items': tuple(range(5))}), tuple(range(5)))
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule.evaluate({'items': tuple(range(6))})

    def test_item_limit_comprehension_does_not_prefetch_input(self):
        context = rule_engine.Context(max_container_items=3)
        rule = rule_engine.Rule('[x for x in items]', context=context)
        items = _CountingSet(range(5))
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule.evaluate({'items': items})
        # exactly the three emitted elements are fetched; the fourth is never pulled once the limit is reached
        self.assertEqual(items.fetched, 3)

    def test_item_limit_allows_filtered_scans_without_output(self):
        # the condition filters every element out so no container items are created despite the large input
        context = rule_engine.Context(max_container_items=1)
        rule = rule_engine.Rule('[x for x in items if x > 100]', context=context)
        self.assertEqual(rule.evaluate({'items': tuple(range(10))}), ())

    def test_item_limit_function_call_result(self):
        # a dynamic argument keeps the call from being folded at parse time so the result is charged at evaluation
        context = rule_engine.Context(max_container_items=5)
        rule = rule_engine.Rule('$range(n)', context=context)
        self.assertEqual(rule.evaluate({'n': 5}), tuple(range(5)))
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule.evaluate({'n': 6})

    def test_item_limit_slice(self):
        context = rule_engine.Context(max_container_items=3)
        rule = rule_engine.Rule('items[0:3]', context=context)
        self.assertEqual(rule.evaluate({'items': tuple(range(5))}), (0, 1, 2))
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule_engine.Rule('items[0:3]', context=rule_engine.Context(max_container_items=2)).evaluate(
                    {'items': tuple(range(5))}
            )

    def test_item_limit_ignores_string_slice(self):
        context = rule_engine.Context(max_container_items=1)
        rule = rule_engine.Rule('word[0:2]', context=context)
        self.assertEqual(rule.evaluate({'word': 'hello'}), 'he')

    def test_item_limit_set_union(self):
        thing = {'left': {1, 2}, 'right': {2, 3}}
        context = rule_engine.Context(max_container_items=3)
        rule = rule_engine.Rule('left | right', context=context)
        self.assertEqual(rule.evaluate(thing), {1, 2, 3})
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule_engine.Rule('left | right', context=rule_engine.Context(max_container_items=2)).evaluate(thing)

    def test_limits_are_independent(self):
        thing = {'items': tuple(range(100))}
        # only the AST step limit is configured and it is the one that trips
        with self.assertRaises(rule_engine.ASTStepLimitError):
            rule_engine.Rule('[x for x in items]', context=rule_engine.Context(max_ast_steps=5)).evaluate(thing)
        # only the container item limit is configured and it is the one that trips
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule_engine.Rule('[x for x in items]', context=rule_engine.Context(max_container_items=5)).evaluate(thing)

class EvaluationLimitResidueTests(unittest.TestCase):
    def test_next_evaluation_is_unaffected_by_failure(self):
        context = rule_engine.Context(max_container_items=3, max_ast_steps=100)
        rule = rule_engine.Rule('[x for x in items]', context=context)
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule.evaluate({'items': tuple(range(10))})
        # metering is disarmed after the failed evaluation and the next one starts with fresh counters
        self.assertFalse(context._tls.metering)
        self.assertEqual(rule.evaluate({'items': (1, 2, 3)}), (1, 2, 3))
        self.assertEqual(context._tls.container_items, 3)
        self.assertFalse(context._tls.metering)

    def test_unlimited_context_unaffected_by_limited_failure(self):
        limited = rule_engine.Rule('[x for x in items]', context=rule_engine.Context(max_container_items=1))
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            limited.evaluate({'items': tuple(range(10))})
        unlimited = rule_engine.Rule('[x for x in items]')
        self.assertEqual(unlimited.evaluate({'items': tuple(range(10))}), tuple(range(10)))

    def test_rule_pickle_preserves_limits(self):
        context = rule_engine.Context(max_container_items=1)
        rule = pickle.loads(pickle.dumps(rule_engine.Rule('[x for x in items]', context=context)))
        with self.assertRaises(rule_engine.ContainerItemLimitError):
            rule.evaluate({'items': (1, 2)})

    def test_thread_local_counter_isolation(self):
        context = rule_engine.Context(max_container_items=3)
        rule = rule_engine.Rule('[x for x in items]', context=context)
        result_queue: 'queue.Queue[bool]' = queue.Queue()
        def worker():
            try:
                rule.evaluate({'items': tuple(range(100))})
            except rule_engine.ContainerItemLimitError:
                result_queue.put(True)
            else:
                result_queue.put(False)
        thread = threading.Thread(target=worker)
        thread.start()
        # the main thread's small evaluation succeeds while the worker thread trips the same context's limit
        self.assertEqual(rule.evaluate({'items': (1, 2, 3)}), (1, 2, 3))
        thread.join()
        self.assertTrue(result_queue.get_nowait())
        self.assertEqual(context._tls.container_items, 3)

if __name__ == '__main__':
    unittest.main()
