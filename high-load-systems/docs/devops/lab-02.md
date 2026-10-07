# DevOps · Лабораторна 2 — Continuous Integration

**Проєкт:** CDN Control Plane API (той самий, що в Лабі 1) — FastAPI + PostgreSQL,
підпапка `high-load-systems/` у монорепозиторії `ostrrovska/uni_year_4`.
**CI-інструмент:** GitHub Actions. **Реєстр образів:** GitHub Container Registry (ghcr.io).

Пайплайн: `.github/workflows/cdn-control-plane-ci.yml` (у корені репо — GitHub Actions
читає воркфлоу лише звідти). Скоупнутий через `paths:` на `high-load-systems/**`, тож на
зміни в інших проєктах монорепо він не запускається.

---

## 1. Відповідність вимогам

| Вимога | Як виконано |
|---|---|
| **1.** CI/CD підключено, запуск на PR і push у робочу гілку, статус у PR | GitHub Actions; тригери `pull_request` + `push: [main]`; статуси jobs видно в PR |
| **2.** Build + Test для сервісу, паралельно й незалежно, кеш залежностей | Jobs `lint` і `test` виконуються паралельно й незалежно; `test` має кроки **Build** (`pip install -e .[dev]` + `compileall`) і **Test** (`pytest`); кеш pip через `actions/setup-python` |
| **3.** Статичний аналіз, блокуючий, результат у PR | Job `lint`: `ruff check .` + `ruff format --check .`; падіння валить перевірку в PR |
| **4.** Складання образу, залежить від build+test, локально, скан вразливостей | Job `docker-image` з `needs: [lint, test]`; образ збирається в раннері; **Trivy** скан (блокуючий, CRITICAL/HIGH) перед публікацією |
| **5.** Публікація в реєстр, авторизація через секрети, лише на push, 2+ теги | Пуш у ghcr.io лише коли `event != pull_request`; авторизація вбудованим `GITHUB_TOKEN` (без ручних секретів); теги `sha-<commit>` завжди + `latest` лише на `main` |
| **6.** Захист основної гілки, обов'язкові перевірки, демо заблокованого PR | Ruleset `docs/devops/main-branch-ruleset.json` (імпорт у Settings → Rules): вимагає PR, робить `lint`/`test`/`docker-image` обов'язковими |

---

## 2. Структура пайплайну

```
pull_request / push(main)
        |
   +----+----+                      (паралельно, незалежно)
   |         |
 lint       test (Postgres service, pytest)
   |         |
   +----+----+
        |
   docker-image   (needs: lint, test)
   build -> Trivy scan -> push* (*лише на push, не на PR)
```

- **lint** — Ruff (лінт + формат). Блокуючий.
- **test** — піднімає сервіс-контейнер `postgres:16`, ставить залежності, компілює іганяє
  39 інтеграційних тестів проти реального Postgres (`TEST_DATABASE_URL` вказує на сервіс;
  тести самі створюють тест-БД і схему).
- **docker-image** — збирає образ з `high-load-systems/docker/Dockerfile`, сканує Trivy,
  і на push публікує в `ghcr.io/ostrrovska/cdn-control-plane`.

Чому один збірний сервіс, а не matrix: проєкт має один Python-образ (він же обслуговує
api/agents/migrate). Лаба дозволяє об'єднувати однотипні сервіси; matrix знадобиться, коли
з'явиться окремий різнорідний сервіс.

---

## 3. Що потрібно зробити вручну в GitHub (я не маю доступу до UI)

1. **Залити й відкрити PR.** Закомітити нові файли на гілці, запушити, відкрити PR у
   `ostrrovska/uni_year_4`. У PR мають з'явитися перевірки `lint`, `test`, `docker-image`
   (вимога 1). На PR образ **не** публікується.
2. **Дозволити публікацію пакетів** (зазвичай уже так): Settings → Actions → General →
   Workflow permissions → Read and write. Окремі секрети не потрібні — публікує `GITHUB_TOKEN`.
3. **Merge у `main`** → job `docker-image` опублікує образ. Перевірити: вкладка **Packages**
   репозиторію → `cdn-control-plane` (за потреби виставити visibility). Підтвердити
   працездатність (вимога 5):
   ```bash
   docker pull ghcr.io/ostrrovska/cdn-control-plane:latest
   docker run --rm -p 8000:8000 ghcr.io/ostrrovska/cdn-control-plane:latest
   ```
4. **Імпортувати захист гілки** (вимога 6): Settings → Rules → Rulesets → New ruleset →
   **Import a ruleset** → обрати `high-load-systems/docs/devops/main-branch-ruleset.json` →
   Create. Це вимагає PR для `main`, забороняє прямий push і робить `lint`/`test`/`docker-image`
   обов'язковими.
5. **Показати заблокований PR** (вимога 6): у гілці свідомо зламати тест або лінт у
   `high-load-systems/` (напр. додати невикористаний імпорт або `assert False` у тест),
   відкрити PR → показати червоні перевірки і що кнопка merge заблокована.

> **Монорепо-нюанс:** через `paths:` перевірки запускаються лише для PR, що чіпають
> `high-load-systems/`. Демонстрації роби саме на таких PR, інакше обов'язкові перевірки
> можуть «висіти» не запущеними.

---

## 4. Скріншоти для захисту

1. PR із зеленими `lint` / `test` / `docker-image` і статусом перевірок.
2. Логи job `test` — Postgres service піднявся, `39 passed`.
3. Логи job `docker-image` — Trivy scan + `push` з тегами `sha-...` і `latest`.
4. Вкладка Packages — опублікований образ; термінал з `docker pull` + запуском.
5. Заблокований PR зі зламаним тестом/лінтом — merge недоступний.
