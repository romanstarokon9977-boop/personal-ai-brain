# Установка Personal AI Brain в Termux

Эта инструкция фиксирует prerequisites и путь установки из текущего репозитория. Она не заменяет runtime-приёмку на POCO F6.

## 1. Подготовить Termux

Обновить пакеты и установить базовые инструменты:

```bash
pkg update && pkg upgrade
pkg install python git nodejs
```

Убедиться, что доступны Python, Git и Node.js:

```bash
python --version
git --version
node --version
npm --version
```

CI проекта использует Python 3.11. Если версия Python в Termux отличается, это расхождение нужно учитывать при проверке совместимости.

## 2. Получить репозиторий

Репозиторий приватный. Клонирование требует доступа к GitHub:

```bash
cd ~
git clone https://github.com/romanstarokon9977-boop/personal-ai-brain.git personal_ai_brain
cd ~/personal_ai_brain
git switch main
```

Если репозиторий уже существует:

```bash
cd ~/personal_ai_brain
git status --short --branch
git pull --ff-only
```

Не выполняйте pull при незакоммиченных изменениях. Не используйте reset/clean для обхода конфликтов.

## 3. Установить Python- и MCP-зависимости

Основная обязательная Python-зависимость, используемая CI:

```bash
python -m pip install --upgrade pip
python -m pip install requests
```

Дополнительные библиотеки для чтения документов:

```bash
python -m pip install pypdf python-docx
```

Установить зафиксированные зависимости MCP filesystem server из lock-файла:

```bash
npm ci --prefix mcp_servers/filesystem
```

Путь после установки должен существовать:

```bash
test -f mcp_servers/filesystem/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js && echo "MCP filesystem server: OK"
```

## 4. Настроить API-ключ

Brain требует переменную окружения `OPENROUTER_API_KEY` при импорте `brain.py`.

Для текущей сессии введите ключ без отображения:

```bash
read -s -p "OpenRouter API key: " OPENROUTER_API_KEY
echo
export OPENROUTER_API_KEY
```

Не помещайте ключ в Git, README, сообщения об ошибках или логи. Для постоянной настройки добавьте экспорт переменной в приватный shell startup-файл Termux, а не в файлы репозитория.

Gemini fallback использует отдельную необязательную переменную `GEMINI_API_KEY`.

## 5. Подготовить Android shared storage для памяти

Выдать Termux разрешение на доступ к общему хранилищу:

```bash
termux-setup-storage
```

После подтверждения Android создать каталог памяти:

```bash
mkdir -p /storage/emulated/0/Documents/AI_Brain
```

Канонический путь памяти в текущем коде:

```text
/storage/emulated/0/Documents/AI_Brain/brain_memory.json
```

Не удаляйте и не перемещайте существующий файл памяти. Перед ручными операциями сделайте резервную копию.

## 6. Запустить Brain

```bash
cd ~/personal_ai_brain
python brain.py
```

Если запуск сообщает, что `OPENROUTER_API_KEY` отсутствует, проверьте:

```bash
printf '%s' "${OPENROUTER_API_KEY:+SET}"
```

Не выводите само значение ключа на экран.

## 7. Локальные модели — отдельная настройка

Локальный inference не устанавливается этой инструкцией автоматически. Для него отдельно требуются:
- совместимая сборка `llama-server`;
- GGUF-файлы моделей в ожидаемом кодом каталоге shared storage;
- проверка портов и параметров запуска на самом устройстве.

Текущие chat services в коде используют порты 8085 и 8088. Embedding provider отдельно ожидает loopback endpoint на 8090; его фактическая работа на POCO F6 ещё должна быть подтверждена. Не подменяйте chat server embedding server.

## 8. Запустить тесты

```bash
OPENROUTER_API_KEY=test-only-placeholder python -m unittest discover -v
```

CI выполняет компиляцию перечисленных модулей, отдельные unittest-модули и полный unittest discovery на Python 3.11.

## 9. Диагностика перед использованием

Проверьте:
- `git status --short --branch` — рабочее дерево чистое;
- `python --version` — версия Python;
- MCP filesystem server — файл запуска существует;
- доступ к каталогу памяти — Termux storage permission выдано;
- секреты — ключ не находится в репозитории;
- локальные сервисы — только те процессы, которые пользователь намеренно запустил.

Устройство-специфичные проверки, резервное копирование и критерии выпуска описаны в [Product Readiness Register](PRODUCT_READINESS.md).
