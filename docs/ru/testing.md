# Проверки и приёмка

*[English](../en/testing.md)*

## Локальные проверки контрактов и оператора

CI устанавливает закреплённые зависимости, проверяет контракты и изолированные operator tests до image build. Неконтейнерные проверки воспроизводятся во временном virtual environment:

```sh
TW_CHECK_VENV=$(mktemp -d "${TMPDIR:-/tmp}/traceweave-checks.XXXXXX")
python3 -m venv "$TW_CHECK_VENV"
"$TW_CHECK_VENV/bin/pip" install -r tools/requirements-validation.txt
"$TW_CHECK_VENV/bin/python" tools/validate_contracts.py
"$TW_CHECK_VENV/bin/python" -m unittest discover -s tests -v
"$TW_CHECK_VENV/bin/python" -m unittest discover -s tests/contracts -p test_contracts.py -v
python3 -I tools/ci_release_tests.py --self-test
sh -n bootstrap.sh traceweave.sh db/entrypoint.sh db/init.sh
```

Они не мигрируют пользовательскую БД. Реальные lifecycle tests создают данные и выполняются только на помеченной синтетической установке.

## Проверка полной поставки

[Docker delivery CI](../../.github/workflows/delivery.yml) проверяет locked independent revisions на Linux amd64/arm64. Он собирает образы и проверяет реальный API/media/export/restart/maintenance/restore, выборочные updates, marked fault recovery, аккаунты, SMTP и HTTPS. Images не публикуются.

| Runner | Границы |
| --- | --- |
| `tools/integration.py` | Синтетическая установка и API lifecycle |
| `tools/update_integration.py` | Frontend-only/backend-only переходы |
| `tools/fault_integration.py` | Помеченные failure/recovery cases |
| `tests/account_https.py` | Account/mail/HTTPS acceptance fixtures |

Используйте `--help` каждого runner и его обязательный marked test root; сохраняйте evidence. Unit suite компонента или генерация документации не заменяют этот протокол.

## Границы приёмки

E0/E1 и локальный Docker-пакет имеют отдельные сохранённые результаты. Полный P0 остаётся отдельно, включая открытую [границу extensions 16 KiB](../change-requests/CR-E2-001-extensions-byte-limit.md), browser/performance и применимые AC. Настоящий Safari требует ручного evidence; headless WebKit недостаточно. Исторические и пропущенные проверки не превращаются в текущие passes.

---

[К документации](index.md) · [README](../../README-ru.md)
