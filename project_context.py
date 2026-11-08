"""Explicit project-context domains for chat isolation."""

DOMAINS = {
    "general": {"label": "Общий контекст", "aliases": ("general", "общий", "общее")},
    "brain": {"label": "Personal AI Brain", "aliases": ("brain", "мозг", "брейн", "personal ai brain")},
    "development": {"label": "Разработка", "aliases": ("development", "dev", "разработка", "код", "программирование")},
    "learning": {"label": "Обучение", "aliases": ("learning", "study", "обучение", "учёба", "учеба")},
    "income": {"label": "Заработок", "aliases": ("income", "бизнес", "заработок", "доход", "работа")},
    "personal": {"label": "Личные задачи", "aliases": ("personal", "личное", "личные задачи", "саморазвитие")},
}

_ALIAS_TO_DOMAIN = {
    alias.casefold(): domain
    for domain, data in DOMAINS.items()
    for alias in (domain, *data["aliases"])
}


def normalize_domain(value):
    """Return canonical domain ID, or None for unknown input."""
    if not isinstance(value, str):
        return None
    return _ALIAS_TO_DOMAIN.get(" ".join(value.casefold().strip().split()))


def domain_label(domain):
    data = DOMAINS.get(domain) if isinstance(domain, str) else None
    return data["label"] if data else DOMAINS["general"]["label"]


def list_domains():
    return [{"id": domain, "label": data["label"]} for domain, data in DOMAINS.items()]
