# TW-E8-002 — версии Docker-образов из GitHub-тегов

| Поле | Содержание |
| --- | --- |
| ID | TW-E8-002 |
| Этап | E8, сопровождение принятой Docker-поставки |
| Цель | Оператор выбирает GitHub-теги `vMAJOR.MINOR.PATCH`; Docker-тег, встроенная версия компонента и OCI version совпадают, даже когда версии backend/frontend различаются. |
| Основания | Прямой запрос владельца 2026-10-10; CR-E8-001; ТЗ §21.5, §25.3–25.4, AC-65/66. Не является полной приёмкой P0. |
| Контракты | Release manifest formatVersion=1; backendVersion, frontendVersion, frontendReleaseId; неизменяемые registry digests; существующие build args BACKEND_VERSION/FRONTEND_VERSION/RELEASE_ID. |
| Входные зависимости | Существующие Dockerfiles и build-source; три самостоятельных Git-репозитория. Публичные GitHub/Docker-теги пока не созданы этой задачей. |
| Владелец | Координатор A — агент /root текущего чата. |
| Разрешённые файлы | SRC/TraceWeave/tools/control.py; SRC/TraceWeave/traceweave.sh; SRC/TraceWeave/tests/test_control.py; SRC/TraceWeave/tests/test_wrapper.py; SRC/TraceWeave/docs/tasks/TW-E8-002-github-release-tags.md; SRC/TraceWeave/docs/ru/releases.md; SRC/TraceWeave/docs/en/releases.md; Artifacts/docker-publication-status.md. |
| Запретные зоны | Код backend/frontend, Dockerfiles (существующих аргументов достаточно), схемы/API, миграции, зависимости/lock-файлы, действующий CI delivery.yml, runtime и пользовательские данные. |
| Проверки | Python unit suite для CLI; независимые версии, отказ до сборки на недопустимых версиях и изменённых исходниках; статическая проверка YAML и встроенных shell/Python блоков документированного workflow. |
| Выход | Документ с полным workflow по тегам; дополнительные параметры build-source, OCI labels и сохранённая совместимость старого локального режима; реальные результаты проверки ниже. |

## План

1. Добавить необязательные версии backend/frontend/delivery; при их отсутствии сохранить прежние локальные идентификаторы.
2. Передать версии существующим Dockerfiles; записать версии и source revision в OCI labels. Для tag-режима проверить также чистоту поставки.
3. Заменить в инструкции push-main/run-number выпуском по тегам, проверкой соответствия тегов исходникам и запретом перезаписи опубликованных версий.
4. Проверить unit suite и извлечённый workflow. Публикация, создание GitHub-тегов и runtime-приёмка не входят в запрос.

## Результат

Цель выполнена локально 2026-10-10. Код поставки находится в ветке `codex/github-release-tags`, без commit/push. Backend/frontend checkout остались чистыми; remotes всех трёх репозиториев проверены. Dockerfiles не изменялись: build-source передаёт существующие build args и OCI labels через Docker CLI.

Изменены разрешённые файлы: tools/control.py, traceweave.sh, tests/test_control.py, tests/test_wrapper.py, обе языковые инструкции releases.md, этот протокол и Artifacts/docker-publication-status.md. Зависимости, миграции и manifest formatVersion не менялись.

### Выполненные проверки

- `git switch -c codex/github-release-tags` — создана отдельная ветка в SRC/TraceWeave.
- `python3 -m unittest discover -s tests -p test_control.py` — первый запуск системным Python: failed из-за отсутствующей jsonschema в окружении; ошибки новой логики не обнаружены. Это не успешная полная проверка.
- Из SRC/TraceWeave: `/Volumes/DATA-R1/Dev/Projects/ResearchGraph/Archive/2026-10-10/.venv/bin/python3 -B -m unittest discover -s tests` — **97 tests, OK** после окончательных изменений. Использовано готовое окружение; новые зависимости не устанавливались. Docker/сеть в unit tests подменены синтетическими stubs.
- `/Volumes/DATA-R1/Dev/Projects/ResearchGraph/Archive/2026-10-10/.venv/bin/python3 -B /private/tmp/check_traceweave_tag_workflow.py` — **PASS**: YAML, ссылки outputs, bash/Python syntax, backend/frontend tag selection, первый полный выпуск, отказ для неправильных тегов/разных full-release версий и изменения pushed tag. Проверяется YAML, извлечённый из документа; workflow в .github не устанавливался.
- Дополнительная Python-проверка — **PASS**: CLI принимает новые аргументы; validator принимает `repository:version@sha256:digest`; четыре отметки Public сохранены; документированный workflow не выбирает исходники вручную по SHA/run_number; ссылки проектных документов существуют.
- `sh -n` для bootstrap.sh/traceweave.sh и `git diff --check` — **PASS**.

### Граница подтверждения

AC-65/66: подготовлены версия/metadata и процедура воспроизводимой публикации; runtime-приёмка Docker/Linux этими проверками не подтверждается. На macOS проверены unit tests и статический workflow. Реальные Docker builds, GitHub execution, registry push, анонимный pull и bootstrap на чистых amd64/arm64 хостах — **not_run**, выполняются по обновлённой инструкции после принятия PR и создания тегов. Actionlint не установлен; его запуск не заявляется. Полная P0-приёмка не меняется.
