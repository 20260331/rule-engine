#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  rule_engine/engine/_access_policy.py
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

import abc
import dataclasses
from typing import Any, Iterable

__all__ = (
		'ANY',
		'AccessPath',
		'AccessPolicy',
		'AttributeAccess',
		'CallAccess',
		'ItemAccess',
		'SliceAccess',
		'SymbolAccess',
		'WhitelistAccessPolicy',
)

@dataclasses.dataclass(frozen=True)
class AccessStep(object):
	"""
	The base class for the individual steps that compose an :py:class:`AccessPath`. Each step corresponds to a single
	read or call performed while a rule is being evaluated.

	.. versionadded:: 5.1.0
	"""
	def render(self) -> str:
		"""Render this step as it would appear in the text of a rule."""
		raise NotImplementedError()

@dataclasses.dataclass(frozen=True)
class SymbolAccess(AccessStep):
	"""A root symbol read, e.g. ``user`` in ``user.name``. Symbols resolved from a non-default scope (such as the
	built-in scope, ``$name``) carry the scope name."""
	name: str
	scope: str | None = None
	def render(self) -> str:
		if self.scope is None:
			return self.name
		return '$' + self.name

@dataclasses.dataclass(frozen=True)
class AttributeAccess(AccessStep):
	"""An attribute (dot syntax) read, e.g. ``.name`` in ``user.name``."""
	name: str
	def render(self) -> str:
		return '.' + self.name

@dataclasses.dataclass(frozen=True)
class ItemAccess(AccessStep):
	"""An index or key read, e.g. ``[0]`` in ``users[0]`` or ``['city']`` in ``address['city']``. The *key* is the
	runtime value used for the lookup and may be an integer index or a scalar mapping key."""
	key: Any
	def render(self) -> str:
		if type(self.key) is int:
			return '[{0}]'.format(self.key)
		return '[{0!r}]'.format(self.key)

@dataclasses.dataclass(frozen=True)
class SliceAccess(AccessStep):
	"""A slice read, e.g. ``[0:2]``. Open bounds are represented with :py:data:`None` so ``arr[:2]`` uses
	``SliceAccess(None, 2)``."""
	start: Any = None
	stop: Any = None
	def render(self) -> str:
		start = '' if self.start is None else str(self.start)
		stop = '' if self.stop is None else str(self.stop)
		return '[{0}:{1}]'.format(start, stop)

@dataclasses.dataclass(frozen=True)
class CallAccess(AccessStep):
	"""A function or method invocation. The callable itself was read as the preceding step; this step records that it
	was called, e.g. the ``()`` in ``name.as_upper()``."""
	def render(self) -> str:
		return '()'

class AccessPath(object):
	"""
	The sequence of :py:class:`AccessStep` instances that lead from a root symbol (or a value that is not anchored to
	the evaluated object) to a value that a rule reads or a function that it calls.

	A path is *rooted* when its first step is a :py:class:`SymbolAccess`; such a path identifies a value within the
	object the rule is being evaluated against. Paths that begin after a value was computed (for example the result of
	arithmetic or an array comprehension) are *unrooted* and still report attribute and function accesses, but their
	steps do not name an object-relative location.

	Instances are immutable; each read produces a new path that extends the previous one.

	.. versionadded:: 5.1.0
	"""
	__slots__ = ('_steps',)
	def __init__(self, steps: tuple[AccessStep, ...] = ()) -> None:
		self._steps = tuple(steps)

	def __eq__(self, other: Any) -> bool:
		if not isinstance(other, AccessPath):
			return NotImplemented
		return self._steps == other._steps

	def __hash__(self) -> int:
		return hash(self._steps)

	def __iter__(self):
		return iter(self._steps)

	def __len__(self) -> int:
		return len(self._steps)

	def __repr__(self) -> str:
		return '<{0} {1!s} >'.format(self.__class__.__name__, self)

	def __str__(self) -> str:
		prefix = '' if self.rooted else '<expr>'
		return prefix + ''.join(step.render() for step in self._steps)

	@property
	def steps(self) -> tuple[AccessStep, ...]:
		"""The tuple of steps that compose the path, in evaluation order."""
		return self._steps

	@property
	def rooted(self) -> bool:
		"""Whether or not the path begins with a root symbol read."""
		return bool(self._steps) and isinstance(self._steps[0], SymbolAccess)

	@classmethod
	def root(cls, name: str, scope: str | None = None) -> 'AccessPath':
		"""Create a new rooted path consisting of a single symbol read."""
		return cls((SymbolAccess(name, scope),))

	@classmethod
	def extend(cls, path: 'AccessPath | None', step: AccessStep) -> 'AccessPath':
		"""Return *path* extended with *step*. If *path* is :py:data:`None`, the resulting path is unrooted and begins
		with *step*."""
		if path is None:
			return cls((step,))
		return cls(path._steps + (step,))

class _AnyStep(object):
	__slots__ = ()
	def __repr__(self) -> str:
		return 'ANY'

ANY = _AnyStep()
"""
A wildcard selector that matches any single :py:class:`AccessStep`. It is used with :py:class:`WhitelistAccessPolicy`
where a rule needs to match regardless of an item's key or index.

.. versionadded:: 5.1.0
"""

class AccessPolicy(abc.ABC):
	"""
	An abstract policy that decides whether a rule is allowed to read a value or call a function at a given
	:py:class:`AccessPath`. A policy is attached to a :py:class:`~rule_engine.engine.Context` via its
	*access_policy* parameter and is consulted immediately before every read or call that occurs while a rule is being
	evaluated (parse-time reductions of constant expressions never touch the evaluated object and are not consulted).

	Subclasses implement :py:meth:`allows` and return :py:data:`False` to deny an access. A denied access raises
	:py:exc:`~rule_engine.errors.AccessDeniedError` before the underlying value is read or function is called, so a
	denial can not be bypassed through default values, safe navigation or error handling within the rule.

	Paths are reported in the order the original expression evaluates: short-circuited branches are not visited,
	comprehension variables carry the path of the element they alias and only the branch taken by a ternary expression
	is reported.

	.. versionadded:: 5.1.0
	"""
	@abc.abstractmethod
	def allows(self, path: AccessPath) -> bool:
		"""
		Return :py:data:`True` to permit the read or call identified by *path* and :py:data:`False` to deny it.

		:param path: The access path that is about to be read or called.
		"""
		raise NotImplementedError()

def _rule_matches(rule: tuple[Any, ...], steps: tuple[AccessStep, ...]) -> bool:
	# the rule and the path match when they agree on the shared prefix (this allows both a rule and its descendants -
	# the descendants are covered by the rule - and the rule's ancestor paths, which must be traversed to reach the
	# permitted location)
	shared = min(len(rule), len(steps))
	for selector, step in zip(rule[:shared], steps[:shared]):
		if selector is ANY:
			continue
		if isinstance(selector, AccessStep):
			if selector != step:
				return False
		elif isinstance(selector, str):
			if not isinstance(step, (SymbolAccess, AttributeAccess)) or step.name != selector:
				return False
		elif type(selector) is int:
			if not isinstance(step, ItemAccess) or type(step.key) is not int or step.key != selector:
				return False
		else:
			raise TypeError('unsupported access rule selector: {!r}'.format(selector))
	return True

class WhitelistAccessPolicy(AccessPolicy):
	"""
	An :py:class:`AccessPolicy` that allows only the paths named by *allowed*. Each rule is a tuple of selectors that
	is matched as a prefix against the steps of an access path, so a rule covers both the named location and everything
	nested beneath it.

	Each selector is one of:

	* a :py:class:`str`, matching a :py:class:`SymbolAccess` or :py:class:`AttributeAccess` of that name;
	* an :py:class:`int`, matching an :py:class:`ItemAccess` with that integer index;
	* :py:data:`ANY`, matching any single step;
	* an explicit :py:class:`AccessStep` instance, matched by equality.

	For example ``WhitelistAccessPolicy([('user',), ('users', ANY, 'email')])`` allows every read below ``user`` and
	the ``email`` attribute of any element of ``users`` (such as ``users[0].email``) while denying ``users[0].ssn``.

	A path is allowed when it equals a rule or is nested beneath one, and the shorter *ancestor* paths that must be
	traversed to reach a permitted location (such as ``users`` or ``users[0]`` while reaching ``users[0].email``) are
	allowed as well. An :py:data:`ANY` selector grants its step regardless of kind, including traversal steps; use a
	concrete selector (such as an integer index) when attribute steps at the same depth must stay denied.

	Unrooted paths (accesses on a computed value, where every input was already permitted when it was read) are allowed
	by default; pass ``allow_unrooted=False`` to deny them.

	.. versionadded:: 5.1.0
	"""
	def __init__(self, allowed: Iterable[tuple[Any, ...]], *, allow_unrooted: bool = True) -> None:
		"""
		:param allowed: The prefix rules that name the access paths which are allowed.
		:param bool allow_unrooted: Whether or not to allow accesses on values that are not anchored to the evaluated
				object (such as attributes of an arithmetic result).
		"""
		self.allowed_rules: tuple[tuple[Any, ...], ...] = tuple(tuple(rule) for rule in allowed)
		self.allow_unrooted = allow_unrooted

	def allows(self, path: AccessPath) -> bool:
		if not path.rooted:
			return self.allow_unrooted
		return any(_rule_matches(rule, path.steps) for rule in self.allowed_rules)
