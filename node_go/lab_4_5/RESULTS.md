# Лабораторна 4 — розширені результати

Протокол одного повного прогону `demo.ps1` і те, що з нього читається.
Основний текст лабораторної — у [README.md](README.md).

---

## 1. Умови прогону

| Параметр | Значення |
|---|---|
| Дата | 17.10.2026 |
| ОС | Windows 10 Pro 19045 |
| Node.js | v22.16.0, Express 5.3.0 |
| Go | go1.27.0 windows/amd64, лише стандартна бібліотека |
| Порти | Node `3100`, Go `8180` |
| Сховище | `memory` на етапах 3–5, `file` на етапах 6–7 |
| Команда | `.\demo.ps1` |

---

## 2. Зведення

| Показник | Node.js | Go |
|---|---|---|
| Запитів в обході маршрутів (етап 4) | 19 | 19 |
| Усі очікувані статуси збіглися | так | так |
| Рядків логу доступу за етап 4 | 20 | 20 |
| Тестів рівня Service | 24 | 8 функцій, `^TestItemService` |
| Тестів рівня API і сховищ | 45 | 11 функцій, `^TestAPI`, `^TestRepository` |
| Усього тестових кейсів | 69 | 84 з підтестами |
| `go vet ./...` / `gofmt -l .` | — | чисто |
| Провалених перевірок | 0 | 0 |

Коди відповіді, покриті прогоном: **200, 201, 204, 400, 404, 409, 500**.

---

## 3. Протокол прогону

```text
=== 1. Збірка ===
   node_modules вже на місці, npm install пропущено

   go build -o bin\lab4-go.exe ./cmd/server - готово

   go vet ./... - чисто

=== 2. Тести рівня Service - без жодного HTTP-сервера ===
   Service конструюється напряму з repository: ані порту, ані Express, ані net/http

-- Node.js: node --test --test-reporter=spec tests/item.service.test.js
  [--] ItemService: creating
    [ok] assigns an id and returns the stored item (2.4288ms)
    [ok] trims the fields and defaults a missing description (0.2587ms)
    [ok] numbers items consecutively (0.2197ms)
  [ok] ItemService: creating (3.9107ms)
  [--] ItemService: validation
    [ok] rejects a missing name (1.1552ms)
    [ok] rejects a whitespace-only name (0.2116ms)
    [ok] rejects a name of the wrong type (0.2023ms)
    [ok] rejects a description of the wrong type (0.2725ms)
    [ok] rejects a body that is not an object (0.3928ms)
    [ok] rejects an identifier that is not a positive integer (0.7571ms)
  [ok] ItemService: validation (3.597ms)
  [--] ItemService: business rule - names are unique
    [ok] rejects a duplicate name regardless of case (0.4132ms)
    [ok] rejects renaming an item onto another item name (0.5131ms)
    [ok] allows an item to keep its own name while editing the description (0.3474ms)
  [ok] ItemService: business rule - names are unique (2.618ms)
  [--] ItemService: reading
    [ok] lists every stored item (0.2829ms)
    [ok] returns an empty list for an empty store (0.1004ms)
    [ok] finds an item by id (0.1822ms)
    [ok] reports a missing item as not found (0.2422ms)
  [ok] ItemService: reading (0.947ms)
  [--] ItemService: updating and deleting
    [ok] updates both fields (0.3094ms)
    [ok] reports updating a missing item as not found (0.172ms)
    [ok] deletes an item, after which it can no longer be found (0.2822ms)
    [ok] reports deleting a missing item as not found (0.1577ms)
    [ok] frees the name of a deleted item (0.213ms)
  [ok] ItemService: updating and deleting (1.3681ms)
  [--] ItemService: dependency inversion
    [ok] refuses a repository that does not implement the contract (0.5071ms)
    [ok] works against any object satisfying the contract (0.2938ms)
    [ok] propagates an infrastructure failure untranslated, so the HTTP layer reports 500 (0.2882ms)
  [ok] ItemService: dependency inversion (1.2738ms)
  [ i] tests 24
  [ i] suites 6
  [ i] pass 24
  [ i] fail 0
  [ i] cancelled 0
  [ i] skipped 0
  [ i] todo 0
  [ i] duration_ms 109.2187

-- Go: go test ./tests -count=1 -run ^TestItemService
  --- PASS: TestItemServiceCreate (0.00s)
  --- PASS: TestItemServiceValidation (0.00s)
  --- PASS: TestItemServiceInvalidIdentifier (0.00s)
  --- PASS: TestItemServiceUniqueName (0.00s)
  --- PASS: TestItemServiceRead (0.00s)
  --- PASS: TestItemServiceUpdate (0.00s)
  --- PASS: TestItemServiceDelete (0.00s)
  --- PASS: TestItemServiceDependencyInversion (0.00s)
  ok  	lab4-go/tests	1.129s

=== 3. Запуск обох сервісів (repository: memory) ===
   node listening on 3100, repository: memory
   go listening on 8180, repository: memory

=== 4. Усі endpoint і всі коди відповіді ===

-- Node.js (Express) - http://localhost:3100
  ok   GET    /health                  200  {"status":"ok","repository":"memory"}
  ok   GET    /api/items               200  []
   порожній список
  ok   POST   /api/items               201  {"id":1,"name":"Keyboard","description":"Mechanical"}
   201 Created
  ok   GET    /api/items               200  [{"id":1,"name":"Keyboard","description":"Mechanical"}]
  ok   GET    /api/items/1             200  {"id":1,"name":"Keyboard","description":"Mechanical"}
   далі - помилки, кожна через один централізований обробник
  ok   POST   /api/items               409  {"error":"item_name_taken","message":"Item with name \"KEYBOARD\" already exists"}
   409: бізнес-правило унікальності імені, без урахування регістру
  ok   POST   /api/items               400  {"error":"invalid_item","message":"name is required and must be a string"}
   400: обов'язкове поле відсутнє
  ok   POST   /api/items               400  {"error":"invalid_item","message":"name must not be empty"}
   400: порожнє значення
  ok   POST   /api/items               400  {"error":"invalid_item","message":"name is required and must be a string"}
   400: неправильний тип даних
  ok   POST   /api/items               400  {"error":"invalid_json","message":"Request body is not valid JSON"}
   400: Invalid JSON
  ok   POST   /api/items               400  {"error":"invalid_content_type","message":"Content-Type must be application/json"}
   400: middleware 2, не JSON
  ok   GET    /api/items/abc           400  {"error":"invalid_id","message":"Item id must be a positive integer, got \"abc\""}
   400: middleware 2 відкидає id до Controller, Service не викликається
  ok   GET    /api/items/0             400  {"error":"invalid_id","message":"Item id must be a positive integer, got \"0\""}
  ok   GET    /api/items/9999          404  {"error":"item_not_found","message":"Item with id 9999 was not found"}
   404: сутності немає
  ok   PUT    /api/items/1             200  {"id":1,"name":"Keypad","description":"Compact"}
  ok   PUT    /api/items/9999          404  {"error":"item_not_found","message":"Item with id 9999 was not found"}
  ok   DELETE /api/items/1             204
   204: тіло порожнє
  ok   GET    /api/items/1             404  {"error":"item_not_found","message":"Item with id 1 was not found"}
   після DELETE сутність справді зникла
  ok   GET    /api/nothing-here        404  {"error":"route_not_found","message":"No route for GET /api/nothing-here"}
   невідомий маршрут - той самий формат помилки

-- Go (net/http) - http://localhost:8180
  ok   GET    /health                  200  {"repository":"memory","status":"ok"}
  ok   GET    /api/items               200  []
   порожній список
  ok   POST   /api/items               201  {"id":1,"name":"Keyboard","description":"Mechanical"}
   201 Created
  ok   GET    /api/items               200  [{"id":1,"name":"Keyboard","description":"Mechanical"}]
  ok   GET    /api/items/1             200  {"id":1,"name":"Keyboard","description":"Mechanical"}
   далі - помилки, кожна через один централізований обробник
  ok   POST   /api/items               409  {"error":"item_name_taken","message":"Item with name \"KEYBOARD\" already exists"}
   409: бізнес-правило унікальності імені, без урахування регістру
  ok   POST   /api/items               400  {"error":"invalid_item","message":"name is required and must be a string"}
   400: обов'язкове поле відсутнє
  ok   POST   /api/items               400  {"error":"invalid_item","message":"name must not be empty"}
   400: порожнє значення
  ok   POST   /api/items               400  {"error":"invalid_item","message":"field \"name\" must be of type string"}
   400: неправильний тип даних
  ok   POST   /api/items               400  {"error":"invalid_json","message":"Request body is not valid JSON"}
   400: Invalid JSON
  ok   POST   /api/items               400  {"error":"invalid_content_type","message":"Content-Type must be application/json"}
   400: middleware 2, не JSON
  ok   GET    /api/items/abc           400  {"error":"invalid_id","message":"Item id must be a positive integer, got \"abc\""}
   400: middleware 2 відкидає id до Controller, Service не викликається
  ok   GET    /api/items/0             400  {"error":"invalid_id","message":"Item id must be a positive integer, got \"0\""}
  ok   GET    /api/items/9999          404  {"error":"item_not_found","message":"Item with id 9999 was not found"}
   404: сутності немає
  ok   PUT    /api/items/1             200  {"id":1,"name":"Keypad","description":"Compact"}
  ok   PUT    /api/items/9999          404  {"error":"item_not_found","message":"Item with id 9999 was not found"}
  ok   DELETE /api/items/1             204
   204: тіло порожнє
  ok   GET    /api/items/1             404  {"error":"item_not_found","message":"Item with id 1 was not found"}
   після DELETE сутність справді зникла
  ok   GET    /api/nothing-here        404  {"error":"route_not_found","message":"No route for GET /api/nothing-here"}
   невідомий маршрут - той самий формат помилки

=== 5. Middleware 1: логування запитів (метод, шлях, код, тривалість) ===

-- Node.js
  POST /api/items 400 2ms
  POST /api/items 400 1ms
  GET /api/items/abc 400 1ms
  GET /api/items/0 400 1ms
  GET /api/items/9999 404 1ms
  PUT /api/items/1 200 1ms
  PUT /api/items/9999 404 1ms
  DELETE /api/items/1 204 1ms
  GET /api/items/1 404 1ms
  GET /api/nothing-here 404 1ms
   усього рядків доступу: 20 (показано останні 10)

-- Go
  POST /api/items 400 0ms
  POST /api/items 400 0ms
  GET /api/items/abc 400 0ms
  GET /api/items/0 400 0ms
  GET /api/items/9999 404 0ms
  PUT /api/items/1 200 0ms
  PUT /api/items/9999 404 0ms
  DELETE /api/items/1 204 0ms
  GET /api/items/1 404 0ms
  GET /api/nothing-here 404 0ms
   усього рядків доступу: 20 (показано останні 10)

=== 6. Підміна Repository: InMemory -> File, той самий Service ===

-- Перший запуск із файловим сховищем
   node listening on 3100, repository: file
   go listening on 8180, repository: file
  ok   POST   /api/items               201  {"id":1,"name":"Persisted","description":"survives a restart"}
  ok   POST   /api/items               201  {"id":1,"name":"Persisted","description":"survives a restart"}

-- Перезапуск: процеси вбито, дані лишились у файлі
   node listening on 3100, repository: file
   go listening on 8180, repository: file
  ok   GET    /api/items               200  [{"id":1,"name":"Persisted","description":"survives a restart"}]
   Node: сутність на місці після перезапуску
  ok   GET    /api/items               200  [{"id":1,"name":"Persisted","description":"survives a restart"}]
   Go: сутність на місці після перезапуску

-- DataStore на диску
  C:\uni_year_4\node_go\lab_4\data\node-items.json
    {
      "items": [
        {
          "id": 1,
          "name": "Persisted",
          "description": "survives a restart"
        }
      ],
      "nextId": 2
    }
  C:\uni_year_4\node_go\lab_4\data\go-items.json
    {
      "items": [
        {
          "id": 1,
          "name": "Persisted",
          "description": "survives a restart"
        }
      ],
      "nextId": 2
    }
   Змінився лише один рядок у src/server.js та cmd/server/main.go (вибір репозиторію).
   Код Service, Controller і Router - той самий, перекомпіляції не було: бінарник той самий.

=== 7. 500 Internal Server Error через той самий обробник ===
   файловий DataStore наведено на зіпсований файл: C:\uni_year_4\node_go\lab_4\data\corrupt.json
   це справжній збій інфраструктури - ані debug-маршруту, ані спецкоду в сервісах
   node listening on 3100, repository: file
   go listening on 8180, repository: file
  ok   GET    /api/items               500  {"error":"internal_error","message":"Internal server error"}
   Node: Service не перетворив збій у 4xx, обробник віддав 500
  ok   GET    /api/items               500  {"error":"internal_error","message":"Internal server error"}
   Go: те саме через response.WriteError

-- Деталі збою лишились у логах сервера, клієнту їх не віддали
  node: unhandled error on GET /api/items: Expected property name or '}' in JSON at position 2 (line 1 column 3)
  go:   2026/10/17 16:56:50 unhandled error on GET /api/items: corrupt data store at C:\uni_year_4\node_go\lab_4\data\corrupt.json: invalid character 'n' looking for beginning of object key string

=== 8. Тести рівня API ===

-- Node.js: node --test --test-reporter=spec tests/item.api.test.js tests/item.repository.test.js
  [--] GET /health
    [ok] answers 200 and names the wired repository (43.6477ms)
  [ok] GET /health (44.2833ms)
  [--] POST /api/items
    [ok] creates an item and answers 201 with the stored representation (20.6811ms)
    [ok] answers 400 when the required field is missing (5.237ms)
    [ok] answers 400 when the name is empty (5.7827ms)
    [ok] answers 400 when the body is not valid JSON (8.9131ms)
    [ok] answers 400 when the content type is not JSON (9.307ms)
    [ok] answers 409 when the name is already taken, ignoring case (4.0959ms)
  [ok] POST /api/items (54.7913ms)
  [--] GET /api/items
    [ok] answers 200 with the list (3.6562ms)
  [ok] GET /api/items (4.4332ms)
  [--] GET /api/items/:id
    [ok] answers 200 for an existing item (6.3539ms)
    [ok] answers 404 for a missing item (6.3104ms)
    [ok] answers 400 for an identifier that is not a number (4.8478ms)
    [ok] answers 400 for a zero identifier (3.0547ms)
  [ok] GET /api/items/:id (21.3189ms)
  [--] PUT /api/items/:id
    [ok] answers 200 and returns the updated item (3.9405ms)
    [ok] answers 404 for a missing item (3.6737ms)
    [ok] answers 400 for an invalid identifier (3.9594ms)
  [ok] PUT /api/items/:id (11.8822ms)
  [--] DELETE /api/items/:id
    [ok] answers 204 with an empty body (3.425ms)
    [ok] leaves the item gone, so a second read answers 404 (2.7445ms)
    [ok] answers 404 when deleting an item that is already gone (2.6726ms)
  [ok] DELETE /api/items/:id (9.1496ms)
  [--] unknown routes
    [ok] answer 404 through the same centralized formatter (3.9714ms)
  [ok] unknown routes (4.2334ms)
  [--] error responses
    [ok] always carry an error code and a human-readable message (11.7206ms)
  [ok] error responses (11.9967ms)
  [--] InMemoryItemRepository: the ItemRepository contract
    [ok] implements every method of the contract (1.025ms)
    [ok] starts empty (1.0555ms)
    [ok] assigns consecutive ids on create (0.2255ms)
    [ok] finds a stored row by id (0.3019ms)
    [ok] signals a missing row with RepositoryNotFoundError (0.7272ms)
    [ok] matches findByName case-insensitively and returns null when absent (0.2353ms)
    [ok] updates a row in place (0.3324ms)
    [ok] removes a row (0.28ms)
    [ok] does not let a caller mutate stored state through a returned object (0.4595ms)
    [ok] serves the same ItemService without a single change to it (1.5916ms)
  [ok] InMemoryItemRepository: the ItemRepository contract (10.1602ms)
  [--] FileItemRepository: the ItemRepository contract
    [ok] implements every method of the contract (0.261ms)
    [ok] starts empty (7.7384ms)
    [ok] assigns consecutive ids on create (7.828ms)
    [ok] finds a stored row by id (4.7191ms)
    [ok] signals a missing row with RepositoryNotFoundError (1.4736ms)
    [ok] matches findByName case-insensitively and returns null when absent (6.1827ms)
    [ok] updates a row in place (8.7654ms)
    [ok] removes a row (7.3203ms)
    [ok] does not let a caller mutate stored state through a returned object (4.0772ms)
    [ok] serves the same ItemService without a single change to it (6.3556ms)
  [ok] FileItemRepository: the ItemRepository contract (55.5326ms)
  [--] FileItemRepository: storage-specific behaviour
    [ok] survives being reopened, which the in-memory one cannot (6.2095ms)
    [ok] serializes concurrent writes instead of losing them (31.847ms)
    [ok] reports a corrupt store as an ordinary failure, not as a missing row (3.2401ms)
  [ok] FileItemRepository: storage-specific behaviour (41.6518ms)
  [--] assertItemRepository
    [ok] names every missing method (0.2359ms)
    [ok] rejects a non-object (0.1071ms)
  [ok] assertItemRepository (0.4568ms)
  [ i] tests 45
  [ i] suites 12
  [ i] pass 45
  [ i] fail 0
  [ i] cancelled 0
  [ i] skipped 0
  [ i] todo 0
  [ i] duration_ms 408.3299

-- Go: go test ./tests -count=1 -run ^(TestAPI|TestRepository)
  --- PASS: TestAPIHealth (0.00s)
  --- PASS: TestAPICreate (0.01s)
  --- PASS: TestAPIList (0.00s)
  --- PASS: TestAPIGetByID (0.00s)
  --- PASS: TestAPIUpdate (0.00s)
  --- PASS: TestAPIDelete (0.00s)
  --- PASS: TestAPIRoutingEdges (0.00s)
  --- PASS: TestAPIInternalError (0.00s)
  --- PASS: TestAPIErrorShape (0.00s)
  --- PASS: TestRepositoryContract (0.03s)
  --- PASS: TestRepositoryFileSpecifics (0.09s)
  ok  	lab4-go/tests	1.249s

=== 9. Що чим підтверджено ===
| Вимога лабораторної                                   | Етап |
|-------------------------------------------------------|------|
| Router / Controller / Service / Repository / DataStore | 2-8  |
| Усі обов'язкові endpoint                              | 4    |
| 200 / 201 / 204                                       | 4    |
| 400 Bad Request (поле, тип, порожнє, JSON, id)        | 4    |
| 404 Not Found                                         | 4    |
| 409 Conflict (дублювання за бізнес-логікою)           | 4    |
| 500 Internal Server Error                             | 7    |
| Централізована обробка помилок, один формат           | 4, 7 |
| Middleware 1: логування method/path/status/duration   | 5    |
| Middleware 2: валідація id і тіла до Service          | 4    |
| Підміна InMemory -> File без зміни Service            | 6    |
| Тести Service без HTTP-сервера                        | 2    |
| Тести API                                             | 8    |

ВСЕ ЗЕЛЕНЕ: усі перевірки цього прогону пройдені.
   логи сервісів: C:\uni_year_4\node_go\lab_4\logs
```

---

## 4. Що з цього читається

### Обидва сервіси відповідають однаково

На всіх 19 запитах статус і машинний код помилки збіглися між Express і
`net/http`. Єдина змістовна розбіжність — текст повідомлення для неправильного
типу поля:

| Запит | Node.js | Go |
|---|---|---|
| `POST {"name":42}` | `invalid_item`, `name is required and must be a string` | `invalid_item`, `field "name" must be of type string` |

Причина архітектурна, а не випадкова. В Express тіло вже розібране в
`express.json()`, тому `42` доходить до валідації моделі як значення не того
типу. У Go `json.Unmarshal` зупиняється раніше й повертає
`*json.UnmarshalTypeError`, а контролер відрізняє цю помилку від синтаксичної —
тому може назвати конкретне поле. Статус і код при цьому однакові, тож клієнту
різниця не видна.

### Валідація справді зупиняє запит до Service

`GET /api/items/abc` і `GET /api/items/0` дають 400 `invalid_id`. Ці відповіді
формує middleware, тому Controller за ці запити не викликається, а Service —
тим більше. Те саме для `Content-Type: text/plain`: 400
`invalid_content_type` приходить до розбору тіла.

### Логування міряє весь ланцюг

У логу є рядки зі статусами 400 і 404, тобто логер бачить і ті відповіді, які
сформував обробник помилок, а не лише успішні. Це наслідок того, що він стоїть
зовні всього ланцюга middleware.

Тривалість у Node — 0–2 мс, у Go — 0–1 мс. Числа тут нічого не доводять: обидва
сервіси працюють з памʼяттю й без навантаження, тож різниця в межах похибки
округлення до цілих мілісекунд. Порівняння продуктивності — тема лабораторної 2,
не цієї.

### Підміна сховища не зачепила бізнес-логіку

Між етапом 5 (`memory`) і етапом 6 (`file`) бінарник Go не перезбирався, а
файли `services/`, `controllers/` і `routes/` не редагувались. Змінилося лише
значення `ITEM_REPO`, яке читає один рядок у composition root. Після вбивства
процесів і повторного запуску `GET /api/items` повернув створену сутність —
тобто працювало справді інше сховище, а не той самий масив у памʼяті.

### 500 відрізняється від 4xx за походженням

Зіпсований файл сховища дав 500 `internal_error` в обох сервісах, причому
клієнт отримав лише `Internal server error`, а справжня причина лишилася в
логах:

```text
node: unhandled error on GET /api/items: Expected property name or '}' in JSON at position 2
go:   unhandled error on GET /api/items: corrupt data store at ...corrupt.json: invalid character 'n'
```

Це і є практичний сенс правила «Service класифікує лише те, що розуміє»: якби
він спробував перетворити будь-який збій репозиторію в доменну помилку, клієнт
отримав би 404 або 400 — тобто неправдиву інформацію про те, хто винен.

### Тести Service не торкаються мережі

24 тести бізнес-логіки в Node виконались за 109 мс, а вісім функцій у Go — за
час, який `go test` округлює до 0.00 с на кожну. Тести API того ж обсягу
коштують 408 мс, бо кожен піднімає сервер на ефемерному порту. Різниця на
порядок — це й є та перевага, за яку заплачено розбиттям на рівні.
