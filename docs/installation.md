# Установка TraceWeave

Это подробная справка для разработчика и администратора. Для начала используйте [короткий локальный запуск](local-use.md) или [установку на VPS с доменом](server-deployment.md).

## Состав и предварительные условия

Постоянно работают четыре сервиса: PostgreSQL `db`, Swift `backend`, статический `frontend` и Caddy `gateway`. Одноразовые `migrate`, `owner` и `ops` запускаются только управляющей командой. Наружу опубликован gateway; порт backend и PostgreSQL на хост не публикуются. PostgreSQL использует TLS `verify-full` с сертификатом для имени `db`. Frontend и gateway не получают originals volume.

Нужен работающий Docker Engine/Desktop с Docker Compose, Linux containers и терминал с TTY. При подготовке пакета использовались Docker Engine 29.8.2 и Compose 5.5.1; файл серверной конфигурации использует Compose `!override`. Проверить установленную среду:

```sh
docker info --format '{{.ServerVersion}}'
docker compose version
```

Образы пока локальные и не опубликованы. До публикации нужен [разработческий путь сборки](#сборка-разработчиком). После публикации нужно получить репозиторий поставки и проверенный манифест выбранного релиза. Манифест должен содержать доступные для нужной архитектуры immutable `repository@sha256:...`; локальный `sha256:...` является image ID конкретного Docker-хоста и не скачивается из реестра. Наличие публичного Git-репозитория само по себе не делает images публичными.

## CLI с Python и без Python

`traceweave.sh` использует установленный `python3`. При его отсутствии wrapper запускает Python в короткоживущем tools-контейнере. В Docker-only режиме нужен локальный Unix Docker socket; удалённый TCP context не поддерживается. Wrapper монтирует checkout в тот же абсолютный путь и Docker socket в operator-контейнер. Этот контейнер имеет полномочия оператора Docker и получает доступ к хосту через daemon; socket не передаётся backend, frontend или gateway.

Для первого Docker-only вызова operator tools image должен быть доступен ещё до запуска Python-контроллера и сборки остальных образов. В текущей локальной поставке подготовьте его напрямую из репозитория поставки:

```sh
docker build -t traceweave/tools:docker-1 -f tools/Dockerfile .
export TW_TOOLS_IMAGE=traceweave/tools:docker-1
./traceweave.sh --help
```

Этот шаг требует Docker, но не host Python, Swift или Node. Wrapper также умеет собрать отсутствующий default tag `traceweave/tools:docker-1`; это отдельная начальная сборка tools image из checkout, а не результат ещё не выполненного `build-source`. Первоначальный operator-образ существует отдельно от tools-образа конкретного релиза: `build-source --release-id e8-docker-1` сохраняет последний под tag `traceweave/tools:e8-docker-1` и записывает его immutable ID в manifest. После успешной сборки используйте tools image выбранного релиза, как показано ниже.

После публикации выберите точный tools `repository@sha256:...` из проверенного manifest, заранее скачайте его через `docker pull` и задайте `TW_TOOLS_IMAGE`. Wrapper может скачать отсутствующий registry digest, но доступность и права проверяют до bootstrap. Приватный registry требует настроенной аутентификации; публичные GHCR-образы этого пакета сейчас не опубликованы. Не подменяйте digest предполагаемым tag и не передавайте непроверенный образ с полномочиями оператора Docker. Другие отсутствующие произвольные tags wrapper отклоняет. Shell остаётся интерактивным: пароли и подтверждения требуют TTY.

Для пользовательской поставки без ручных действий разработчик включает `releases/tools-image.txt` с одной строкой — опубликованным digest tools из `releases/stable.json`. При отсутствии host Python wrapper автоматически читает этот файл и скачивает tools image; `TW_TOOLS_IMAGE` вручную не нужен. Если файл отсутствует, остаётся прежний разработческий fallback со сборкой tools image из checkout. Публичный пакет со сценарием «только скачивание» должен содержать оба release-файла и пройти проверку без host Python.

CLI сам формирует Compose environment из `runtime/installation.json` и `runtime/release.json`. Копировать `.env` или запускать сырой `docker compose up` вместо bootstrap не требуется. По умолчанию состояние хранится в `runtime/` этого checkout. Другой приватный каталог можно выбрать через абсолютный `TW_RUNTIME_DIR`; все последующие команды должны использовать тот же каталог. Docker-only wrapper передаёт этот путь и монтирует его в operator-контейнер по тому же абсолютному адресу. Файлы после административных операций принадлежат UID/GID пользователя хоста.

Для `build-source` wrapper добавляет только нужные backend/frontend checkout как read-only mounts по тем же абсолютным путям. Стандартный Git worktree поддерживается: отдельно подключается read-only его проверенный общий `.git` каталог с objects/refs и worktree metadata. Нестандартный Git directory отклоняется с явным сообщением; для него используйте host Python. Если явный `--release` указывает на файл вне checkout/runtime, подключается read-only только этот manifest. Относительные пути разрешаются относительно каталога вызова, исходные аргументы сохраняются. Весь родительский каталог или файловая система хоста не монтируются. Пути bind mounts с запятыми отклоняются.

## Первый локальный запуск

Следующий сценарий рассчитан на уже собранный локальный релиз `e8-docker-1`:

```sh
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

Для опубликованной поставки default — `releases/stable.json`, входящий в проверенный пакет релиза. Его пока нет: публичный релиз не выпущен. Для локального или другого конкретного релиза передайте существующий файл в `--release`. CLI не выбирает случайный локальный manifest и не меняет установленный релиз при повторном bootstrap. Email и имя первого аккаунта можно передать флагами либо ввести по приглашению bootstrap; пароль всегда вводится скрыто.

Локальный HTTP допускается только с hostname `127.0.0.1`, gateway привязан к loopback. `--port` меняет локальный порт и итоговый origin; например, `--port 18080` даёт `http://127.0.0.1:18080`. Порт проверяется до записи новой installation config; в Docker-only режиме проверка использует публикацию порта на реальном Docker-хосте. `http://localhost` и HTTP на внешнем интерфейсе не принимаются. Уже сохранённый origin является свойством установки: другую установку создают отдельно, а не меняют адрес её существующей конфигурации вручную.

Bootstrap генерирует случайные пароли ролей PostgreSQL, CA и сертификат, создаёт внешние volumes, выполняет миграции и предлагает скрытый ввод пароля первого аккаунта. Минимум пароля — 3 Unicode scalar, максимум — 1024 байта UTF-8; строка сохраняется точно, без trim или нормализации. Пароль не передают в аргументах, environment или shell history. Email используется при входе, имя — в профиле.

Новая установка получает внутреннюю application-сеть `172.28.X.0/24` с закреплённым gateway `172.28.X.2`. Динамические адреса backend/frontend выдаются только из `172.28.X.128/25`, поэтому они не могут занять доверенный адрес gateway. Выбранные subnet, адрес gateway и динамический диапазон сохраняются в installation state. При start/resume контроллер сначала запускает и проверяет `db` и `gateway`, затем приложения; такой порядок также защищает адрес gateway в старых установках без сохранённого динамического диапазона.

Повторный bootstrap сохраняет секреты, CA, данные и аккаунт. Для старого владельца без email операторская команда `bootstrap --email` присоединяет адрес; UUID и прежний password hash остаются прежними. Это административная операция оператора Docker, не публичное присвоение аккаунта из браузера. Если первый запуск прервался, оставьте gateway в обслуживании и выполните `resume` с теми же email/name либо повторите bootstrap по сообщению CLI.

## HTTPS на сервере

Оператор заранее настраивает DNS своего домена на хост, доступность стандартных TCP-портов 80 и 443 и постоянное место для Docker volumes. Серверный origin — `https://` с реальным hostname без пути, credentials, query или fragment и без нестандартного HTTPS-порта. Override публикует gateway как `0.0.0.0:80 → 8080` и `0.0.0.0:443 → 8443`; Caddy сохраняет сертификаты в отдельных volumes. `--port` не заменяет серверные 80/443.

Первому HTTPS-аккаунту требуется подтверждение email, поэтому SMTP настраивается уже при первом bootstrap. Выбор действительных данных не требует редактирования конфигурационного файла:

```sh
printf 'Полный HTTPS origin вашего домена: '
IFS= read -r TW_PUBLIC_ORIGIN
printf 'Путь к проверенному release manifest: '
IFS= read -r TW_RELEASE_MANIFEST
printf 'Email первого аккаунта: '
IFS= read -r TW_OWNER_EMAIL
printf 'Имя первого аккаунта: '
IFS= read -r TW_OWNER_NAME
printf 'SMTP URL без credentials, smtp:// или smtps://, с портом: '
IFS= read -r TW_SMTP_URL
printf 'SMTP login: '
IFS= read -r TW_SMTP_USER
printf 'Email отправителя: '
IFS= read -r TW_SMTP_FROM
./bootstrap.sh --release "$TW_RELEASE_MANIFEST" \
  --origin "$TW_PUBLIC_ORIGIN" \
  --email "$TW_OWNER_EMAIL" --name "$TW_OWNER_NAME" \
  --smtp-url "$TW_SMTP_URL" --smtp-user "$TW_SMTP_USER" \
  --smtp-from "$TW_SMTP_FROM"
```

Пароли SMTP и аккаунта читаются отдельно скрытым вводом. После открытия gateway первый серверный аккаунт подтверждает адрес по ссылке из письма перед входом. Публичная регистрация по умолчанию отключена. Встроенного почтового сервера нет: укажите доступный SMTP-сервис. Для новой установки SMTP-флаги передают bootstrap; для работающей установки используется `configure-mail`:

```sh
printf 'SMTP URL без credentials, smtp:// или smtps://, с портом: '
IFS= read -r TW_SMTP_URL
printf 'SMTP login: '
IFS= read -r TW_SMTP_USER
printf 'Email отправителя: '
IFS= read -r TW_SMTP_FROM
./traceweave.sh configure-mail --smtp-url "$TW_SMTP_URL" \
  --smtp-user "$TW_SMTP_USER" --smtp-from "$TW_SMTP_FROM" \
  --enable-registration
```

Пароль SMTP читается скрыто из TTY и сохраняется только в `runtime/secrets/smtp_password`. URL не принимает встроенные логин/пароль, path, query или fragment. Регистрация разрешается только в серверном HTTPS-режиме. Чтобы оставить или отключить регистрацию при настройке SMTP, вызовите ту же команду без `--enable-registration`. CLI включает и проверяет обслуживание, штатно останавливает backend, пересоздаёт его с выбранной конфигурацией, проверяет готовность и затем открывает доступ. SIGKILL/OOM не считается успешной остановкой.

Проверка подтверждения адреса и сброса пароля должна включать реальную отправку и переход по полученной ссылке. Ответ «запрос принят» не обещает, что адрес существует в системе или письмо доставлено. Без настроенного SMTP публичные почтовые действия недоступны; оператор может управлять аккаунтами через [CLI](operations.md#аккаунты).

## Права и хранение секретов

`runtime/` и `runtime/secrets/` имеют права `0700`; приватное состояние и журнал — `0600`. Файлы, подключаемые через Compose secrets, создаются `0444`, чтобы разные непривилегированные контейнерные UID могли читать их bind mounts. Защиту на хосте обеспечивает закрытый родительский каталог, а внутри контейнера — выбор конкретных secrets для сервиса. `ca.key` остаётся `0600` и не подключается к рабочим сервисам. Не расширяйте права родительских каталогов и не добавляйте runtime в Git. [Механизм Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

Backend и frontend работают с UID/GID `10001:10001`; gateway также запускается с `10001:10001`. Их root filesystem read-only, capabilities удалены, `no-new-privileges` включён. PostgreSQL entrypoint выполняет необходимую подготовку своих файлов и передаёт серверный процесс пользователю postgres. Одноразовый `ops` работает от root для установки прав и offline backup/restore; Compose удаляет все capabilities и добавляет только `CHOWN`, `DAC_OVERRIDE`, `FOWNER`. Это не режим рабочих приложений. Операторский Docker-only wrapper — отдельная административная граница с Docker socket.

## Сборка разработчиком

Нужны три независимых checkout: этот репозиторий, `TraceWeaveBackend` и `TraceWeaveFrontend` на согласованных ревизиях с Dockerfile. Они не объединяются в monorepo. Swift и Node для сборки выполняются в Docker. В Docker-only режиме проверку исходных ревизий выполняет Git tools-контейнера; host Python, Swift и Node не нужны. Сначала подготовьте operator tools image по инструкции выше.

Оба source checkout обязательно должны быть committed и чистыми: без staged/unstaged изменений и неигнорируемых untracked файлов. Проверьте статус; обе команды должны вывести пустой результат:

```sh
git -C ../TraceWeaveBackend status --porcelain=v1 --untracked-files=all
git -C ../TraceWeaveFrontend status --porcelain=v1 --untracked-files=all
```

Это удобная предварительная проверка при наличии host Git. Сам `build-source` выполняет обязательную проверку Git (в Docker-only режиме — внутри tools-контейнера) и отказывает до сборки при грязном checkout. Он фиксирует Git HEAD и diff hash backend/frontend, hash контракта и проверяет их вместе с чистым статусом повторно после сборки. Изменение source/контракта во время сборки не создаёт manifest.

```sh
./traceweave.sh build-source --release-id e8-docker-1 \
  --backend-path ../TraceWeaveBackend \
  --frontend-path ../TraceWeaveFrontend
```

По умолчанию source paths — соседние `../TraceWeaveBackend` и `../TraceWeaveFrontend` относительно репозитория поставки. Для других расположений используйте фактические флаги `--backend-path` и `--frontend-path` с существующими путями; явные относительные пути отсчитываются от каталога вызова.

Команда собирает tools, gateway, backend и frontend с отдельными tags выбранного release ID, скачивает pinned PostgreSQL и пишет `releases/e8-docker-1.local.json` с локальными immutable image IDs. Tags этого примера — `traceweave/tools:e8-docker-1`, `traceweave/gateway:e8-docker-1`, `traceweave/backend:e8-docker-1` и `traceweave/frontend:e8-docker-1`; прежние релизные tags сохраняются. Если локальный manifest с таким ID уже существует, сборка отказывает до изменения images: выберите новый `--release-id` и используйте новый путь manifest. Не удаляйте старый manifest для повторного использования ID: он фиксирует образы для отката.

Закрепите operator tools image успешной сборки перед bootstrap и последующими Docker-only командами:

```sh
TW_TOOLS_IMAGE=$(docker image inspect --format '{{.Id}}' traceweave/tools:e8-docker-1)
export TW_TOOLS_IMAGE
./traceweave.sh --help
```

Локальные `releases/*.local.json` исключены из Git, поскольку содержат image IDs конкретного Docker-хоста. Команда не публикует images и не обновляет работающую установку. Поддерживаемая платформа в этом манифесте соответствует текущему Docker daemon; другая архитектура требует отдельной сборки и проверки.

Frontend generated API должен заранее соответствовать `contracts/openapi.yaml` поставки. Если Docker build выявил несовпадение, в frontend checkout выполните `npm ci`, затем `OPENAPI_CONTRACT_PATH` с абсолютным путём к этому контракту, `npm run api:generate`, `npm run typecheck` и `npm test`. Исправленный generated код должен войти в согласованную source-ревизию; image build не регенерирует контракт молча. Сборка pinned статики соответствует [режиму static deployment Vite](https://vite.dev/guide/static-deploy.html).
