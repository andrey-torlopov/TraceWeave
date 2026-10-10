# TW-E8-003 — первый выпуск Docker Hub по GitHub-тегам

| Поле | Содержание |
| --- | --- |
| ID | TW-E8-003 |
| Этап | E8, публикация принятой Docker-поставки |
| Цель | В трёх GitHub-репозиториях есть релизные теги; backend/frontend публикуются автоматически по версии тега; первый полный выпуск включает четыре публичных multiarch образа с совпадающими версиями. |
| Основания | Прямое разрешение владельца 2026-10-10 на файлы, commits, push, теги и Docker Hub publication; CR-E8-001; ТЗ §21.5, §25.3–25.4, AC-65/66; TW-E8-002. |
| Контракты | Release manifest formatVersion=1; SemVer; OCI version/ref/revision; registry digests; существующие API/миграции не меняются. |
| Входные зависимости | Три самостоятельных repositories; GitHub Actions; DOCKERHUB_TOKEN и DOCKERHUB_USERNAME; доступ Contents: Read к обоим приватным source repositories; четыре Public Docker Hub repositories с immutable tags. |
| Владелец | Координатор A — агент /root текущего чата; независимый агент выполняет только review. |
| Разрешённые файлы | SRC/TraceWeaveBackend/.github/workflows/dockerhub.yml; SRC/TraceWeaveFrontend/.github/workflows/dockerhub.yml; SRC/TraceWeave/.github/workflows/delivery.yml; файлы TW-E8-002; SRC/TraceWeave/docs/tasks/TW-E8-003-dockerhub-publication.md; SRC/TraceWeave/docs/ru/releases.md; SRC/TraceWeave/docs/en/releases.md; SRC/TraceWeave/releases/0.1.0.json; SRC/TraceWeave/releases/stable.json; SRC/TraceWeave/releases/tools-image.txt; Artifacts/docker-publication-status.md; PROJECT.md. |
| Запретные зоны | Доменные sources, API/схемы, миграции, зависимости/lock-файлы, пользовательские runtime/БД/volumes, глобальные настройки. Приватность GitHub repositories не менять без отдельного указания. |
| Проверки | Unit suite; shell/Python/YAML checks; remote refs; имена секретов без значений; Public/immutable Docker Hub settings; native amd64/arm64 CI; registry manifests/digests; анонимный pull и отдельный синтетический runtime. |
| Выход | Установленные workflows, версии и настройки GitHub, протокол реальных CI/registry результатов, инструкция оставшихся действий владельца. |

## План

1. Исправить предусловие fault suite и доступ к приватному counterpart; проверять Public/immutable tags до сборок.
2. Принять изменения сборщика в поставку, создать начальные v0.1.0 в трёх repositories до установки tag-trigger workflows.
3. Установить одинаковые publication workflows в backend/frontend; задать counterpart/delivery variables.
4. Запустить полный выпуск из backend после готовности source access и immutable tags; проверить фактический результат. После успешной приёмки выпустить manifest/Release assets.

## Preflight 2026-10-10

- GitHub SSH и CLI доступны вне sandbox; admin/push права подтверждены во всех трёх repositories. Main локально совпадает с remote.
- Backend/frontend приватные, поставка публичная. В обоих source repositories уже есть Secret DOCKERHUB_TOKEN и Variable DOCKERHUB_USERNAME=andreytorlopov. Других настроек пока нет.
- Четыре Docker Hub repositories Public; immutable_tags_settings.enabled=false. Владельцу отправлены инструкции включения immutable tags и добавления SOURCE_REPOSITORIES_TOKEN (Contents: Read backend/frontend).
- GitHub tag rulesets недоступны приватным source repositories на текущем тарифе (HTTP 403). Неизменяемость source tags остаётся правилом оператора; SHA разрешается один раз перед jobs и сохраняется в provenance. Приватность repositories сохраняется.
- Независимый review выявил необходимость start между integration.py и fault_integration.py.

## Release gate

- Operation: fast-forward integration, push commits/tags и первый Docker Hub release.
- Environment: три repositories andrey-torlopov и namespace Docker Hub andreytorlopov; без VPS deployment.
- Version/ref: первый v0.1.0; существующие tags отсутствуют и не перезаписываются.
- Expected effect: source tags и workflows; после успешных проверок четыре Public multiarch images.
- Rollback: рабочая установка не меняется. Предыдущий публичный выпуск отсутствует; при неудаче manifest/stable не продвигается. Ошибку исходников исправлять новым commit/tag; опубликованные immutable tags не удалять. Миграции не меняются; восстановление рабочей установки не требуется.
- Verification: unit/static checks, remote refs, Actions job conclusions и registry metadata; невыполненные проверки отмечать явно.
- Confirmation: текущее прямое поручение владельца разрешает эти действия; дополнительная публикация/развёртывание вне указанного scope не выполняется.

## Результат

В работе. Публикация пока не подтверждена.
