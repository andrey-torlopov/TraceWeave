# Релизы и обновление

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

Frontend runtime metadata находится вне webroot в `/opt/traceweave/frontend-release.json`, backend — в `/app/backend-release.json`. Readiness сравнивает baked frontend `releaseId` с `frontendReleaseId` манифеста, его version/hash — с `frontendVersion`/`contractHash`, backend version/hash — с `backendVersion`/`backendContractHash`, историю БД — с `migrations`. При замене только backend новый общий `releaseId` сохраняет прежние frontend image, `frontendReleaseId`, `frontendVersion` и `contractHash`. Gateway отдаёт `/release.json` с общим release ID, frontend version, contract hash и списком supported hashes даже во время обслуживания.

Публикация пока не выполнена. Образы приложения в GHCR не заявляются доступными. Владелец отдельно публикует проверенные multiarch images и manifest с registry digests, настраивает их public visibility и документирует наблюдённую приёмку. [Правила GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry). Публикация не обновляет установку автоматически.

## Совместимость вкладок и pending

Все запросы frontend несут `X-TraceWeave-Client-Contract`, защищённые запросы также expected account ID. Сохранённый pending удерживает точное тело, operationId, account и contract hash. При 503 он остаётся доступным для точного повтора, при смене аккаунта не отправляется от имени нового пользователя. Unsupported client получает 409 `client_upgrade_required` до мутации; черновик сохраняется. Смена сессии получает `account_changed`, восстановление требует прежнего аккаунта либо явного разбора черновиков.

Update отказывается удалять любой previously supported hash из списка. Добавление нового supported hash требует согласованного backend release; одной правки JSON недостаточно. Несовместимое удаление API требует отдельной процедуры миграции клиентов/pending и не выполняется обычным update. Идемпотентный повтор уже отправленного запроса должен оставаться возможным без нового operationId.

HTML frontend использует no-cache/no-store, hashed assets — immutable cache. Перед заменой frontend updater копирует текущие `/srv/assets/*` в внешний `previous_assets` volume; frontend получает его read-only как `/srv/previous-assets`, без дополнительного каталога `assets/`. Текущие файлы имеют приоритет, старые служат fallback только для `/assets/*`; отсутствующие JS/CSS возвращают 404. Автоматическая очистка retained assets в CLI не реализована. Сохраняйте их на весь период поддержки вкладок; удаление требует отдельного решения после завершения соответствующего compatibility window. [Причина сохранения assets при Vite deployments](https://vite.dev/guide/build.html#load-error-handling).

UI проверяет новый release и предлагает обновить страницу после сохранения/разбора незавершённых действий. Принудительного reload нет. Черновик редактора связи может находиться только в памяти страницы; закрытие вкладки не является процедурой обновления.

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
