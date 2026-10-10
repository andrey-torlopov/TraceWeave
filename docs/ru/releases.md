# Релизы и обновления

*[English](../en/releases.md)*

Выпуск **0.1.1** опубликован с образами для amd64/arm64. Проверенный [manifest](../../releases/0.1.1.json), [выбор по умолчанию](../../releases/stable.json) и [образ tools](../../releases/tools-image.txt) доступны в репозитории и [GitHub Release v0.1.1](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.1).

## Точная установка 0.1.1

Каталог назначения должен быть новым:

```sh
git clone --branch v0.1.1 --depth 1 https://github.com/andrey-torlopov/TraceWeave.git TraceWeave-0.1.1
cd TraceWeave-0.1.1
curl -fL --output releases/0.1.1.json https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.1/0.1.1.json
curl -fL --output releases/tools-image.txt https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.1/tools-image.txt
./bootstrap.sh --release releases/0.1.1.json
```

Папка релиза и его manifest должны соответствовать друг другу. Образы закреплены по digest — идентификатору содержимого. Приватные исходники и вход в реестр не нужны. Историческая документация внутри тега может содержать старые статусы; актуальные пользовательские гайды доступны в main.

## Обновление существующей установки

Для перехода с **0.1.0** сохраните прежний каталог поставки и runtime. Используйте отдельный [manifest обновления](../../releases/0.1.1-update.json): он заменяет backend/frontend на 0.1.1 и сохраняет gateway/tools 0.1.0 и прежний PostgreSQL18.6. Полный `0.1.1.json` предназначен для новой установки; существующий оператор отклонит замену gateway/tools обычной командой update.

Из каталога установленной 0.1.0:

```sh
curl -fL --output releases/0.1.1-update.json https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.1/0.1.1-update.json
./traceweave.sh update --release releases/0.1.1-update.json
./traceweave.sh status
```

Обновление выполняет offline backup и сохраняет прежние browser assets для открытой вкладки. История миграций и контракт не меняются; `./traceweave.sh rollback` возвращает прежнюю пару образов с сохранением записанных после обновления данных. Оригиналы файлов сохраняются. Выпуск 0.1.1 добавляет удаление узла из его меню, инспектора и редактора с удалением всех инцидентных связей.

Обновления не устанавливаются автоматически. После получения совместимой поставки и её проверенного manifest, из каталога установки с прежним runtime:

```sh
printf 'Абсолютный путь к проверенному manifest обновления: '
IFS= read -r TW_RELEASE_MANIFEST
test -f "$TW_RELEASE_MANIFEST"
./traceweave.sh update --release "$TW_RELEASE_MANIFEST"
./traceweave.sh status
```

Прочитайте preflight и подтвердите действие в терминале. Обновление сохраняет volumes; при необходимости выполняет backup и миграцию под обслуживанием. Не смешивайте случайные версии отдельных images. Открытая вкладка может попросить обновление после сохранения черновика.

Откат образов допускается при совместимой истории схемы:

```sh
./traceweave.sh rollback
```

После изменения схемы может понадобиться совместимый исправляющий выпуск или восстановление прежнего backup. [Восстановление и прерванные операции](operations.md). Публикация выпуска не обновляет уже установленное приложение.

---

[К документации](index.md) · [README](../../README-ru.md)
