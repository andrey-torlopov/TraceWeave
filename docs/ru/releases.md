# Релизы и обновление

*[English](../en/releases.md)*

## Манифест совместимой поставки

Релиз — конкретный набор независимо собранных backend/frontend images плюс закреплённые PostgreSQL, gateway и tools. Манифест формата 1 содержит следующие проверяемые поля:

| Поле | Смысл |
| --- | --- |
| `releaseId`, `backendVersion`, `frontendVersion` | Явные идентификаторы поставки и компонентов. |
| `frontendReleaseId` | Release ID, записанный при сборке конкретного frontend image; может отличаться от ID всей поставки при замене только backend. |
| `images.backend/frontend/postgres/gateway/tools` | Immutable `repository@sha256:...` или локальный `sha256:...` image ID. Плавающий tag не допускается. |
| `contractHash`, `backendContractHash` | SHA-256 OpenAPI входа сборки frontend/backend. |
| `supportedClientContractHashes` | Контракты старых/текущих вкладок, которые выбранный backend принимает. Own `contractHash` обязателен. |
| `postgresMajor` | Сейчас строго 18; major upgrade требует отдельного плана. |
| `migrations` | Непрерывная последовательность `version` от 1 и точный SHA-256 каждой миграции. |
| `platforms`, `source`, `validation`, `rollback` | Архитектуры сборки, source revisions/diff hashes, evidence и путь восстановления. Source builder записывает эти поля; выпуск должен подтвердить их до публикации. |

Локальный source builder по умолчанию использует ID `docker-1`; инструкции текущего пакета явно выбирают `e8-docker-1`. Он требует committed и чистые backend/frontend checkout, включая неигнорируемые untracked файлы; Git HEAD, статус source и hash контракта проверяются до и после сборки. Файл `releases/e8-docker-1.local.json` появляется только после успешного `build-source`; документация не подменяет его фиктивным digest. Повторная сборка с уже существующим локальным manifest этого ID отказывает до изменения images. Для следующей сборки нужен новый ID: старые manifest и tags сохраняют путь отката. Все четыре собранных образа удерживаются под отдельными tags, включая `traceweave/tools:e8-docker-1`; отдельный fallback tag `traceweave/tools:docker-1` может оставаться для первоначального Docker-only CLI. Tags помогают удерживать локальные images, но manifest закрепляет их immutable IDs. Для Docker-only bootstrap выбирайте immutable tools ID/digest именно нужного релиза по [инструкции подготовки CLI](installation.md#cli-с-python-и-без-python). Локальные `releases/*.local.json` исключены из Git; публичный release manifest должен использовать доступные registry digests.

Для публикации по GitHub-тегам сборщик принимает независимые `--backend-version`, `--frontend-version`, `--delivery-version` в формате `MAJOR.MINOR.PATCH` без `v`. Версии backend/frontend передаются существующим Dockerfiles и записываются в manifest; при явной frontend version её же получает `frontendReleaseId`. Gateway/tools получают delivery version в OCI labels. Все четыре образа получают OCI version/source/ref.name, компоненты — revision; при явной delivery version записывается также commit поставки и проверяется её чистота до/после сборки. Checkout выбранных тегов и совпадение tag/version проверяет workflow публикации. Без новых аргументов прежний локальный режим с версиями из release ID сохраняется. [Проектная задача](../tasks/TW-E8-002-github-release-tags.md).

Frontend runtime metadata находится вне webroot в `/opt/traceweave/frontend-release.json`, backend — в `/app/backend-release.json`. Readiness сравнивает baked frontend `releaseId` с `frontendReleaseId` манифеста, его version/hash — с `frontendVersion`/`contractHash`, backend version/hash — с `backendVersion`/`backendContractHash`, историю БД — с `migrations`. При замене только backend новый общий `releaseId` сохраняет прежние frontend image, `frontendReleaseId`, `frontendVersion` и `contractHash`. Gateway отдаёт `/release.json` с общим release ID, frontend version, contract hash и списком supported hashes даже во время обслуживания.

Первый публичный выпуск `0.1.0` опубликован в Docker Hub: `andreytorlopov/traceweave-backend`, `traceweave-frontend`, `traceweave-gateway`, `traceweave-tools`, все с тегом `0.1.0` и архитектурами `linux/amd64`, `linux/arm64`. GitHub-тег каждого исходного repository — `v0.1.0`, встроенная версия — `0.1.0`. [Native проверки и публикация прошли](https://github.com/andrey-torlopov/TraceWeaveBackend/actions/runs/38072087934); [приёмка из реестра на чистых хостах прошла](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38073642033), включая Docker-only bootstrap/lifecycle и HTTPS/SMTP/accounts. Проверенный manifest — [releases/0.1.0.json](../../releases/0.1.0.json), выбор по умолчанию для новой установки — [releases/stable.json](../../releases/stable.json), tools digest — [releases/tools-image.txt](../../releases/tools-image.txt). Эти же файлы и publication evidence доступны в [GitHub Release v0.1.0](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.0). Все image repositories Public с неизменяемыми тегами. Backend/frontend GitHub sources остаются приватными. Публикация не обновляет существующие установки автоматически.

## Настройки публикации Docker Hub

Workflow `.github/workflows/dockerhub.yml` расположен в backend и frontend. Push тега `vMAJOR.MINOR.PATCH` публикует только этот компонент после проверок Linux amd64/arm64; ручной запуск с `full_release=true` выпускает backend/frontend/gateway/tools одной новой версии. GitHub `v0.1.0` соответствует Docker `0.1.0` и встроенной версии `0.1.0`. Проверенные images передаются между jobs без пересборки; итоговый manifest фиксирует version tag и registry digest. Повторная публикация существующего тега запрещена.

В backend/frontend нужны следующие Actions settings:

| Тип | Имя | Значение первого выпуска |
| --- | --- | --- |
| Secret | `DOCKERHUB_TOKEN` | Docker Hub PAT с Read/Write; уже добавлен владельцем. |
| Secret | `SOURCE_REPOSITORIES_TOKEN` | GitHub fine-grained PAT, Contents: Read в TraceWeaveBackend и TraceWeaveFrontend; оба repository приватные. |
| Variable | `DOCKERHUB_USERNAME` | `andreytorlopov` |
| Variable | `TRACEWEAVE_DELIVERY_TAG` | `v0.1.0` |
| Variable | `TRACEWEAVE_COUNTERPART_TAG` | `v0.1.0` — frontend tag в backend settings и backend tag в frontend settings. |

В **TraceWeave** требуется только Secret `SOURCE_REPOSITORIES_TOKEN` для интеграционного CI. Docker Hub Secret/variables в поставке не используются. Стандартный `GITHUB_TOKEN` не даёт доступ ко второму приватному repository. [Официальный пример private checkout](https://github.com/actions/checkout#checkout-multiple-repos-private).

Четыре Docker Hub repositories `andreytorlopov/traceweave-{backend,frontend,gateway,tools}` должны быть Public и иметь **All tags are immutable**. Workflow проверяет это до сборок. Первый выпуск уже запущен вручную из Actions backend с `release_tag=v0.1.0`, `full_release=true`. Не запускайте его повторно: Docker-теги опубликованы и неизменяемы. Следующий полный выпуск требует новой одинаковой версии во всех трёх GitHub repositories; component-only выпуск — нового тега изменённого компонента. Доступность images и готовность installable manifest подтверждаются отдельно. [Протокол текущего выпуска](../tasks/TW-E8-003-dockerhub-publication.md).

## Что выпустить для запуска одной командой

Публичный GitHub-репозиторий TraceWeave хранит поставку, CLI, Compose и контракты; backend/frontend находятся в отдельных приватных repositories. Реестр этого выпуска — Docker Hub. PostgreSQL берётся из официального публичного образа.

До выдачи пользователю команды `./bootstrap.sh` разработчик выполняет:

1. Собирает и проверяет backend, frontend, gateway и tools из согласованных source revisions для заявленных платформ. Delivery CI тестирует две архитектуры без публикации; отдельный Docker Hub workflow публикует проверенные images; `build-source` собирает только архитектуру своего Docker-хоста.
2. Авторизуется в выбранном реестре, присваивает релизные tags и отправляет четыре образа. Для двух платформ выпускает общий image index каждого компонента. Это отдельная операция [публикации images](https://docs.docker.com/docker-hub/repos/manage/hub-images/push/).
3. Делает все четыре image repositories публичными и проверяет анонимное скачивание. Публичность GitHub source repository и видимость Docker Hub repository — независимые настройки.
4. Выпускает версионированный JSON в `releases/` с фактическими registry digests вместо локальных image IDs, сохраняя hashes контрактов, версии компонентов и migrations. Имя файла соответствует реальному release ID, не условному примеру.
5. Включает тот же проверенный manifest как `releases/stable.json` и единственную строку `images.tools` как `releases/tools-image.txt`. Второй файл позволяет скачать tools без установленного Python; digest должен совпадать с manifest.
6. Проверяет `./bootstrap.sh` на чистом Docker-хосте с пустым runtime, включая режим без host Python, и выпускает папку поставки с этими файлами.

`stable.json` выбирается только для новой установки. Повторный bootstrap использует `runtime/release.json`; новая версия устанавливается отдельно командой update. Не менять уже выпущенные версии или migrations ради повторной публикации.

## Совместимость вкладок и pending

Все запросы frontend несут `X-TraceWeave-Client-Contract`, защищённые запросы также expected account ID. Сохранённый pending удерживает точное тело, operationId, account и contract hash. При 503 он остаётся доступным для точного повтора, при смене аккаунта не отправляется от имени нового пользователя. Unsupported client получает 409 `client_upgrade_required` до мутации; черновик сохраняется. Смена сессии получает `account_changed`, восстановление требует прежнего аккаунта либо явного разбора черновиков.

Update отказывается удалять любой previously supported hash из списка. Добавление нового supported hash требует согласованного backend release; одной правки JSON недостаточно. Несовместимое удаление API требует отдельной процедуры миграции клиентов/pending и не выполняется обычным update. Идемпотентный повтор уже отправленного запроса должен оставаться возможным без нового operationId.

HTML frontend использует no-cache/no-store, hashed assets — immutable cache. Перед заменой frontend updater копирует текущие `/srv/assets/*` в внешний `previous_assets` volume; frontend получает его read-only как `/srv/previous-assets`, без дополнительного каталога `assets/`. Текущие файлы имеют приоритет, старые служат fallback только для `/assets/*`; отсутствующие JS/CSS возвращают 404. Автоматическая очистка retained assets в CLI не реализована. Сохраняйте их на весь период поддержки вкладок; удаление требует отдельного решения после завершения соответствующего compatibility window. [Причина сохранения assets при Vite deployments](https://vite.dev/guide/build.html#load-error-handling).

UI проверяет новый release и предлагает обновить страницу после сохранения/разбора незавершённых действий. Принудительного reload нет. Черновик редактора связи может находиться только в памяти страницы; закрытие вкладки не является процедурой обновления.

## Новая установка конкретной версии

Для `0.1.0` выберите исходники `v0.1.0` и скачайте assets того же [GitHub Release](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.0) в `releases/`. Каталог `TraceWeave-0.1.0` должен быть новым:

```sh
set -eu
git clone --branch v0.1.0 --depth 1 https://github.com/andrey-torlopov/TraceWeave.git TraceWeave-0.1.0
cd TraceWeave-0.1.0
curl -fL --output releases/0.1.0.json https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.0/0.1.0.json
curl -fL --output releases/tools-image.txt https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.0/tools-image.txt
./bootstrap.sh --release "$PWD/releases/0.1.0.json"
./traceweave.sh status
```

Нужны Git, curl, Docker и Compose plugin. Host Python необязателен: wrapper читает `releases/tools-image.txt` и запускает опубликованный tools-контейнер. Файл должен совпадать с `images.tools` manifest; сохраняйте его для последующих команд. Введите данные первого аккаунта в интерактивном bootstrap. Пустая новая установка выбирает указанный manifest; повторный bootstrap сохраняет версию существующей установки.

## Установка выбранного релиза

Получите проверенный manifest, убедитесь, что его images доступны для архитектуры Docker-хоста, и согласуйте окно обслуживания. CLI заранее проверяет совместимость и наличие images, показывает изменяемые компоненты, schemaChanged и путь отката. Введённый путь должен указывать на существующий файл:

```sh
printf 'Путь к проверенному manifest нового релиза: '
IFS= read -r TW_NEXT_RELEASE_MANIFEST
./traceweave.sh update --release "$TW_NEXT_RELEASE_MANIFEST"
./traceweave.sh status
```

CLI проверяет минимум 1 GiB свободного места в runtime; при offline backup ops перед dump дополнительно проверяет бюджет по фактическому размеру БД и оригиналов — [расчёт capacity](operations.md#приватный-offline-backup). До подтверждения и preflight заглушка не включается. Затем она проверяется через публичный маршрут, текущие assets сохраняются и выполняются только нужные замены:

| Изменение | Порядок |
| --- | --- |
| Только frontend | Gateway maintenance → сохранить assets → заменить frontend → проверить → открыть; backend не останавливается, backup/миграции не выполняются. |
| Backend без схемы | Maintenance → assets → штатная остановка backend → проверенный offline backup → заменить нужные images → проверить → открыть. |
| Backend со схемой | То же, затем одноразовый migrate из нового image до запуска нового backend. История только append-only. |
| PostgreSQL/gateway/tools image | Обычный update отклоняет изменение. Нужна отдельная процедура обслуживания. |

`release.json` переключается только после ready проверки, прежний manifest сохраняется как `previous-release.json`. Клиентские запросы не проходят через промежуточную комбинацию backend/frontend. Update не выполняет общее `compose down` и не удаляет volumes. [Выборочная замена сервисов Compose](https://docs.docker.com/compose/how-tos/production/); gateway переключается через [Caddy reload](https://caddyserver.com/docs/command-line#caddy-reload).

Runtime phases и journal позволяют обнаружить обрыв SSH/скрипта или рестарт хоста. Обычный start блокируется при незавершённой операции. После сбоя не открывайте gateway вручную: [resume/recovery](operations.md#прерванная-операция) обязаны проверить текущие images, schema и readiness.

## Откат и восстановление

```sh
./traceweave.sh rollback
```

Image rollback допускается только когда фактическая история миграций точно равна истории целевого релиза. Если БД остановлена, контроллер сначала запускает db/gateway под проверенной заглушкой до чтения истории. Rollback подтверждает maintenance и штатную остановку backend, возвращает совместимую пару backend/frontend, проверяет ready и открывает gateway, сохраняя новые данные. При сбое update использует закреплённый `update-source.json`; после успешно завершённого update целевой предыдущий manifest — `previous-release.json`.

После миграции старый backend может отказаться от новой схемы даже при добавочной миграции. CLI запрещает image rollback при отличающейся истории. Оставьте maintenance; выберите исправляющий совместимый релиз либо [restore pre-update backup в новые volumes](operations.md#restore-в-новые-volumes). Автоматических обратных SQL-миграций нет. Restore делает safety backup текущего состояния и сохраняет прежние volumes; данные, появившиеся после выбранной копии, оператор рассматривает отдельно.

Локальный manifest с image IDs работает только пока эти images есть на данном хосте. Перед переносом или disaster recovery нужны опубликованные immutable images либо отдельный приватный перенос image archives и конфигурации; один JSON не содержит содержимое image. PostgreSQL major upgrade, удаление старых API/asset compatibility и cleanup volumes не смешиваются с обычным UI/API релизом.

---

[К документации](index.md) · [README](../../README-ru.md)
