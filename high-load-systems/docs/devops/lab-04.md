# DevOps · Лабораторна 4 — Пакування застосунку в Helm-чарт

**Проєкт:** CDN Control Plane API (той самий, що в Лабах 1–3) — FastAPI + PostgreSQL,
підпапка `high-load-systems/` у монорепозиторії `ostrrovska/uni_year_4`.
**Чарт:** [`chart/cdn-control-plane/`](../../chart/cdn-control-plane/). **Helm:** 3.19.4.
**Додаткове завдання:** варіант **(b)** — хук `pre-upgrade` (міграція схеми) і тест
релізу `helm test`.

Лаба 3 описала застосунок п'ятнадцятьма маніфестами в [`k8s/`](../../k8s/). Вони працюють,
але в них зашиті і тег образу, і кількість реплік, і ім'я кожного об'єкта — розгорнути з
них друге середовище можна лише копіюванням каталогу. Ця робота перетворює їх на чарт, у
якому все це стало значеннями.

---

## 1. Відповідність вимогам

| Вимога | Як виконано |
|---|---|
| **1a.** Helm 3 встановлено, версію перевірено | Helm **v3.19.4**; крок 01 демо падає, якщо версія не починається з `v3.` — [`lab-04-output/01-environment.txt`](lab-04-output/01-environment.txt). Саме 3, а не 4: winget і choco нині за замовчуванням ставлять 4.3.1, тож бінарник узято з `get.helm.sh` |
| **1b.** Кластер minikube запущено | Той самий кластер, що в Лабі 3 |
| **1c.** Маніфести Лаби 3 розгортаються і застосунок працює | Підтверджено `./scripts/devops_lab3_demo.ps1` |
| **1d.** Реліз Лаби 3 видалено, щоб уникнути конфлікту імен | Обрано сильніший варіант: не видаляти, а зробити конфлікт неможливим — окремий namespace, окремий node port і імена об'єктів із префіксом релізу. Крок 01 демо це **перевіряє**, а не декларує — [`lab-04-output/01-environment.txt`](lab-04-output/01-environment.txt). Якщо реліз Лаби 3 усе ж треба прибрати: `kubectl delete -f k8s/` |
| **2a.** Каталог чарта в репозиторії | [`chart/cdn-control-plane/`](../../chart/cdn-control-plane/) |
| **2b.** `Chart.yaml`: name, description, version, appVersion | [`chart/cdn-control-plane/Chart.yaml`](../../chart/cdn-control-plane/Chart.yaml) |
| **2c.** Різниця між `version` і `appVersion` пояснена | §2 |
| **3a.** Кожен маніфест Лаби 3 — окремий файл у `templates/` | 13 шаблонів + 2 хуки + 1 тест — §3 |
| **3b.** Жорстко прописані значення замінено на `.Values` | §3; перевіряється `helm template` для двох середовищ |
| **3c.** Імена об'єктів будуються з імені релізу | Усе через `{{ include "cdn.fullname" . }}`, тож чарт ставиться двічі в один кластер |
| **3d.** Значення Secret беруться зі значень чарта | [`templates/secret.yaml`](../../chart/cdn-control-plane/templates/secret.yaml) не містить жодного літерала — обидва ключі приходять із `.Values` |
| **4a.** У значення винесено образ, репліки, сервіс, ресурси, конфігурацію, Ingress | Повна таблиця — §4 |
| **4b.** Значення за замовчуванням відповідають середовищу розробки | `values.yaml` — 2 репліки, малі ресурси, кеш увімкнено, Ingress вимкнено |
| **4c.** Прапорець `enabled` для необов'язкових об'єктів | `ingress.enabled`, `postgresql.persistence.enabled`, `redis.enabled`, `agents.enabled`, `migrate.enabled`, `seed.enabled` |
| **5a.** `_helpers.tpl` з іменованими шаблонами для імені та міток | [`templates/_helpers.tpl`](../../chart/cdn-control-plane/templates/_helpers.tpl): `cdn.name`, `cdn.fullname`, `cdn.chart`, `cdn.labels`, `cdn.selectorLabels`, `cdn.image`, `cdn.databaseUrl`, `cdn.redisUrl` |
| **5b.** Шаблони підключено в усіх маніфестах через `include` | Кожен файл у `templates/` викликає `cdn.fullname` і `cdn.labels` |
| **5c.** `NOTES.txt` із інструкцією, як відкрити застосунок | [`templates/NOTES.txt`](../../chart/cdn-control-plane/templates/NOTES.txt) — різний текст для Ingress, NodePort і ClusterIP |
| **6a.** `values-dev.yaml` і `values-prod.yaml`, що відрізняються репліками, ресурсами, тегом і Ingress | §4; відмінності зведено в таблицю |
| **6b.** Різниця показана без встановлення чарта | §5 — `helm template` для обох середовищ |
| **6c.** Пріоритет `values.yaml` / `-f` / `--set` | §5 |
| **7a.** Перевірка чарта на помилки | `helm lint` — §6 |
| **7b.** Згенеровані маніфести порівняно з Лабою 3 | §6 |
| **7c.** Реліз встановлено у власний namespace | `helm install ... -n cdn-helm --create-namespace` — §6 |
| **7d.** Перелік релізів, статус і значення | `helm list`, `helm status`, `helm get values` — §6 |
| **7e.** Де Helm зберігає стан релізу | §6 — Secret типу `helm.sh/release.v1` у namespace релізу |
| **8a.** Оновлення зміною тега через `--set` | §7 |
| **8b.** Оновлення з файлом значень іншого середовища | §7 |
| **8c.** Історія ревізій і що саме змінювалося | §7 |
| **8d.** Відкат і його відображення в історії | §7 |
| **8e.** Видалення однією командою, namespace порожній | §7 |
| **9.** Завдання на вибір — варіант (b): хук і тест релізу | §8 |
| **10a.** Чарт закомічено в репозиторій | Разом із цим звітом |
| **10b.** Параметри values таблицею і команди встановлення для обох середовищ | Розділ **Deployment — Kubernetes and Helm** у [`README.md`](../../README.md); повна таблиця всіх параметрів — §4 |
| **10c.** Звіт із підтвердженням пунктів 6–9 | §5–§8; повні транскрипти — [`docs/devops/lab-04-output/`](lab-04-output/) |

---

## 2. `version` проти `appVersion` для цього проєкту

```yaml
version: 0.1.0      # версія самого чарта - упаковки
appVersion: "1.0.0" # версія застосунку, який чарт ставить за замовчуванням
```

Це два незалежні лічильники, і плутають їх саме тому, що зараз вони виглядають схоже.

**`version`** рухається, коли змінюється упаковка: доданий шаблон, перейменоване значення,
виправлений селектор, змінене значення за замовчуванням. Образ при цьому може лишитися
той самий. Якщо завтра я винесу `postgresql` у залежність від стороннього чарта — застосунок
не зміниться жодним байтом, а `version` мусить стати `0.2.0`, бо старі `values.yaml`
користувачів перестануть підходити.

**`appVersion`** рухається, коли виходить нова версія CDN Control Plane API. Саме вона —
значення за замовчуванням для `image.tag`: у [`_helpers.tpl`](../../chart/cdn-control-plane/templates/_helpers.tpl)
тег береться як `.Values.image.tag | default .Chart.AppVersion`, тож порожній `image.tag`
означає «той застосунок, під який цей чарт писався». Випуск `1.1.0` без жодної зміни в
шаблонах піднімає лише `appVersion`.

Практичний наслідок: `helm search` і `helm list` показують обидва числа окремо, і за
`version` видно, чи треба перечитувати `values.yaml`, а за `appVersion` — чи змінився код.

---

## 3. Перенесення маніфестів у шаблони

```
chart/cdn-control-plane/
  Chart.yaml
  values.yaml                  значення за замовчуванням (середовище розробки)
  values-dev.yaml              overlay: 1 репліка, NodePort 30081, seed, DEBUG
  values-prod.yaml             overlay: 3 репліки, ClusterIP + Ingress, тег 1.1.0, WARNING
  templates/
    _helpers.tpl               іменовані шаблони
    NOTES.txt                  підказка після встановлення
    configmap.yaml             <- k8s/10-app-configmap.yaml
    secret.yaml                <- k8s/12-secret.yaml
    postgresql-pvc.yaml        <- k8s/20-postgres-pvc.yaml
    postgresql-deployment.yaml <- k8s/21-postgres-deployment.yaml
    postgresql-service.yaml    <- k8s/22-postgres-service.yaml
    redis-deployment.yaml      <- k8s/30-redis-deployment.yaml
    redis-service.yaml         <- k8s/31-redis-service.yaml
    api-deployment.yaml        <- k8s/50-api-deployment.yaml
    api-service.yaml           <- k8s/51-api-service.yaml
    ingress.yaml               <- k8s/52-api-ingress.yaml
    agents-deployment.yaml     <- k8s/60-agents-deployment.yaml
    hooks/migrate-job.yaml     <- k8s/40-migrate-job.yaml   (став хуком, §8)
    hooks/seed-job.yaml        <- k8s/70-seed-job.yaml      (став хуком, §8)
    tests/test-api-ready.yaml  нове — тест релізу, §8
```

Двох речей з `k8s/` у чарті немає свідомо. **Namespace** не шаблонізовано: ним володіє
`helm install --create-namespace`, а чарт, який створює власний namespace, не можна
поставити у вже наявний. **`11-postgres-configmap.yaml`** розчинився у
`postgresql-deployment.yaml` — два ключі, які читає лише контейнер бази, не заслуговують
на окремий об'єкт, коли шаблон і так бачить `.Values.postgresql.auth`.

### Що саме перестало бути жорстко прописаним

| У Лабі 3 було зашито | У чарті стало |
|---|---|
| `name: cdn-api`, `cdn-postgres`, ... | `{{ include "cdn.fullname" . }}-api` тощо |
| `image: ...:1.0.0` | `{{ include "cdn.image" . }}` з `image.repository` + `image.tag` |
| `replicas: 2` | `{{ .Values.api.replicaCount }}` |
| `nodePort: 30080` | `{{ .Values.api.service.nodePort }}`, і лише коли тип — NodePort |
| `DATABASE_URL: postgresql+asyncpg://cdn:cdn@cdn-postgres:5432/...` | `{{ include "cdn.databaseUrl" . }}` — збирається з `postgresql.auth` і імені релізу |
| `REDIS_URL: redis://cdn-redis:6379/0` | `{{ include "cdn.redisUrl" . }}` |
| `storage: 1Gi` | `{{ .Values.postgresql.persistence.size }}` |
| наявність Ingress | `{{- if .Values.ingress.enabled }}` |

**Три `replicas: 1`, що лишилися в шаблонах, — свідомі.** Значенням стала саме та
кількість реплік, яку має сенс змінювати: `api.replicaCount`. У PostgreSQL одна репліка —
наслідок `ReadWriteOnce`-тому і `strategy: Recreate`, у Redis — кеша без реплікації, а в
симуляторі агентів це вимога коректності: він переписує ті самі heartbeat-рядки за
таймером, тож друга копія додає лише конкуренцію за ті самі рядки. Винести їх у
`values.yaml` означало б додати ручку, яка ламає реліз у будь-якому положенні, крім `1`.

**Чому імена будуються з імені релізу.** Якби об'єкт звався просто `cdn-api`, другий
`helm install` у тому самому namespace упав би на конфлікті імен. З `cdn.fullname` релізи
`a` і `b` дають `a-cdn-control-plane-api` і `b-cdn-control-plane-api` — і співіснують.
Єдине, що лишається глобальним і тому не може повторитися, — фіксований `nodePort`; саме
тому його значення за замовчуванням порожнє, і Kubernetes обирає порт сам.

**Чому Secret не містить жодного літерала.** Шаблон бере `DATABASE_URL` з
`cdn.databaseUrl`, а `POSTGRES_PASSWORD` — з `.Values.postgresql.auth.password`. Значення
за замовчуванням лабораторне (`cdn`), і будь-яке розгортання перекриває його через `--set`
із секрету CI або зі сховища. Пароля в шаблоні немає взагалі — це і є вимога 3d.

---

## 4. Значення чарта

### Повна таблиця параметрів

| Параметр | Тип | За замовчуванням | Призначення |
|---|---|---|---|
| `nameOverride` | string | `""` | Перекриває ім'я чарта в іменах об'єктів |
| `fullnameOverride` | string | `""` | Повністю перекриває базове ім'я об'єктів |
| `image.repository` | string | `ghcr.io/ostrrovska/cdn-control-plane` | Репозиторій образу застосунку |
| `image.tag` | string | `""` | Тег образу; порожній — береться `Chart.appVersion` |
| `image.pullPolicy` | string | `IfNotPresent` | Теги завантажені через `minikube image load`, тож pull не потрібен |
| `config.appEnv` | string | `development` | Маркер середовища |
| `config.logLevel` | string | `INFO` | Рівень логування |
| `config.dbPoolSize` | int | `10` | Постійний розмір пулу з'єднань |
| `config.dbMaxOverflow` | int | `10` | Додаткові з'єднання понад пул |
| `config.dbPoolTimeout` | int | `10` | Скільки секунд чекати вільне з'єднання |
| `config.heartbeatStaleAfterSeconds` | int | `120` | Коли вузол вважається застарілим |
| `config.heartbeatIntervalSeconds` | int | `10` | Очікуваний період телеметрії |
| `config.nodeOverloadThresholdPercent` | int | `85` | Поріг перевантаження вузла |
| `config.routingDefaultCandidates` | int | `3` | Кандидатів у відповіді маршрутизації |
| `config.routingMaxCandidates` | int | `10` | Стеля для `?limit=` |
| `config.cache.enabled` | bool | `true` | Вмикає Redis-кеш; `false` — `NullCache` |
| `config.cache.routeTtlSeconds` | int | `10` | TTL кешованої маршрутизації |
| `config.cache.statsTtlSeconds` | int | `30` | TTL кешованої статистики |
| `api.replicaCount` | int | `2` | Кількість реплік API |
| `api.service.type` | string | `NodePort` | Тип Service |
| `api.service.port` | int | `80` | Порт Service |
| `api.service.nodePort` | int/string | `""` | Фіксований node port; порожній — Kubernetes обирає сам |
| `api.rollingUpdate.maxUnavailable` | int | `0` | Скільки реплік дозволено втратити під час оновлення |
| `api.rollingUpdate.maxSurge` | int | `1` | Скільки реплік понад норму дозволено підняти |
| `api.preStopSleepSeconds` | int | `5` | Пауза перед SIGTERM, щоб под дослужив запити, поки його виключення з endpoint-ів розходиться по вузлах |
| `api.resources` | object | 100m/128Mi → 1/384Mi | requests і limits для API |
| `agents.enabled` | bool | `true` | Симулятор edge-агентів |
| `agents.watchIntervalSeconds` | int | `10` | Період циклу heartbeat-ів |
| `agents.resources` | object | 50m/96Mi → 500m/256Mi | requests і limits для воркера |
| `migrate.enabled` | bool | `true` | Хук міграції схеми |
| `migrate.resources` | object | 50m/128Mi → 500m/256Mi | requests і limits для хука |
| `seed.enabled` | bool | `false` | Демо-фліт edge-вузлів |
| `seed.resources` | object | 50m/128Mi → 500m/256Mi | requests і limits для seed |
| `postgresql.enabled` | bool | `true` | Піднімати БД у складі релізу |
| `postgresql.image` | string | `postgres:16-alpine` | Образ бази |
| `postgresql.auth.username` | string | `cdn` | Користувач БД |
| `postgresql.auth.database` | string | `cdn_control_plane` | Ім'я бази |
| `postgresql.auth.password` | string | `cdn` | Пароль — лабораторний, перекривається через `--set` |
| `postgresql.persistence.enabled` | bool | `true` | PVC; при `false` база живе на `emptyDir` |
| `postgresql.persistence.size` | string | `1Gi` | Розмір тому |
| `postgresql.persistence.storageClass` | string | `""` | Порожній — StorageClass кластера за замовчуванням |
| `postgresql.resources` | object | 100m/256Mi → 1/512Mi | requests і limits для БД |
| `externalDatabase.url` | string | `""` | Обов'язковий, якщо `postgresql.enabled: false` |
| `redis.enabled` | bool | `true` | Піднімати кеш у складі релізу |
| `redis.image` | string | `redis:7-alpine` | Образ кешу |
| `redis.maxmemory` | string | `192mb` | Стеля пам'яті Redis |
| `redis.maxmemoryPolicy` | string | `allkeys-lru` | Політика витіснення |
| `redis.resources` | object | 50m/64Mi → 500m/256Mi | requests і limits для кешу |
| `externalRedis.url` | string | `""` | Зовнішній Redis, якщо `redis.enabled: false` |
| `ingress.enabled` | bool | `false` | Створювати Ingress |
| `ingress.className` | string | `nginx` | IngressClass |
| `ingress.host` | string | `cdn.local` | Хост, на який відповідає Ingress |
| `ingress.annotations` | object | retry на наступний upstream | Анотації Ingress |
| `podSecurityContext` | object | `runAsNonRoot`, uid/gid 1000 | Образ уже створює непривілейованого користувача `app` |

### Чим відрізняються середовища

| Параметр | `values-dev.yaml` | `values-prod.yaml` |
|---|---|---|
| `image.tag` | `1.0.0` | `1.1.0` |
| `api.replicaCount` | 1 | 3 |
| `api.resources.requests` | 50m / 128Mi | 250m / 256Mi |
| `api.resources.limits` | 500m / 256Mi | 2 / 768Mi |
| `api.service.type` | `NodePort` (30081) | `ClusterIP` |
| `ingress.enabled` | `false` | `true`, хост `cdn.example.com` |
| `config.logLevel` | `DEBUG` | `WARNING` |
| `config.appEnv` | `development` | `production` |
| `seed.enabled` | `true` | `false` |
| `postgresql.persistence.size` | 1Gi | 10Gi |
| `redis.maxmemory` | 64mb | 512mb |

> **Чому в dev порт 30081, а не 30080.** 30080 уже належить
> [`k8s/51-api-service.yaml`](../../k8s/51-api-service.yaml) з Лаби 3, а node port —
> ресурс рівня кластера. Різні порти означають, що маніфести Лаби 3 і чарт Лаби 4 можуть
> бути підняті одночасно й порівнюватися наживо.

> **Чому prod — ClusterIP, а не NodePort.** У продакшні єдиною точкою входу має бути
> Ingress. NodePort поруч із ним — друга, нічим не прикрита точка входу.

### Команди встановлення

```bash
# Середовище розробки
helm install cdn-dev ./chart/cdn-control-plane \
    -f ./chart/cdn-control-plane/values-dev.yaml \
    -n cdn-dev --create-namespace --wait

# Продакшн-подібне середовище
helm install cdn-prod ./chart/cdn-control-plane \
    -f ./chart/cdn-control-plane/values-prod.yaml \
    -n cdn-prod --create-namespace --wait \
    --set postgresql.auth.password="$PG_PASSWORD"   # реальний пароль - не з файлу

# Перевірка після встановлення
helm test cdn-dev -n cdn-dev
```

Увесь демонстраційний прогін пунктів 6–9 автоматизовано:

```powershell
./scripts/devops_lab4_demo.ps1
```

Кожен крок позначено пунктом завдання, друкує живий доказ і **перевіряє результат**.
Підсумок останнього прогону: **14 перевірок із 14 пройдено**. Повні транскрипти —
[`docs/devops/lab-04-output/`](lab-04-output/).

---

## 5. Різниця між середовищами без встановлення (пункт 6)

### 6b. Порівняння без кластера

`helm template` рендерить чарт локально й нічого не чіпає в кластері. Обидва результати
збережено: [`rendered-dev.yaml`](lab-04-output/rendered-dev.yaml) і
[`rendered-prod.yaml`](lab-04-output/rendered-prod.yaml).

```bash
helm template cdn-dev  chart/cdn-control-plane -f values-dev.yaml  > rendered-dev.yaml
helm template cdn-prod chart/cdn-control-plane -f values-prod.yaml > rendered-prod.yaml
```

| | dev | prod |
|---|---|---|
| тег образу | 1.0.0 | 1.1.0 |
| реплік api | 1 | 3 |
| тип Service | NodePort 30081 | ClusterIP |
| Ingress | немає | є, `cdn.example.com` |
| `LOG_LEVEL` | DEBUG | WARNING |

Обидва рендери дають по 13 документів; у prod серед них з'являється `Ingress`, а
`Job` зі seed зникає — бо `seed.enabled: false`.

### 6c. Пріоритет значень

Виміряно на одному параметрі — `image.tag`:

```
chart values.yaml                        -> image tag 1.0.0
-f values-prod.yaml                      -> image tag 1.1.0
-f values-prod.yaml --set image.tag=...  -> image tag 9.9.9
```

Порядок: **значення чарта → файли `-f` (зліва направо) → `--set`**. Останній виграє
завжди, і саме тому реальний пароль подається через `--set` із секрету CI, а не лежить
у файлі значень.

Перший рядок варто прочитати уважно: у `values.yaml` поле `image.tag` **порожнє**, і
`_helpers.tpl` підставляє `Chart.appVersion` (`1.0.0`). Тобто «за замовчуванням» означає
«версія застосунку, під яку писався цей чарт», а не випадково зафіксований тег.

---

## 6. Перевірка та встановлення (пункт 7)

Транскрипт — [`lab-04-output/07-install.txt`](lab-04-output/07-install.txt).

### 7a. Лінт

```bash
$ helm lint chart/cdn-control-plane -f values-dev.yaml
==> Linting chart/cdn-control-plane
[INFO] Chart.yaml: icon is recommended

1 chart(s) linted, 0 chart(s) failed
```

Демо лінтує всі три набори значень — `values.yaml` без оверлея, `values-dev.yaml` і
`values-prod.yaml` — і падає на будь-якому збої. Дефолти перевіряються саме тому, що це
вони працюють при встановленні однією командою на чистому кластері, а помилка в
prod-оверлеї інакше виявилася б лише на кроці 8b, посеред життєвого циклу.

### 7b. Порівняння з маніфестами Лаби 3

Рендер чарта з dev-значеннями дає той самий набір об'єктів, що й `k8s/`: ті самі
Deployment (api, postgresql, redis, agents), ті самі Service, ConfigMap, Secret і PVC.

Дві відмінності — навмисні:

- **Namespace у чарті немає.** Ним володіє `helm install --create-namespace`; чарт, що
  створює власний namespace, не можна поставити у вже наявний.
- **`migrate` і `seed` більше не звичайні Job, а хуки.** `helm template` рендерить їх
  разом з рештою документів — відокремлює їх уже сам Helm під час встановлення, виконуючи
  власною фазою; видно це в `helm get hooks`, а не в рендері. Саме це й було метою (див. §8).

### 7c. Встановлення у власний namespace

```bash
$ helm install cdn chart/cdn-control-plane -f values-dev.yaml \
      -n cdn-helm --create-namespace --wait --timeout 10m
NAME: cdn
STATUS: deployed
REVISION: 1
```

### 7d. Релізи, статус і значення

```bash
$ helm list -n cdn-helm
NAME  NAMESPACE  REVISION  STATUS    CHART                    APP VERSION
cdn   cdn-helm   1         deployed  cdn-control-plane-0.1.0  1.0.0

$ helm get values cdn -n cdn-helm
USER-SUPPLIED VALUES:
api:
  replicaCount: 1
  service:
    nodePort: 30081
    type: NodePort
image:
  tag: 1.0.0
...
```

`helm get values` показує **лише те, що передав користувач**, а не повний злитий набір —
для повного потрібен `helm get values --all`. Це зручно саме тим, що одразу видно, чим
конкретний реліз відрізняється від замовчувань чарта.

### 7e. Де Helm зберігає стан релізу

```bash
$ kubectl get secret -n cdn-helm -l owner=helm
NAME                        TYPE                 DATA   AGE
sh.helm.release.v1.cdn.v1   helm.sh/release.v1   1      24s
```

Один Secret типу `helm.sh/release.v1` **на кожну ревізію**, у namespace самого релізу.
Всередині — gzip-нутий JSON із відрендереними маніфестами й значеннями. Це і є весь стан:
жодного серверного компонента немає — саме Tiller Helm 3 і прибрав. Практичний наслідок:
права на реліз — це звичайні RBAC-права на секрети в цьому namespace, а видалення цих
секретів «забуває» реліз, не чіпаючи самі об'єкти.

---

## 7. Життєвий цикл релізу (пункт 8)

Транскрипт — [`lab-04-output/08-lifecycle.txt`](lab-04-output/08-lifecycle.txt).

### 8a. Оновлення тега через `--set`

```bash
$ helm upgrade cdn chart/cdn-control-plane -f values-dev.yaml \
      --set image.tag=1.1.0 -n cdn-helm --wait
REVISION: 2
```

Перед застосуванням нових подів Helm окремою фазою виконав хук міграції (§8).

### 8b. Оновлення файлом іншого середовища

```bash
$ helm upgrade cdn chart/cdn-control-plane -f values-prod.yaml -n cdn-helm \
      --set api.service.type=NodePort \
      --set postgresql.persistence.size=1Gi --wait
REVISION: 3
```

Реліз переїхав на 3 репліки, продакшн-ресурси і `LOG_LEVEL=WARNING`.

> **Два `--set` тут не косметика, і другий — найцікавіша знахідка роботи.**
> `api.service.type=NodePort` потрібен лише щоб демо могло достукатися до релізу без
> ingress-контролера.
>
> А `postgresql.persistence.size=1Gi` з'явився після реальної помилки. `values-prod.yaml`
> просить 10Gi, тоді як dev-реліз створив претензію на 1Gi, і оновлення впало:
>
> ```
> Error: UPGRADE FAILED: cannot patch "cdn-cdn-control-plane-postgresql" with kind
> PersistentVolumeClaim: ... is forbidden: only dynamically provisioned pvc can be
> resized and the storageclass that provisions the pvc must support resize
> ```
>
> Це обмеження **кластера, а не Helm**: розмір PersistentVolumeClaim фіксується в момент
> її створення, а hostpath-провізіонер minikube розширення не підтримує взагалі. Чистий
> prod-реліз свої 10Gi отримає; вирощити в них наявний реліз правкою значення не можна.
> Урок для захисту: не кожне значення чарта можна безпечно змінити на вже встановленому
> релізі — для сховища потрібна або підтримка resize у StorageClass, або нова претензія.

### 8c. Історія ревізій

```bash
$ helm history cdn -n cdn-helm
REVISION  STATUS      CHART                    APP VERSION  DESCRIPTION
1         superseded  cdn-control-plane-0.1.0  1.0.0        Install complete
2         superseded  cdn-control-plane-0.1.0  1.0.0        Upgrade complete
3         deployed    cdn-control-plane-0.1.0  1.0.0        Upgrade complete
```

Що саме змінювалося:

| Ревізія | Команда | Зміна |
|---|---|---|
| 1 | `helm install -f values-dev.yaml` | тег 1.0.0, 1 репліка, NodePort 30081, seed увімкнено |
| 2 | `helm upgrade --set image.tag=1.1.0` | лише тег образу: 1.0.0 → 1.1.0 |
| 3 | `helm upgrade -f values-prod.yaml` | 3 репліки, продакшн-ресурси, `LOG_LEVEL` DEBUG → WARNING |

Колонка `APP VERSION` всюди `1.0.0`, хоча ревізія 2 ставила образ `1.1.0` — бо це
`Chart.appVersion`, а не фактичний тег. Ще одна ілюстрація різниці з §2: `--set
image.tag` змінює розгорнутий образ, але не версію застосунку, яку **декларує чарт**.

### 8d. Відкат

```bash
$ helm rollback cdn 2 -n cdn-helm --wait
Rollback was a success! Happy Helming!

$ helm history cdn -n cdn-helm
REVISION  STATUS      DESCRIPTION
1         superseded  Install complete
2         superseded  Upgrade complete
3         superseded  Upgrade complete
4         deployed    Rollback to 2       <- відкат як НОВА ревізія
```

Реліз повернувся до 1 репліки. Ревізія 3 не зникла — вона позначена `superseded`, а
відкат дописався як ревізія 4 з описом `Rollback to 2`. Історія — журнал, а не стек:
відкат сам є зміною, яку видно й до якої теж можна відкотитися.

Порівняно з `kubectl rollout undo` з Лаби 3 відмінність принципова. `kubectl` відкочує
**один об'єкт** — Deployment. `helm rollback` відкочує **весь реліз** разом: Deployment,
ConfigMap, Secret, Service й Ingress повертаються до узгодженого між собою стану однієї
ревізії. Саме тому значення й маніфести зберігаються разом у секреті релізу.

### 8e. Видалення однією командою

```bash
$ helm uninstall cdn -n cdn-helm --wait
release "cdn" uninstalled

$ kubectl get all -n cdn-helm
No resources found in cdn-helm namespace.
```

У namespace лишається тільки PVC — **навмисно**: у шаблоні претензії стоїть
`helm.sh/resource-policy: keep`, щоб випадковий `helm uninstall` не знищив базу разом із
даними. Прибрати її — окрема свідома дія `kubectl delete pvc`.

---

## 8. Завдання на вибір — варіант (b): хук і тест релізу (пункт 9)

Транскрипт — [`lab-04-output/09-hook-and-test.txt`](lab-04-output/09-hook-and-test.txt).

### Хук міграції

[`templates/hooks/migrate-job.yaml`](../../chart/cdn-control-plane/templates/hooks/migrate-job.yaml):

```yaml
annotations:
  "helm.sh/hook": post-install,pre-upgrade
  "helm.sh/hook-weight": "-5"
  "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
```

**Навіщо він тут узагалі.** `docker-compose.yml` виконує `alembic upgrade head` окремим
one-shot сервісом саме тому, що при `--scale api=N` кожна репліка інакше кинулася б
накатувати ту саму міграцію на ту саму базу. Compose вміє сказати «спочатку міграція,
потім api» через `depends_on`. **Kubernetes такого ребра не має взагалі**, тож у `k8s/`
міграція — звичайний Job, і порядок там тримається лише на тому, що api не проходить
readiness, доки схеми немає (на холодному кластері це видно як кілька невдалих спроб —
див. §5b звіту Лаби 3). Хук закриває дірку по-справжньому: Helm виконує його окремою
фазою й лише потім застосовує решту релізу.

> **`post-install`, а не `pre-install` — і це головна технічна тонкість роботи.**
> Спершу хук був написаний як `pre-install,pre-upgrade`, що виглядає очевидним читанням
> умови. Але `pre-install`-хуки виконуються **до** створення будь-якого об'єкта релізу,
> тож на першому встановленні Job стукався б у Service PostgreSQL, якого Helm ще не
> створив, вичерпав би `backoffLimit` і завалив би встановлення.
>
> `post-install` працює лише тому, що **readiness не залежить від схеми**:
> `/health/ready` виконує `SELECT 1`, тож поди api стають Ready щойно відповідає
> PostgreSQL, `--wait` задовольняється, і аж тоді хук накатує схему. Якби readiness
> робила запит до реальної таблиці, встановлення зайшло б у глухий кут з іншого боку.
> Висновок, який варто назвати на захисті: **те, що перевіряє readiness-проба, визначає,
> які фази хуків тобі взагалі доступні**.
>
> `pre-upgrade` — це та половина, якої вимагає завдання, і та, що важлива в експлуатації:
> на кожному наступному релізі схема накатується строго перед викочуванням нових подів.

**Про `hook-delete-policy`.** Спершу стояло лише `before-hook-creation` — і після
`helm uninstall` у namespace лишалися Job міграції, Job seed і под тесту, тобто пункт 8e
не виконувався. Додано `hook-succeeded`, а `hook-failed` **свідомо не додано**: успішний
хук прибирає себе сам, і namespace справді порожній, а **невдалий лишається** — рівно
тоді, коли його логи й потрібні.

Оскільки успішний Job одразу зникає, демо доводить виконання хука двома незалежними
слідами, що переживають його видалення:

```bash
$ helm get hooks cdn -n cdn-helm      # реліз декларує хук, з фазою і вагою
"helm.sh/hook": post-install,pre-upgrade

$ kubectl get events -n cdn-helm --sort-by=.lastTimestamp
53s  Normal  Completed  job/cdn-cdn-control-plane-migrate  Job completed   <- post-install
47s  Normal  Completed  job/cdn-cdn-control-plane-seed     Job completed
36s  Normal  Completed  job/cdn-cdn-control-plane-migrate  Job completed   <- pre-upgrade
```

Два записи `migrate` — це обидві фази: один при встановленні, другий перед оновленням.

### Тест релізу

[`templates/tests/test-api-ready.yaml`](../../chart/cdn-control-plane/templates/tests/test-api-ready.yaml)
— под з анотацією `"helm.sh/hook": test`, який ходить по `/health`, `/health/ready` і
`/api/v1/stats/network`.

```bash
$ helm test cdn -n cdn-helm --logs
TEST SUITE:     cdn-cdn-control-plane-test-api-ready
Phase:          Succeeded
```

У транскрипті після цього стоїть `Error: unable to get pod logs ... not found` — і це
очікувана ціна пункту 8e. `hook-delete-policy` містить `hook-succeeded`, тож под тесту
зникає одразу після успіху, раніше, ніж Helm устигає забрати його логи; на статус
`Succeeded` це не впливає. Логи потрібні рівно в протилежному випадку — коли тест
**падає**, а такий под лишається, бо `hook-failed` свідомо не додано.

Тест доводить більше, ніж «поди в статусі Running». Він ходить **через Service**, тож
мають бути правильними DNS, селектор, список endpoint-ів і readiness-гейт; а
`/health/ready` виконує `SELECT 1`, тож зелений тест означає, що реліз справді дістає
свою базу. Окремий образ для цього не потрібен: у застосунковому образі вже є `curl` —
його ставить `docker/Dockerfile` заради власного `HEALTHCHECK`.

---

## 9. Скріншоти для захисту

1. `helm version` — саме 3.x (вимога 1a).
2. `helm lint` і дві команди `helm template` поруч, із видимою різницею dev/prod
   (вимоги 7a, 6b).
3. Термінал із `helm install ... --create-namespace --wait` і виводом `NOTES.txt`
   (вимоги 7c, 5c).
4. `helm list -n cdn-helm` + `helm get values cdn -n cdn-helm` (вимога 7d).
5. `kubectl get secret -n cdn-helm -l owner=helm` — секрети `helm.sh/release.v1`
   по одному на ревізію (вимога 7e).
6. `helm history cdn -n cdn-helm` **до** і **після** `helm rollback`, щоб було видно
   ревізію 4 з описом `Rollback to 2` (вимоги 8c, 8d).
7. `helm test cdn -n cdn-helm --logs` зі статусом `Phase: Succeeded` (вимога 9).
8. `helm uninstall` і наступний `kubectl get all -n cdn-helm` із
   `No resources found` (вимога 8e).
9. Підсумкова PASS-таблиця `./scripts/devops_lab4_demo.ps1` — 14 перевірок.
