# Установка TraceWeave на отдельный VPS Ubuntu 24.04

**Статус:** инструкция подготовлена для будущего опубликованного релиза. Сейчас образы TraceWeave и готовый публичный release manifest ещё не опубликованы. Не начинайте bootstrap на чистом VPS без проверенного манифеста с доступными `repository@sha256:…` для архитектуры сервера. Локальные image IDs `sha256:…` не скачиваются из реестра. Текущий путь разработчика — [сборка из исходников](installation.md#сборка-разработчиком).

## 1. Подготовить сервер и доступ

Нужен **VPS/VDS с Ubuntu 24.04 и правами sudo для Docker**, а не shared/PHP-хостинг. Выберите архитектуру, которую поддерживает релиз, и диск с запасом для данных, backup и новых restore volumes. Образы скачиваются и контейнеры работают на VPS; браузер обращается к домену через gateway, SSH нужен оператору для управления. Backend, frontend и PostgreSQL не публикуют собственные порты.

На **компьютере оператора** создайте отдельный SSH-ключ и задайте passphrase:

```sh
ssh-keygen -t ed25519 -f "$HOME/.ssh/traceweave_vps" -C traceweave-vps
cat "$HOME/.ssh/traceweave_vps.pub"
printf 'IP VPS: '; IFS= read -r TW_VPS_IP
printf 'Начальный SSH-пользователь из панели VPS: '; IFS= read -r TW_ADMIN_USER
ssh -i "$HOME/.ssh/traceweave_vps" "$TW_ADMIN_USER@$TW_VPS_IP"
```

До подключения добавьте содержимое `.pub` в панель VPS при создании сервера либо в `~/.ssh/authorized_keys` начального пользователя через консоль провайдера. Сверьте fingerprint сервера с данными панели. Файл без `.pub` — приватный ключ: он остаётся на компьютере оператора; его не передают на VPS, в GitHub или поддержку. [SSH-ключи Ubuntu](https://ubuntu.com/server/docs/how-to/security/openssh-server/).

В начальной SSH-сессии **на VPS** создайте отдельного пользователя; в последний ввод вставьте одну строку из `.pub`:

```sh
printf 'Имя нового пользователя-оператора: '; IFS= read -r TW_OPERATOR_USER
sudo adduser "$TW_OPERATOR_USER"
sudo usermod -aG sudo "$TW_OPERATOR_USER"
sudo install -d -m 700 -o "$TW_OPERATOR_USER" -g "$TW_OPERATOR_USER" "/home/$TW_OPERATOR_USER/.ssh"
printf 'Полная строка публичного SSH-ключа: '; IFS= read -r TW_PUBLIC_KEY
printf '%s\n' "$TW_PUBLIC_KEY" | sudo tee "/home/$TW_OPERATOR_USER/.ssh/authorized_keys" >/dev/null
sudo chown "$TW_OPERATOR_USER:$TW_OPERATOR_USER" "/home/$TW_OPERATOR_USER/.ssh/authorized_keys"
sudo chmod 600 "/home/$TW_OPERATOR_USER/.ssh/authorized_keys"
```

Оставьте начальную сессию открытой. Во втором терминале **компьютера оператора** подключитесь новым пользователем и проверьте `sudo -v`; IP и имя введите заново:

```sh
printf 'IP VPS: '; IFS= read -r TW_VPS_IP
printf 'Пользователь-оператор: '; IFS= read -r TW_OPERATOR_USER
ssh -i "$HOME/.ssh/traceweave_vps" "$TW_OPERATOR_USER@$TW_VPS_IP"
```

В этой новой SSH-сессии **на VPS**:

```sh
sudo -v
```

## 2. Установить Docker, проверить DNS и firewall

Далее команды выполняются **на VPS под оператором**. Установите Docker Engine из официального apt-репозитория по [инструкции Docker для Ubuntu](https://docs.docker.com/engine/install/ubuntu/), включая пакет `docker-compose-plugin`. Не смешивайте эту установку с пакетами `docker.io`/старым `docker-compose`. Затем:

```sh
sudo apt update
sudo apt install git curl python3
sudo usermod -aG docker "$USER"
```

Переподключитесь по SSH, чтобы новая группа вступила в силу, и проверьте:

```sh
docker info --format '{{.ServerVersion}}'
docker compose version
docker run --rm hello-world
```

Группа `docker` даёт полномочия уровня root; добавляйте только оператора установки. [Права Docker](https://docs.docker.com/engine/install/linux-postinstall/). Нужен современный Compose plugin с поддержкой `!override`; проверенная среда пакета — Engine 29.8.2 / Compose 5.5.1. Host Python 3 используется для CLI; Swift и Node.js на VPS не нужны.

В DNS создайте **A** выбранного домена на публичный IPv4 VPS. **AAAA** добавляйте только при работающем IPv6 до этого же VPS; ошибочный AAAA удалите. В firewall провайдера разрешите входящий TCP **22** с IP оператора и **80/443** из интернета, исходящие DNS/HTTPS и порт вашего SMTP. Проверьте, что 80/443 не заняты другим сервером. Docker-порты могут обходить UFW; не полагайтесь только на него — [ограничения firewall Docker](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations).

```sh
printf 'Публичный домен без https://, порта и пути: '; IFS= read -r TW_DOMAIN
getent ahosts "$TW_DOMAIN"
TW_PUBLIC_ORIGIN="https://$TW_DOMAIN"
```

Дождитесь правильного DNS и внешней доступности портов. Gateway Caddy сам получает и продлевает сертификат; его хранилище сохраняется в volume. Отдельный nginx или certbot не требуется. [Условия автоматического HTTPS Caddy](https://caddyserver.com/docs/automatic-https).

## 3. Получить поставку и запустить bootstrap

Публичный репозиторий клонируется через HTTPS; SSH-ключ GitHub не нужен. Получите проверенный manifest и точную ревизию delivery из **будущего опубликованного релиза**. Сохраните manifest на VPS; не придумывайте registry URL и не редактируйте digest вручную.

```sh
git clone https://github.com/andrey-torlopov/TraceWeave.git "$HOME/TraceWeave"
cd "$HOME/TraceWeave"
printf 'Ревизия delivery из выбранного релиза: '; IFS= read -r TW_DELIVERY_REVISION
git checkout --detach "$TW_DELIVERY_REVISION"
export TW_RUNTIME_DIR="$HOME/traceweave-runtime"
umask 077
printf 'Полный путь к проверенному release manifest на VPS: '; IFS= read -r TW_RELEASE_MANIFEST
test -f "$TW_RELEASE_MANIFEST"
printf 'Email первого аккаунта: '; IFS= read -r TW_OWNER_EMAIL
printf 'Имя первого аккаунта: '; IFS= read -r TW_OWNER_NAME
printf 'SMTP URL с портом, без логина/пароля: '; IFS= read -r TW_SMTP_URL
printf 'SMTP login: '; IFS= read -r TW_SMTP_USER
printf 'Email разрешённого SMTP-отправителя: '; IFS= read -r TW_SMTP_FROM
./bootstrap.sh --release "$TW_RELEASE_MANIFEST" --origin "$TW_PUBLIC_ORIGIN" \
  --email "$TW_OWNER_EMAIL" --name "$TW_OWNER_NAME" \
  --smtp-url "$TW_SMTP_URL" --smtp-user "$TW_SMTP_USER" --smtp-from "$TW_SMTP_FROM"
```

SMTP обязателен уже для первого HTTPS-аккаунта: до входа нужно подтвердить email. Возьмите у почтового провайдера рабочие параметры, разрешённого отправителя и SMTP-пароль. URL — `smtp://` с обязательным STARTTLS либо `smtps://`, с hostname и портом, без credentials/пути/query. Bootstrap отдельно запросит **SMTP-пароль и пароль аккаунта скрытым вводом в TTY**; не передавайте их аргументами, переменными окружения или файлами в Git. Публичная регистрация по умолчанию отключена; её включение описано в [настройке SMTP](installation.md#https-на-сервере).

```sh
./traceweave.sh status
curl --fail --show-error "$TW_PUBLIC_ORIGIN/health/ready"
curl --fail --show-error "$TW_PUBLIC_ORIGIN/release.json"
```

Ожидаются фаза `ready`, четыре healthy сервиса и HTTP 200 с действительным TLS-сертификатом. Откройте домен, подтвердите email по письму и войдите. Не используйте `curl -k`. При ошибке смотрите `./traceweave.sh logs backend gateway`; не открывайте gateway вручную.

## 4. Управлять, сохранять копии и обновлять

В **каждой новой SSH-сессии** задавайте тот же runtime и checkout: `export TW_RUNTIME_DIR="$HOME/traceweave-runtime"; cd "$HOME/TraceWeave"`. Менять этот путь для существующей установки нельзя.

```sh
./traceweave.sh stop
./traceweave.sh start
./traceweave.sh status
./traceweave.sh backup
```

`stop` сохраняет volumes. `backup` временно включает обслуживание, штатно останавливает backend, проверяет согласованную копию и возвращает доступ; сохраните напечатанное имя каталога и проверьте фазу `ready`. Копия содержит данные всех аккаунтов. Для защиты от потери VPS перенесите **полный завершённый каталог** на отдельное защищённое хранилище; простой backup на том же диске недостаточен.

На **компьютере оператора**, где уже заданы IP и SSH-пользователь:

```sh
printf 'Имя завершённого backup из вывода CLI: '; IFS= read -r TW_BACKUP_NAME
printf 'Полный путь к приватному каталогу копий на этом компьютере: '; IFS= read -r TW_LOCAL_BACKUPS
mkdir -p "$TW_LOCAL_BACKUPS"
chmod 700 "$TW_LOCAL_BACKUPS"
scp -i "$HOME/.ssh/traceweave_vps" -r \
  "$TW_OPERATOR_USER@$TW_VPS_IP:traceweave-runtime/backups/$TW_BACKUP_NAME" "$TW_LOCAL_BACKUPS/"
```

SSH шифрует перенос; хранение копии также должно быть защищено. Отдельно сохраните приватные secrets/config/release manifests согласно [backup и restore](operations.md#приватный-offline-backup). Для проверки восстановления используйте отдельную установку; restore создаёт новые volumes и safety backup, а не сливает старые и новые данные.

На VPS обновление запускается только с проверенным manifest нового совместимого релиза:

```sh
printf 'Полный путь к manifest нового релиза: '; IFS= read -r TW_NEXT_RELEASE_MANIFEST
./traceweave.sh update --release "$TW_NEXT_RELEASE_MANIFEST"
./traceweave.sh status
```

Изучите preflight и подтвердите операцию в TTY. `./traceweave.sh rollback` возвращает предыдущие images только при той же истории схемы; после миграции нужен совместимый исправляющий релиз либо restore pre-update backup. После обрыва SSH сначала `status`/логи, затем соответствующий `resume` или recovery. Полные процедуры: [управление и сбои](operations.md), [релизы и откат](releases.md). Не удаляйте runtime/volumes и не выполняйте `docker compose down -v` как способ восстановления.
