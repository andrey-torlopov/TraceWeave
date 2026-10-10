# Обзор архитектуры

*[English](../en/architecture.md)*

## Репозитории и сервисы

Этот репозиторий — оркестратор, а не монорепозиторий. Backend/frontend имеют отдельную Git-историю и lock-файлы; `releases/source-lock.json` закрепляет совместимые source revisions для CI.

| Сервис | Ответственность и данные |
| --- | --- |
| `gateway` | Единый HTTP/HTTPS вход, routing, обслуживание и `/release.json`; сертификаты Caddy в постоянных volumes. |
| `frontend` | Собранный static UI, текущие и сохранённые assets; без originals и DB secrets. |
| `backend` | Swift API, валидация и jobs; private immutable originals/staging/exports. |
| `db` | PostgreSQL 18, UTF-8 и TLS verify-full для имени `db`; приватный volume. |
| `migrate`, `owner`, `ops` | Одноразовые административные сервисы. |

Локально gateway публикуется только на loopback:8080. `compose.server.yaml` публикует серверные 80/443. Порты backend/БД внутренние. Фиксированный адрес gateway — единственный доверенный reverse proxy.

## Состояние оператора

`bootstrap.sh`/`traceweave.sh` вызывают Python controller; если host Python отсутствует, используется tools container. Docker socket получает только операторский tools. Runtime содержит installation config, secrets, выбранный manifest, phases, lock и journal вне контейнеров приложения.

Bootstrap создаёт приватные DB credentials/CA, volumes, выполняет миграции и создаёт первый аккаунт. Повтор запускает установленную версию. Update явно проверяет совместимость, включает maintenance и проверяет readiness. Offline backup объединяет dump БД и оригиналы; restore создаёт новые volumes и сохраняет прежние.

## Требования и контракты

Канонические [ТЗ](../TECHNICAL_SPECIFICATION.md), [решения контрактов](../contract-decisions.md), [ADR](../adr/) и [change requests](../change-requests/) остаются здесь. Языковые руководства не создают переведённые нормативные копии. [CR-E8-001](../change-requests/CR-E8-001-docker-delivery.md) активирует Docker/аккаунты; прежняя отсрочка не блокирует пакет.

---

[К документации](index.md) · [README](../../README-ru.md)
