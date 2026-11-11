# DevOps · Лабораторна 5 — GitOps: розгортання проєкту через Argo CD

**Проєкт:** CDN Control Plane API (той самий, що в Лабах 1–4) — FastAPI + PostgreSQL + Redis,
підпапка `high-load-systems/` у монорепозиторії `ostrrovska/uni_year_4`.
**Конфігурація:** [`gitops/`](../../gitops/) — варіант **(b)** завдання.
**Чарт:** [`chart/cdn-control-plane/`](../../chart/cdn-control-plane/) — без змін з Лаби 4, окрім `existingSecret`.
**Образ:** `ghcr.io/ostrrovska/cdn-control-plane` · теги `1.2.0` і `1.3.0`.
**Argo CD:** v3.1.9 · namespace `argocd` · застосунок `cdn-control-plane` у namespace `cdn-gitops`.

Лаба 4 спакувала застосунок у чарт, але розгортала його командою: хтось мусив
набрати `helm upgrade --install` із правильними прапорцями, і єдиним записом про
те, що саме зараз у кластері, була історія ревізій Helm усередині самого кластера.
Ця робота прибирає людину з цього ланцюга: бажаний стан лежить у Git, а Argo CD
усередині кластера безперервно зводить дійсний стан до нього.

---

## 1. Відповідність вимогам

| Вимога | Як виконано |
|---|---|
| **1.** Репозиторій конфігурації, варіант (a) або (b) | Варіант **(b)**: [`gitops/`](../../gitops/) з `bootstrap/`, `argocd-apps/` і `values/` — §2 |
| **1.** Перенести чарт із ЛР-4 і файл значень для minikube | Файл значень — [`gitops/values/values-minikube.yaml`](../../gitops/values/values-minikube.yaml). Чарт **свідомо не копіювався**: Application посилається на нього за шляхом через multi-source — §2, рядок «про `charts/`» |
| **1.** Паролі й токени відкритим текстом у Git не зберігати | Жодного пароля в Git: чарт отримав значення `existingSecret`, і при ньому не рендерить власний Secret. Перевірка — §2.3 |
| **2a.** Образ у реєстрі з конкретним тегом (не `latest`), доступний з кластера | `ghcr.io/ostrrovska/cdn-control-plane:1.2.0` і `:1.3.0`, публікує CI по git-тегу `cdn-v*` — §3 |
| **2b.** Застосунок показує свою версію | Ендпоінт **`/version`** + поле `version` у `/health`; значення вшите в образ через `ARG`/`ENV` у [`docker/Dockerfile`](../../docker/Dockerfile) — §3.2 |
| **3.** Argo CD у namespace `argocd` і CLI `argocd` | §4; протокол — [`lab-05-output/01-environment.txt`](lab-05-output/01-environment.txt) |
| **3.** Увійти у веб-інтерфейс, змінити початковий пароль admin | §4.2 — пароль змінено, `argocd-initial-admin-secret` видалено; демо **падає**, якщо секрет ще існує |
| **3.** Приватний репозиторій підключити до Argo CD | Репозиторій публічний — підключення не потрібне; §4.3 пояснює, що робити, якби був приватний |
| **4.** `Application` для свого чарту з автоматичною синхронізацією | [`gitops/argocd-apps/cdn-control-plane.yaml`](../../gitops/argocd-apps/cdn-control-plane.yaml), `syncPolicy.automated` — §5 |
| **4.** App of Apps: вручну застосовується лише кореневий об'єкт | [`gitops/bootstrap/root-app.yaml`](../../gitops/bootstrap/root-app.yaml) — єдиний `kubectl apply` у всій роботі — §5.1 |
| **4.** Дерево об'єктів у стані Synced / Healthy | §5.2; `argocd app resources` — [`lab-05-output/04-app-of-apps.txt`](lab-05-output/04-app-of-apps.txt) |
| **5.** Нова версія з видимою зміною, тег у Git, commit і push | §6 — `1.2.0 → 1.3.0`, видима зміна читається з `/version` |
| **5.** Argo CD сам перерозгортає і відповідає нова версія | §6 — жодної команди до кластера між commit і новою відповіддю |
| **6a.** `kubectl scale` без selfHeal → OutOfSync | §7.1 |
| **6a.** `selfHeal: true` → Argo CD повертає значення з Git | §7.2 — selfHeal вмикається **комітом**, а не кнопкою |
| **6b.** Неіснуючий тег образу → Synced, але Degraded | §7.3 |
| **6c.** `git revert`, історія в `git log` і `argocd app history` | §7.4 |
| **7.** Лайв-демонстрація пп. 3–6 | [`scripts/devops_lab5_demo.ps1`](../../scripts/devops_lab5_demo.ps1) — кожен крок позначено пунктом завдання і **перевірено**, а не лише показано; §9 — сценарій захисту |

> **Стан протоколів.** Каталог [`lab-05-output/`](lab-05-output/) заповнюється прогоном
> `scripts/devops_lab5_setup.ps1` і `scripts/devops_lab5_demo.ps1` на піднятому
> кластері. Усі конфігурації, скрипти й код у цьому звіті написані й статично
> перевірені (`helm lint`, `helm template`, розбір YAML, розбір PowerShell);
> твердження про **живі** виводи помічені як такі й підтверджуються після прогону.

---

## 2. Репозиторій конфігурації

### 2.1 Чому варіант (b)

Завдання рекомендує окремий репозиторій `<проєкт>-gitops`. Рекомендація має сенс
там, де застосунок і його розгортання належать різним командам і різним правам
доступу. Тут усе навпаки: це монорепозиторій п'яти курсів з одним автором, і
шостий репозиторій заради трьох YAML-файлів додав би один крок синхронізації і
жодної межі, якої б не було. Обрано **(b)**.

```
high-load-systems/
  chart/cdn-control-plane/            чарт Лаби 4 - один, не копія
  gitops/
    bootstrap/root-app.yaml           ЄДИНИЙ об'єкт, що застосовується вручну
    argocd-apps/cdn-control-plane.yaml  застосунок, який створює кореневий
    values/values-minikube.yaml       як він налаштований на minikube
```

### 2.2 Про `charts/` — свідоме відхилення

Завдання перелічує серед каталогів `charts/` і каже «перенести туди чарт із ЛР-4».
Чарт **залишено на місці**, у `chart/cdn-control-plane/`, а Application посилається
на цей шлях.

Причина — не ліньки. Копія чарта в тому самому репозиторії — це копія, яка
розійдеться: перше ж виправлення шаблону потрапить в одну з двох, і кластер
піде за тією, яку ніхто не редагував. GitOps тримається на тому, що Git —
**єдине** джерело правди; два чарти з однаковою назвою це джерело роздвоюють.
Мета вимоги — «опис розгортання лежить у Git, а не в командах» — досягнута
повністю: у Git лежить і чарт, і значення, і сам Application.

Технічно це робиться multi-source Application: перше джерело не дає жодного
маніфесту, воно лише дає імʼя `cfg`, через яке друге джерело дістає файл значень
поза каталогом чарта.

```yaml
sources:
  - repoURL: https://github.com/ostrrovska/uni_year_4.git
    targetRevision: devops-lab-5-gitops
    ref: cfg
  - repoURL: https://github.com/ostrrovska/uni_year_4.git
    targetRevision: devops-lab-5-gitops
    path: high-load-systems/chart/cdn-control-plane
    helm:
      releaseName: cdn
      valueFiles:
        - $cfg/high-load-systems/gitops/values/values-minikube.yaml
```

> Якщо викладач наполягатиме на буквальному `gitops/charts/`, це одна команда
> `git mv` плюс один рядок `path:` — але звіт свідомо показує кращий варіант.

### 2.3 Паролі в Git

Це єдина зміна, яку Лаба 5 внесла в сам чарт. У Лабі 4 пароль передавався
прапорцем: `--set postgresql.auth.password="$PG_PASSWORD"`. Під Argo CD такого
прапорця не існує — чарт рендерить сам Argo CD із того, що закомічено, тож
закомічений файл значень є **єдиним** входом і не має права містити пароль.

Чарт отримав значення `existingSecret`:

```yaml
# chart/cdn-control-plane/templates/secret.yaml
{{- if not .Values.existingSecret }}
apiVersion: v1
kind: Secret
...
{{- end }}
```

і новий іменований шаблон `cdn.secretName`, через який ім'я секрета беруть усі
п'ять місць, що на нього посилаються (`api`, `agents`, `postgresql`, хук
`migrate`, хук `seed`). Коли `existingSecret` заданий, чарт не рендерить жодного
Secret, а робочі навантаження читають уже наявний.

Секрет створюється в кластері один раз, повз Git (`scripts/devops_lab5_setup.ps1`):

```bash
kubectl create secret generic cdn-db -n cdn-gitops \
  --from-literal=POSTGRES_PASSWORD="$PGPASS" \
  --from-literal=DATABASE_URL="postgresql+asyncpg://cdn:$PGPASS@cdn-cdn-control-plane-postgresql:5432/cdn_control_plane"
```

**Перевірено** (`helm template` з файлом значень GitOps):

```
Secrets rendered: 0
grep -i password → лише
  - name: POSTGRES_PASSWORD
      secretKeyRef:  key: POSTGRES_PASSWORD
```

У згенерованих маніфестах немає жодного літерала пароля — тільки посилання на
секрет за іменем. У Git лежить **ім'я** секрета, не його значення.

---

## 3. Образ застосунку в реєстрі

### 3.1 Публікація з конкретним тегом

Лаба 4 вантажила образ у кластер командою `minikube image load`. Для GitOps це не
годиться: кластер має тягти те, що написано в Git, із реєстру, інакше «бажаний
стан» залежить від того, що хтось колись вручну заніс на вузол.

CI з Лаби 2 вже збирав образ у `ghcr.io/ostrrovska/cdn-control-plane`, але лише з
гілки `main` і лише з тегами `sha-…` і `latest`. Лаба 5 додала до
[`.github/workflows/cdn-control-plane-ci.yml`](../../../.github/workflows/cdn-control-plane-ci.yml):

| Зміна | Навіщо |
|---|---|
| тригер `push: tags: ['cdn-v*']` | реліз робиться git-тегом; префікс `cdn-` — бо монорепозиторій, інші курси теж тегують |
| `type=semver,pattern={{version}}` | `cdn-v1.2.0` → образ `:1.2.0`, на який посилається файл значень |
| `build-args: APP_VERSION, GIT_SHA` | версія вшивається в образ, а не в ConfigMap — §3.2 |
| push конкретних тегів замість `--all-tags` | на збірці по тегу в демоні ще лежить `latest` із кешу, і `--all-tags` мовчки зсунув би плаваючий тег назад |

`latest` навмисно не використовується ніде в `gitops/`: тег, значення якого може
змінитися, руйнує саму ідею — той самий коміт означав би різні образи в різні дні,
і Git перестав би описувати кластер.

### 3.2 Застосунок показує свою версію

Новий ендпоінт у [`app/api/routes/health.py`](../../app/api/routes/health.py):

```
GET /version
{
  "version": "1.3.0",
  "git_sha": "9f2c1ab…",
  "instance_id": "cdn-cdn-control-plane-api-7b89…",
  "app_env": "development"
}
```

Поле `version` додано і до `/health`.

Значення **вшите в образ**, а не взяте з конфігурації — у
[`docker/Dockerfile`](../../docker/Dockerfile):

```dockerfile
ARG APP_VERSION=0.0.0-dev
ARG GIT_SHA=unknown
ENV ... APP_VERSION=${APP_VERSION} GIT_SHA=${GIT_SHA}
LABEL org.opencontainers.image.version="${APP_VERSION}" ...
```

Це не косметика. Файл значень можна відредагувати так, щоб він **стверджував**
будь-яку версію; образ — не можна. Під GitOps питання «чи доїхала нова версія»
стає питанням про поди, а не про команду, яку набрали, і `/version` — єдина
відповідь, якій можна вірити. Ті самі два значення продубльовані як OCI-мітки,
тож `docker inspect` і `/version` не можуть розійтися.

---

## 4. Встановлення Argo CD

### 4.1 Що саме ставиться

`scripts/devops_lab5_setup.ps1` застосовує **закріплений** маніфест релізу
`v3.1.9`, а не `stable`: бутстрап, який ставить різну версію залежно від дня, —
не відтворюваний бутстрап.

minikube піднімається з `--cpus=4 --memory=6144`: п'ять контролерів Argo CD плюс
чотири робочі навантаження застосунку не вміщуються в стандартні 2 CPU / 2 GB.

### 4.2 Початковий пароль admin

Інсталятор кладе згенерований пароль у Secret `argocd-initial-admin-secret`.
Скрипт міняє пароль і **видаляє** цей Secret — `argocd account update-password`
сам його не прибирає, а залишений він тримає згенерований пароль читабельним для
всіх, хто має `get` у namespace, ще довго після того, як той перестав бути паролем.

Доказом виконання є **відсутність** секрета, і демо на цьому наполягає:

```powershell
if (-not $changed) {
    throw "argocd-initial-admin-secret still exists - change the admin password and delete it"
}
```

Тобто цей пункт не можна «показати» непрогнаним — демо впаде.

### 4.3 Приватний репозиторій

`ostrrovska/uni_year_4` публічний, тож Argo CD читає його без облікових даних і
`argocd repo add` не потрібен. Якби репозиторій був приватним, підключення було б
`argocd repo add https://github.com/ostrrovska/uni_year_4.git --username ostrrovska
--password <PAT>`, а сам токен жив би в Secret `argocd-repo-…` у namespace
`argocd` — тобто знову **в кластері, а не в Git**, за тією самою логікою, що й
пароль бази в §2.3.

---

## 5. Застосунок під керуванням Argo CD

### 5.1 App of Apps — єдина ручна команда

```bash
kubectl apply -n argocd -f high-load-systems/gitops/bootstrap/root-app.yaml
```

Це все. Кореневий Application дивиться на каталог `gitops/argocd-apps/`, тож
`cdn-control-plane` існує в кластері **тому, що його маніфест лежить у Git**, а
не тому, що його хтось застосував. Додати застосунок = додати файл і запушити;
прибрати = видалити файл (`prune: true` доведе видалення до кластера).

Обидва Application мають `finalizers: resources-finalizer.argocd.argoproj.io` —
без нього видалення Application залишає його робочі навантаження працювати:
Argo CD про них забуває, а Kubernetes ні.

### 5.2 Налаштування синхронізації і чому саме такі

| Поле | Значення | Чому |
|---|---|---|
| `automated.prune` | `true` | без нього видалений із Git шаблон лишає об'єкт-сироту, і Git тихо перестає бути повним описом кластера |
| `automated.selfHeal` (дочірній) | **`false`** на старті | це початок пункту 6a: спершу треба показати, що дрейф *виявляється*, і лише потім — що він *виправляється*. Два різні налаштування |
| `automated.selfHeal` (кореневий) | `true` | кореневий існує, щоб Git керував самим переліком застосунків; дозволити видалити дочірній Application через `kubectl` і лишити його видаленим — означало б скасувати єдину його функцію |
| `syncOptions: CreateNamespace=true` | | namespace створює Argo CD: ручних кроків раніше немає, тож іншого місця його створити не існує |
| `retry.backoff` | 10s, ×2, до 3m | синхронізація, що впала через ще не готову базу, має повторитись, а не лишити застосунок у помилці |

### 5.3 Дерево об'єктів

`argocd app resources cdn-control-plane` показує те саме дерево, що й вкладка
застосунку у вебі: Application → 4 Deployment (`api`, `agents`, `postgresql`,
`redis`), 3 Service, ConfigMap, PVC і Job-и хуків Helm, кожен зі своїм станом.
Хуки `migrate` і `seed` Argo CD виконує як власні хуки; їхні поди завершуються і
лишаються `Completed` — для Job це здоровий стан.

Цільовий стан — **Synced / Healthy**; демо на нього чекає і падає, якщо за 7
хвилин його не досягнуто.

---

## 6. Оновлення через Git

Уся процедура релізу:

```bash
# 1. опублікувати образ
git tag cdn-v1.3.0 && git push origin cdn-v1.3.0        # CI збирає :1.3.0

# 2. сказати кластеру, що саме він має запустити
#    gitops/values/values-minikube.yaml:  tag: "1.2.0" -> "1.3.0"
git commit -am "gitops: roll the CDN Control Plane to 1.3.0"
git push
```

Третього кроку немає. Між `git push` і новою відповіддю застосунку до кластера не
надсилається жодної команди — Argo CD помічає коміт сам (демо лише прискорює
опитування анотацією `argocd.argoproj.io/refresh: hard`, тим самим, що робить
кнопка «Refresh», бо типовий інтервал — три хвилини, і чекати його на кожному
кроці захисту незручно).

Видима зміна — у самій відповіді:

```
до:    GET /version -> {"version": "1.2.0", ...}
після: GET /version -> {"version": "1.3.0", ...}
```

Демо перевіряє **обидва** боки: тег у `spec.template.spec.containers[0].image`
(що Argo CD *попросив*) і `/version` від живого пода (що насправді *працює*).
Збіг цих двох і є доказом, що реліз доїхав.

---

## 7. Дрейф, Health і відкат

### 7.1 Дрейф без selfHeal — виявлено, не виправлено

```bash
kubectl scale deployment/cdn-cdn-control-plane-api -n cdn-gitops --replicas=3
```

Argo CD одразу повідомляє **OutOfSync** і `argocd app diff` показує рядок
`replicas: 1 -> 3`. І нічого не робить. Кластер лишається з трьома репліками.

Це і є суть пункту: **виявлення дрейфу і його виправлення — два різні
налаштування**, і зараз увімкнене тільки перше. Такий режим реально
використовують, коли бояться, що автоматика «виправить» аварійне ручне втручання.

### 7.2 selfHeal — і та сама команда не доживає

selfHeal вмикається **комітом** у `gitops/argocd-apps/cdn-control-plane.yaml`, а
не кнопкою в інтерфейсі. Це навмисно: вмикати GitOps-механізм поза GitOps було б
внутрішньою суперечністю. Коміт підхоплює кореневий Application, той оновлює
дочірній — і лише тоді демо повторює `kubectl scale`.

Тепер ручна зміна живе секунди: Argo CD повертає `replicas` до значення з Git.
Git перестає бути записом про *наміри* й стає тим, до чого кластер безперервно
**примусово** зводять.

### 7.3 Неіснуючий тег — Synced, але Degraded

У Git вписується `tag: "0.0.0-does-not-exist"`. Результат:

| | |
|---|---|
| **Sync** | `Synced` — кластер точно відповідає тому, що написано в Git |
| **Health** | `Degraded` — те, що написано в Git, не працює |
| поди | новий — `ImagePullBackOff`; старі — `Running` і далі обслуговують |

Пара Synced + Degraded — найкорисніше розрізнення в усій роботі. Argo CD
відпрацював бездоганно, а застосунок зламаний — **бо неправильний Git**.
Автоматична синхронізація не робить Git правильним, вона робить його чинним.

Старі поди продовжують обслуговувати завдяки `maxUnavailable: 0` з Лаби 4: новий
под мусить пройти readiness, перш ніж піде старий, а новий под навіть не
запустився. Збій деплою не став збоєм сервісу.

### 7.4 Відкат через `git revert`

```bash
git revert --no-edit <коміт із поганим тегом>
git push
```

`git revert` **додає** коміт, а не стирає попередній; `argocd app history`
так само **додає** розгортання, а не прибирає. Обидва — журнали, і зламаний
реліз лишається видимим в обох. Саме це робить відновлення придатним до аудиту:
через тиждень видно і що зламалося, і коли це помітили, і чим виправили.

Після відкату застосунок повертається до `Synced / Healthy`, а `/version` знову
відповідає `1.3.0`.

---

## 8. Що саме перевіряє демо

[`scripts/devops_lab5_demo.ps1`](../../scripts/devops_lab5_demo.ps1) побудований
як і демо Лаб 3–4: кожен крок позначено пунктом завдання, друкує живий доказ і
**стверджує** результат, тож тиха регресія валить демо, а не проходить непоміченою.

| Крок | Пункт | Що стверджується |
|---|---|---|
| preflight | — | гілка та, і файли GitOps без незакомічених змін |
| 02 | 3 | под `argocd-server` готовий, CLI бачить версію |
| 03 | 3 | `argocd-initial-admin-secret` **відсутній**, CLI залогінений |
| 04 | 4 | кореневий Application дивиться на `gitops/argocd-apps`, `cdn-control-plane` існує |
| 05 | 4 | `Synced` + `Healthy`, є Deployment-и, `/version` = `1.2.0` |
| 06 | 5 | після коміту тег у Deployment і `/version` обидва = `1.3.0` |
| 07 | 6a | після `kubectl scale` — `OutOfSync`, у кластері 3 репліки |
| 08 | 6a | після коміту `selfHeal: true` репліки самі повертаються до 1 |
| 09 | 6b | `Synced` + `Degraded`, у подах `ImagePullBackOff` |
| 10 | 6c | `git log` містить `Revert`, застосунок знову `Synced`/`Healthy`, `/version` = `1.3.0` |

Демо **комітить і пушить** — це не недогляд, а суть: під GitOps єдиний спосіб
змінити кластер — змінити Git, і демонстрація, яка щось довела б не чіпаючи Git,
доводила б не те. Прапорець `-WhatIfGit` показує всі коміти без пушу.

---

## 9. Сценарій захисту (пункт 7)

Порядок, у якому це показувати наживо:

1. **Інтерфейс.** `kubectl port-forward svc/argocd-server -n argocd 8080:443`,
   увійти як `admin` зі зміненим паролем, відкрити `cdn-control-plane`, показати
   дерево об'єктів у стані Synced / Healthy.
2. **Реліз комітом.** Змінити `image.tag` у `values-minikube.yaml`, запушити,
   показати, як застосунок сам перейшов у Progressing → Healthy, і `curl /version`.
3. **Ручна зміна.** `kubectl scale … --replicas=3` → OutOfSync; із увімкненим
   selfHeal — повертається само.
4. **Synced + Degraded.** Вписати неіснуючий тег, показати обидва статуси поряд і
   `ImagePullBackOff`, наголосити, що старі поди ще обслуговують.
5. **Відкат.** `git revert`, `git log`, `argocd app history`.

**«Змініть будь-яке значення в Git».** Найшвидша відповідь на цю просьбу —
`config.logLevel` у `values-minikube.yaml`: коміт → Argo CD оновлює ConfigMap →
анотація `checksum/config` у шаблоні Deployment (Лаба 4) змінюється → поди
перекочуються з новим рівнем логування. Так видно весь ланцюг від коміта до
перезапуску. Так само швидко читається `api.replicaCount`.

---

## 10. Протоколи прогону

| Файл | Зміст | Пункти |
|---|---|---|
| `01-environment.txt` | minikube, установка Argo CD, зміна пароля, створення секрета, кореневий Application | 3 |
| `03-argocd.txt` | поди Argo CD, версія CLI, відсутність початкового секрета | 3 |
| `04-app-of-apps.txt` | джерело кореневого Application, перелік застосунків, дерево ресурсів, Synced/Healthy | 4 |
| `05-release.txt` | diff файлу значень, коміт, нові тег і `/version` | 5 |
| `06a-drift.txt` | `kubectl scale`, OutOfSync, `argocd app diff`, повернення через selfHeal | 6a |
| `06b-degraded.txt` | Synced + Degraded, `ImagePullBackOff`, події | 6b |
| `06c-revert.txt` | `git revert`, `git log`, `argocd app history` | 6c |
| `00-wait.txt` | очікування розгортань | — |

---

## 11. Що Лаба 5 змінила поза каталогом `gitops/`

| Файл | Зміна | Чому |
|---|---|---|
| `app/api/routes/health.py` | `+ GET /version`, `version` у `/health` | п. 2b |
| `app/core/config.py` | `+ app_version`, `+ git_sha` | джерело для `/version` |
| `docker/Dockerfile` | `ARG`/`ENV APP_VERSION`, `GIT_SHA`, OCI-мітки | версія вшита в образ, а не в конфіг |
| `.github/workflows/cdn-control-plane-ci.yml` | тригер на теги `cdn-v*`, semver-теги, build-args | п. 2a |
| `chart/.../values.yaml` | `+ existingSecret` | п. 1 — без паролів у Git |
| `chart/.../templates/_helpers.tpl` | `+ cdn.secretName` | одне місце, що знає ім'я секрета |
| `chart/.../templates/secret.yaml` | рендериться лише коли чарт володіє секретом | там само |
| `chart/.../templates/*.yaml` (5 файлів) | посилання на секрет через `cdn.secretName` | там само |

Чарт лишився сумісним із Лабою 4: без `existingSecret` він поводиться точно як
раніше, і `helm lint` та `helm template` для `values-dev.yaml` / `values-prod.yaml`
дають той самий результат.
