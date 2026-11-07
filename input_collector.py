#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated input collectors for Personal AI Brain.

No imports from brain.py, memory, chat_system, tool_registry
or any project module. No file I/O or network side effects on import.
"""


def _collect_multiline_input(reader=input, terminator="конец", initial_lines=None):
    """Collect lines until terminator; return (text, cancelled, was_empty).

    reader: callable returning one line.
            KeyboardInterrupt or EOFError => cancelled=True.
    terminator: line ends collection when line.strip().lower() == terminator.
    initial_lines: optional list of pre-collected lines ('long abc' first line).
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


def _stdin_has_pending_input(timeout, stream=None):
    """Return whether stdin becomes readable before timeout.

    On unsupported/non-selectable streams, fail open to ordinary single-line
    input rather than blocking or changing the chat loop.
    """
    import select
    import sys

    stream = sys.stdin if stream is None else stream
    try:
        ready, _, _ = select.select([stream], [], [], max(0.0, float(timeout)))
        return bool(ready)
    except (OSError, ValueError, TypeError):
        return False


def _collect_burst_input(
    first_line,
    reader=input,
    idle_timeout=2.0,
    terminator="конец",
    has_pending_input=None,
):
    """Join immediately-following input lines until stdin is idle.

    This is a best-effort terminal burst collector: it groups lines arriving
    within idle_timeout. It does not infer semantic completion. The explicit
    legacy 'long' mode remains available for deterministic multiline entry.
    Returns (text, cancelled, was_empty).
    """
    collected = [first_line] if first_line else []
    cancelled = False
    readiness = has_pending_input or _stdin_has_pending_input

    while True:
        try:
            if not readiness(idle_timeout):
                break
            line = reader()
        except (KeyboardInterrupt, EOFError):
            cancelled = True
            break

        if line.strip().lower() == terminator:
            break
        collected.append(line)

    text = "\n".join(collected).strip()
    return text, cancelled, (text == "")
