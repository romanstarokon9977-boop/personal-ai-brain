#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated multiline input collector for Personal AI Brain.

No imports from brain.py, memory, chat_system, tool_registry
or any project module. No file I/O, no network, no side effects on import.
"""


def _collect_multiline_input(reader=input, terminator="конец", initial_lines=None):
    """Collect lines until terminator; return (text, cancelled, was_empty).

    reader: callable returning one line.
            KeyboardInterrupt or EOFError => cancelled=True.
    terminator: line ends collection when line.strip().lower() == terminator.
    initial_lines: optional list of pre-collected lines ('long abc' first line).

    text: "\\n".join(collected).strip() (empty lines inside preserved).
    cancelled: True if KeyboardInterrupt/EOFError was caught.
    was_empty: True if text == "".
    """
    collected = list(initial_lines) if initial_lines else []
    cancelled = False
    while True:
        try:
            line = reader()
        except (KeyboardInterrupt, EOFError):
            cancelled = True
            break
        if line.strip().lower() == terminator:
            break
        collected.append(line)
    text = "\n".join(collected).strip()
    return text, cancelled, (text == "")
