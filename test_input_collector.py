#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated tests for input_collector._collect_multiline_input.

Imports only input_collector. Does not touch brain.py, memory, chat_system,
tool_registry, verifier, or any project module.
"""

import unittest
import input_collector


def _reader_from(seq):
    it = iter(seq)
    def reader():
        x = next(it)
        if isinstance(x, BaseException):
            raise x
        return x
    return reader


class TestCollectorCtrlC(unittest.TestCase):
    def test_ctrl_c_after_two_lines_cancels(self):
        reader = _reader_from(["a", "b", KeyboardInterrupt()])
        text, cancelled, was_empty = input_collector._collect_multiline_input(reader=reader)
        self.assertEqual(text, "a\nb")
        self.assertTrue(cancelled)
        self.assertFalse(was_empty)


class TestCollectorBasics(unittest.TestCase):
    def test_normal_collection(self):
        reader = _reader_from(["a", "b", "конец"])
        text, cancelled, was_empty = input_collector._collect_multiline_input(reader=reader)
        self.assertEqual(text, "a\nb")
        self.assertFalse(cancelled)
        self.assertFalse(was_empty)

    def test_terminator_case_insensitive(self):
        reader = _reader_from(["  КОНЕЦ  "])
        text, cancelled, was_empty = input_collector._collect_multiline_input(reader=reader)
        self.assertEqual(text, "")
        self.assertFalse(cancelled)
        self.assertTrue(was_empty)

    def test_terminator_strip_variants(self):
        reader = _reader_from(["a", " конец "])
        text, cancelled, was_empty = input_collector._collect_multiline_input(reader=reader)
        self.assertEqual(text, "a")
        self.assertFalse(cancelled)
        self.assertFalse(was_empty)

    def test_embedded_terminator_not_stopper(self):
        reader = _reader_from(["это конец", "a", "конец"])
        text, cancelled, was_empty = input_collector._collect_multiline_input(reader=reader)
        self.assertEqual(text, "это конец\na")
        self.assertFalse(cancelled)
        self.assertFalse(was_empty)

    def test_empty_lines_preserved(self):
        reader = _reader_from(["a", "", "b", "конец"])
        text, cancelled, was_empty = input_collector._collect_multiline_input(reader=reader)
        self.assertEqual(text, "a\n\nb")
        self.assertFalse(cancelled)
        self.assertFalse(was_empty)

    def test_eof_cancels(self):
        reader = _reader_from(["a", EOFError()])
        text, cancelled, was_empty = input_collector._collect_multiline_input(reader=reader)
        self.assertEqual(text, "a")
        self.assertTrue(cancelled)
        self.assertFalse(was_empty)

    def test_long_abc_initial_lines(self):
        reader = _reader_from(["x", "конец"])
        text, cancelled, was_empty = input_collector._collect_multiline_input(
            reader=reader, initial_lines=["abc"]
        )
        self.assertEqual(text, "abc\nx")
        self.assertFalse(cancelled)
        self.assertFalse(was_empty)



class TestAutomaticBurstCollector(unittest.TestCase):
    def test_single_line_finishes_after_idle(self):
        text, cancelled, was_empty = input_collector._collect_burst_input(
            "hello", reader=_reader_from([]),
            has_pending_input=lambda timeout: False
        )
        self.assertEqual(text, "hello")
        self.assertFalse(cancelled)
        self.assertFalse(was_empty)

    def test_consecutive_messages_are_joined(self):
        reader = _reader_from(["second", "third"])
        readiness = iter([True, True, False])
        text, cancelled, was_empty = input_collector._collect_burst_input(
            "first", reader=reader,
            has_pending_input=lambda timeout: next(readiness)
        )
        self.assertEqual(text, "first\nsecond\nthird")
        self.assertFalse(cancelled)
        self.assertFalse(was_empty)

    def test_legacy_terminator_stops_burst(self):
        reader = _reader_from(["second", "конец", "must-not-be-read"])
        readiness = iter([True, True, True])
        text, cancelled, was_empty = input_collector._collect_burst_input(
            "first", reader=reader,
            has_pending_input=lambda timeout: next(readiness)
        )
        self.assertEqual(text, "first\nsecond")
        self.assertFalse(cancelled)
        self.assertFalse(was_empty)

    def test_ctrl_c_cancels_burst(self):
        reader = _reader_from([KeyboardInterrupt()])
        text, cancelled, was_empty = input_collector._collect_burst_input(
            "first", reader=reader,
            has_pending_input=lambda timeout: True
        )
        self.assertEqual(text, "first")
        self.assertTrue(cancelled)
        self.assertFalse(was_empty)

    def test_empty_first_line_and_no_followup(self):
        text, cancelled, was_empty = input_collector._collect_burst_input(
            "", reader=_reader_from([]),
            has_pending_input=lambda timeout: False
        )
        self.assertEqual(text, "")
        self.assertFalse(cancelled)
        self.assertTrue(was_empty)


if __name__ == "__main__":
    unittest.main(verbosity=2)
