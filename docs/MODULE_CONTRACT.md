# Контракт модулей Personal AI Brain

## Формат manifest v1

Каждый будущий модуль должен иметь декларативный manifest:
- `schema_version` — версия схемы manifest;
- `module_id` — стабильный slug;
- `name`, `description`;
- `version` — стабильный SemVer MAJOR.MINOR.PATCH;
- `api_version` — поддерживаемый контракт Brain;
- `entrypoint` — dotted Python import path, только декларация;
- `capabilities` и `permissions`;
- `dependencies` с минимальной версией;
- `risk` — low/medium/high;
- `auto_enable` — всегда false.

## Проверки

`module_contract.validate_manifest()` проверяет строгую схему, типы, версию API, безопасный формат entrypoint, допустимые capabilities/permissions, соответствие риска и запрет автоматического включения.

`module_contract.validate_catalog()` проверяет уникальность ID, наличие зависимостей, минимальные версии и циклы. Результат содержит dependency-first порядок для будущего загрузчика.

## Границы безопасности

- Валидатор ничего не импортирует и не исполняет.
- Manifest не выдаёт разрешения сам по себе: фактические права назначаются отдельной политикой Tool Registry/Autonomy Controller.
- Новый модуль по умолчанию выключен; включение требует отдельного решения пользователя.
- `process.execute` и `publish` требуют уровня риска high.
- Нельзя объявить capability без соответствующего permission.
- Неизвестные поля и неизвестные права отклоняются, а не игнорируются.

## Текущий статус

Это версия контракта и проверка каталога. Динамическая загрузка, установка зависимостей, sandbox, подпись пакетов и автоматическое обновление модулей не реализованы. Entry point остаётся декларацией и не запускается.
