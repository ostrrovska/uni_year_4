# DevOps · Лабораторна 3 — Розгортання застосунку в Kubernetes

**Проєкт:** CDN Control Plane API (той самий, що в Лабах 1–2) — FastAPI + PostgreSQL,
підпапка `high-load-systems/` у монорепозиторії `ostrrovska/uni_year_4`.
**Кластер:** minikube з драйвером `docker`. **Маніфести:** [`k8s/`](../../k8s/), по одному
файлу на об'єкт. **Образ:** `ghcr.io/ostrrovska/cdn-control-plane`, теги `1.0.0` і `1.1.0`.

Лаба 1 спакувала застосунок у контейнери й описала топологію в `docker-compose`, Лаба 2
зібрала CI, що публікує образ у ghcr.io. Ця робота переносить ту саму топологію в
Kubernetes: ті самі чотири ролі (`postgres`, `migrate`, `api`, `agents`), плюс `redis`,
який додала Лаба 4 курсу високонавантажених систем.

---

## 1. Відповідність вимогам

| Вимога | Як виконано |
|---|---|
| **1a.** Образ власного проєкту з попередніх лаб | Той самий `docker/Dockerfile` з Лаби 1, без змін у логіці збірки |
| **1b.** Образ у реєстрі або завантажений у minikube | `minikube image load` — варіант, прямо дозволений умовою. У ghcr.io лежать теги `latest` і `sha-<commit>` з Лаби 2; семантичні теги CI поки не публікує (див. §9) |
| **1c.** Конкретний тег версії, не `latest` | Усі маніфести посилаються на `:1.0.0`. Крок 01 демо окремо перевіряє, що серед завантажених у кластер тегів немає `latest` |
| **1d.** Щонайменше дві версії образу | `1.0.0` і `1.1.0`, зібрані з `--build-arg APP_VERSION=`. Версія запікається в образ і повертається в `/health`, тож оновлення видно по відповіді, а не лише по маніфесту |
| **2a.** minikube та kubectl встановлено | minikube v1.39.0 (`%LOCALAPPDATA%\Programs\k8stools`), kubectl з Docker Desktop — [`lab-03-output/02-environment.txt`](lab-03-output/02-environment.txt) |
| **2b.** Кластер із драйвером docker | `minikube start --driver=docker --cpus=4 --memory=3072 --disk-size=12g` |
| **2c.** Стан вузла та подів у `kube-system` | Крок 01 демо перевіряє, що вузол `Ready` і що в `kube-system` працює control plane — [`lab-03-output/02-environment.txt`](lab-03-output/02-environment.txt) |
| **2d.** Доповнення metrics-server та ingress | Увімкнено й перевірено кроком 01: демо падає, якщо обидва не `enabled` — [`lab-03-output/02-environment.txt`](lab-03-output/02-environment.txt) |
| **3a.** Namespace за іменем проєкту | `cdn-control-plane` — [`k8s/00-namespace.yaml`](../../k8s/00-namespace.yaml) |
| **3b.** Усі об'єкти лише в цьому namespace | Кожен маніфест явно вказує `namespace:`, тож `kubectl apply -f k8s/` не залежить від активного контексту |
| **4a.** Каталог `k8s/`, по одному файлу на об'єкт | 15 файлів, нумерованих за порядком застосування — §3 |
| **4b.** Deployment: ≥2 реплік, узгоджені labels/selector, requests+limits, liveness+readiness | [`k8s/50-api-deployment.yaml`](../../k8s/50-api-deployment.yaml): `replicas: 2`, selector збігається з labels шаблона пода, `requests`/`limits` на CPU і пам'ять, `livenessProbe` на `/health`, `readinessProbe` на `/health/ready` |
| **4c.** Service, достатній для доступу всередині кластера і з хоста | [`k8s/51-api-service.yaml`](../../k8s/51-api-service.yaml) — `NodePort 30080`: всередині працює як ClusterIP, з хоста доступний через `minikube service` |
| **4d.** ConfigMap: ≥2 параметри, підключені як змінні оточення | [`k8s/10-app-configmap.yaml`](../../k8s/10-app-configmap.yaml) — 14 параметрів, підключені через `envFrom` |
| **4e.** Secret: ≥1 чутливий параметр | [`k8s/12-secret.yaml`](../../k8s/12-secret.yaml) — `POSTGRES_PASSWORD` і рядок підключення `DATABASE_URL` |
| **4f.** Ingress або NodePort | Обидва: NodePort (без залежностей) і [`k8s/52-api-ingress.yaml`](../../k8s/52-api-ingress.yaml) як повноцінна заміна nginx/HAProxy з Лаби 3 курсу ВНС |
| **4g.** PersistentVolumeClaim для компонента зі станом | [`k8s/20-postgres-pvc.yaml`](../../k8s/20-postgres-pvc.yaml) — 1Gi RWO, еквівалент тому `pgdata` у Compose |
| **5a.** Застосування однією командою з каталогу | `kubectl apply -f k8s/` — §4 |
| **5b.** Перелік створених об'єктів | §5, крок 02 |
| **5c.** Застосунок відкривається і працює | §5, крок 03 — `/health`, `/health/ready`, `/api/v1/stats/network` |
| **5d.** Значення з ConfigMap і Secret справді в контейнері | §5, крок 04 — `kubectl exec -- env` |
| **6a.** Самовідновлення | §6, крок 05 |
| **6b.** Масштабування і розподіл трафіку | §6, крок 06 |
| **6c.** Оновлення образу, rolling update | §6, крок 07 |
| **6d.** Історія оновлень і відкат | §6, крок 08 |
| **6e.** Застосунок доступний під час оновлення | §6, крок 07 — паралельний опит `/health` протягом усього rollout |
| **7a.** Неіснуючий тег і стан ImagePullBackOff | §7, крок 09 |
| **7b.** Причина через опис пода та Events | §7, крок 10 |
| **7c.** Логи контейнера і вхід усередину | §7, крок 11 |
| **7d.** Виправлення помилки | §7, крок 12 |
| **8a.** Каталог `k8s/` у репозиторії | Закомічено разом із цим звітом |
| **8b.** Порядок розгортання і параметри ConfigMap/Secret | Розділ **Deployment — Kubernetes and Helm** у [`README.md`](../../README.md), і докладніше тут: §4 і §8 |
| **8c.** Звіт зі збереженим виводом команд для пунктів 5–7 | §5–§7; повні транскрипти — [`docs/devops/lab-03-output/`](lab-03-output/) |

---

## 2. Від docker-compose до Kubernetes

Застосунок не переписувався — переписувався лише опис того, як його запускати. Відповідність
один до одного:

| docker-compose (Лаби 1–4) | Kubernetes | Чому саме так |
|---|---|---|
| `postgres` + том `pgdata` | Deployment + **PVC** + ClusterIP Service | Одна БД, один RWO-том, нема peer discovery — StatefulSet дав би стабільну мережеву ідентичність, яка тут нікому не потрібна |
| `redis` (кеш Лаби 4) | Deployment + ClusterIP Service, **без PVC** | Кеш, що пережив рестарт із застарілими записами, гірший за холодний |
| `migrate` (one-shot) | **Job** `alembic upgrade head` | Той самий аргумент, що й у Compose: при `--scale api=N` кожна репліка інакше кинулася б накатувати ту саму міграцію |
| `api1`, `api2`, `api3` | **Один Deployment**, `replicas: 2` | Три іменовані сервіси були обхідним шляхом: nginx OSS резолвить ім'я upstream один раз на старті. kube-proxy тримає список endpoint-ів актуальним, тож обхідний шлях більше не потрібен |
| `lb` (nginx :8080), `haproxy` (:8090) | **Service + Ingress** | Балансування робить kube-proxy, активні health-check-и — kubelet через `readinessProbe`. Те, заради чого в Лабі 3 довелося ставити HAProxy поруч із nginx, тут є з коробки |
| `agents` | Deployment, 1 репліка | Одна репліка — вимога коректності, а не ресурсів: воркер переписує ті самі рядки heartbeat за таймером |
| `seed` (профіль `demo`) | Job | У Kubernetes нема профілів; seed детермінований і ідемпотентний (ключі UUIDv5), тож повторний запуск нічого не псує |

> **Що саме замінив Ingress.** У Лабі 3 курсу ВНС довелося тримати два балансувальники:
> nginx як основний і HAProxy — бо nginx OSS не вміє активних health-check-ів і дізнається
> про мертвий backend лише зі зламаного клієнтського запиту. У Kubernetes ця дірка закрита
> на рівні платформи: `readinessProbe` опитує `/health/ready` за таймером, і репліка, що
> втратила БД, виходить із Service ще до того, як до неї дійде перший клієнтський запит.
> Налаштування проби — `periodSeconds: 2`, `failureThreshold: 2`, `successThreshold: 2` —
> це дослівно HAProxy-івське `inter 2s fall 2 rise 2` з
> [`loadbalancer/haproxy/haproxy.cfg`](../../loadbalancer/haproxy/haproxy.cfg).

> **Чому `failureThreshold: 2`, а не 1.** Це не обережність, а вимірювання.
> У [`loadbalancer/nginx/pools/3.conf`](../../loadbalancer/nginx/pools/3.conf) записаний
> прогін, де `max_fails=1` викинув здорову репліку з пулу через один скинутий конект під
> навантаженням, і пропускна здатність впала з 190 до 110 req/s. Миттєво перевантажений
> інстанс — не мертвий інстанс, і одна невдала проба не має права стверджувати протилежне.

---

## 3. Маніфести

```
k8s/
  00-namespace.yaml            Namespace cdn-control-plane
  10-app-configmap.yaml        конфігурація застосунку (14 параметрів)
  11-postgres-configmap.yaml   POSTGRES_USER / POSTGRES_DB — для самої БД
  12-secret.yaml               POSTGRES_PASSWORD, DATABASE_URL
  20-postgres-pvc.yaml         1Gi RWO
  21-postgres-deployment.yaml  strategy: Recreate
  22-postgres-service.yaml     ClusterIP
  30-redis-deployment.yaml     без persistence, allkeys-lru
  31-redis-service.yaml        ClusterIP
  40-migrate-job.yaml          alembic upgrade head
  50-api-deployment.yaml       2 репліки, проби, requests/limits
  51-api-service.yaml          NodePort 30080
  52-api-ingress.yaml          host cdn.local
  60-agents-deployment.yaml    симулятор edge-агентів
  70-seed-job.yaml             демо-фліт
```

Нумерація — не вимога Kubernetes, а зручність: `kubectl apply -f k8s/` обробляє файли за
алфавітом, тож namespace створюється першим, а конфігурація — раніше за тих, хто її читає.
Жодної реальної залежності це не гарантує (у Kubernetes нема `depends_on`), і покладатися
на неї не можна — порядок забезпечують проби, а не імена файлів.

**Два ConfigMap, а не один.** `cdn-postgres-config` налаштовує сам контейнер бази,
`cdn-app-config` — застосунок. Застосунок ніколи не бачить `POSTGRES_USER`: він отримує
вже зібраний `DATABASE_URL` із Secret. Змішати їх було б простіше на один файл і гірше на
одну пропущену межу відповідальності.

**Чому `stringData`, а не base64.** Base64 — це кодування, не шифрування. Записати пароль
у `data:` означало б зробити файл менш читабельним, нічого при цьому не захистивши. У
Secret лежать лише лабораторні дані (`cdn`/`cdn`, ті самі, що в Compose); у реальному
розгортанні Secret узагалі не лежав би в git, а приїжджав би зі сховища.

**Чому `strategy: Recreate` у postgres.** Стандартний RollingUpdate підняв би новий под до
того, як зупиниться старий, і обидва спробували б під'єднати той самий ReadWriteOnce-том —
новий залишився б у `Pending` назавжди.

**`maxUnavailable: 0` в api.** Саме це перетворює «застосунок залишався доступним» з
імовірності на гарантію: новий под мусить пройти readiness, перш ніж старому дозволять
зникнути. Доказ — у §6, крок 07.

---

## 4. Команди — підготовка та розгортання

```bash
# Кластер і доповнення (вимоги 2b, 2d)
minikube start --driver=docker --cpus=4 --memory=3072 --disk-size=12g
minikube addons enable ingress
minikube addons enable metrics-server

# Стан вузла та системних подів (вимога 2c)
kubectl get nodes -o wide
kubectl get pods -n kube-system

# Дві версії образу (вимоги 1c, 1d). APP_VERSION оголошено в Dockerfile останнім,
# тож зміна версії інвалідовує лише верхній шар, а не pip install.
docker build -f docker/Dockerfile --build-arg APP_VERSION=1.0.0 \
    -t ghcr.io/ostrrovska/cdn-control-plane:1.0.0 .
docker build -f docker/Dockerfile --build-arg APP_VERSION=1.1.0 \
    -t ghcr.io/ostrrovska/cdn-control-plane:1.1.0 .

# Завантаження в кластер (вимога 1b) — реєстр не потрібен, і imagePullPolicy:
# IfNotPresent гарантує, що pull навіть не спробують
minikube image load ghcr.io/ostrrovska/cdn-control-plane:1.0.0
minikube image load ghcr.io/ostrrovska/cdn-control-plane:1.1.0

# Розгортання однією командою з каталогу (вимога 5a)
kubectl apply -f k8s/

# Дочекатися схеми й реплік
kubectl wait --for=condition=complete job/cdn-migrate -n cdn-control-plane --timeout=300s
kubectl rollout status deployment/cdn-api -n cdn-control-plane

# Відкрити застосунок (вимога 5c)
minikube service cdn-api -n cdn-control-plane --url     # -> http://<minikube-ip>:30080
# або, не займаючи порт 8080, який належить Compose-стеку курсу ВНС:
kubectl port-forward svc/cdn-api 8181:80 -n cdn-control-plane
curl http://127.0.0.1:8181/health         # liveness  -> 200
curl http://127.0.0.1:8181/health/ready   # readiness -> 200 (503, якщо БД недоступна)
```

Увесь демонстраційний прогін пунктів 5–7 автоматизовано:

```powershell
./scripts/devops_lab3_demo.ps1
```

Кожен крок позначено пунктом завдання, друкує живий доказ і **перевіряє результат** —
мовчазна регресія валить демо, а не проходить непоміченою. Повні транскрипти кожної
команди пишуться в [`docs/devops/lab-03-output/`](lab-03-output/).

> **Про порти.** Compose-стек курсу ВНС тримає 8080 (nginx + дашборд), 8090 і 8404
> (HAProxy та його статистика), 5434 (PostgreSQL). Тому Kubernetes-частина навмисно взяла
> NodePort 30080 і port-forward на 8181: обидва стеки можуть бути підняті одночасно, і
> `scripts/lab3_demo.ps1` / `lab4_demo.ps1` / `smoke.ps1` продовжують працювати без змін.

---

## 5. Розгортання (пункт 5)

Повний транскрипт — [`lab-03-output/05-deploy.txt`](lab-03-output/05-deploy.txt). Усе
нижче знято на **чистому кластері**: namespace попередньо видалено цілком.

### 5a. Одна команда з каталогу

```
$ kubectl apply -f k8s/
namespace/cdn-control-plane created
configmap/cdn-app-config created
configmap/cdn-postgres-config created
secret/cdn-secrets created
persistentvolumeclaim/cdn-postgres-data created
deployment.apps/cdn-postgres created
service/cdn-postgres created
deployment.apps/cdn-redis created
service/cdn-redis created
job.batch/cdn-migrate created
deployment.apps/cdn-api created
service/cdn-api created
ingress.networking.k8s.io/cdn-api created
deployment.apps/cdn-agents created
job.batch/cdn-seed created
```

П'ятнадцять об'єктів, одна команда, порожній кластер.

### 5b. Створені об'єкти

```
$ kubectl get pods -n cdn-control-plane -o wide
NAME                            READY   STATUS      RESTARTS     AGE   IP            NODE
cdn-agents-cf447c9f7-p7v72      1/1     Running     0            16s   10.244.0.49   minikube
cdn-api-bf5c997b-6mwfz          1/1     Running     0            17s   10.244.0.47   minikube
cdn-api-bf5c997b-cz9ht          1/1     Running     0            17s   10.244.0.48   minikube
cdn-migrate-fl7n7               0/1     Completed   1 (8s ago)   17s   10.244.0.51   minikube
cdn-postgres-55b89fb78d-2vdvn   1/1     Running     0            17s   10.244.0.46   minikube
cdn-redis-7d6ff79598-pwwn7      1/1     Running     0            17s   10.244.0.45   minikube
cdn-seed-p8nq5                  0/1     Error       1 (9s ago)   16s   10.244.0.50   minikube
```

> **`RESTARTS 1` у `cdn-migrate` і `Error` у `cdn-seed` — це не збій, а межа можливостей
> чистих маніфестів.** На порожньому кластері обидва Job стартують одночасно з PostgreSQL:
> перша спроба міграції падає, бо база ще не приймає з'єднань, а перша спроба seed — на
> `relation "regions" does not exist`. У Compose це вирішував `depends_on`; у Kubernetes
> такого ребра немає взагалі, і єдиний доступний примітив упорядкування — повтор. Саме
> тому `restartPolicy: OnFailure` і навмисно щедрий `backoffLimit: 20` в обох Job. За
> кілька секунд обидва доходять до `Complete`.
>
> Лаба 4 закриває цю дірку по-справжньому: там міграція стає хуком, який Helm доганяє до
> кінця окремою фазою, а seed — `post-install` з більшою вагою. Це вже справжня гарантія
> порядку, а не гонка, яку зазвичай виграють повтори.

### 5c. Застосунок відповідає

```
$ curl http://127.0.0.1:8181/health
{"status":"ok","instance_id":"cdn-api-bf5c997b-6mwfz","app_version":"1.0.0"}

$ curl http://127.0.0.1:8181/health/ready
{"status":"ready","instance_id":"cdn-api-bf5c997b-6mwfz"}

$ curl http://127.0.0.1:8181/api/v1/stats/network
{"nodes_total":12,"nodes_by_status":{"draining":1,"degraded":1,"healthy":10},
 "fleet_capacity_mbps":375000,"assets_total":8,"replicas_total":73, ...}
```

`instance_id` — це ім'я пода: `INSTANCE_ID` навмисно не задано, і застосунок падає назад
на hostname. Завдяки цьому `/health` сам себе ідентифікує, і цикл по ньому стає прямим
доказом розподілу трафіку (пункт 6b). `app_version` приходить з образу.

> **Чому в прикладах `127.0.0.1:8181`, а не NodePort.** На Windows із драйвером `docker`
> IP minikube (`192.168.49.2`) живе всередині WSL-віртуалки й не маршрутизується з хоста:
> `curl http://192.168.49.2:30080/health` просто не відповідає. NodePort і Ingress створені
> й коректні, але дістатися до них із Windows можна лише через тунель —
> `minikube service cdn-api -n cdn-control-plane --url` або `kubectl port-forward`. Демо
> бере port-forward на 8181, бо він не потребує прав адміністратора і не займає 8080,
> який належить Compose-стеку курсу ВНС.

### 5d. Значення з ConfigMap і Secret усередині контейнера

```
$ kubectl exec cdn-api-bf5c997b-6mwfz -n cdn-control-plane -- env
APP_ENV=development
CACHE_ENABLED=true
DATABASE_URL=postgresql+asyncpg://cdn:cdn@cdn-postgres:5432/cdn_control_plane
HEARTBEAT_INTERVAL_SECONDS=10
LOG_LEVEL=INFO
REDIS_URL=redis://cdn-redis:6379/0
```

Перші п'ять рядків прийшли з ConfigMap через `envFrom`, `DATABASE_URL` — із Secret.

---

## 6. Життєвий цикл (пункт 6)

Повний транскрипт — [`lab-03-output/06-lifecycle.txt`](lab-03-output/06-lifecycle.txt).

### 6a. Самовідновлення

```
$ kubectl delete pod cdn-api-bf5c997b-6mwfz -n cdn-control-plane
pod "cdn-api-bf5c997b-6mwfz" deleted

$ kubectl get pods -n cdn-control-plane -l app.kubernetes.io/component=api
NAME                     READY   STATUS    RESTARTS   AGE
cdn-api-bf5c997b-c95gr   1/1     Running   0          5s     <- новий
cdn-api-bf5c997b-cz9ht   1/1     Running   0          25s
```

ReplicaSet помічає розбіжність між бажаними двома репліками і наявною однією та створює
заміну — не той самий под, а новий, з іншим іменем.

### 6b. Масштабування і розподіл трафіку

```
$ kubectl scale deployment/cdn-api --replicas=4 -n cdn-control-plane
deployment.apps/cdn-api scaled

$ зсередини кластера, через Service: 60 x curl -s http://cdn-api/health
    19 cdn-api-bf5c997b-c95gr
    16 cdn-api-bf5c997b-cz9ht
    11 cdn-api-bf5c997b-njlcp
    14 cdn-api-bf5c997b-r2p4q
failed requests: 0
```

Чотири репліки, 60 запитів, нуль помилок. Розкид 19/16/11/14 — нормальна поведінка
kube-proxy: він розподіляє з'єднання випадково, а не строгим round robin, тож на шістдесяти
запитах рівних п'ятнадцяти не буває.

> **Чому замір робиться зсередини кластера, а не через port-forward.**
> `kubectl port-forward svc/...` резолвить Service один раз, обирає **один** под і тунелює
> прямо до нього — він не балансує. Перша версія демо міряла розподіл через port-forward і
> чесно повідомила «трафік дійшов лише до 1 репліки»: це була вада заміру, а не маніфестів.
> Тому обидві проби запускаються окремим подом усередині кластера й ходять через ClusterIP
> Service — тобто через те, що kube-proxy справді балансує.

### 6c + 6e. Rolling update і доступність під час нього

```
$ kubectl set image deployment/cdn-api api=ghcr.io/ostrrovska/cdn-control-plane:1.1.0 -n cdn-control-plane
deployment.apps/cdn-api image updated

$ kubectl rollout status deployment/cdn-api -n cdn-control-plane
Waiting for deployment "cdn-api" rollout to finish: 2 out of 4 new replicas have been updated...
Waiting for deployment "cdn-api" rollout to finish: 3 out of 4 new replicas have been updated...
Waiting for deployment "cdn-api" rollout to finish: 1 old replicas are pending termination...
deployment "cdn-api" successfully rolled out
```

Паралельно з оновленням окремий под усередині кластера безперервно опитував `/health` і
рахував, яка саме збірка відповіла:

```
    87 app_version 1.0.0
   473 app_version 1.1.0
   failed requests: 0 of 560
```

Обидві версії в одній вибірці означають, що проба справді накрила перехід, а не зняла стан
до або після нього. **Нуль невдалих запитів із 560** — це і є пункт 6e.

> **`maxUnavailable: 0` необхідне, але його не досить.** Перший вимір із уже виправленою
> пробою все одно втратив **2 запити з 557**. Причина не в стратегії оновлення: видалення
> пода зі списку endpoint-ів Service і надсилання йому SIGTERM відбуваються **паралельно**,
> а kube-proxy на кожному вузлі дізнається про видалення мить по тому — і в цьому вікні
> запити ще летять у процес, який уже закрив сокет.
>
> Лікується хуком `preStop` зі `sleep 5` на контейнері api: він відкладає SIGTERM, а не
> завершення. Под продовжує обслуговувати, доки видалення endpoint-а розходиться по вузлах,
> і лише потім uvicorn починає graceful shutdown. Після цього — 0 з 560, двічі поспіль.
> Формулювання для захисту: `maxUnavailable: 0` гарантує, що **готових** подів достатньо;
> воно не гарантує, що трафік перестав приходити в той под, який іде геть.

### 6d. Історія ревізій і відкат

```
$ kubectl rollout history deployment/cdn-api -n cdn-control-plane
REVISION  CHANGE-CAUSE
1         <none>          <- початкове розгортання, тег 1.0.0
2         <none>          <- set image -> 1.1.0

$ kubectl rollout undo deployment/cdn-api -n cdn-control-plane
deployment.apps/cdn-api rolled back

$ kubectl rollout history deployment/cdn-api -n cdn-control-plane
REVISION  CHANGE-CAUSE
2         <none>
3         <none>          <- сам відкат, як нова ревізія
```

Після відкату `/health` знову віддає `app_version 1.0.0`. Важлива деталь: ревізія 1
**зникла** зі списку, а відкат з'явився як ревізія 3. Історія — це журнал, а не стек:
відкат не стирає те, від чого відкотилися, він дописується в кінець і сам підлягає відкату.

---

## 7. Діагностика (пункт 7)

Повний транскрипт — [`lab-03-output/07-diagnostics.txt`](lab-03-output/07-diagnostics.txt).

### 7a. Неіснуючий тег

```
$ kubectl set image deployment/cdn-api api=ghcr.io/ostrrovska/cdn-control-plane:9.9.9-does-not-exist -n cdn-control-plane

$ kubectl get pods -n cdn-control-plane -l app.kubernetes.io/component=api
NAME                       READY   STATUS         RESTARTS   AGE
cdn-api-65bc558786-8mx8m   0/1     ErrImagePull   0          4s     <- новий ReplicaSet
cdn-api-bf5c997b-455v2     1/1     Running        0          24s
cdn-api-bf5c997b-kdx52     1/1     Running        0          12s
cdn-api-bf5c997b-rhn5d     1/1     Running        0          18s
cdn-api-bf5c997b-t5xz5     1/1     Running        0          29s
```

`ErrImagePull` на першій спробі; далі kubelet переходить у `ImagePullBackOff` зі зростаючою
паузою між спробами.

### 7b. Причина — в описі пода і в Events

```
$ kubectl describe pod cdn-api-65bc558786-8mx8m -n cdn-control-plane
Events:
  Warning  Failed  kubelet  Failed to pull image
    "ghcr.io/ostrrovska/cdn-control-plane:9.9.9-does-not-exist":
    rpc error: code = NotFound desc = failed to resolve reference ... : not found
```

Найважливіше тут — чотири старі поди зі списку вище: вони **не постраждали**. Той самий
`maxUnavailable: 0` не дозволив прибрати жодну робочу репліку, доки нова не стане Ready, а
стати Ready вона не може. Застосунок увесь цей час відповідає `app_version 1.0.0` —
зламане оновлення зависає, але не роняє реліз.

### 7c. Логи і вхід у контейнер

```
$ kubectl logs cdn-api-bf5c997b-455v2 -n cdn-control-plane --tail=15
{"level":"INFO","logger":"app.core.middleware","message":"request.completed", ...}

$ kubectl exec cdn-api-bf5c997b-455v2 -n cdn-control-plane -- sh -c "id -u && pwd && ls app"
1000
/srv/app
__init__.py  api  core  db  models  schemas  services
```

uid 1000 і робочий каталог `/srv/app` — підтвердження, що `securityContext` із маніфеста
справді застосувався і процес не має root.

### 7d. Виправлення

```
$ kubectl set image deployment/cdn-api api=ghcr.io/ostrrovska/cdn-control-plane:1.0.0 -n cdn-control-plane
$ kubectl rollout status deployment/cdn-api -n cdn-control-plane
deployment "cdn-api" successfully rolled out
```

Зламаний ReplicaSet згортається до нуля, чотири репліки знову Ready, 20 із 20 запитів
обслужено. Повний прогін демо: **13 перевірок із 13 пройдено**.

---

## 8. Параметри ConfigMap і Secret

Усі значення читаються `pydantic-settings` як змінні оточення у `UPPER_SNAKE`
([`app/core/config.py`](../../app/core/config.py)). Невідомі ключі ігноруються
(`extra="ignore"`), тож додати параметр у ConfigMap не можна зламати запущений под.

### ConfigMap `cdn-app-config` — підключається через `envFrom`

| Параметр | Значення | Призначення |
|---|---|---|
| `APP_ENV` | `development` | Інформаційний маркер середовища |
| `LOG_LEVEL` | `INFO` | Рівень кореневого логера |
| `DB_POOL_SIZE` | `10` | Постійний розмір пулу з'єднань SQLAlchemy |
| `DB_MAX_OVERFLOW` | `10` | Скільки з'єднань понад пул дозволено відкрити |
| `DB_POOL_TIMEOUT` | `10` | Скільки секунд чекати вільне з'єднання |
| `HEARTBEAT_STALE_AFTER_SECONDS` | `120` | Після скількох секунд мовчання вузол вважається застарілим |
| `HEARTBEAT_INTERVAL_SECONDS` | `10` | Очікуваний період телеметрії від агента |
| `NODE_OVERLOAD_THRESHOLD_PERCENT` | `85` | Поріг, за яким вузол стає перевантаженим |
| `ROUTING_DEFAULT_CANDIDATES` | `3` | Скільки edge-вузлів повертати за замовчуванням |
| `ROUTING_MAX_CANDIDATES` | `10` | Стеля для `?limit=` |
| `CACHE_ENABLED` | `true` | Вмикає Redis; при `false` застосунок працює на `NullCache` |
| `REDIS_URL` | `redis://cdn-redis:6379/0` | Адреса кешу всередині кластера |
| `CACHE_ROUTE_TTL_SECONDS` | `10` | TTL кешованої відповіді маршрутизації |
| `CACHE_STATS_TTL_SECONDS` | `30` | TTL кешованої агрегації `/stats/network` |

`HEARTBEAT_STALE_AFTER_SECONDS` тут 120, а не продакшн-реалістичні 30 — рівно як у
`docker-compose.yml`: на живому показі засіяний фліт не повинен устигати випасти з пулу
маршрутизації між двома командами `curl`.

`CACHE_ROUTE_TTL_SECONDS` дорівнює `HEARTBEAT_INTERVAL_SECONDS` не випадково: кешована
відповідь містить у собі придатність і навантаження, обчислені з heartbeat-ів, тож її
несвіжість не має права пережити один цикл телеметрії.

### ConfigMap `cdn-postgres-config`

| Параметр | Значення | Призначення |
|---|---|---|
| `POSTGRES_USER` | `cdn` | Користувач, якого створює `initdb` |
| `POSTGRES_DB` | `cdn_control_plane` | Ім'я бази, яку створює `initdb` |

### Secret `cdn-secrets`

| Параметр | Хто читає | Призначення |
|---|---|---|
| `POSTGRES_PASSWORD` | контейнер `postgres` | Пароль суперкористувача, який виставляє `initdb` |
| `DATABASE_URL` | `api`, `agents`, `migrate`, `seed` | Повний async-рядок підключення |

`DATABASE_URL` обов'язково зі схемою `postgresql+asyncpg://`: і застосунок, і
[`migrations/env.py`](../../migrations/env.py) будують із нього async-движок, і звичайний
`postgresql://` впаде на старті.

Реальних паролів від робочих систем у Secret немає — це та сама пара `cdn`/`cdn`, що й у
`docker-compose.yml` з Лаби 1.

---

## 9. Що лишилося поза межами роботи

**Семантичні теги в CI.** Пайплайн Лаби 2 публікує `sha-<commit>` завжди і `latest` на
`main`. Теги `1.0.0`/`1.1.0` зібрані локально й завантажені через `minikube image load` —
варіант, прямо передбачений умовою (пункт 1b). Щоб ті самі теги з'являлися і в ghcr.io,
достатньо додати `type=semver,pattern={{version}}` у `docker/metadata-action` і тригер на
`tags: ['v*']`. Свідомо не зроблено: `.github/workflows/cdn-control-plane-ci.yml` — це
оцінений артефакт Лаби 2, і міняти його заради зручності цієї роботи не варто.

**HPA і PodDisruptionBudget.** Горизонтальне автомасштабування тут було б передчасним:
стеля — не CPU, а з'єднання до БД. `(DB_POOL_SIZE + DB_MAX_OVERFLOW) × replicas` — це
20 з'єднань на под проти `max_connections: 100` у PostgreSQL за замовчуванням, тобто
4 репліки. Вище потрібен не більший HPA, а пулер (PgBouncer) перед базою.

**`/metrics`.** Доповнення `metrics-server` дає метрики рівня подів і вузлів
(`kubectl top`), але застосунок не експортує власних метрик у форматі Prometheus — сьогодні
спостережуваність тримається на структурованих JSON-логах у stdout, кожен рядок яких несе
`instance_id`.

---

## 10. Скріншоти для захисту

1. `minikube status` + `kubectl get nodes -o wide` + `kubectl get pods -n kube-system` —
   кластер на драйвері docker, вузол Ready (вимоги 2b, 2c).
2. `minikube addons list` із увімкненими `ingress` і `metrics-server`, та `kubectl top pods
   -n cdn-control-plane` як доказ, що metrics-server працює (вимога 2d).
3. `minikube image ls | findstr cdn-control-plane` — обидва теги `1.0.0` і `1.1.0` у
   кластері, жодного `latest` (вимоги 1b, 1c, 1d).
4. Термінал із `kubectl apply -f k8s/` і наступним `kubectl get all,pvc,ingress -n
   cdn-control-plane` (вимоги 5a, 5b).
5. Браузер із відкритим `/docs` або `/api/v1/stats/network` через
   `minikube service cdn-api -n cdn-control-plane --url` (вимога 5c).
6. `kubectl exec ... -- env` із видимими `APP_ENV`, `CACHE_ENABLED`, `REDIS_URL` і
   `DATABASE_URL` (вимога 5d).
7. Підсумкова PASS-таблиця `./scripts/devops_lab3_demo.ps1` — 13 перевірок (вимоги 2, 5–7).
8. Окремо найцікавіше місце: тали оновлення `87 x 1.0.0 / 473 x 1.1.0, 0 з 560 невдалих`
   поруч із `kubectl rollout history` до і після `undo` (вимоги 6c, 6d, 6e).
9. `kubectl get pods` зі станом `ImagePullBackOff` на новому поді й чотирма робочими
   старими, плюс блок `Events` із `kubectl describe pod` (вимоги 7a, 7b).
