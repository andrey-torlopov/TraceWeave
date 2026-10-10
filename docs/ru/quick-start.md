# Быстрый старт

*[English](../en/quick-start.md)*

## Собрать локальную установку

Нужны Docker Engine/Desktop, Compose и TTY. Расположите backend/frontend рядом с checkout поставки:

```sh
git clone https://github.com/andrey-torlopov/TraceWeave.git
git clone https://github.com/andrey-torlopov/TraceWeaveBackend.git
git clone https://github.com/andrey-torlopov/TraceWeaveFrontend.git
cd TraceWeave
printf 'Новый локальный release ID: '
IFS= read -r TW_RELEASE_ID
./traceweave.sh build-source --release-id "$TW_RELEASE_ID" \
  --backend-path ../TraceWeaveBackend \
  --frontend-path ../TraceWeaveFrontend
./bootstrap.sh --release "releases/$TW_RELEASE_ID.local.json"
./traceweave.sh status
```

Клонирование выполняется из каталога для трёх checkout. Если они уже существуют, начните с `cd TraceWeave` из родительского каталога. Backend/frontend должны быть чистыми и закоммиченными. Новый ID состоит из букв, цифр, точек, подчёркиваний и дефисов; builder не перезаписывает существующий локальный manifest.

Bootstrap запросит email, имя и скрытый пароль аккаунта. Откройте **http://127.0.0.1:8080** и войдите. Создайте исследование и два документа, добавьте связь, перезагрузите страницу для чтения подтверждённых данных. Локальному HTTP не нужны SMTP и домен.

## Повторные запуски

```sh
./traceweave.sh stop
./bootstrap.sh
```

Остановка сохраняет volumes и установленную версию. Используйте прежний checkout/runtime. Локальный manifest фиксирует образы этого Docker-хоста и не позволяет скачать приложение на другой хост.

## Опубликованная поставка

Публичные images пока не выпущены. Когда проверенный пакет содержит `releases/stable.json` и `releases/tools-image.txt`, новая установка запускается прямо через `./bootstrap.sh`. См. [локальный запуск](local-use.md), [установку](installation.md), [сервер](server-deployment.md).

---

[К документации](index.md) · [README](../../README-ru.md)
