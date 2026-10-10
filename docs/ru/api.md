# API и контракты

*[English](../en/api.md)*

## Единые источники

- [OpenAPI и схемы](https://github.com/andrey-torlopov/TraceWeave/tree/main/contracts) в `TraceWeave/contracts/`.
- [Техническое задание](https://github.com/andrey-torlopov/TraceWeave/blob/main/docs/TECHNICAL_SPECIFICATION.md) и принятые изменения в `TraceWeave/docs/`.
- [Изменение Docker/аккаунтов](https://github.com/andrey-torlopov/TraceWeave/blob/main/docs/change-requests/CR-E8-001-docker-delivery.md) имеет приоритет над прежними правилами единственного владельца и отложенного Docker.

OpenAPI имеет версию 1.1.0 и записан JSON-синтаксисом, совместимым с YAML. Наличие маршрута в контракте не доказывает его реализацию.

## Протокол запросов

Production UI и `/api/v1` используют один origin. Сессия выдаёт CSRF-token; вход использует email и пароль. Cookie имеют HttpOnly, SameSite=Strict и Secure под HTTPS. Браузер передаёт `X-TraceWeave-Client-Contract`, защищённый запрос также содержит `X-TraceWeave-Account-ID`.

Обычная запись исследования проходит через `POST /api/v1/investigations/{id}/commands` с `operationId`, `clientId`, `baseRevision` и командами. Один принятый пакет увеличивает ревизию один раз. Повтор сохраняет исходные байты и идентификатор; идемпотентность проверяется раньше устаревшей ревизии. Скобки в маршруте обозначают параметры API.

## Ошибки и восстановление

| Ответ | Значение и действие клиента |
| --- | --- |
| `409 revision_conflict` | Сохранить черновик, загрузить серверную версию и явно разобрать различия. |
| `409 idempotency_mismatch` | Один operation ID использован для разных байтов; это не повтор запроса. |
| `409 account_changed` | Остановить очередь прежнего аккаунта. |
| `409 client_upgrade_required` | Сохранить черновики до решения перезагрузить страницу. |
| `413 storage_quota_exceeded` | Исчерпано место аккаунта или установки. |
| `503 service_maintenance` | Сохранить pending, учитывать `Retry-After`, повторять явно. |

Конверт ошибки содержит `code`, `message`, `requestId`, `details`. Полные поля и ограничения задают канонические схемы; документация не создаёт отдельную копию DTO.

---

[К документации](index.md) · [README](../../README-ru.md)
