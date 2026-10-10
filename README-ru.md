<p align="center">
  <img src="docs/banner.svg" alt="TraceWeave Delivery" width="720"/>
</p>

<p align="center"><strong>Docker Compose · Caddy · PostgreSQL 18</strong></p>

# TraceWeave

*Читать на других языках: [English](README.md)*

Репозиторий установки и эксплуатации TraceWeave. Он объединяет отдельные backend и frontend с PostgreSQL и единой публичной точкой входа.

## Ключевые возможности

- **Локальная Docker-установка и настройка HTTPS на сервере.**
- **Интерактивный bootstrap, создание аккаунта и сохранение состояния установки.**
- **Обслуживание, совместимые обновления, offline backup и restore в новые volumes.**
- **Единые OpenAPI, SQL, схемы архива, ТЗ и принятые изменения требований.**

## Быстрый старт

Соберите исходники по [быстрому старту](docs/ru/quick-start.md). Для опубликованной поставки с `releases/stable.json` выполните:

```sh
./bootstrap.sh
```

Bootstrap запросит email, имя и скрытый пароль, затем покажет адрес **http://127.0.0.1:8080**.

**Статус:** публичные контейнерные образы пока не выпущены. Доступна сборка исходников; полная приёмка P0 остаётся отдельной проверкой.

## Документация

- [Установка](docs/ru/installation.md)
- [Быстрый старт](docs/ru/quick-start.md)
- [Архитектура](docs/ru/architecture.md)
- [API и контракты](docs/ru/api.md)
- [Проверки](docs/ru/testing.md)
- [Полная документация](docs/ru/index.md)
- [История изменений](CHANGELOG.md)

## Репозитории проекта

| Репозиторий | Ответственность |
| --- | --- |
| [TraceWeaveBackend](https://github.com/andrey-torlopov/TraceWeaveBackend) | API, доменная валидация, PostgreSQL, оригиналы и задания экспорта |
| [TraceWeaveFrontend](https://github.com/andrey-torlopov/TraceWeaveFrontend) | Браузерный интерфейс, граф, редакторы и восстановление черновиков |
| [TraceWeave](https://github.com/andrey-torlopov/TraceWeave) | Compose, gateway, CLI оператора, единые контракты и ТЗ |

ТЗ и машинные контракты хранятся только в репозитории поставки. Документация компонентов описывает реализацию без отдельной копии требований.
