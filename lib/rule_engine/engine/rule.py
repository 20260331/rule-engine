#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  rule_engine/engine/rule.py
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

import collections.abc
import decimal
import re
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping, TYPE_CHECKING

from .. import errors
from ..ast.expression.resolution import verify_symbol_value_type
from ..parser import Parser
from ..types import DataType, _DataTypeDef
from .context import Context

if TYPE_CHECKING:
    import graphviz

_PARAMETER_NAME_REGEX = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*\Z')
#: Grammar words that the lexer rejects as plain symbols but which could otherwise reach the parameter declaration
#: API verbatim (e.g. ``@true`` is lexed as a PARAMETER token).
_RESERVED_PARAMETER_NAMES = frozenset(('elif', 'else', 'while'))

class Rule(object):
    """
    A rule which parses a string with a logical expression and can then evaluate an arbitrary object for whether or not
    it matches based on the constraints of the expression.
    """
    parser: Parser = Parser()
    """
    The :py:class:`~rule_engine.parser.Parser` instance that will be used for parsing the rule text into a compatible
    abstract syntax tree (AST) for evaluation.
    """
    def __init__(self, text: str, context: Context | None = None, *, params: Mapping[str, Any] | None = None) -> None:
        """
        :param str text: The text of the logical expression.
        :param context: The context to use for evaluating the expression on arbitrary objects. This can be used to
                change the default behavior. The default context is :py:class:`.Context` but any object providing the same
                interface (such as a subclass) can be used.
        :type context: :py:class:`.Context`
        :param params: An optional mapping of typed parameter declarations. Each key is the name of a parameter as it
                appears in the rule text with the ``@`` prefix (e.g. ``@limit``) and each value is either a Rule Engine
                data type definition (such as :py:attr:`~rule_engine.types.DataType.FLOAT` or
                ``DataType.SET(DataType.STRING)``) or a Python type / type hint (such as ``int`` or ``set[str]``).
                Parameters are parsed once with the rule and receive concrete values through :py:meth:`.bind`. Their
                names can not collide with reserved words or built-in symbols, and the ``@`` prefix keeps them distinct
                from thing fields and assignment (comprehension) variables.

        .. versionadded:: 5.1.0
                Added the *params* parameter and the :py:meth:`.bind` method for typed, reusable rule parameters.
        """
        context = context or Context()
        self.text = text
        self.context = context
        self.params: Mapping[str, _DataTypeDef] = self._normalize_params(params, context)
        with context.parameter_declarations(self.params):
            self.statement = self.parser.parse(text, context)

    @classmethod
    def _normalize_params(cls, params: Mapping[str, Any] | None, context: Context) -> Mapping[str, _DataTypeDef]:
        if params is None:
            return MappingProxyType({})
        if not isinstance(params, collections.abc.Mapping):
            raise TypeError('params must be a mapping of parameter names to data types, not ' + type(params).__name__)
        reserved = frozenset(cls.parser.reserved_words.keys()) | _RESERVED_PARAMETER_NAMES
        # Builtins.__contains__ raises for missing names, so build the name set through iteration instead
        builtin_names = frozenset(context.builtins)
        normalized: dict[str, _DataTypeDef] = {}
        for name, declaration in params.items():
            if not isinstance(name, str):
                raise TypeError('parameter names must be strings, not ' + type(name).__name__)
            if not _PARAMETER_NAME_REGEX.match(name):
                raise ValueError('invalid parameter name: {0!r}'.format(name))
            if name in reserved:
                raise ValueError('parameter name {0!r} conflicts with a reserved keyword'.format(name))
            if name in builtin_names:
                raise ValueError("parameter name {0!r} conflicts with built-in symbol '${0}'".format(name))
            if DataType.is_definition(declaration):
                data_type = declaration
            elif isinstance(declaration, type) or hasattr(declaration, '__origin__'):
                data_type = DataType.from_type(declaration)
            else:
                raise TypeError(
                        "parameter {0!r} must be declared with a data type definition or Python type, not {1!r}".format(
                                name, declaration
                        )
                )
            normalized[name] = data_type
        return MappingProxyType(normalized)

    def __getstate__(self) -> dict[str, Any]:
        return {'text': self.text, 'context': self.context, 'params': dict(self.params)}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.text = state['text']
        self.context = state['context']
        # normalized declarations are stored as plain data types in the pickle state; bypass _normalize_params because
        # built-in / keyword validation already ran when the rule was created
        self.params = MappingProxyType(dict(state.get('params', {})))
        with self.context.parameter_declarations(self.params):
            self.statement = self.parser.parse(self.text, self.context)

    def __repr__(self) -> str:
        return "<{0} text={1!r} >".format(self.__class__.__name__, self.text)

    def __str__(self) -> str:
        return self.text

    def filter(self, things: Iterable[Any]) -> Iterator[Any]:
        """
        A convenience function for iterating over *things* and yielding each member that :py:meth:`.matches` return True
        for.

        :param things: The collection of objects to iterate over.
        """
        yield from (thing for thing in things if self.matches(thing))

    @classmethod
    def is_valid(
            cls,
            text: str,
            context: Context | None = None,
            *,
            params: Mapping[str, Any] | None = None
    ) -> bool:
        """
        Test whether or not the rule is syntactically correct. This verifies the grammar is well structured and that
        there are no type compatibility issues regarding literals, parameters or symbols with known types (see
        :py:meth:`~.Context.resolve_type` for specifying symbol type information).

        :param str text: The text of the logical expression.
        :param context: The context as would be passed to the :py:meth:`.__init__` method. This can be used for
                specifying symbol type information.
        :param params: The typed parameter declarations as would be passed to the :py:meth:`.__init__` method. Any
                ``@name`` references in *text* must be declared here.
        :return: Whether or not the expression is well formed and appears valid.
        :rtype: bool
        """
        context = context or Context()
        try:
            parameters = cls._normalize_params(params, context)
            with context.parameter_declarations(parameters):
                cls.parser.parse(text, context)
        except errors.EngineError:
            return False
        return True

    def bind(self, values: Mapping[str, Any] | None = None, /, **keyword_values: Any) -> 'RuleBinding':
        """
        Bind concrete *values* to this rule's declared parameters and return a :py:class:`RuleBinding` that reuses the
        already parsed rule without re-parsing it. Every declared parameter must receive exactly one value; providing
        values for undeclared parameters or omitting required ones raises
        :py:exc:`~rule_engine.errors.ParameterBindingError`, while values incompatible with the declared data types
        raise :py:exc:`~rule_engine.errors.SymbolTypeError`.

        Multiple bindings of the same rule are fully independent — values are copied into the binding and kept in
        thread-specific storage only for the duration of an evaluation — so bindings can be created, reused and shared
        across threads without leaking state into one another.

        :param values: A mapping of parameter names to their values. Parameter names which are valid Python
                identifiers can alternatively (or additionally) be supplied as keyword arguments.
        :return: A binding object sharing this rule's parsed statement.
        :rtype: :py:class:`RuleBinding`
        """
        if values is not None and not isinstance(values, collections.abc.Mapping):
            raise TypeError('parameter values must be provided as a mapping, not ' + type(values).__name__)
        merged: dict[str, Any] = dict(values or {})
        merged.update(keyword_values)

        missing = tuple(name for name in self.params if name not in merged)
        unexpected = tuple(name for name in merged if name not in self.params)
        messages: list[str] = []
        if missing:
            messages.append('missing required parameter{0}: {1!r}'.format('s' if len(missing) != 1 else '', missing))
        if unexpected:
            messages.append('unexpected parameter{0}: {1!r}'.format('s' if len(unexpected) != 1 else '', unexpected))
        if messages:
            raise errors.ParameterBindingError('; '.join(messages), missing=missing, unexpected=unexpected)

        for name, value in merged.items():
            verify_symbol_value_type(name, value, self.params[name])
        return RuleBinding(self, merged)

    def evaluate(self, thing: Any) -> Any:
        """
        Evaluate the rule against the specified *thing* and return the value. This can be used to, for example, apply
        the symbol resolver.

        :param thing: The object on which to apply the rule.
        :return: The value the rule evaluates to. Unlike the :py:meth:`.matches` method, this is not necessarily a
                boolean.
        """
        self.context._tls.reset()
        with decimal.localcontext(self.context.decimal_context):
            return self.statement.evaluate(thing)

    def matches(self, thing: Any) -> bool:
        """
        Evaluate the rule against the specified *thing*. This will either return whether *thing* matches, or an
        exception will be raised.

        :param thing: The object on which to apply the rule.
        :return: Whether or not the rule matches.
        :rtype: bool
        """
        return bool(self.evaluate(thing))

    def to_graphviz(self) -> 'graphviz.Digraph':
        """
        Generate a diagram of the parsed rule's AST using GraphViz.

        :return: The rule diagram.
        :rtype: :py:class:`graphviz.Digraph`
        """
        import graphviz
        digraph = graphviz.Digraph(comment=self.text)
        self.statement.to_graphviz(digraph)
        return digraph

class RuleBinding(object):
    """
    A :py:class:`Rule` together with the concrete values bound to its declared parameters. The rule text is parsed
    exactly once (when the :py:class:`Rule` is created) and every binding reuses the same parsed statement. Bindings
    are immutable and isolated from one another: the bound values are copied at creation time and are only installed
    on the context's thread-specific storage for the duration of an evaluation, so evaluating one binding can never
    affect the results of another — even across threads.

    .. versionadded:: 5.1.0
    """
    __slots__ = ('rule', '_values')
    rule: 'Rule'
    _values: dict[str, Any]
    def __init__(self, rule: 'Rule', values: Mapping[str, Any]) -> None:
        self.rule = rule
        self._values = dict(values)

    def __getstate__(self) -> dict[str, Any]:
        return {'rule': self.rule, '_values': self._values}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.rule = state['rule']
        self._values = state['_values']

    def __repr__(self) -> str:
        return "<{0} text={1!r} parameters={2!r} >".format(self.__class__.__name__, self.rule.text, tuple(self._values))

    @property
    def context(self) -> Context:
        """The :py:class:`.Context` of the bound rule."""
        return self.rule.context

    @property
    def text(self) -> str:
        """The rule text of the bound rule."""
        return self.rule.text

    @property
    def params(self) -> Mapping[str, _DataTypeDef]:
        """The typed parameter declarations of the bound rule."""
        return self.rule.params

    @property
    def values(self) -> Mapping[str, Any]:
        """The concrete parameter values provided to this binding (a read-only view)."""
        return MappingProxyType(self._values)

    def evaluate(self, thing: Any) -> Any:
        """
        Evaluate the bound rule against the specified *thing* and return the value. Parameter references (``@name``)
        are resolved from this binding's values rather than from *thing*.

        :param thing: The object on which to apply the rule.
        :return: The value the rule evaluates to. Unlike the :py:meth:`.matches` method, this is not necessarily a
                boolean.
        """
        self.rule.context._tls.reset()
        with decimal.localcontext(self.rule.context.decimal_context):
            with self.rule.context.parameter_values(self._values):
                return self.rule.statement.evaluate(thing)

    def matches(self, thing: Any) -> bool:
        """
        Evaluate the bound rule against the specified *thing*.

        :param thing: The object on which to apply the rule.
        :return: Whether or not the rule matches.
        :rtype: bool
        """
        return bool(self.evaluate(thing))

    def filter(self, things: Iterable[Any]) -> Iterator[Any]:
        """
        A convenience function for iterating over *things* and yielding each member that :py:meth:`.matches` return
        True for.

        :param things: The collection of objects to iterate over.
        """
        yield from (thing for thing in things if self.matches(thing))

class DebugRule(Rule):
    parser: Parser  # set per-instance in __init__ (overrides the class-level attribute on Rule)
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.parser = Parser(debug=True)
        super(DebugRule, self).__init__(*args, **kwargs)
