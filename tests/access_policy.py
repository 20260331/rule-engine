#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  tests/access_policy.py
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

import dataclasses
import pickle
import threading
import unittest

import rule_engine.builtins as builtins
import rule_engine.engine as engine
import rule_engine.errors as errors
import rule_engine.types as types
from rule_engine.engine import (
		ANY,
		AccessPath,
		AccessPolicy,
		AttributeAccess,
		CallAccess,
		ItemAccess,
		SliceAccess,
		SymbolAccess,
		WhitelistAccessPolicy,
)

class _RecordingPolicy(AccessPolicy):
	"""A policy that records every path it is asked about, granting or denying access per its *grant* value."""
	def __init__(self, grant: bool = True) -> None:
		self.grant = grant
		self.paths: list[AccessPath] = []
	def allows(self, path: AccessPath) -> bool:
		self.paths.append(path)
		return bool(self.grant(path) if callable(self.grant) else self.grant)
	def strings(self) -> list[str]:
		return [str(path) for path in self.paths]

class _TrackingDict(dict):
	"""A mapping that records every key that is read through it."""
	def __init__(self, *args, **kwargs) -> None:
		super().__init__(*args, **kwargs)
		self.read_keys: list[str] = []
	def __getitem__(self, key):
		self.read_keys.append(key)
		return super().__getitem__(key)

class AccessPathTests(unittest.TestCase):
	def test_root_symbol(self):
		path = AccessPath.root('user')
		self.assertTrue(path.rooted)
		self.assertEqual(path.steps, (SymbolAccess('user'),))
		self.assertEqual(str(path), 'user')

	def test_builtin_symbol(self):
		path = AccessPath.root('all', scope=builtins.Builtins.scope_name)
		self.assertTrue(path.rooted)
		self.assertEqual(str(path), '$all')
		self.assertEqual(path.steps, (SymbolAccess('all', scope='built-in'),))

	def test_extend_attribute_item_slice_call(self):
		path = AccessPath.root('users')
		path = AccessPath.extend(path, ItemAccess(0))
		path = AccessPath.extend(path, AttributeAccess('name'))
		self.assertEqual(str(path), 'users[0].name')
		path = AccessPath.extend(AccessPath.root('m'), ItemAccess('city'))
		self.assertEqual(str(path), "m['city']")
		path = AccessPath.extend(AccessPath.root('nums'), SliceAccess(1, 3))
		self.assertEqual(str(path), 'nums[1:3]')
		self.assertEqual(str(AccessPath.extend(AccessPath.root('nums'), SliceAccess(None, 2))), 'nums[:2]')
		self.assertEqual(str(AccessPath.extend(AccessPath.root('nums'), SliceAccess(1, None))), 'nums[1:]')
		self.assertEqual(str(AccessPath.extend(AccessPath.root('nums'), SliceAccess(None, None))), 'nums[:]')
		path = AccessPath.extend(AccessPath.extend(AccessPath.root('s'), AttributeAccess('encode')), CallAccess())
		self.assertEqual(str(path), 's.encode()')

	def test_unrooted_path(self):
		path = AccessPath.extend(None, AttributeAccess('to_flt'))
		self.assertFalse(path.rooted)
		self.assertEqual(str(path), '<expr>.to_flt')
		path = AccessPath.extend(AccessPath.extend(None, ItemAccess(0)), CallAccess())
		self.assertFalse(path.rooted)
		self.assertEqual(str(path), '<expr>[0]()')

	def test_equality_and_hash(self):
		self.assertEqual(AccessPath.root('a'), AccessPath.root('a'))
		self.assertEqual(hash(AccessPath.root('a')), hash(AccessPath.root('a')))
		self.assertNotEqual(AccessPath.root('a'), AccessPath.root('b'))
		self.assertNotEqual(AccessPath.root('a'), ('a',))

class WhitelistAccessPolicyTests(unittest.TestCase):
	def test_exact_descendant_and_ancestor(self):
		policy = WhitelistAccessPolicy([('user', 'name')])
		self.assertTrue(policy.allows(AccessPath.root('user')))  # ancestor traversal
		self.assertTrue(policy.allows(AccessPath.extend(AccessPath.root('user'), AttributeAccess('name'))))
		self.assertFalse(policy.allows(AccessPath.extend(AccessPath.root('user'), AttributeAccess('ssn'))))

	def test_wildcard_and_index(self):
		thing = {'users': [{'name': 'Bob', 'ssn': '1'}]}
		policy = WhitelistAccessPolicy([('users', ANY, 'name')])
		self.assertTrue(policy.allows(AccessPath.root('users')))
		path = AccessPath.extend(AccessPath.extend(AccessPath.root('users'), ItemAccess(0)), AttributeAccess('name'))
		self.assertTrue(policy.allows(path))
		denied = AccessPath.extend(AccessPath.extend(AccessPath.root('users'), ItemAccess(0)), AttributeAccess('ssn'))
		self.assertFalse(policy.allows(denied))

		# a concrete integer selector does not grant attribute steps at the same depth
		index_policy = WhitelistAccessPolicy([('users', 0, 'name')])
		self.assertTrue(index_policy.allows(AccessPath.extend(AccessPath.root('users'), ItemAccess(0))))
		self.assertFalse(index_policy.allows(AccessPath.extend(AccessPath.root('users'), AttributeAccess('length'))))

	def test_builtin_scope_is_distinct(self):
		builtin_all = AccessPath.root('all', scope=builtins.Builtins.scope_name)
		thing_all = AccessPath.root('all')
		policy = WhitelistAccessPolicy([(SymbolAccess('all', scope='built-in'),)])
		self.assertTrue(policy.allows(builtin_all))
		self.assertFalse(policy.allows(thing_all))

	def test_unrooted(self):
		unrooted = AccessPath.extend(None, AttributeAccess('to_flt'))
		self.assertTrue(WhitelistAccessPolicy([]).allows(unrooted))
		self.assertFalse(WhitelistAccessPolicy([], allow_unrooted=False).allows(unrooted))

	def test_invalid_selector(self):
		policy = WhitelistAccessPolicy([('a', 1.5)])
		with self.assertRaises(TypeError):
			policy.allows(AccessPath.extend(AccessPath.root('a'), ItemAccess(1.5)))

@dataclasses.dataclass
class _PolicyPerson:
	name: str
	employer: '_PolicyCompany'

@dataclasses.dataclass
class _PolicyCompany:
	name: str
	ceo: '_PolicyPerson'

class AccessPolicyEvaluationTests(unittest.TestCase):
	def setUp(self):
		self.thing = {
				'user': {'name': 'Alice', 'ssn': '111-11-1111'},
				'users': [
						{'name': 'Bob', 'ssn': '222-22-2222', 'tags': ('x', 'y')},
						{'name': 'Cara', 'ssn': '333-33-3333', 'tags': ('z',)},
				],
				'nums': [1, 2, 3],
				'm': {'city': 'Berlin'},
				'prefix': 'city',
				'words': 'Alice',
		}

	def evaluate(self, text, *, policy=None, context=None, thing=None, grant=True, type_resolver=None):
		policy = policy or _RecordingPolicy(grant=grant)
		context = context or engine.Context(access_policy=policy, type_resolver=type_resolver)
		rule = engine.Rule(text, context=context)
		# no policy decisions are made while parsing (only constant expressions could reduce and they never touch thing)
		self.assertEqual(policy.paths, [])
		result = rule.evaluate(self.thing if thing is None else thing)
		return result, policy, context

	def test_symbol_and_attribute_paths(self):
		result, policy, _ = self.evaluate('user.name == "Alice"')
		self.assertTrue(result)
		self.assertEqual(policy.strings(), ['user', 'user.name'])

	def test_deep_nested_path(self):
		alice = _PolicyPerson(name='Alice', employer=None)
		acme = _PolicyCompany(name='ACME', ceo=alice)
		alice.employer = acme
		context = engine.Context(
				resolver=engine.resolve_attribute,
				type_resolver=engine.type_resolver_from_dataclass(_PolicyPerson),
				access_policy=_RecordingPolicy()
		)
		rule = engine.Rule('employer.ceo.name == "Alice"', context=context)
		self.assertTrue(rule.matches(alice))
		policy = context.access_policy
		self.assertEqual(policy.strings(), ['employer', 'employer.ceo', 'employer.ceo.name'])

	def test_index_and_key_paths(self):
		_, policy, _ = self.evaluate('users[1].name == "Cara"')
		self.assertEqual(policy.strings(), ['users', 'users[1]', 'users[1].name'])
		_, policy, _ = self.evaluate("m['city'] == 'Berlin'")
		self.assertEqual(policy.strings(), ['m', "m['city']"])

	def test_dynamic_key_path_and_order(self):
		_, policy, _ = self.evaluate('m[prefix] == "Berlin"')
		# container is read first, the key expression is evaluated second and the keyed lookup is guarded third
		self.assertEqual(policy.strings(), ['m', 'prefix', "m['city']"])

	def test_slice_paths(self):
		# an omitted slice start is normalized to zero at parse time, while an omitted stop stays open
		cases = (
				('nums[0:2]', 'nums[0:2]'),
				('nums[:2]', 'nums[0:2]'),
				('nums[1:]', 'nums[1:]'),
				('nums[0:2][1]', 'nums[0:2][1]'),
		)
		for text, rendered in cases:
			_, policy, _ = self.evaluate(text)
			self.assertEqual(policy.strings()[-1], rendered, text)

	def test_method_call_path(self):
		type_resolver = engine.type_resolver_from_dict({'words': types.DataType.STRING, 'prefix': types.DataType.STRING})
		# a zero-argument call: the attribute read and the call are two distinct decisions
		result, policy, _ = self.evaluate('words.encode("utf-8")', type_resolver=type_resolver)
		self.assertEqual(result, b'Alice')
		self.assertEqual(policy.strings(), ['words', 'words.encode', 'words.encode()'])
		# arguments are evaluated in their original order, between reading the function and invoking it
		_, policy, _ = self.evaluate('words.starts_with(prefix)', type_resolver=type_resolver)
		self.assertEqual(policy.strings(), ['words', 'words.starts_with', 'prefix', 'words.starts_with()'])

	def test_builtin_call_path(self):
		# $all with a constant body is not reducible (the function is a symbol), so the built-in read and call are
		# reported at evaluation time
		_, policy, _ = self.evaluate('$all([true])')
		self.assertEqual(policy.strings(), ['$all', '$all()'])

	def test_denied_call_is_not_invoked(self):
		invoked = []
		def resolver(thing, name):
			if name == 'fn':
				return lambda value: invoked.append(value) or value
			return thing[name]
		policy = _RecordingPolicy(grant=lambda path: not isinstance(path.steps[-1], CallAccess))
		context = engine.Context(access_policy=policy, resolver=resolver)
		rule = engine.Rule('fn(true)', context=context)
		with self.assertRaises(errors.AccessDeniedError) as exc:
			rule.evaluate(self.thing)
		self.assertEqual(str(exc.exception.path), 'fn()')
		self.assertEqual(invoked, [])

	def test_short_circuit_and(self):
		# the right hand side must not be evaluated (and therefore not be checked) when the left side is false
		_, policy, _ = self.evaluate('user.name == "nobody" and user.ssn == "x"')
		self.assertEqual(policy.strings(), ['user', 'user.name'])

	def test_short_circuit_or(self):
		_, policy, _ = self.evaluate('user.name == "Alice" or user.ssn == "x"')
		self.assertEqual(policy.strings(), ['user', 'user.name'])

	def test_ternary_only_taken_branch(self):
		_, policy, _ = self.evaluate('user.name == "Alice" ? user.name : user.ssn')
		self.assertEqual(policy.strings(), ['user', 'user.name', 'user', 'user.name'])
		_, policy, _ = self.evaluate('user.name == "nobody" ? user.ssn : user.name')
		self.assertEqual(policy.strings(), ['user', 'user.name', 'user', 'user.name'])

	def test_safe_navigation_null_skips_following_read(self):
		policy = _RecordingPolicy()
		context = engine.Context(access_policy=policy, default_value=None)
		self.assertIsNone(engine.Rule('missing&.ssn', context=context).evaluate(self.thing))
		# the root symbol is read (and resolves to null) but the attribute is never accessed nor decided on
		self.assertEqual(policy.strings(), ['missing'])

	def test_safe_item_out_of_bounds_is_guarded(self):
		policy = _RecordingPolicy()
		context = engine.Context(access_policy=policy)
		self.assertIsNone(engine.Rule('nums&[9]', context=context).evaluate(self.thing))
		# the guarded index lookup happens before the failed read returns null safely
		self.assertEqual(policy.strings(), ['nums', 'nums[9]'])

	def test_denied_root_symbol_is_not_resolved(self):
		resolved = []
		def resolver(thing, name):
			resolved.append(name)
			return thing[name]
		policy = _RecordingPolicy(grant=lambda path: path.steps[0].name != 'secret')
		context = engine.Context(access_policy=policy, resolver=resolver)
		thing = dict(self.thing, secret='value')
		with self.assertRaises(errors.AccessDeniedError):
			engine.Rule('secret', context=context).evaluate(thing)
		self.assertNotIn('secret', resolved)

	def test_denied_attribute_is_not_read(self):
		tracking = _TrackingDict(self.thing['user'])
		thing = {'user': tracking}
		policy = WhitelistAccessPolicy([('user', 'name')])
		context = engine.Context(access_policy=policy)
		with self.assertRaises(errors.AccessDeniedError):
			engine.Rule('user.ssn', context=context).evaluate(thing)
		self.assertNotIn('ssn', tracking.read_keys)

	def test_denial_is_not_bypassed_by_default_value_or_safe_navigation(self):
		policy = WhitelistAccessPolicy([('user', 'name')])
		context = engine.Context(access_policy=policy, default_value=None)
		with self.assertRaises(errors.AccessDeniedError):
			engine.Rule('user.ssn', context=context).evaluate(self.thing)
		with self.assertRaises(errors.AccessDeniedError):
			engine.Rule('user&.ssn', context=context).evaluate(self.thing)

	def test_parse_time_reduction_does_not_consult_policy(self):
		policy = _RecordingPolicy(grant=False)
		context = engine.Context(access_policy=policy)
		# these expressions fully reduce at parse time and never touch thing
		self.assertEqual(engine.Rule('1 + 2', context=context).evaluate(self.thing), 3)
		self.assertEqual(engine.Rule('"hi".as_upper', context=context).evaluate(self.thing), 'HI')
		self.assertEqual(engine.Rule('"hi".encode("utf-8")', context=context).evaluate(self.thing), b'hi')
		self.assertEqual(policy.paths, [])

	def test_comprehension_alias_paths(self):
		result, policy, _ = self.evaluate('[u.name for u in users]')
		self.assertEqual(result, ('Bob', 'Cara'))
		self.assertEqual(policy.strings(), [
				'users',
				'users[0]', 'users[0].name',
				'users[1]', 'users[1].name',
		])

	def test_comprehension_condition_keeps_alias_path(self):
		result, policy, _ = self.evaluate('[u for u in nums if u > 1]')
		self.assertEqual(result, (2, 3))
		self.assertEqual(policy.strings(), ['nums', 'nums[0]', 'nums[1]', 'nums[2]'])

	def test_comprehension_alias_attributes(self):
		# nested comprehensions are expressed as nested array expressions
		result, policy, _ = self.evaluate('[[t for t in u.tags] for u in users]')
		self.assertEqual(result, (('x', 'y'), ('z',)))
		self.assertEqual(policy.strings(), [
				'users',
				'users[0]', 'users[0].tags', 'users[0].tags[0]', 'users[0].tags[1]',
				'users[1]', 'users[1].tags', 'users[1].tags[0]',
		])

	def test_comprehension_result_keeps_iterable_provenance(self):
		result, policy, _ = self.evaluate('[u.name for u in users][0]')
		self.assertEqual(result, 'Bob')
		self.assertEqual(policy.strings()[-1], 'users[0]')

	def test_comprehension_denies_element_field(self):
		policy = WhitelistAccessPolicy([
				('users', ANY, 'name'), ('nums',),
				(SymbolAccess('all', scope=builtins.Builtins.scope_name),),
		])
		context = engine.Context(access_policy=policy)
		with self.assertRaises(errors.AccessDeniedError) as exc:
			engine.Rule('$all([u.ssn == "x" for u in users])', context=context).evaluate(self.thing)
		self.assertEqual(str(exc.exception.path), 'users[0].ssn')

	def test_unrooted_computed_value_path(self):
		result, policy, _ = self.evaluate('(nums.length + 1).to_flt == 4')
		self.assertTrue(result)
		last = policy.paths[-1]
		self.assertFalse(last.rooted)
		self.assertEqual(str(last), '<expr>.to_flt')

	def test_literal_collection_is_unrooted(self):
		_, policy, _ = self.evaluate('[user.name][0] == "Alice"')
		last = policy.paths[-1]
		self.assertFalse(last.rooted)
		self.assertEqual(str(last), '<expr>[0]')

	def test_error_carries_path(self):
		policy = WhitelistAccessPolicy([])
		context = engine.Context(access_policy=policy)
		with self.assertRaises(errors.AccessDeniedError) as exc:
			engine.Rule('user.ssn', context=context).evaluate(self.thing)
		self.assertIsInstance(exc.exception.path, AccessPath)
		self.assertEqual(str(exc.exception.path), 'user')

class AccessPolicyContextTests(unittest.TestCase):
	def test_invalid_policy_type(self):
		with self.assertRaisesRegex(TypeError, r'^access_policy must be an AccessPolicy instance'):
			engine.Context(access_policy=object())

	def test_policy_is_optional(self):
		context = engine.Context()
		self.assertIsNone(context.access_policy)
		self.assertTrue(engine.Rule('foo == "bar"').matches({'foo': 'bar'}))

	def test_pickled_context_keeps_policy(self):
		policy = WhitelistAccessPolicy([('user', 'name')])
		context = engine.Context(access_policy=policy)
		thing = {'user': {'name': 'Alice', 'ssn': 'x'}}
		self.assertTrue(engine.Rule('user.name == "Alice"', context=context).matches(thing))
		restored = pickle.loads(pickle.dumps(context))
		self.assertIsInstance(restored.access_policy, WhitelistAccessPolicy)
		self.assertTrue(engine.Rule('user.name == "Alice"', context=restored).matches(thing))
		with self.assertRaises(errors.AccessDeniedError):
			engine.Rule('user.ssn', context=restored).evaluate(thing)

	def test_thread_isolation(self):
		# a single context shared across threads must keep allowing and denying correctly in every thread
		policy = WhitelistAccessPolicy([('nums',)])
		context = engine.Context(access_policy=policy)
		thing = {'nums': [1, 2, 3], 'secret': 'x'}
		errors_seen: list[BaseException] = []
		def allowed_worker():
			try:
				for _ in range(100):
					assert engine.Rule('nums[0] == 1', context=context).matches(thing)
			except BaseException as error:
				errors_seen.append(error)
		def denied_worker():
			try:
				for _ in range(100):
					try:
						engine.Rule('secret', context=context).evaluate(thing)
					except errors.AccessDeniedError:
						continue
					errors_seen.append(AssertionError('denial was lost'))
			except BaseException as error:
				errors_seen.append(error)
		threads = [threading.Thread(target=allowed_worker if i % 2 == 0 else denied_worker) for i in range(8)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()
		self.assertEqual(errors_seen, [])
