# ADR-E0-TECHNOLOGY-001 — проверенные технические решения

Статус: решения координатора A, 2026-10-08; общая приёмка E0 — отдельный Artifacts/e0-acceptance.md. Основание: OQ-01…OQ-06, ТЗ §§2,12–16,21–24 и CR-E0-002.

## Совместимый набор и платформа

Swift6.2.4, Vapor4.122.2, Fluent4.13.0, FluentPostgresDriver2.14.0, SQLKit3.36.0, PostgreSQL18.6 и согласованные pg_dump/pg_restore18.6. macOS26.6.2 arm64; deployment target26.0 соответствует установленной native Argon2. Более ранняя ОС, Intel и Linux не заявлены поддержанными. Версии frontend и полные lock-файлы перечислены в docs/toolchain.md.

## Пароли, файлы и архивы

Используется reference C Argon2id через systemLibrary/pkg-config, не собственная криптография. Параметры:64MiB/3/1, соль16байт из криптографического RNG, хеш32байта, параметры в encoded hash. Actor ограничивает очередь, NIOThreadPool снимает блокирующую работу с event loop. Точные параметры проверяются тестом и при verify; смена параметров требует отдельного решения.

ZIPFoundation0.9.20: чтение/запись через chunk callbacks, проверка CRC/SHA, имён, symlink и фактических размеров до использования файлов. Yams6.2.2: корректное YAML-экранирование front matter. Markdown в Swift формируется из структурированного снимка, без HTML-исполнения; browser preview выполняет react-markdown10.1.0+remark-gfm4.0.1.

Bounded format sniffing для production media: читать только ограниченный заголовок и структурные поля формата, сверять фактический контейнер и заявленные ограничения. Полная реализация форматов/preview и негативные медиаfixtures входят в E4; E0 подтверждает streaming primitives и не считается готовой загрузкой материалов. Не читать оригинал целиком в Data и не использовать имя пользователя как storage path.

HTTP streaming: bounded await loop, запись и SHA за один проход на thread pool, autoreleasepool на каждом Foundation chunk. Отдельные GET/HEAD с точными 206/416 и размером; размер файла не определяет объём RAM. Не переносить experimental probe routes в production API.

## Frontend и CSP

Общий keyed draft store — useSyncExternalStore, без дублирования Markdown в карточке/инспекторе. Нативный dialog с проверенной клавиатурной навигацией; отдельная library не нужна. React Flow открытого ядра; библиотечная геометрия ограничена адаптером.

CSP для production build:

```text
default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'
```

Исключение unsafe-inline относится **только к CSS**, поскольку React Flow устанавливает transform/размеры/позиции через style properties. Inline JavaScript и unsafe-eval запрещены. Политика приходит HTTP-заголовком; frame-ancestors в HTML meta не считается защитой. Chromium E0 проверяет реальный build и отсутствие внешних запросов; Safari/Firefox/Edge остаются E8. Разрешения media/blob URL рассматриваются на E4 отдельно.

## Контракты и PostgreSQL

docs/contract-decisions.md фиксирует zIndex, defaults, FTS chunks и long-token storage, cursor, query limits, пул/таймауты, retention технических jobs. Принята отдельная POST search read route для запроса до1MiB UTF8; доменные изменения всё равно только через commands. SQL baseline0001 вводит нормализованные таблицы, composite FK и deferred constraints. Номер production migration0001 закреплён; при переносе требуется проверка точного хеша SQL.

Сохранение — PostgreSQL row-lock, запись ledger до commit в той же transaction, проверка idempotency перед revision. Составные чтения — REPEATABLE READ READ ONLY. Fluent withConnection не равен гарантированному BEGIN: для transaction boundary использовать Database.transaction, что подтверждено реальными concurrency tests.

## Последствия

PostgreSQL и native Argon2 обязательны локально; Docker не обязателен. Синтетические E0-пробы остаются изолированными. Production auth, команды, загрузки, архивы и backup требуют собственных integration tests по мере этапов; технические пробы не закрывают пользовательские AC.
