# TW-E8-003 — первый выпуск Docker Hub по GitHub-тегам

| Поле | Содержание |
| --- | --- |
| ID | TW-E8-003 |
| Этап | E8, публикация принятой Docker-поставки |
| Цель | В трёх GitHub-репозиториях есть релизные теги; backend/frontend публикуются автоматически по версии тега; первый полный выпуск включает четыре публичных multiarch образа с совпадающими версиями. |
| Основания | Прямое разрешение владельца 2026-10-10 на файлы, commits, push, теги и Docker Hub publication; CR-E8-001; ТЗ §21.5, §25.3–25.4, AC-65/66; TW-E8-002. |
| Контракты | Release manifest formatVersion=1; SemVer; OCI version/ref/revision; registry digests; существующие API/миграции не меняются. |
| Входные зависимости | Три самостоятельных repositories; GitHub Actions; DOCKERHUB_TOKEN и DOCKERHUB_USERNAME; доступ Contents: Read к обоим приватным source repositories; четыре Public Docker Hub repositories с immutable tags. |
| Владелец | Координатор A — агент /root текущего чата; агент /root/release_verification владеет только новым registry-verification.yml, интеграция и выпуск остаются у координатора. |
| Разрешённые файлы | SRC/TraceWeaveBackend/.github/workflows/dockerhub.yml; SRC/TraceWeaveFrontend/.github/workflows/dockerhub.yml; SRC/TraceWeave/.github/workflows/delivery.yml; SRC/TraceWeave/.github/workflows/registry-verification.yml; файлы TW-E8-002; SRC/TraceWeave/docs/tasks/TW-E8-003-dockerhub-publication.md; SRC/TraceWeave/docs/ru/releases.md; SRC/TraceWeave/docs/en/releases.md; SRC/TraceWeave/releases/0.1.0.json; SRC/TraceWeave/releases/stable.json; SRC/TraceWeave/releases/tools-image.txt; Artifacts/docker-publication-status.md; PROJECT.md. |
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

## Первый этап: до настройки source access

Подготовка и GitHub integration выполнены; Docker Hub publication ожидает SOURCE_REPOSITORIES_TOKEN.

- В main поставки отправлен aa8543b (builder, CLI/tests/docs, private source checkout); v0.1.0 создан на этом commit.
- В backend main отправлен 3b4882b, во frontend main — a0fa01d: одинаковые .github/workflows/dockerhub.yml, зарегистрированные GitHub как active. Их v0.1.0 закрепляют исходный принятый код до установки tag-trigger workflow: backend 3367a53, frontend b270b1c. Теги созданы и отправлены до workflows; ручной первый full_release строит именно их, номера версий не зависят от workflow commit.
- В backend/frontend установлены Variables TRACEWEAVE_DELIVERY_TAG=v0.1.0 и TRACEWEAVE_COUNTERPART_TAG=v0.1.0; прежние DOCKERHUB_TOKEN/DOCKERHUB_USERNAME сохранены. Secret SOURCE_REPOSITORIES_TOKEN пока отсутствует в трёх repositories.
- Владелец включил immutable tags; актуальный Docker Hub API подтвердил Public и immutable_tags_settings={enabled:true,rules:[".*"]} для всех четырёх repositories.
- Проверки: 97 unit tests OK; sh -n OK; git diff --check OK; actionlint 1.7.12 (официальный archive/checksum, временный каталог) OK для всех трёх workflows. Извлечённые shell/Python/YAML блоки, tag selection и provenance checks PASS. Remote main/tag commits и bytes обоих workflows сверены с локальными файлами через GitHub API.
- После main push запустился [delivery CI 38071338668](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38071338668): обе архитектуры failed на checkout приватного backend; до unit/build/integration не дошли. Это подтверждает отсутствие source-access Secret и не является дефектом Docker Hub PAT. После настройки Secret этот run можно rerun; полный publication run запускается отдельно из backend main.
- Registry push, release Docker builds, anonymous pulls, registry-digest manifest/stable promotion и чистый bootstrap — not_run до готовности source access. GitHub Release assets не создавались; существующие Git tags не переносятся. Рабочие установки, миграции, зависимости и БД не изменены.

Команда первого выпуска после добавления Secret во все три repositories:

```sh
gh workflow run dockerhub.yml --repo andrey-torlopov/TraceWeaveBackend --ref main -f release_tag=v0.1.0 -f full_release=true
```

Не запускайте обычный frontend v0.1.0 параллельно полному выпуску: полный выпуск публикует также frontend. Следующий компонент выпускается новым version tag. AC-65/66 подтверждены только в объёме подготовленного version/provenance workflow; реальная registry/runtime приёмка ещё не завершена.

## Продолжение после настройки Source Secret

Владелец создал SOURCE_REPOSITORIES_TOKEN и добавил его в три repositories. API подтвердил наличие имён (значения не читаются); checkout обоих приватных sources реально прошёл. Запущен [полный publication run 38072087934](https://github.com/andrey-torlopov/TraceWeaveBackend/actions/runs/38072087934) из backend main с release_tag=v0.1.0/full_release=true. Prepare, contract/unit/frontend checks прошли на обеих архитектурах; native Docker builds в работе.

Добавлен отдельный workflow registry-verification.yml: только workflow_dispatch, полный candidate JSON и delivery tag, две свежие native VM, пустой DOCKER_CONFIG, anonymous pulls и проверка OCI/baked metadata/source/contract. HTTP integration использует Docker-only CLI с PATH без host Python; абсолютный host Python служит только HTTP/PTY test harness. HTTPS/SMTP/account lifecycle проверяется отдельно. Только помеченные synthetic runtimes, stop сохраняет volumes; в artifact попадает компактное evidence без приватных логов. Actionlint, bash syntax всех 7 run blocks и AST heredocs прошли; настоящий registry run возможен после получения публикационного artifact.
