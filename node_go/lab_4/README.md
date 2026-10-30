# Лабораторна 4: багаторівнева архітектура серверного застосунку

Два сервіси — Node.js (Express) і Go (`net/http`) — реалізують однаковий CRUD
з першої лабораторної, але вже розкладений на рівні
`Router → Controller → Service → Repository → DataStore`.
Мета — показати, що кожен рівень знає лише про сусідній знизу, що бізнес-логіка
не залежить від способу зберігання даних, і що завдяки цьому Service можна
тестувати без запуску HTTP-сервера.

Повний протокол прогону `demo.ps1` — у [RESULTS.md](RESULTS.md).
Цей файл самодостатній: теорія, що зроблено, запуск, що демонструвати, висновки.

---

## 1. Теорія, яку перевіряємо

### Що саме дає розбиття на рівні

У лабораторній 1 обидва сервіси були одним файлом: той самий `if` розбирав
метод запиту, перевіряв поля, шукав елемент у масиві й формував JSON. Це
працює, але має три конкретні наслідки. По-перше, бізнес-правило неможливо
перевірити, не піднявши сервер і не відкривши порт. По-друге, щоб перейти з
масиву на базу даних, треба правити ті самі функції, що формують HTTP-відповіді.
По-третє, кожен endpoint формує помилку власноруч, тому формат помилок
розповзається, і достатньо забути один `return`, щоб отримати два записи
відповіді в один сокет.

Розбиття на рівні прибирає саму можливість цих помилок, а не лише самі помилки.
Правило, яке все тримає: **рівень має знати лише про той, що нижче, і нічого
про той, що вище**. Controller знає про Service, Service — про інтерфейс
Repository, Repository — про сховище. Назад залежності немає: Service не знає,
що його викликали з HTTP, а Repository не знає, що існує якийсь Service.

### Чому Service не має права знати HTTP-код

Найпоширеніша помилка в такій архітектурі — написати в Service
`throw new HttpError(404)`. Формально шари є, але Service стає непридатним для
будь-якого іншого транспорту: CLI, черга повідомлень, gRPC. Тому тут Service
кидає **доменну** помилку з полем `kind` (`validation`, `not_found`,
`conflict`) і машинним кодом (`item_not_found`), і жодного числа не згадує.

Єдина таблиця `kind → HTTP status` живе в HTTP-рівні:
`node-service/src/middleware/error-handler.js` і
`go-service/internal/response/response.go`. Саме це робить вимогу завдання
«Controller перетворює помилки Service у відповідні HTTP status codes»
буквально правдивою, і саме тому Service тестується без жодного згадування
кодів 400/404/409.

Окремий випадок — збій інфраструктури. Якщо файл сховища зіпсований, це не
помилка клієнта, і Service **не перетворює** її ні в що: вона йде нагору як
звичайна помилка, і обробник віддає 500 (`internal_error`), залишивши справжній
текст у логах сервера. Якби Service спробував це класифікувати, клієнт отримав
би 400 замість 500 — тобто неправду про те, хто винен.

### Dependency inversion: чому Service не знає про сховище

Сама по собі наявність файлу `repository.js` нічого не інвертує. Інверсія
починається там, де Service залежить від **абстракції**, а конкретну реалізацію
йому передають зовні.

У Go це робиться інтерфейсом. `repository.ItemRepository` оголошений у тому ж
пакеті, що й реалізації, а `service.NewItemService` приймає саме інтерфейс.
`InMemoryItemRepository` і `FileItemRepository` його реалізують, і рядок
`var _ ItemRepository = (*FileItemRepository)(nil)` перевіряє це на етапі
компіляції, а не під час першого запиту.

У JavaScript інтерфейсів немає, тому контракт заданий структурно: список
обов'язкових методів і функція `assertItemRepository`, яку викликає
`createApp` під час складання застосунку. Якщо передати неповний об'єкт,
застосунок падає одразу з переліком відсутніх методів, а не через годину на
першому `findByName`.

Практичний критерій, який це перевіряє: щоб замінити сховище, має змінитися
**рівно один рядок** — той, що обирає реалізацію в `server.js` / `main.go`.
Етап 6 у `demo.ps1` показує саме це: той самий бінарник Go, той самий код
Service, інше сховище, дані переживають перезапуск процесу.

### Middleware — це спільна логіка, а не декоратор

Вимога «створити два middleware» легко виконується формально й безглуздо.
Корисне middleware — те, що інакше довелося б дублювати.

Логування запитів дублювалося б у кожному endpoint, причому неправильно: код
відповіді відомий лише тоді, коли відповідь уже віддана. Тому в Express
використано подію `res.on('finish')`, а в Go — обгортку над
`http.ResponseWriter`, яка перехоплює `WriteHeader`. Логер стоїть зовні всього
ланцюга, тому міряє і час самої обробки помилок.

Перевірка `:id` дублювалася б тричі — у GET, PUT і DELETE. В Express вона
підключена одним рядком `router.param('id', validateId)`, у Go — обгорткою
`middleware.ValidateID` на трьох маршрутах із `{id}`. Крім того, middleware
віддає вже розібране число далі (через `req.itemId` і `context`), тому жоден
Controller не парсить id повторно.

І головне: саме middleware виконує вимогу «некоректний запит не повинен
потрапляти безпосередньо до Service або Repository». На запит
`GET /api/items/abc` відповідь 400 формується **до** того, як Controller
отримає керування, тож Service за цей запит не викликається взагалі.

### Чому Service тестується без сервера, і чому це не дрібниця

Коли Service не згадує ні `req`, ні `res`, ні Express, ні `net/http`, його тест
— це звичайне створення об'єкта: `new ItemService(new InMemoryItemRepository())`.
Жодного порту, жодного очікування готовності, жодного `fetch`. Тому 24 тести
бізнес-логіки в Node виконуються за ~110 мс, а не за десятки секунд.

Тести API потрібні окремо й перевіряють інше: що маршрути підключені, що
middleware стоять у правильному порядку, що коди відповіді ті, які обіцяні.
Вони піднімають застосунок на **ефемерному порту** (`listen(0)` в Node,
`httptest.NewServer` у Go), тому не конфліктують із запущеними сервісами й
можуть виконуватись паралельно з ними.

---

## 2. Що побудовано

| Каталог | Що це |
|---|---|
| `node-service/` | Node.js 22 + Express 5, порт `3100`, одна залежність |
| `go-service/` | Go 1.27 + стандартний `net/http`, порт `8180`, без залежностей |
| `demo.ps1` | Один скрипт, що демонструє всі вимоги лабораторної |

Порти свідомо інші, ніж у лабораторних 1–2 (`3000`/`8080`), щоб lab_4 могла
працювати одночасно з ними.

### Node.js

| Файл | Роль |
|---|---|
| `src/server.js` | Точка входу: читає `ITEM_REPO`, обирає сховище, слухає порт |
| `src/app.js` | Composition root: складає repository → service → controller → router, підключає middleware. Не викликає `listen()` — тому тести можуть узяти ефемерний порт |
| `src/routes/item.routes.js` | Router: шляхи, методи, middleware, привʼязка до методів Controller. Логіки немає |
| `src/routes/health.routes.js` | Router для `GET /health` |
| `src/controllers/item.controller.js` | Controller: читає запит, кличе один метод Service, обирає код відповіді |
| `src/controllers/health.controller.js` | Controller проби живучості; повідомляє, яке сховище підключено |
| `src/services/item.service.js` | Service: бізнес-логіка і правило унікальності імені. Про HTTP не знає |
| `src/repositories/item.repository.js` | Контракт `ItemRepository`: перелік методів, `assertItemRepository`, `RepositoryNotFoundError` |
| `src/repositories/in-memory.item.repository.js` | DataStore: масив у памʼяті процесу |
| `src/repositories/file.item.repository.js` | DataStore: JSON-файл; записи серіалізовані через чергу промісів |
| `src/models/item.js` | Форма `Item` і правила полів в одному місці |
| `src/errors/domain-error.js` | Доменна помилка з `kind` і `code`, без жодного HTTP-коду |
| `src/middleware/request-logger.js` | Middleware 1: `GET /api/items/10 200 4ms` |
| `src/middleware/validation.js` | Middleware 2: `validateId` і `requireJsonBody` |
| `src/middleware/error-handler.js` | Єдина таблиця `kind → status`; тут же 400 для зламаного JSON і 500 для решти |
| `tests/item.service.test.js` | 24 тести Service без HTTP-сервера |
| `tests/item.api.test.js` | Тести API на ефемерному порту через `fetch` |
| `tests/item.repository.test.js` | Один набір перевірок, прогнаний через **обидві** реалізації сховища |

### Go

| Файл | Роль |
|---|---|
| `cmd/server/main.go` | Composition root: `newRepository` повертає **інтерфейс**, не структуру |
| `internal/router/router.go` | Router: патерни Go 1.22 (`GET /api/items/{id}`) і підключення middleware |
| `internal/controller/item.go` | Controller; кожен метод **повертає** `error` замість того, щоб формувати відповідь |
| `internal/controller/health.go` | Controller проби живучості |
| `internal/service/item.go` | Service; залежить від `repository.ItemRepository` |
| `internal/repository/item.go` | `ItemRepository` — інтерфейс — і сентинел `ErrNotFound` |
| `internal/repository/memory.go` | DataStore: слайс під `sync.RWMutex` |
| `internal/repository/file.go` | DataStore: JSON-файл під `sync.Mutex`, запис через тимчасовий файл і `Rename` |
| `internal/model/item.go` | `Item`, `Draft`, правила полів |
| `internal/apperr/apperr.go` | Доменна помилка: `Kind`, `Code`, `Message`. Про HTTP не знає |
| `internal/response/response.go` | Єдина таблиця `kind → status`, `Handle` (аналог `next(err)`), `WriteError` |
| `internal/middleware/logging.go` | Middleware 1 |
| `internal/middleware/validation.go` | Middleware 2: `ValidateID`, `RequireJSONBody` |
| `internal/middleware/recover.go` | `panic` → те саме 500, що й звичайний збій |
| `tests/service_test.go` | Тести Service без сервера |
| `tests/api_test.go` | Тести API через `httptest.NewServer` |
| `tests/repository_test.go` | Таблиця, прогнана через обидві реалізації |

Чому `response` — окремий пакет, а не частина `controller`: форматувальник
помилок потрібен і middleware валідації, а `controller` уже імпортує
`middleware`. Спільний пакет розриває цикл імпортів і залишає таблицю
статусів в одному місці.

### Маршрути

| Метод | Шлях | Успіх | Помилки |
|---|---|---|---|
| GET | `/health` | 200 | — |
| GET | `/api/items` | 200 | 500, якщо сховище нечитабельне |
| GET | `/api/items/:id` | 200 | 400 (некоректний id), 404 |
| POST | `/api/items` | 201 | 400 (JSON, тіло, поле, тип), 409 (дублікат імені) |
| PUT | `/api/items/:id` | 200 | 400, 404, 409 |
| DELETE | `/api/items/:id` | 204 | 400, 404 |

### Предметна область: `Item` замість `User`

У тексті завдання приклади наведені для `User`, і там же сказано: «формат може
бути змінений відповідно до предметної області вашого проєкту». Оскільки
лабораторна 4 — це розширення лабораторної 1, сутність узято звідти без змін:

| У завданні | Тут | Чому так |
|---|---|---|
| `User { id, name, email }` | `Item { id, name, description }` | Сутність лабораторної 1, яку завдання і вимагає розширити |
| `/api/users` | `/api/items` | Той самий набір методів і кодів |
| `UserRepository` | `ItemRepository` | Той самий контракт: `Create`, `FindByID`, `Update`, `Delete` (+ `FindAll`, `FindByName`) |
| унікальність `email` | унікальність `name`, без урахування регістру | Бізнес-правило, яке дає чесний 409 Conflict |

### Формат помилки

Один для обох сервісів і для всіх endpoint:

```json
{
    "error": "item_not_found",
    "message": "Item with id 42 was not found"
}
```

| Код | Статус | Коли |
|---|---|---|
| `invalid_id` | 400 | id не додатне ціле — відкидається middleware, до Service |
| `invalid_json` | 400 | тіло не розбирається як JSON |
| `invalid_content_type` | 400 | у POST/PUT немає `Content-Type: application/json` |
| `invalid_body` | 400 | тіло — не JSON-обʼєкт |
| `invalid_item` | 400 | поле відсутнє, порожнє, не того типу або задовге |
| `item_not_found` | 404 | сутності з таким id немає |
| `route_not_found` | 404 | такого маршруту немає |
| `item_name_taken` | 409 | імʼя вже зайняте (бізнес-правило) |
| `internal_error` | 500 | збій інфраструктури; деталі лишаються в логах сервера |

---

## 3. Як відтворити

### Усе одним скриптом

```powershell
cd C:\uni_year_4\node_go\lab_4
.\demo.ps1
```

Скрипт сам збирає обидва сервіси, запускає й зупиняє їх, проходить усі
endpoint, перевіряє кожен код відповіді, підміняє сховище і прогонює тести.
Якщо щось не так, він завершується з ненульовим кодом і червоним рядком
`ПРОВАЛЕНО ПЕРЕВІРОК`.

Про кодування: `demo.ps1` збережений у UTF-8 **з BOM**, бо без BOM Windows
PowerShell 5.1 читає файл як ANSI і ламається на українському тексті. Крім того
скрипт сам виставляє `[Console]::OutputEncoding` у UTF-8 і замінює значки
`node`-репортера (`✔`, `▶`, `ℹ`) на `[ok]`, `[--]`, `[ i]` — інакше в консолі з
DOS-кодуванням вони показуються як `Γ£ö` і `Γû╢`. Якщо запускати тести напряму
(`npm test`), значки лишаються оригінальними; щоб вони відображались правильно,
достатньо `chcp 65001`.

Корисні прапорці:

```powershell
.\demo.ps1 -SkipTests                   # лише живі HTTP-етапи
.\demo.ps1 -NodePort 3200 -GoPort 8280  # якщо порти зайняті
.\demo.ps1 -Go "C:\Program Files\Go\bin\go.exe"
```

### Запуск сервісів вручну

```powershell
# Термінал 1 — Node.js
cd C:\uni_year_4\node_go\lab_4\node-service
npm install
npm start

# Термінал 2 — Go
cd C:\uni_year_4\node_go\lab_4\go-service
go build -o bin\lab4-go.exe .\cmd\server
.\bin\lab4-go.exe
```

Те саме з файловим сховищем замість памʼяті — єдина різниця у змінних
середовища, код не змінюється:

```powershell
$env:ITEM_REPO = "file"
$env:ITEM_DATA_FILE = "C:\uni_year_4\node_go\lab_4\data\items.json"
npm start        # або .\bin\lab4-go.exe
```

| Змінна | Типове значення | Призначення |
|---|---|---|
| `PORT` | `3100` / `8180` | Порт сервісу |
| `ITEM_REPO` | `memory` | `memory` або `file` — вибір DataStore |
| `ITEM_DATA_FILE` | `data/items.json` | Шлях до файлу, якщо `ITEM_REPO=file` |

### Тести

```powershell
cd C:\uni_year_4\node_go\lab_4\node-service
npm test                  # усі: Service + API + сховища
npm run test:service      # лише Service, без HTTP-сервера
npm run test:api          # лише API

cd C:\uni_year_4\node_go\lab_4\go-service
go vet ./...
go test ./... -v
go test ./tests -run "^TestItemService" -v   # лише Service
```

### Кілька запитів вручну

```powershell
Invoke-RestMethod http://localhost:3100/health
Invoke-RestMethod http://localhost:3100/api/items -Method Post `
    -ContentType "application/json" `
    -Body '{"name":"Keyboard","description":"Mechanical"}'
Invoke-RestMethod http://localhost:3100/api/items
```

`Invoke-RestMethod` кидає виняток на 4xx, тому для перевірки помилок зручніше
`curl.exe`, який просто покаже відповідь:

```powershell
curl.exe -i http://localhost:3100/api/items/abc
curl.exe -i http://localhost:8180/api/items/9999
```

---

## 4. Що демонструвати на захисті

Найкоротший шлях — запустити `.\demo.ps1` один раз і йти по етапах у виводі.
Нижче — що саме показувати на кожну вимогу.

| Вимога | Де показати | На що вказати |
|---|---|---|
| Рівні розділені | дерево каталогів + таблиці в розділі 2 | один каталог = один рівень; у `routes/` немає логіки, у `services/` немає `req`/`res` |
| Router без бізнес-логіки | `node-service/src/routes/item.routes.js`, `go-service/internal/router/router.go` | обидва файли — лише перелік маршрутів і middleware, ~30 рядків |
| Controller не чіпає сховище | `item.controller.js`, `internal/controller/item.go` | в обох файлах слово `repository` є лише в коментарі, а не у виклику; єдина залежність — `this.service` / `c.service`. Контролер проби живучості отримує лише **назву** сховища рядком, а не сам обʼєкт |
| Service без HTTP і без SQL | `item.service.js`, `internal/service/item.go` | в імпортах немає `express`, `net/http`, `req`, `res`; лише модель, помилки й контракт сховища |
| Усі обовʼязкові endpoint | **етап 4** | 6 маршрутів × 2 сервіси, усі `ok` |
| 200 / 201 / 204 | **етап 4** | GET → 200, POST → 201, DELETE → 204 з порожнім тілом |
| 400: обовʼязковість, типи, порожні значення, JSON, id | **етап 4** | п'ять різних 400 з різними `error`-кодами |
| 404 | **етап 4** | `item_not_found` для сутності, `route_not_found` для маршруту |
| 409 (дублювання) | **етап 4** | POST `{"name":"KEYBOARD"}` після `Keyboard` → 409 `item_name_taken` |
| 500 | **етап 7** | зіпсований файл сховища → 500 `internal_error`, деталі лишились у логах |
| Централізована обробка помилок | **етапи 4 і 7** + `error-handler.js` / `response.go` | усі помилки мають однаковий формат; у контролерах немає жодного формування помилки |
| Middleware 1 (логування) | **етап 5** | рядки `GET /api/items/10 200 1ms` — метод, шлях, код, тривалість |
| Middleware 2 (валідація) | **етап 4**, рядок `GET /api/items/abc` | 400 приходить до Controller; Service за цей запит не викликався |
| Інверсія залежності | **етап 6** | `/health` показує `repository: file`; дані вижили після перезапуску; бінарник Go той самий |
| Interface у Go | `internal/repository/item.go` | оголошення `ItemRepository` + `var _ ItemRepository = (*FileItemRepository)(nil)` |
| Контракт у Node | `src/repositories/item.repository.js` | `ITEM_REPOSITORY_METHODS` + `assertItemRepository`, що викликається в `createApp` |
| Тести Service без сервера | **етап 2** | 24 тести Node за ~110 мс; жодного порту |
| Тести API | **етап 8** | GET, POST, некоректний POST, 404, DELETE, коди відповіді |

### Питання, які ставлять, і короткі відповіді

**Де тут Router, Controller, Service, Repository, DataStore?**
Router — `routes/item.routes.js` і `internal/router/router.go`. Controller —
`controllers/`, `internal/controller/`. Service — `services/`,
`internal/service/`. Repository — `repositories/`, `internal/repository/`.
DataStore — масив у памʼяті або JSON-файл, і Service не знає, який із них
підключений.

**Покажіть, що Controller не працює з базою напряму.**
Пошук по `item.controller.js` і `internal/controller/item.go` слова
`repository` не дає нічого: Controller має лише посилання на Service. Так само
в Service немає ні SQL, ні шляху до файлу — лише виклики методів контракту.

**Як замінити InMemory на базу даних?**
Написати `DatabaseItemRepository` із тими самими шістьма методами і підставити
його в `createRepository` / `newRepository` — один рядок. У Go компілятор
перевірить відповідність інтерфейсу, в Node це зробить `assertItemRepository`
під час старту. Код Service не змінюється. Етап 6 робить саме цю підміну, лише
цільове сховище — файл, а не СУБД. Що підміна безпечна, доводить
`tests/item.repository.test.js` і `tests/repository_test.go`: один і той самий
набір перевірок проходять обидві реалізації.

**Чому Service кидає `kind`, а не HTTP-код?**
Щоб його можна було викликати не з HTTP. Таблиця `kind → status` в одному
місці: `middleware/error-handler.js` і `internal/response/response.go`.

**Чому 500, а не 400, коли файл сховища зіпсований?**
Бо винен не клієнт. Service не класифікує такі помилки й пропускає їх нагору
незміненими; обробник віддає 500, а справжній текст помилки лишається в логах
сервера й не їде клієнту. Етап 7 показує і відповідь, і запис у лозі.

**Чому `/api/items`, а не `/api/users`?**
Завдання прямо дозволяє змінити формат під предметну область проєкту, а
лабораторна 4 розширює лабораторну 1, де сутність — `Item`. Відповідність
наведена таблицею в розділі 2.

---

## Результати

### Дослід 1. Усі маршрути й коди відповіді

19 запитів до кожного сервісу, кожен із перевіркою очікуваного статусу й
очікуваного коду помилки. Обидва сервіси дають **однакові** статуси й однакові
`error`-коди на всіх 19 запитах.

Єдина змістовна різниця — текст повідомлення при неправильному типі поля:
Express повертає `name is required and must be a string` (бо `42` не рядок уже
на етапі валідації моделі), а Go — `field "name" must be of type string` (бо
помилку виявляє `json.Unmarshal` і контролер розрізняє синтаксичну помилку від
помилки типу). Код і статус при цьому однакові: `invalid_item`, 400.

### Дослід 2. Middleware логування

По 20 рядків доступу на сервіс за один прогін етапу 4, формат точно такий, як у
завданні:

```text
POST /api/items 400 1ms
GET /api/items/abc 400 1ms
DELETE /api/items/1 204 1ms
GET /api/nothing-here 404 0ms
```

Код відповіді в рядку — це той, що реально поїхав клієнту, включно з тими, що
сформував обробник помилок: логер стоїть зовні всього ланцюга.

### Дослід 3. Підміна Repository

| Крок | Node.js | Go |
|---|---|---|
| `ITEM_REPO=file`, `/health` | `repository: file` | `repository: file` |
| POST `Persisted` | 201 | 201 |
| процес убито, запущено знову | — | — |
| GET `/api/items` | сутність на місці | сутність на місці |

Бінарник Go між двома запусками не перезбирався, файли Service, Controller і
Router не змінювались. Змінилося значення `ITEM_REPO`, яке читає один рядок у
composition root.

### Дослід 4. Тести

| Набір | Node.js | Go |
|---|---|---|
| Service, без HTTP | 24 тести | 8 функцій (`^TestItemService`) |
| API + сховища | 45 тестів | 11 функцій (`^TestAPI`, `^TestRepository`) |
| Разом | **69** | **84 кейси** з підтестами |

`go vet ./...` і `gofmt -l .` чисті. Тести Service виконуються за ~110 мс,
бо не піднімають сервер.

---

## Висновки

Розбиття на рівні тут коштувало приблизно вчетверо більше файлів, ніж у
лабораторній 1, і дало три речі, яких у лабораторній 1 не було в принципі.

**Бізнес-логіка стала перевірюваною.** 24 тести правил у Node виконуються за
~110 мс, бо Service — звичайний обʼєкт, а не ендпойнт. У лабораторній 1 ті самі
перевірки вимагали б запуску сервера, вибору вільного порту й очікування
готовності — тобто на два порядки більше часу й окремого джерела нестабільності.

**Сховище стало змінним.** Критерій, за яким це видно, — не наявність каталогу
`repositories/`, а той факт, що для переходу з масиву на файл змінився один
рядок у composition root, і той самий зібраний бінарник Go працював з обома
сховищами. Якби Service знав про масив, цей перехід зачепив би бізнес-логіку.

**Помилки стали однорідними.** Таблиця `kind → status` існує в одному місці на
сервіс, тому 400, 404, 409 і 500 мають однакову форму на всіх endpoint, і
додати новий endpoint не означає знову писати формування помилки. Корисний
побічний ефект — межа між «винен клієнт» і «винен сервер» стала явною: Service
класифікує лише те, що розуміє, а все інше пропускає нагору, і саме тому
зіпсований файл сховища дає 500, а не 400.

Ціна теж реальна: щоб додати одне поле до `Item`, треба торкнутися моделі,
валідації й обох реалізацій сховища, а щоб прочитати шлях одного запиту —
відкрити чотири файли замість одного. Для сервісу з шістьма маршрутами це
дорого. Виправдовує себе це там, де бізнес-правил більше, ніж маршрутів, і де
сховище з часом змінюється — тобто рівно в тих умовах, для яких архітектуру і
придумали.

Порівняння двох реалізацій: Express дає готові `Router`, `router.param` і
механізм error-middleware, тому HTTP-обвʼязка виходить коротшою. Стандартний
`net/http` після Go 1.22 вміє достатньо (метод і `{id}` у патерні маршруту),
але централізацію помилок довелося зробити самостійно — через обгортку
`Handle`, що приймає хендлери, які повертають `error`. Натомість Go дає те,
чого в JavaScript немає взагалі: невідповідність реалізації контракту сховища
виявляє компілятор, а не тест.
