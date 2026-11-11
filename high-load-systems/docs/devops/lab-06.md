# DevOps · Лабораторна 6 — Progressive delivery: canary з Argo Rollouts

**Проєкт:** CDN Control Plane API (той самий, що в Лабах 1–5) — FastAPI + PostgreSQL + Redis.
**Репозиторій конфігурації:** [`gitops/`](../../gitops/) з ЛР-5, гілка `devops-lab-6-rollouts`.
**Контролер:** Argo Rollouts v1.10.2 (чарт `argo-rollouts` 2.43.12) у namespace `argo-rollouts`.
**Обраний варіант:** **(a) canary**. Blue-green реалізований у чарті й вмикається зміною значень — §3.3.
**Образи:** `ghcr.io/ostrrovska/cdn-control-plane` · `1.3.0` (стабільний), `1.4.0` (реліз), `1.5.0` (скасований).

> **Стан протоколів.** Усе нижче прогнано на живому кластері: minikube, Argo CD
> v3.1.9, Argo Rollouts v1.10.2, образи з GHCR. Демо пройшло **всі 8 перевірок**
> (`8 checks passed`), протоколи — у [`lab-06-output/`](lab-06-output/).
> Прогін також знайшов два дефекти, обидва виправлені й описані: вичерпання
> ресурсів вузла (§7a) і той самий замок синхронізації, що в ЛР-5 (§5.2).

Лаба 5 зробила розгортання автоматичним: коміт у Git — і кластер сам приходить до
описаного стану. Але «автоматично» там означало «негайно і повністю»: Deployment
замінював усі поди так швидко, як дозволяли його налаштування, і єдиним способом
дізнатися, що нова версія зламана, було дочекатися, коли вона вже скрізь. Ця
робота вставляє в цей шлях **кроки й ворота**: новий образ спершу отримує 20%
трафіку, зупиняється і чекає на людину.

---

## 1. Відповідність вимогам

| Вимога | Як виконано |
|---|---|
| **1.** Контролер Argo Rollouts — застосунок у `argocd-apps/` | [`gitops/argocd-apps/argo-rollouts.yaml`](../../gitops/argocd-apps/argo-rollouts.yaml); кореневий `root` підхопив його сам — §2.1 |
| **1.** `sync-wave: "-1"` — раніше за застосунки | Є; демо **перевіряє** значення анотації, а не лише наявність |
| **1.** Актуальна версія чарта в `targetRevision` | `2.43.12` (Argo Rollouts v1.10.2), визначено через `helm search repo argo/argo-rollouts` — §2.1 |
| **1.** Окремий коміт, дочекатися Healthy, лише тоді Rollout | Саме так і зроблено: коміт `1607885` (контролер) → Healthy + CRD → коміт `2bbcee9` (Rollout) — §2.2 |
| **1.** `retry` у `syncPolicy` застосунку | Був ще з ЛР-5: `limit: 5`, backoff 10s ×2 до 3m |
| **1.** Плагін `kubectl argo rollouts` | v1.10.2, Windows-бінарник у `%LOCALAPPDATA%\Programs\k8stools` |
| **2.** `deployment.yaml` під умовою `{{- if not .Values.rollout.enabled }}` | [`api-deployment.yaml`](../../chart/cdn-control-plane/templates/api-deployment.yaml) — §3.1 |
| **2.** Створити `templates/rollout.yaml` | [`rollout.yaml`](../../chart/cdn-control-plane/templates/rollout.yaml) — §3.1 |
| **2.** Блок `template:` — той самий, що в Deployment | **Не копія, а спільний шаблон** `cdn.apiPodTemplate`; перевірено, що рендер байт-у-байт однаковий — §3.2 |
| **2.** Збільшити `version` у `Chart.yaml` | `0.1.0 → 0.2.0`: змінилася упаковка, не застосунок |
| **3.** Стратегія: canary або blue-green | **(a) canary**: 20 → pause → 60 → 80; `replicaCount: 5` — §3.3 |
| **3.** blue-green: другий Service | [`api-service-preview.yaml`](../../chart/cdn-control-plane/templates/api-service-preview.yaml) — рендериться лише під blueGreen; §3.3 |
| **4.** Реліз через Git: новий тег, push | §4 — `1.3.0 → 1.4.0` одним комітом |
| **4.** Пауза: `Health Status: Suspended` | §4.1 — заміряно |
| **4.** Canary: запити **зсередини кластера** | §4.2 — под `curlimages/curl` через Service; чому не port-forward — там само |
| **4.** `promote` | §4.3 |
| **5.** Скасування: `abort` → Synced + Degraded | §5.1 |
| **5.** Завершення через `git revert` | §5.2 |
| **6.** Захист: лайв-демонстрація | [`scripts/devops_lab6_demo.ps1`](../../scripts/devops_lab6_demo.ps1) — **8/8 перевірок пройдено** на живому кластері; сценарій — §7 |

---

## 2. Контролер Argo Rollouts через Argo CD

### 2.1 Ще один Application, і нічого більше

Контролер приходить тим самим шляхом, що й усе інше: файл у `gitops/argocd-apps/`,
який підхоплює кореневий Application. Жодного `helm install`, жодного
`kubectl apply` — **ручних команд у цій роботі немає взагалі**, бо кореневий
об'єкт було застосовано ще в ЛР-5.

Це перший у репозиторії Application, чиє джерело — **сторонній Helm-репозиторій**,
а не цей проєкт. У цьому й сенс абстракції: Argo CD байдуже, звідки чарт.

```yaml
source:
  repoURL: https://argoproj.github.io/argo-helm
  chart: argo-rollouts
  targetRevision: 2.43.12
```

Версія **закріплена**, а не діапазон: уся передумова GitOps у тому, що Git описує
кластер, а «той чарт, який репозиторій віддає сьогодні» не описує нічого.

Дві свідомі зміни типових значень:

| Значення | Навіщо |
|---|---|
| `controller.replicas: 1` | друга репліка — резерв для leader election; на однвузловому кластері з 3 ГБ вона не дає нічого, а ~100 МіБ потрібні п'яти канарковим реплікам |
| `dashboard.enabled: true` | за замовчуванням вимкнений, а п.4 завдання вимагає `kubectl argo rollouts dashboard` |
| `ServerSideApply=true` | чарт везе CRD; великий CRD не застосовується через `kubectl apply`, бо той кладе весь маніфест у `last-applied-configuration` і впирається в ліміт 262144 байти |

### 2.2 Порядок: спершу CRD, потім те, що їх використовує

`sync-wave: "-1"` ставить контролер попереду `cdn-control-plane` (у того анотації
немає, тож він на хвилі 0). Це не формальність: застосунок, чиї маніфести містять
`kind: Rollout`, **не може** синхронізуватися, поки CRD не існує — падає з
`no matches for kind "Rollout"`.

Методичка радить додати контролер окремим комітом і дочекатися Healthy, перш ніж
комітити Rollout. Зроблено буквально:

```
1607885  devops: lab 6 - install Argo Rollouts as an Application
         -> argo-rollouts Synced/Healthy, CRD rollouts.argoproj.io з'явився
2bbcee9  devops: lab 6 - the API becomes an Argo Rollout, canary strategy
```

Хвиля й `retry` — два незалежні запобіжники: перша задає порядок, другий рятує,
якщо застосунок усе ж прийшов раніше.

---

## 3. Rollout у Helm-чарті

### 3.1 Два об'єкти, один під

`api-deployment.yaml` тепер рендериться **лише** коли `rollout.enabled` хибний:

```
{{- if not .Values.rollout.enabled }}
```

Умова не косметична. Deployment і Rollout з одним селектором — це два
контролери, що керують одними подами, і кожен відкочує роботу іншого. Демо це
**перевіряє**: шукає Deployment з іменем Rollout-а і падає, якщо знаходить.

### 3.2 Шаблон пода не копіюється — і це свідоме відхилення

Методичка каже: «Блок `template:` скопіюйте з `deployment.yaml` без змін».
Я цього не зробив. Шаблон пода (66 рядків: проби, `preStop`, `envFrom`,
контрольні суми конфігу) винесено в іменований шаблон `cdn.apiPodTemplate` у
[`_helpers.tpl`](../../chart/cdn-control-plane/templates/_helpers.tpl), і обидва
об'єкти його `include`:

```yaml
  template:
    {{- include "cdn.apiPodTemplate" . | nindent 4 }}
```

Причина та сама, що з чартом у ЛР-5: дві копії розходяться. Перше ж виправлення
проби потрапить в одну з них, і тоді лише одна описує те, що справді працює —
причому саме та, яку ніхто не редагував. А тут розбіжність була б ще підступнішою:
`rollout.enabled` вирішує, **який з двох** об'єктів узагалі існує, тож застаріла
копія мовчить, доки хтось не перемкне прапорець.

**Перевірено:** рендер `spec.template` у Deployment (`values-dev.yaml`) і в Rollout
(ті самі значення + `--set rollout.enabled=true`) — **байт-у-байт однаковий**.

У Rollout свідомо **немає** `progressDeadlineSeconds` з `api` і
`strategy.rollingUpdate`: у Rollout є власні однойменні поля, і залишені
Deployment-івські налаштування тихо не робили б нічого.

### 3.3 Стратегія — значення, а не шаблон

`templates/rollout.yaml` передає стратегію наскрізь:

```yaml
  strategy:
    {{- toYaml .Values.rollout.strategy | nindent 4 }}
```

Тому вибір між canary і blue-green — **зміна файла значень і нічого більше**.
Обрано варіант **(a) canary**:

```yaml
api:
  replicaCount: 5
rollout:
  enabled: true
  strategy:
    canary:
      steps:
        - setWeight: 20
        - pause: {}            # чекати людину
        - setWeight: 60
        - pause: {duration: 30s}
        - setWeight: 80
        - pause: {duration: 30s}
```

**Чому саме п'ять реплік.** Без service mesh Argo Rollouts виражає вагу канарки
як частку кількості реплік, і один Service стоїть перед обома версіями.
`setWeight: 20` від п'яти — рівно один канарковий под, тобто приблизно кожна
п'ята відповідь нова. З однією реплікою «20%» не має куди лягти.

Blue-green теж реалізований: [`api-service-preview.yaml`](../../chart/cdn-control-plane/templates/api-service-preview.yaml)
рендериться під умовою `and .Values.rollout.enabled .Values.rollout.strategy.blueGreen`,
а готовий блок значень лежить закоментованим у кінці `values-minikube.yaml`.
Перемикання — заміна блоку `strategy` і `replicaCount: 4`.

**Запобіжник проти «вічного OutOfSync».** Argo Rollouts дописує в селектор
Service мітку `rollouts-pod-template-hash`, щоб націлити його на один ReplicaSet.
Git такого значення містити не може — воно похідне від шаблону пода. Тому в
Application додано:

```yaml
  ignoreDifferences:
    - group: ""
      kind: Service
      jsonPointers:
        - /spec/selector
```

Без цього Argo CD бачив би правку контролера як дрейф, `selfHeal` її відкочував,
контролер писав би знову — нескінченна боротьба двох автоматів. Оголошено
заздалегідь, хоч при canary Service не чіпається: вибір стратегії — рівень
значень, і це не має від нього залежати.

---

## 4. Реліз через Git

Процедура та сама, що в ЛР-5, — змінити тег і запушити:

```bash
# gitops/values/values-minikube.yaml:  tag: "1.3.0" -> "1.4.0"
git commit -am "gitops: canary release of the CDN Control Plane 1.4.0" && git push
```

Різниця — у тому, що відбувається далі.

### 4.1 Реліз зупиняється сам

Argo Rollouts доводить канарку до 20% і впирається в `pause: {}`. Argo CD
повідомляє застосунок як **Suspended** — окремий стан, не Progressing і не
Healthy:

```
$ kubectl argo rollouts get rollout cdn-cdn-control-plane-api -n cdn-gitops
Status:        ॥ Paused
Strategy:      Canary
  Step:        1/6
  SetWeight:   20
  ActualWeight: 20
```

Це і є progressive delivery: у розкладі є ворота, і вони чекають людину.

### 4.2 Розподіл трафіку — заміряний, а не заявлений

Запити треба робити **зсередини кластера**. `kubectl port-forward` зʼєднується з
**одним** подом і показав би 100% однієї версії — найпоширеніший спосіб зіпсувати
цю демонстрацію. Демо запускає под `curlimages/curl` і б'є через Service:

```bash
kubectl -n cdn-gitops run probe --rm -it --image=curlimages/curl \
  -- sh -c 'for i in $(seq 1 40); do curl -s http://cdn-cdn-control-plane-api/version; echo; done'
```

Заміряно двічі, і обидва рази розподіл збігся з оголошеною вагою:

| Прогін | Стабільна | Канарка | Частка канарки |
|---|---|---|---|
| вручну, `1.3.0 → 1.4.0` | 31 з 40 | 9 з 40 | **22.5%** |
| демо, `1.4.0 → 1.5.0` | 24 з 32 | 8 з 32 | **25%** |

Оголошено `setWeight: 20`; один под із пʼяти — це 20%, а відхилення в кілька
відсотків — звичайний розкид round-robin на невеликій вибірці. Повний вивід —
[`lab-06-output/04-release.txt`](lab-06-output/04-release.txt).

Демо **стверджує** обидві межі: хоча б одна відповідь від канарки і хоча б одна
від стабільної версії. Якби Service роздавав усе на один под — а саме так і
сталося б через `port-forward` — перевірка впала б.

### 4.3 `promote`

```bash
kubectl argo rollouts promote cdn-cdn-control-plane-api -n cdn-gitops
```

Далі кроки 60% і 80% проходять самі, по таймеру, і Rollout стає Healthy на
`1.4.0`. Те саме доступно в інтерфейсі Argo CD: об'єкт Rollout → ⋮ → Resume,
Promote-Full, Abort, Retry.

---

## 5. Скасування релізу

### 5.1 `abort` — Synced, але Degraded

Коміт із `1.5.0`, дочекатися першої паузи, і:

```bash
kubectl argo rollouts abort cdn-cdn-control-plane-api -n cdn-gitops
```

| | |
|---|---|
| **Sync** | `Synced` — маніфест у кластері точно відповідає Git, а Git справді каже `1.5.0` |
| **Health** | `Degraded` — реліз скасовано, канаркові поди прибрано |
| трафік | повністю на `1.4.0` — стабільній версії |

Пара та сама, що в ЛР-5 п.6b, але причина інша і цікавіша. Там Git просив
неможливого (тег, якого немає). Тут Git просить цілком можливого, образ
існує — **скасувала людина**. Кластер слухається Git і все одно не в тому стані,
який Git описує. Саме це й означає abort.

### 5.2 Завершення через Git

`abort` зупинив реліз, але не змінив наміру, записаного в Git. Поки там новий
тег, застосунок лишатиметься Degraded — і правильно:

```bash
git revert --no-edit <коміт із 1.5.0> && git push
```

**Але самого коміту тут не досить** — і це рівно той замок, що в §7.4 ЛР-5.
Синхронізація, яка привезла скасований реліз, лишається `Running`: хвиля чекає,
доки Rollout стане здоровим, а скасований Rollout здоровим не буде **за
визначенням**. Argo CD нової синхронізації не починає, тож відкат лежить у Git
побаченим і незастосованим:

```
phase=Running
msg=one or more synchronization tasks completed unsuccessfully
    due to application controller sync timeout. Retrying attempt #5 at 8:25PM.
```

Заміряно: `argocd app terminate-op cdn-control-plane` знімає замок, і застосунок
повертається до `Synced / Healthy` за секунди замість хвилин очікування
власного тайм-ауту контролера. Демо робить це автоматично — і лише тоді, коли
операція справді ще `Running`, бо це дія оператора, а не частина GitOps-циклу.

Після цього Rollout повертається до Healthy. Альтернатива з методички —
`kubectl argo rollouts retry rollout`, якщо проблему виправлено **поза образом**;
тут вона не підходить, бо виправляти треба саме намір.

---

## 6. Що саме перевіряє демо

[`scripts/devops_lab6_demo.ps1`](../../scripts/devops_lab6_demo.ps1) — та сама
будова, що в Лабах 3–5: кожен крок позначено пунктом завдання, друкує живий доказ
і **стверджує** результат.

| Крок | Пункт | Що стверджується |
|---|---|---|
| preflight | — | гілка та, `values-minikube.yaml` без незакомічених змін |
| 02 | 1 | `argo-rollouts` Synced/Healthy, анотація хвилі саме `-1`, усі CRD на місці |
| 03 | 2 | Rollout існує, Deployment з тим самим іменем **відсутній** |
| 04 | 3 | у кластері стоїть саме канарка з першим кроком `setWeight: 20` |
| 05 | 4 | після коміту застосунок **Suspended**, Rollout **Paused** |
| 06 | 4 | заміряний розподіл: є відповіді і від канарки, і від стабільної |
| 07 | 4 | після `promote` **усі** відповіді на новій версії, Rollout Healthy |
| 08 | 5 | після `abort` — `Synced` + `Degraded`, трафік на стабільній |
| 09 | 5 | після `git revert` — Healthy на `1.4.0` |

---

## 7. Сценарій захисту (пункт 6)

Підготувати заздалегідь: кластер піднятий, образи `1.3.0`, `1.4.0`, `1.5.0` у
GHCR (уже опубліковані), два вікна:

```bash
kubectl argo rollouts get rollout cdn-cdn-control-plane-api -n cdn-gitops --watch
kubectl argo rollouts dashboard        # http://localhost:3100
```

і цикл запитів **усередині кластера**:

```bash
kubectl -n cdn-gitops run probe --rm -it --image=curlimages/curl \
  -- sh -c 'while true; do curl -s http://cdn-cdn-control-plane-api/version; echo; sleep 0.5; done'
```

Порядок показу — рівно той, що в завданні:

1. **Реліз комітом.** Змінити тег на `1.4.0`, запушити. У `--watch` видно, як
   піднімається один канарковий под; у циклі запитів приблизно кожна п'ята
   відповідь нова; `argocd app get` показує **Suspended**.
2. **Promote.** `kubectl argo rollouts promote …` або ⋮ → Promote в Argo CD.
   Кроки 60% і 80% проходять по таймеру, усі відповіді стають новими, Healthy.
3. **Новий реліз і abort.** Тег `1.5.0`, дочекатися паузи, `abort`. Показати
   **Synced + Degraded** поряд і що трафік повернувся на `1.4.0`.
4. **git revert.** Застосунок знову Healthy.

**Якщо попросять змінити значення в Git.** Найнаочніше — `setWeight` першого
кроку з 20 на 40: коміт → Argo CD оновлює Rollout → у наступному релізі канарка
бере дві репліки з п'яти замість однієї. Важливо знати й зворотний бік:
**Rollout стартує лише при зміні шаблону пода** (образ, змінні, мітки), а не
`replicas` чи `strategy`. Зміна самої стратегії не запускає викочування — вона
застосується до наступного.

---

## 7a. Що зламалося на живому прогоні

Перший прогін демо впав на кроці 5 — і причина не в Argo Rollouts, а в
**розмірі кластера**. Варто знати, бо на захисті це повториться.

П'ять реплік API замість однієї — це +4 поди по ~120 МіБ, і разом зі стеком
Лаби 3, який ще працював у namespace `cdn-control-plane`, вузол дійшов до 35
подів і 76% пам'яті. Першим не витримав CoreDNS:

```
ComparisonError: Failed to load target state: failed to generate manifest:
  rpc error: code = Unavailable desc = connection error:
  desc = "transport: Error while dialing: dial tcp: lookup argocd-repo-server: i/o timeout"
```

Argo CD не міг достукатися до власного `argocd-repo-server` — не через помилку
в конфігурації, а тому що резолвінг імені в кластері почав відвалюватися.
Далі спрацював уже знайомий з §7.4 ЛР-5 механізм: синхронізація, що впала,
лишилася в стані `Running` і **тримала замок застосунку**, тож наступні спроби
отримували `another operation is already in progress`.

Вихід — той самий:

```bash
argocd app terminate-op cdn-control-plane
argocd app sync cdn-control-plane
```

і зменшити навантаження: стек Лаби 3 згорнуто до нуля
(`kubectl scale deployment ... -n cdn-control-plane --replicas=0`), що оборотно
і повертається з `k8s/`.

**Висновок для захисту.** Canary на 5 реплік — не безкоштовний. Перед
демонстрацією варто прибрати з кластера все, що не бере участі: стек Лаби 3,
зайві репліки контролерів. Інакше перший симптом буде не «канарка не ділить
трафік», а щось зовсім несхоже — таймаути DNS усередині Argo CD.

---

## 8. Протоколи прогону

| Файл | Зміст | Пункти |
|---|---|---|
| `01-controller.txt` | Application контролера, поди, CRD, версія плагіна | 1 |
| `02-rollout.txt` | Rollout у кластері, відсутність конкурентного Deployment | 2 |
| `03-strategy.txt` | кроки canary як їх бачить кластер | 3 |
| `04-release.txt` | коміт, Suspended/Paused, заміряний розподіл, promote | 4 |
| `05-abort.txt` | abort, Synced+Degraded, `git revert`, повернення до Healthy | 5 |

---

## 9. Що Лаба 6 змінила

| Файл | Зміна |
|---|---|
| `gitops/argocd-apps/argo-rollouts.yaml` | новий — контролер як Application, хвиля `-1` |
| `gitops/argocd-apps/cdn-control-plane.yaml` | `ignoreDifferences` на `/spec/selector` Service; гілка |
| `gitops/bootstrap/root-app.yaml` | гілка `devops-lab-6-rollouts` |
| `gitops/values/values-minikube.yaml` | canary, `replicaCount: 5`; blue-green закоментований поряд |
| `chart/.../templates/rollout.yaml` | новий — Rollout зі спільного шаблону пода |
| `chart/.../templates/api-service-preview.yaml` | новий — preview Service для blue-green |
| `chart/.../templates/api-deployment.yaml` | під умовою `not .Values.rollout.enabled`, підключає спільний шаблон |
| `chart/.../templates/_helpers.tpl` | `cdn.apiPodTemplate` — шаблон пода в одному місці |
| `chart/.../values.yaml` | блок `rollout`, вимкнений за замовчуванням |
| `chart/.../Chart.yaml` | `version: 0.2.0` |
| `scripts/devops_lab6_demo.ps1` | новий — демо з перевірками |

Чарт лишився сумісним із Лабами 3–5: `rollout.enabled` за замовчуванням хибний,
тож `values-dev.yaml` і `values-prod.yaml` рендерять той самий Deployment, що й
раніше. Перевіряється `python -I scripts/check_chart_render.py` — усі чотири
набори значень, із забороною дубльованих ключів.
