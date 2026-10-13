#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  rule_engine/parser/utilities.py
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

import ast as pyast
import binascii
import datetime
import decimal
import re

from . import errors

from ..types.quantity import Quantity, get_unit

import dateutil.parser

_sub_regex = r'[0-9]+([,.][0-9]+)?'
timedelta_regex = (
        r'P(?!\b)'
        r'(?P<weeks>' + _sub_regex + r'W)?'
        r'(?P<days>' + _sub_regex + r'D)?'
        r'(T'
        r'(?P<hours>' + _sub_regex + r'H)?'
        r'(?P<minutes>' + _sub_regex + r'M)?'
        r'(?P<seconds>' + _sub_regex + r'S)?'
        r')?'
)

# unit symbols are ordered longest first so alternation prefers e.g. "ms" over "m" and "KiB" over "B"
quantity_unit_regex = r'KiB|ms|s|B'
_quantity_value_regex = r'(?:[0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?|\.[0-9]+(?:[eE][+-]?[0-9]+)?)'
# the trailing negative look-ahead keeps the unit from matching a prefix of a longer identifier (e.g. "s" in "seconds")
quantity_regex = _quantity_value_regex + r'(?:' + quantity_unit_regex + r')(?![0-9A-Za-z_])'

def parse_datetime(string: str, default_timezone: datetime.tzinfo) -> datetime.datetime:
    """
    Parse a timestamp string. If the timestamp does not specify a timezone, *default_timezone* is used.

    :param str string: The string to parse.
    :param datetime.tzinfo default_timezone: The default timezone to set.
    :rtype: datetime.datetime
    """
    try:
        dt = dateutil.parser.isoparse(string)
    except ValueError:
        raise errors.DatetimeSyntaxError('invalid datetime literal', string) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_timezone)
    return dt

def parse_float(string: str) -> decimal.Decimal:
    """
    Parse a literal string representing a floating point value.

    :param str string: The string to parse.
    :rtype: decimal.Decimal
    """
    if re.match('^0[0-9]', string):
        raise errors.FloatSyntaxError('invalid floating point literal (leading zeros in decimal literals are not permitted)', string)
    try:
        if re.match('^0[box]', string):
            val = decimal.Decimal(pyast.literal_eval(string))
        else:
            val = decimal.Decimal(string)
    except Exception:
        raise errors.FloatSyntaxError('invalid floating point literal', string) from None
    return val

def parse_quantity(string: str) -> Quantity:
    """
    Parse a literal string representing a dimensioned quantity (a decimal number immediately followed by a unit
    symbol, e.g. ``30s``, ``500ms``, ``1024B`` or ``1KiB``).

    :param str string: The string to parse.
    :rtype: Quantity

    .. versionadded:: 5.1.0
    """
    match = re.match(r'^(?P<value>' + _quantity_value_regex + r')(?P<unit>' + quantity_unit_regex + r')$', string)
    if not match:
        raise errors.QuantitySyntaxError('invalid quantity literal', string)
    try:
        value = parse_float(match.group('value'))
    except errors.FloatSyntaxError:
        raise errors.QuantitySyntaxError('invalid quantity literal', string) from None
    try:
        unit = get_unit(match.group('unit'))
    except ValueError:
        raise errors.QuantitySyntaxError('invalid quantity literal (unknown unit)', string) from None
    return Quantity(value, unit)

def parse_timedelta(string: str) -> datetime.timedelta:
    """
    Parse a literal string representing a time period in the ISO-8601 duration format.

    :param str string: The string to parse.
    :rtype: datetime.timedelta
    """
    if string == "P":
        raise errors.TimedeltaSyntaxError('empty timedelta string', string)

    match = re.match("^" + timedelta_regex + "$", string)
    if not match:
        raise errors.TimedeltaSyntaxError('invalid timedelta string', string)

    groups: dict[str, float] = {
            key: float((val if val is not None else "0n")[:-1].replace(',', '.'))
            for key, val in match.groupdict().items()
    }

    return datetime.timedelta(
            weeks=groups['weeks'],
            days=groups['days'],
            hours=groups['hours'],
            minutes=groups['minutes'],
            seconds=groups['seconds'],
    )
