"""Bounded, domain-scoped retrieval of prior chat context."""

from typing import Callable, Optional

import project_context


CHAT_RECALL_MAX_RESULTS = 3
MAX_CHAT_CONTEXT_CHARS = 1800


def build_chat_history_context(
    query: str,
    context_domain: str,
    active_chat_id: Optional[str] = None,
    max_results: int = CHAT_RECALL_MAX_RESULTS,
    recall_func: Optional[Callable] = None,
) -> Optional[str]:
    """Return a small same-domain history context block, or None.

    Retrieval is read-only. Invalid domains and retrieval failures fail closed.
    The active chat is excluded to avoid injecting the current conversation twice.
    """
    if not isinstance(query, str) or not query.strip():
        return None

    domain = project_context.normalize_domain(context_domain)
    if domain is None:
        return None

    try:
        limit = max(1, min(int(max_results), CHAT_RECALL_MAX_RESULTS))
    except (TypeError, ValueError):
        limit = CHAT_RECALL_MAX_RESULTS

    if recall_func is None:
        try:
            import chat_recall
            recall_func = chat_recall.recall_as_context
        except Exception:
            return None

    try:
        context = recall_func(
            query,
            exclude_chat_id=active_chat_id,
            max_results=limit,
            context_domain=domain,
        )
    except Exception:
        return None

    if not isinstance(context, str) or not context.strip():
        return None

    context = context.strip()
    if len(context) > MAX_CHAT_CONTEXT_CHARS:
        context = context[:MAX_CHAT_CONTEXT_CHARS].rstrip() + "\n...[контекст истории сокращён]"
    return context
