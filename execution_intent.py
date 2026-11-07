"""Conservative detection of explicit plan-only instructions in execution goals."""

import unicodedata


_PLAN_ONLY_MARKERS = (
    "пока не приступай",
    "пока не приступать",
    "пока не начинай",
    "только план",
    "только составь план",
    "только составить план",
    "только подготовь план",
    "только подготовить план",
    "без исполнения",
    "без выполнения",
    "не выполняй",
    "не выполнять",
    "не приступай к выполнению",
    "не приступать к выполнению",
    "не начинай выполнение",
    "не начинайте выполнение",
    "не запускай выполнение",
    "не запускать выполнение",
    "не запускай инструменты",
    "не запускать инструменты",
    "не вызывай инструменты",
    "не вызывать инструменты",
    "не используй инструменты",
    "не использовать инструменты",
    "без запуска инструментов",
    "без вызова инструментов",
    "не выполняй шаги",
    "не выполнять шаги",
    "не запускай шаги",
    "не запускать шаги",
)


def is_plan_only_request(text):
    """Return True when the goal explicitly prohibits starting execution.

    False positives are intentionally safety-biased: an ambiguous request
    should produce a saved, pending plan rather than execute tools.
    """
    if not isinstance(text, str) or not text.strip():
        return False

    normalized = " ".join(
        unicodedata.normalize("NFKC", text).casefold().replace("ё", "е").split()
    )
    return any(marker in normalized for marker in _PLAN_ONLY_MARKERS)
