# Согласованные контракты TraceWeave

Записи ниже версионированы по принятому пакету. Исторические размеры каталогов и номера следующих миграций относятся к дате записи. Актуальное дополнение — CR-E8-001 в конце документа; машинный SSOT находится в `contracts/` репозитория поставки.

Владелец: A-contracts, координатор A. Основание: ТЗ 1.1 §§5, 8–17, 22–29; принятое CR-E0-002. Реализация API начинается после общей приёмки E0. Этот документ уточняет машинные формы, не заменяет инварианты ТЗ.

## Артефакты и формат

- `contracts/openapi.yaml` — OpenAPI 3.1.0, JSON-синтаксис, который является допустимым YAML; редактируется как единый исходный контракт. 35 точных вариантов команд и все 36 HTTP-операций §14.3 и один дополнительный read-only POST поиска (OQ05, решение координатора). Тест сравнивает каталог и маршруты прямо с ТЗ плюс это явно принятое дополнение.
- `contracts/archive-v1.schema.json` — самодостаточный Draft 2020-12. `manifest.json` валидируется против `$defs/Manifest`, `project.json` против `$defs/Project`. Корневая `oneOf` допускает оба файла. Внешних `$ref` нет.
- `contracts/database.sql` — проверенная на PostgreSQL 18 SQL-модель для миграции 0001, не команда обновления существующей пользовательской БД. Координатор переносит её в первую версионированную Fluent-миграцию; принятые production-миграции затем не переписываются.
- `tools/validate_contracts.py` — проверка OpenAPI, всех встроенных примеров, ссылок, закрытых объектов, байтовых лимитов, реальных дат, переносимого проекта и хешей уже изолированного каталога архива. Не распаковщик ZIP, не plugin-runner, не мигратор пользовательских данных.

Все обычные DTO закрыты через `additionalProperties: false`. Исключение — **содержимое** namespaced `extensions`: JSON-значения под явно проверенным ключом наподобие `org.example`, общий лимит 16 KiB. Там не разрешаются выполнения, сетевые обращения или дополнительные права. `plugin` в происхождении оставлен для исторической совместимости, но endpoints исполнения нет, capabilities сообщает `plugins: false`, `pluginProtocolVersion: null`.

## Значения и формы

- UUID — 36 символов, hex в нижнем регистре. UUID v4 используется по умолчанию, но контракт не отвергает другие корректные версии UUID. Числа — только конечные, безопасный диапазон ±9 007 199 254 740 991; ревизии неотрицательны. JSON parser отвергает повторные ключи, NaN/Infinity и переполнение вида `1e999`.
- `zIndex`: целое −1 000 000…1 000 000. Новое положение по умолчанию `zIndex: 0`. Поднятие открытой карточки хранится в workspace. Координаты ±1 000 000 — абсолютные; дельта группы допускает ±2 000 000, но проверяется конечная позиция каждого участника.
- Заголовки/ключи: NFC + trim, затем длина по Unicode scalar values. Теги: NFC + trim, уникальность после этой нормализации, регистр тега сохраняется. `normalizedKey` атрибута — NFC + trim + Unicode case folding. Backend и frontend разделяют fixtures этой нормализации.
- Markdown не обрезается и не нормализуется. `x-maxUtf8Bytes`, `x-maxJsonUtf8Bytes`, `x-realCalendarDate`, `x-normalize`, `x-uniqueNormalized` — обязательные прикладные проверки сверх стандартного Schema; валидатор Python их выполняет. Для `x-normalize: NFC+trim` нормализация входа выполняется **до** стандартных minLength/maxLength: 400 decomposed scalars `e + combining acute` становятся 200 NFC scalars и допустимы. Python handlers minLength/maxLength измеряют это нормализованное представление; схемы сохраняют канонические пределы. Валидатор без preprocessing x-normalize не является полным входным валидатором данного контракта. Markdown и строки без x-normalize измеряются без преобразований. Сгенерированный TypeScript-клиент не заменяет проверку сервером.
- **E1 technical validation clarification, принято координатором:** U+0000 исключён из сохраняемых текстов, строковых значений и ключей вложенных `extensions`: PostgreSQL `text`/`jsonb` не представляют этот символ. В API и archive-v1 ограничения синхронны и выражены стандартным `pattern`; вложенные extension-ключи проверяет `propertyNames`. Сервер возвращает 422 `validation_failed`, не удаляя символ и не записывая часть пакета. Это явная валидация ограничения принятого хранилища, без замены данных. Пароль не относится к сохраняемому открытому тексту и может содержать U+0000 в пределах scalar/UTF-8 лимитов; Argon2 получает длину байтов. Бинарные оригиналы также исключены из текстового ограничения. NUL недопустим и в строковых параметрах поиска, передаваемых PostgreSQL. Отрицательные contract/HTTP regressions и положительный password regression фиксируют границу.
- `NodeInput` требует `id`, `typeId`, `title`: отсутствие остальных полей означает `subtitle: null`, `bodyMarkdown: ""`, `assessment: unreviewed`, `confidence: null`, `tags: []`, `extensions: {}`, `attributes: []`. Сервер задаёт `origin: {kind: manual}` и даты. Это позволяет создать узел с одним пользовательским заголовком без фиктивных дат. `GroupNodeInput` требует `id`, `title`; `group`-тип разрешает сам сервер.
- В полном DTO опциональные значения передаются явно как `null`; коллекции — как `[]`. Patch требует хотя бы одно разрешённое поле: отсутствие = не менять, `null` = очистить только nullable-поле. Служебные ID/даты, исходные байты, пути и хеши через patch не меняются.
- `CalendarDate` проверяет реальный календарь, год 0001…9999. `datetime`-атрибут принимает RFC3339 со смещением; серверные timestamps сериализуются UTC с `Z`.
- Иконки — закрытый набор `IconKey` в OpenAPI и capabilities. Новая разрешённая иконка добавляется согласованным изменением контракта и каталога UI, не принимает произвольный SVG/URL.
- `GraphNode` и `GraphRelation` содержат краткие данные без Markdown тела/заметки, provenance и originals. Редактор читает полный документ/связь отдельным GET. Библиотечные parentId, DOM-размеры и агрегированные рёбра отсутствуют в серверной модели.

## Команды, ошибки и чтение

Сервер блокирует строку исследования, проверяет принятую идемпотентность **до** `baseRevision`, сравнивает SHA-256 и исходные UTF-8 байты запроса, затем валидирует итоговое состояние. Один успешный пакет — одна новая ревизия. `replayed` меняется только в ответе повтора; остальные поля взяты из сохранённого результата. История доменных ключей хранится весь срок жизни исследования.

Неизвестный `kind` → 400 `invalid_command`; ошибка формы/полей → 422 `validation_failed` с JSON Pointer; конфликт → 409 с конкретным кодом. Ошибки — закрытая `oneOf`, а не произвольный `details`. Нет stack trace, SQL, содержимого документов и путей ОС. `Retry-After` обязателен у 429. Ошибки архивных данных содержат безопасный pointer и описание.

`report.snapshotCreate`, undo и redo — единственные команды своего пакета; это выражено в Schema. `elements.trash` не допускает пустые оба массива. Схема не заменяет сервисные проверки: принадлежность и активность ссылок; системную семантику типов; канонизацию концов; полные множества перемещения; строгий restore; вершину undo/redo; итоговый состав отчёта. Эти проверки обязательны в production service и тестах E2–E7.

`GET reports/{reportId}` возвращает определение, вычисленный `preview` на согласованной ревизии и список снимков — отдельный обходящий ревизию mutation endpoint не нужен. Список отчётов возвращает определения вместе с summary сохранённых снимков. Снимок содержит собственный полный типизированный контент; Markdown производится из него. `sourceRevision` равна `baseRevision` до создания снимка.

GET графа, документа, связи, материала, preview и страниц: короткая `REPEATABLE READ READ ONLY` транзакция, один согласованный revision. GET исследования поддерживает `ETag: "<UUID>:<revision>"` и 304. Формирование содержимого отчёта и фиксация export-снимка происходят до фоновой упаковки, с pin originals.

## Сортировка и cursor

Размер страницы 50, максимум 200. Списки исследований/материалов/отчётов/корзины сортируются по UUID по возрастанию. Поиск — `(objectKind COLLATE "C", objectId)` по возрастанию: asset, node, relation. Это устойчивый порядок, а не обещание ранжирования релевантности. История операций сортируется по `revisionAfter DESC`, затем ID.

Cursor — base64url без padding от канонического UTF-8 JSON `CursorPayload`: версия 1, scope ID, ревизия, resource, SHA-256 канонического фильтра, последний тип/UUID и nullable `lastOperationRevision`. В digest входят строка запроса, нормализованные отсортированные фильтры и сортировка. Сервер проверяет весь shape, допустимый resource, scope, digest и сортировочный ключ; cursor не даёт права доступа. Невалидный cursor → 400 `invalid_cursor`, изменилась ревизия → 409 `cursor_stale`. Содержимое cursor можно прочитать: секретов там нет.

Для списка исследований `revision` означает `owners.collection_revision`. Создание, изменение названия/описания, archive/unarchive и commit импорта увеличивают её в той же транзакции. Остальные доменные изменения увеличивают только revision исследования. Строка owner при этих операциях сериализует изменение collection revision; CLI соблюдает тот же порядок блокировок. Bulk-maintenance получает отдельную эксклюзивную maintenance-блокировку до любых строковых блокировок.

Координаторское уточнение OQ05: GET search принимает `q` до 4 096 scalars; дополнительный read-only `POST /api/v1/investigations/{id}/search` принимает `SearchRequest` JSON с `q` до 1 MiB UTF-8. Это делает доступным точный поиск длинной лексемы, а не только её индексацию. Результат — тот же `SearchPage`, фильтры/cursor/ownership совпадают, ревизия не меняется. POST требует Origin+CSRF. Клиент использует POST также при URI свыше 8 KiB; серверный предел заголовков/URI 64 KiB не требует URL длиной в мегабайты. Не добавляется новый путь доменной записи.

Обычная строка поиска — слова AND; значения одного фильтра OR, разные фильтры AND. Тип/тег/assessment/наличие материалов применяются к узлам; для объектов без соответствующего доменного поля фильтр исключает объект. Фильтр relationTypes включает связи указанного типа и узлы с активной инцидентной связью этого типа; материалы этим фильтром исключаются. Пустой запрос возвращает отфильтрованный список. Возвращаемый snippet — обычный текст без HTML, до 500 scalars.

## Полнотекстовый поиск без усечения

SQL содержит реальные FK-объекты `search_objects`, фрагменты `search_fragments` с generated `tsvector` и GIN, точные телефон/домен `search_exact_values`, длинные токены `search_long_tokens`. Они обновляются в одной транзакции с доменом.

1. До `ts_parse('default', ...)` привести текст и запрос к NFC и Unicode case folding. Swift-проба применяет `precomposedStringWithCanonicalMapping.folding(options: .caseInsensitive, locale: Locale(identifier: "en_US_POSIX"))`. Не полагаться на locale кластера: реальная проба на данном PostgreSQL обнаружила несовпадение «Привет»/«ПРИВЕТ» при прямом `simple`.
2. Парсер PostgreSQL определяет полные токены. Короткие токены пакуются целиком во фрагменты нормализованного текста до 16 KiB; разрезать слово на границе фрагмента нельзя. `to_tsvector('pg_catalog.simple', ...)` задан явно.
3. Токены от 1 800 UTF-8 bytes сохраняются отдельными полными `normalized_token` и SHA-256, не превращаются в обычный текстовый marker. Поиск проверяет hash **и полное равенство строки**, поэтому введённый пользователем текст `twlong<hash>` не выдаётся за совпавший длинный токен.
4. Для каждого слова запроса требуется совпадение хотя бы в одном фрагменте/long-token row того же объекта: AND объединяется **на уровне объекта**, а не одного фрагмента. Никакие части допустимого документа не отбрасываются; актуальный предел — 5 MiB по CR-E2-002. Поля/источники также индексируются полностью.
5. Телефон/домен: отдельные нормализованные значения и поиск точного фрагмента. Экранировать `%`, `_`, escape перед `LIKE`, помимо параметризации. Телефон нормализуется до цифр; домен — NFC + case folding, без сетевого DNS-запроса. Специальный режим поиска фрагментов сохраняет оригинальное отображение.

Реальный SQL-тест подтверждает GIN, кириллицу/латиницу и AND между разными фрагментами; Swift-проба координатора дополнительно подтверждает 1 MiB и длинный токен. Эта историческая E0-проба не подтверждает новый предел 5 MiB; на E6 требуется повторная проверка максимального документа. Это не замена Target-проверки E6. Лимиты PostgreSQL требуют такого разбиения: [официальные ограничения FTS](https://www.postgresql.org/docs/18/textsearch-limitations.html).

## PostgreSQL и технические процессы

- Пул: максимум 8 соединений на один backend-процесс, minimum 1; connect timeout 5 s, acquire timeout 5 s, `lock_timeout` 3 s, `statement_timeout` 15 s, `idle_in_transaction_session_timeout` 15 s. Значения конфигурируются без изменения модели; bounded background workers — 2 export/import, 4 uploads. Сжатие, файловый I/O и password hashing не занимают event loop.
- Длинные файлы передаются потоково вне write-транзакции. Upload lifetime 24 h; завершённый ticket регистрируется только один раз. Registered ticket/связь asset сохраняются весь срок жизни материала. Повтор completed PUT возвращает 409 `upload_completed`; повтор interrupted PUT начинает запись заново в новый partial.
- Готовый export-файл живёт 24 h. Удаление его файла не удаляет job result, сохранённый snapshot или pins снимка. Истёкший download → 404; новую сборку клиент создаёт с новым ключом.
- Технические idempotency keys upload/export/import хранятся как минимум 7 суток после terminal-состояния и не удаляются во время queued/running. При cleanup данные задач помечаются terminal/expired, затем ключ может быть удалён только по этой политике. Ключи создания исследования и commit импорта хранятся весь срок жизни владельца; повтор commit не создаёт второе исследование. `import.validate` также хранит ответ в collection ledger.
- Импорт до upload: `state: queued`, `phase: awaiting_upload`. После upload: queued/uploaded; после успешной проверки: succeeded/validated с plan. Только validated допускает commit. После commit: succeeded/committed с ID нового исследования. `state` и `phase` — техническая информация; изменения процента не меняют доменную ревизию.
- Первичная приёмка только macOS, Linux и контейнеризация отложены CR-E0-002.

## Целостность и переносимый архив

SQL использует отдельные таблицы, FK с `(investigation_id, id)`, CHECK, частичный unique активных отношений, уникальность членства, пары вложения и primary attachment. Deferred triggers проверяют конечное состояние пакета: активная связь не ведёт к удалённому концу; группа активна и не вложена; asset hash/size совпадают с blob; активное вложение не ссылается на материал в корзине. UPDATE blob identity/bytes metadata, snapshot content и operation history запрещён. Удаление используемого blob отклоняется FK, включая snapshot/export pins.

Snapshot content и forward/reverse effects — уместные структурированные JSONB, а не запись всего живого графа. Их закрытую форму проверяет общая contract/domain библиотека перед записью; PostgreSQL отдельно проверяет базовый shape, неизменяемость и FK. Внутри SQL нет JSON Schema runtime-extension, которую пришлось бы устанавливать на пользовательский кластер.

`project.json` не содержит owner, sessions, csrf, путь storage, незавершённые процессы, idempotency и browser state. Отдельные коллекции включают корзину, исторические снимки и переносимые deletion batches. Blob entry именуется только `blobs/<sha256>`; manifest содержит project.json и все фактические blobs, без собственного рекурсивного хеша.

Исторические node/relation IDs проверяются внутри snapshot, а не по сегодняшним узлам. Содержимое исторического документа может отличаться от текущего или больше не иметь живого документа. Материалы снимка имеют отдельные pins на существующие immutable blobs. `sourceStatus: outside_scope` не содержит `sourceTitle` и не подтягивает документ источника.

Импорт назначает новую последовательность ревизий и новую таблицу замены всех **внутренних** UUID, включая исторические объекты. Явные `sourceInvestigationId/sourceObjectId` в provenance сохраняют идентичность внешнего исходника и не превращаются в FK новой установки. Совпадающие внутренние ID в разных версиях одного документа получают одну согласованную замену, но исторические поля остаются замороженными.

Проверка каталога валидирует структуру, все ссылки, размеры и потоковые SHA-256, запрещает symlink/unlisted entries. Безопасный ZIP-reader, суммарные streaming-лимиты, real MIME и атомарный import commit реализуются и тестируются на E7; этот E0-валидатор не выдаётся за полный production-importer.

## Проверка и границы доказательства

Команды с загруженным защищённым `var/e0/test.env`:

```bash
.venv/bin/python tools/validate_contracts.py --self-test
.venv/bin/python -m unittest discover -s tests/contracts -v
```

Тесты PostgreSQL требуют именно `RG_CONTRACT_DATABASE_URL`, имя БД `traceweave_test_*`, роль `traceweave_test`. Production-переменная не используется как fallback. Схема и synthetic rows создаются внутри транзакции и откатываются, никаких DROP пользовательских таблиц/данных нет. Без DSN SQL-проверки честно помечаются `not_run`, и E0 приёмку это не закрывает.

Тесты связывают форму контрактов с AC-02/03/10/11/15/16/24/26/29/33/35–38/41–44/45–51/53/54/57/70; сами AC приложения ещё не считаются passed. E0 не доказывает Swift DTO, полный HTTP service, целевую производительность, потоковый ZIP-import, macOS Safari или Linux. Эти проверки принадлежат последующим этапам.

Нормативные машинные форматы проверены по [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0.html) и [JSON Schema Validation 2020-12](https://json-schema.org/draft/2020-12/json-schema-validation).

## Протокол E0-003, 2026-10-08

Фактически выполнены обе команды выше на macOS с настоящим выделенным PostgreSQL. Последний `tools/validate_contracts.py --self-test`: **94 теста прошли**, без skips; 29 проверок SQL-модели и 65 проверок схем/API/архива. Машинный вывод: `{"archiveDefinitions":49,"commandKinds":35,"examples":202,"operations":37,"schemas":203}`.

Выявлены и исправлены: PostgreSQL locale не обеспечивал ожидаемую кириллическую нормализацию; SQL calendar validator принимал часть JSON-null/нестроковых полей из-за трёхзначной логики; API GET не обеспечивал передачу очень длинного точного поискового терма. Добавлены отрицательные regression-проверки; ожидания исходных требований не ослаблялись. SQL provenance теперь проверяет допустимые ключи/формы и не возвращает `NULL` для неизвестного варианта.

Ограничение инструмента: Python 3.9 из текущего окружения при импорте OpenAPI validator печатает `urllib3 NotOpenSSLWarning` о LibreSSL; эти проверки не выполняют HTTPS-запросов, schema refs полностью локальные. Warning не скрывается. Production Python runtime приложению не требуется.

Изменены только назначенные файлы: три файла `contracts/`, `tools/validate_contracts.py`, `tests/contracts/test_contracts.py`, `tests/contracts/test_database.py`, этот документ. Новые проверочные зависимости установлены координатором в project `.venv`: jsonschema 4.25.1, openapi-spec-validator 0.7.2, psycopg 3.2.13; версии окружающего toolchain фиксирует координатор. Пользовательские БД, исходники frontend/backend, глобальные настройки и чужие файлы не изменены.

TRACE:
- Skill: implementation-from-plan.
- Task folder: отдельной task-lab-папки нет; пакет `docs/tasks/E0-003.md`.
- References read: нормативное ТЗ §§1–5, 8–18, 22–29; CR-E0-002; E0-003; delivery-pipeline.md; официальные OpenAPI/JSON Schema/PostgreSQL FTS материалы.
- Knowledge read: general/_rules.md, python/_rules.md.
- Patterns/policies applied: closed discriminated DTO, relational ownership constraints, immutable snapshots/originals, exact request replay, repeatable reads, bounded local tests, no plugin runtime.
- Verification: 94 passed; PostgreSQL setup/data транзакционно откатились; все HTTP paths/kinds сверены с ТЗ и принятым уточнением OQ05.
- Residual risk: не production-реализация; перечисленные в документе domain-service, streaming archive и браузерные проверки остаются E1–E8; общий gate E0 принимает координатор после остальных проб.

## CR-E4-001 / migration0004 — 2026-10-09

По запросу владельца оригиналы распределяются в blobs/images, blobs/audio, blobs/video. Migration0004 сохраняет прежний storage key и добавляет nullable проверенные MIME/kind/dimensions Blob. API storage key не раскрывается; существующие UploadTicket/AssetDocument достаточны. SQL0001–0003 неизменны. Следующий свободный номер0005. Эффективная contracts/database.sql синхронизирована с0004.

Для прежнего Blob с четырьмя NULL verified-полями разрешено только однократное заполнение после проверки существующего оригинала/размера/SHA. Затем MIME/kind/dimensions неизменяемы, как и storage key/hash/size. Migration0004 и её backend resource имеют SHA-256 `4b5d9cb32c93361a11e61b27f2b6b77c3e6835d87f94530befcdd54e1eb51f88`. Миграции fresh/upgrades и контрактный SQL проверены. Эксклюзивная lease сервера использует ключ8476007;8476004–6 уже заняты maintenance/migration/owner-create. OpenAPI и lock-файлы не менялись. HTTP upload/commands/content, crash recovery и перенос трёх каталогов в новую БД подтверждены в `Artifacts/media-attachments.md`. Полный E7 backup остаётся отдельно.

## CR-E7-001 / migration0005 — Obsidian ZIP, 2026-10-09

`obsidian_vault` — отдельный вид `ExportCreate`/`ExportJob`, использующий существующие POST exports, GET status и GET download. Тело создания содержит ровно `idempotencyKey`, `kind`, `sourceRevision`. Контракт `project_archive` не меняется: перенос в Obsidian не является полным backup/import TraceWeave.

Migration0005 расширяет два CHECK в `export_jobs`, сохраняя ранее допустимые строки. Её SQL и backend resource имеют SHA-256 `19b968caedbe37512cdd5856c345e937894125f7b6d34fea103223179909262b`.

Согласованный снимок фиксирует все активные узлы, связи с активными концами, атрибуты, группы, координаты, источники и необходимые оригиналы. Исследование может быть архивным. Техническое задание не меняет доменную ревизию. Сохранённый снимок и blob pins позволяют скачивать неизменный результат после последующих правок.

Уточнение политики повторов для нового вида: точный повтор POST проверяет исходные байты до проверки текущей ревизии. Для готового, но истёкшего ZIP он явно ставит повторную сборку **сохранённого снимка** в очередь. Новый ключ фиксирует текущую ревизию. Готовый файл доступен 24 часа; потерянный ответ POST не требует нового ключа. При рестарте queued продолжается, running получает явную ошибку прерванной сборки.

ZIP содержит README.md, Documents/*.md, Relations/*.md, Attachments/{Images,Audio,Video,Files} по наличию материалов, Attachments/README.md и metadata/{snapshot,files}.json. Имена безопасны и включают UUID. Направление связи сохраняется явно: родители — источники входящих, дети — цели исходящих; ненаправленные связи перечисляются отдельно. Читаемые Markdown-ссылки преобразуются через AST, кодовые примеры не переписываются. В генерируемых заметках HTML экранирован, внешние изображения становятся ссылками; файлы оригиналов побайтно неизменны.

Один worker собирает ZIP вне event loop, максимум восемь queued/running заданий; общий предел захватываемых метаданных — 64 MiB. Превышение завершается явной ошибкой без усечения состава. Каждый оригинал читается порциями по 64 KiB и проверяется по размеру/SHA-256; неполный результат недоступен для скачивания. Пользовательские имена файлов не используются как серверные пути. Credentials, owner/session и storage keys исключены из публичного снимка.

Pinned зависимости: swift-markdown 0.7.3, swift-cmark 0.9.0 (транзитивная); остальные pins сохранены. Новые лицензии внесены в THIRD_PARTY_NOTICES.md. Следующий свободный номер миграции — 0006. Протокол выполнения и ограничения проверки: Artifacts/obsidian-export.md.

## CR-E8-001 / migration0006 — Docker и аккаунты, 2026-10-10

Принятие: [CR-E8-001](change-requests/CR-E8-001-docker-delivery.md), прямой запрос владельца реализовать Docker-план. Общие контракты, нормативное ТЗ, ADR и CR перенесены в отдельный delivery repository `SRC/TraceWeave`; workspace пути являются совместимыми symlink и не содержат независимых копий. Backend/frontend остаются отдельными репозиториями.

OpenAPI `info.version=1.1.0`, SHA-256 `bd1c6ed182bbd63e91401bc7018593a92b76682c62c498a35a928e7dd26f832c`. Добавлены account config/register/verify/resend/reset, свой profile и password rotation, gateway `/release.json`. Owner содержит nullable `email` и `emailVerified`; исторический nullable email не разрешает вход на обновлённый сервер без операторского `account attach-email`. UUID, прежний Argon2 hash и доменные данные сохраняются; первому HTTP посетителю аккаунт не передаётся.

Login требует email и password. Email: ASCII, trim/lowercase, без удаления `+tag` или точек. Пароль: минимум три Unicode scalar values, максимум 1024 UTF-8 байта; без trim/NFC и без изменения исходных байтов. CLI читает пароль и его точное подтверждение скрыто из TTY. Первый локальный аккаунт оператор создаёт подтверждённым; HTTPS аккаунт подтверждается письмом. Публичная регистрация включается явно только с HTTPS/SMTP. Argon2id и ограниченная очередь хеширования сохранены.

Письма используют проверенный TLS, SMTP credential file и одноразовые 32-byte tokens; в БД хранится только SHA-256. Для публичных register/resend/reset ответы существующему/неизвестному/ineligible email имеют одну форму 202, а общая ошибка SMTP — 503 `mail_unavailable`. Внешне одинаковые decoy письма не дают действующего токена; реальный токен истекает, повтор запрещён. Profile/password/reset не меняют чужой аккаунт; password rotation отзывает прочие сессии, reset — все. Origin/CSRF, достоверный proxy address и лимиты по email/адресу применяются отдельно.

Migration0006 append-only, SHA-256 `46f035d60a0a3abd06ca418fb12ca215ffdec4355ae40330b59ee44c28043889`: убран singleton, добавлены email verification, unique canonical email, token/rate-limit tables, прежние сессии отозваны. SQL0001–0005 не переписаны. Эффективная `database.sql` соответствует0001–0006; следующий номер0007.

Контейнерный клиент передаёт `X-TraceWeave-Client-Contract`, а защищённый запрос также `X-TraceWeave-Account-ID`. Сервер проверяет client/account до записи: неизвестный hash →409 `client_upgrade_required`, смена аккаунта →409 `account_changed`. Pending сохраняет исходные байты, operationId и аккаунт; временный503 не создаёт новый operationId. Обычный update не удаляет previously supported hash. Client hashes включаются в runtime только из проверенного manifest.

Gateway maintenance: HTML и API503, `Cache-Control: no-store`, `Retry-After: 15`; API ошибка `service_maintenance`, UUID requestId, `details: null`. `/release.json` доступен в maintenance и содержит общий releaseId, frontendVersion, contractHash, supported hashes. Baked frontendReleaseId допускает новый общий releaseId при независимом backend update; manifest сравнивается с baked component metadata и фактическими migration checksums до открытия gateway.

Ресурсы нескольких аккаунтов: uploads receiving максимум2 на аккаунт/4 на установку; активные export jobs максимум4/8. Хранилище:10GiB на аккаунт/100GiB на установку, включая атомарные ожидаемые reservations; завершённый оригинал учитывается один раз. Общие транзакционные advisory locks8476010 (exports) и8476011 (uploads) предшествуют owner/investigation locks. Полное переполнение →413 `storage_quota_exceeded` с закрытыми scope/limitBytes/actualBytes. Replay проверяется раньше ёмкости очереди.

Backup — операторский offline dump плюс все immutable originals и manifest хешей, выбранной пары images и миграций. Restore — новая БД/новый files volume, проверка ссылок/хешей, отзыв sessions/tokens и явная ошибка transient uploads/exports/imports. Старые volumes и safety backup сохраняются. Проверки и ограничения текущего пакета: workspace `Artifacts/docker-implementation.md`; инструкции поставки: [installation](installation.md), [operations](operations.md), [releases](releases.md). Полный P0 и прежний Q-04 не принимаются этим изменением.
