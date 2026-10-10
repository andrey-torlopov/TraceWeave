# TraceWeave

Репозиторий поставки TraceWeave: Compose, независимый gateway с технической страницей, bootstrap, управление установкой и общие контракты. Backend и frontend остаются отдельными репозиториями. Данные сохраняются в именованных Docker volumes.

**Статус:** Docker-пакет реализован и прошёл локальную контейнерную интеграцию, включая backup/restore и независимые обновления. Образы приложения ещё не опубликованы; доступные GHCR-образы и готовый публичный манифест здесь не заявляются. Локальную сборку выполняет разработчик из трёх согласованных checkout. После публикации совместимого манифеста оператору нужны только этот репозиторий, Docker с Compose и терминал; Python 3 необязателен.

## Локальная сборка и первый запуск

Из корня репозитория поставки, когда соседние `TraceWeaveBackend` и `TraceWeaveFrontend` находятся на согласованных committed Docker-ревизиях и имеют пустой Git status, включая неигнорируемые untracked файлы. Без host Python сначала нужен operator tools image; его можно собрать напрямую через Docker из этого checkout:

```sh
if ! command -v python3 >/dev/null 2>&1; then
  docker build -t traceweave/tools:docker-1 -f tools/Dockerfile .
  export TW_TOOLS_IMAGE=traceweave/tools:docker-1
fi
./traceweave.sh build-source --release-id e8-docker-1 \
  --backend-path ../TraceWeaveBackend \
  --frontend-path ../TraceWeaveFrontend
TW_TOOLS_IMAGE=$(docker image inspect --format '{{.Id}}' traceweave/tools:e8-docker-1)
export TW_TOOLS_IMAGE
printf 'Email первого аккаунта: '
IFS= read -r TW_OWNER_EMAIL
printf 'Имя первого аккаунта: '
IFS= read -r TW_OWNER_NAME
./bootstrap.sh --release releases/e8-docker-1.local.json \
  --origin http://127.0.0.1:8080 \
  --email "$TW_OWNER_EMAIL" --name "$TW_OWNER_NAME"
./traceweave.sh status
```

Выберите ещё не использованный release ID. Если `releases/e8-docker-1.local.json` уже существует, `build-source` откажется от повторной сборки под этим ID; задайте новый ID и используйте его tags и manifest в последующих командах. Все четыре собранных образа, включая `traceweave/tools:e8-docker-1`, сохраняются под отдельными релизными tags. После сборки пример закрепляет operator tools по immutable image ID. Локальные `releases/*.local.json` исключены из Git: их image IDs привязаны к этому Docker-хосту.

Пароль аккаунта вводится скрыто в TTY. Стандартного пароля нет. Bootstrap создаёт приватную конфигурацию и секреты, применяет миграции и открывает gateway после проверки версий, схемы и готовности. Повторный bootstrap не создаёт новый аккаунт и не меняет его пароль. При занятом порте задайте `--port 18080`; итоговый адрес будет `http://127.0.0.1:18080`.

## Повседневные команды

```sh
./traceweave.sh start
./traceweave.sh status
./traceweave.sh logs backend
./traceweave.sh restart
./traceweave.sh backup
./traceweave.sh stop
```

`start` запускает закреплённый релиз. Для смены версии нужна отдельная команда `update --release`, для прерванной операции — `resume` либо явное восстановление. CLI не удаляет volumes. Системный backup содержит данные всех аккаунтов; пользовательский Obsidian ZIP его не заменяет.

## Документация

- [Установка](docs/installation.md): локальный HTTP, серверный HTTPS, SMTP, секреты, Docker-only CLI и сборка из исходников.
- [Управление](docs/operations.md): команды, обслуживание, приватный backup, restore в новые volumes и восстановление после сбоя.
- [Релизы](docs/releases.md): immutable images, манифест, совместимость старых вкладок, обновление и откат.

Текущие наблюдения проверок фиксируются координатором отдельно. Успешная сборка образов не означает полную приёмку приложения, проверку Safari/телефона или проверку публичного HTTPS-хоста.
