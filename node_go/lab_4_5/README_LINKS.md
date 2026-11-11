# Лабораторна 5 — завдання і код

## 1. Створення тестового джерела даних

- Генератор 256 MB NDJSON — [tools/generate-dataset.js](node-service/tools/generate-dataset.js#L103)
- Запис із дотриманням backpressure — [tools/generate-dataset.js:152](node-service/tools/generate-dataset.js#L152)
- Детермінований LCG — [tools/generate-dataset.js:34](node-service/tools/generate-dataset.js#L34)
- Завдання на сторінці — [src/services/lab-demo.service.js → taskDataset](node-service/src/services/lab-demo.service.js#L189)

## 2. Readable Stream і параметри розміру порцій

- `fs.createReadStream` із `highWaterMark` — [src/streams/pipeline.runner.js:103](node-service/src/streams/pipeline.runner.js#L103)
- Розрізання порцій на рядки — [src/streams/line-split.transform.js](node-service/src/streams/line-split.transform.js#L17)
- `_transform`: межі порцій і `StringDecoder` — [src/streams/line-split.transform.js:39](node-service/src/streams/line-split.transform.js#L39)
- `_flush`: останній рядок без `\n` — [src/streams/line-split.transform.js:76](node-service/src/streams/line-split.transform.js#L76)
- Статистика порцій — [src/streams/line-split.transform.js:91](node-service/src/streams/line-split.transform.js#L91)
- Дослід трьох `highWaterMark` — [tools/stream-run.js](node-service/tools/stream-run.js#L119)
- Тести меж порцій — [tests/stream.transform.test.js](node-service/tests/stream.transform.test.js#L44)
- Завдання на сторінці — [src/services/lab-demo.service.js → taskReadable](node-service/src/services/lab-demo.service.js#L257)

## 3. Transform Stream і запис у новий файл

- Transform: парсинг, фільтр, статистика, збагачення — [src/streams/event-analyzer.transform.js](node-service/src/streams/event-analyzer.transform.js#L24)
- `_transform` — [src/streams/event-analyzer.transform.js:68](node-service/src/streams/event-analyzer.transform.js#L68)
- `_flush` і підсумкова статистика — [src/streams/event-analyzer.transform.js:123](node-service/src/streams/event-analyzer.transform.js#L123)
- Бакети затримки — [src/streams/event-analyzer.transform.js:16](node-service/src/streams/event-analyzer.transform.js#L16)
- Writable у новий файл — [src/streams/pipeline.runner.js:116](node-service/src/streams/pipeline.runner.js#L116)
- Тести фільтра і статистики — [tests/stream.transform.test.js](node-service/tests/stream.transform.test.js#L118)
- Завдання на сторінці — [src/services/lab-demo.service.js → taskTransform](node-service/src/services/lab-demo.service.js#L350)

## 4. Звʼязування Streams через pipe()

- `readable.pipe(split).pipe(analyze).pipe(writable)` — [src/streams/pipeline.runner.js:62](node-service/src/streams/pipeline.runner.js#L62)
- Складання ланцюга і вибір режиму — [src/streams/pipeline.runner.js:75](node-service/src/streams/pipeline.runner.js#L75)
- `stream.pipeline()` як альтернатива — [src/streams/pipeline.runner.js:199](node-service/src/streams/pipeline.runner.js#L199)
- Тест `pipe` ≡ `pipeline` — [tests/stream.pipeline.test.js](node-service/tests/stream.pipeline.test.js#L68)
- Завдання на сторінці — [src/services/lab-demo.service.js → taskPipe](node-service/src/services/lab-demo.service.js#L515)

## 5. Backpressure у Streams

- Повільний Writable (`setTimeout` у `_write`) — [src/streams/slow-writable.js:21](node-service/src/streams/slow-writable.js#L21)
- Сценарій A — без контролю швидкості — [src/streams/pipeline.runner.js:325](node-service/src/streams/pipeline.runner.js#L325)
- Сценарій B — `pause()` / `drain` вручну — [src/streams/pipeline.runner.js:331](node-service/src/streams/pipeline.runner.js#L331)
- Сценарій C — `pipe()` — [src/streams/pipeline.runner.js:320](node-service/src/streams/pipeline.runner.js#L320)
- Запуск сценаріїв і замір — [src/streams/pipeline.runner.js:246](node-service/src/streams/pipeline.runner.js#L246)
- Семплер RSS і `writableLength` — [src/streams/metrics.js:16](node-service/src/streams/metrics.js#L16)
- Таблиця порівняння — [tools/backpressure-compare.js:101](node-service/tools/backpressure-compare.js#L101)
- Окремий процес на сценарій — [tools/backpressure-compare.js:167](node-service/tools/backpressure-compare.js#L167)
- Тести трьох сценаріїв — [tests/stream.backpressure.test.js](node-service/tests/stream.backpressure.test.js#L65)
- Готова таблиця результатів — [docs/lab5/backpressure.md](docs/lab5/backpressure.md)
- Завдання на сторінці — [src/services/lab-demo.service.js → taskBackpressure](node-service/src/services/lab-demo.service.js#L612)

## 6. WebSocket-сервер

- Створення сервера, `noServer: true` — [src/realtime/ws-server.js:31](node-service/src/realtime/ws-server.js#L31)
- Обробка HTTP `upgrade` — [src/realtime/ws-server.js:63](node-service/src/realtime/ws-server.js#L63)
- `connection` — [src/realtime/ws-server.js:77](node-service/src/realtime/ws-server.js#L77)
- `message` — [src/realtime/ws-server.js:122](node-service/src/realtime/ws-server.js#L122)
- `broadcast` — [src/realtime/broadcaster.js:81](node-service/src/realtime/broadcaster.js#L81)
- `disconnect` — [src/realtime/ws-server.js:156](node-service/src/realtime/ws-server.js#L156)
- Підключення до HTTP-сервера — [src/server.js:52](node-service/src/server.js#L52)
- Формат кадрів — [src/realtime/ws-protocol.js:105](node-service/src/realtime/ws-protocol.js#L105)
- Завдання на сторінці — [src/services/lab-demo.service.js → taskWebsocket](node-service/src/services/lab-demo.service.js#L750)

## 7. Реєстрація клієнта і обмін повідомленнями

- Реєстр активних зʼєднань — [src/realtime/client-registry.js:72](node-service/src/realtime/client-registry.js#L72)
- Реєстрація клієнта — [src/realtime/client-registry.js:78](node-service/src/realtime/client-registry.js#L78)
- Знімок для HTTP і кадру `stats` — [src/realtime/client-registry.js:120](node-service/src/realtime/client-registry.js#L120)
- `GET /api/ws/clients` — [src/routes/realtime.routes.js](node-service/src/routes/realtime.routes.js), [src/controllers/realtime.controller.js](node-service/src/controllers/realtime.controller.js), [src/services/realtime.service.js](node-service/src/services/realtime.service.js)
- Обробка `{"type":"message"}` і розсилка іншим — [src/realtime/ws-server.js:231](node-service/src/realtime/ws-server.js#L231)
- Фан-аут і фільтр за підписками — [src/realtime/broadcaster.js:81](node-service/src/realtime/broadcaster.js#L81)
- Теми підписок — [src/realtime/broadcaster.js:17](node-service/src/realtime/broadcaster.js#L17)
- Тести broadcast — [tests/ws.lifecycle.test.js](node-service/tests/ws.lifecycle.test.js#L234)
- Завдання на сторінці — [src/services/lab-demo.service.js → taskRegistry](node-service/src/services/lab-demo.service.js#L844)

## 8. Життєвий цикл WebSocket-зʼєднання

- Стани зʼєднання — [src/realtime/client-registry.js:18](node-service/src/realtime/client-registry.js#L18)
- `clientId`, `connectedAt`, `state` — [src/realtime/client-registry.js:25](node-service/src/realtime/client-registry.js#L25)
- Нове підключення і кадр `welcome` — [src/realtime/ws-server.js:77](node-service/src/realtime/ws-server.js#L77)
- Автентифікація `hello` і таймаут — [src/realtime/ws-server.js:182](node-service/src/realtime/ws-server.js#L182)
- Валідація кадрів — [src/realtime/ws-protocol.js:36](node-service/src/realtime/ws-protocol.js#L36)
- Реакція на невалідний кадр — [src/realtime/ws-server.js:248](node-service/src/realtime/ws-server.js#L248)
- Закриття зʼєднання — [src/realtime/ws-server.js:156](node-service/src/realtime/ws-server.js#L156)
- Втрата клієнта: heartbeat і `terminate()` — [src/realtime/ws-server.js:262](node-service/src/realtime/ws-server.js#L262)
- Коди закриття — [src/realtime/ws-protocol.js:185](node-service/src/realtime/ws-protocol.js#L185)
- Клієнт для перевірки життєвого циклу — [src/lab/ws-probe.js](node-service/src/lab/ws-probe.js), [tools/ws-client.js](node-service/tools/ws-client.js)
- Тести життєвого циклу — [tests/ws.lifecycle.test.js](node-service/tests/ws.lifecycle.test.js)
- Завдання на сторінці — [src/services/lab-demo.service.js → taskLifecycle](node-service/src/services/lab-demo.service.js#L964)

## 9. Інтеграція Streams і WebSockets

- Звʼязка подій конвеєра з розсилкою — [src/realtime/job-bridge.js:15](node-service/src/realtime/job-bridge.js#L15)
- Кадр `progress` — [src/realtime/job-bridge.js:29](node-service/src/realtime/job-bridge.js#L29), [src/realtime/ws-protocol.js:156](node-service/src/realtime/ws-protocol.js#L156)
- Кадр `chunk` з обробленими записами — [src/realtime/job-bridge.js:36](node-service/src/realtime/job-bridge.js#L36), [src/realtime/ws-protocol.js:147](node-service/src/realtime/ws-protocol.js#L147)
- Генерація подій прогресу в конвеєрі — [src/streams/pipeline.runner.js:153](node-service/src/streams/pipeline.runner.js#L153)
- Вибірка оброблених записів — [src/streams/pipeline.runner.js:172](node-service/src/streams/pipeline.runner.js#L172)
- Сервіс задач (не знає про WebSocket) — [src/services/stream.service.js:38](node-service/src/services/stream.service.js#L38)
- `POST /api/stream/jobs` — [src/routes/stream.routes.js](node-service/src/routes/stream.routes.js), [src/controllers/stream.controller.js](node-service/src/controllers/stream.controller.js)
- Підключення мостика — [src/server.js:65](node-service/src/server.js#L65)
- Тести прогресу і `chunk` — [tests/stream.pipeline.test.js](node-service/tests/stream.pipeline.test.js#L121)
- Завдання на сторінці — [src/services/lab-demo.service.js → taskIntegration](node-service/src/services/lab-demo.service.js#L1094)

## 10. Backpressure у WebSocket-сценарії

- Політика рішень — [src/realtime/backpressure-policy.js:43](node-service/src/realtime/backpressure-policy.js#L43)
- Класифікація кадрів — [src/realtime/backpressure-policy.js:37](node-service/src/realtime/backpressure-policy.js#L37)
- Спостереження за `bufferedAmount` — [src/realtime/backpressure-policy.js:67](node-service/src/realtime/backpressure-policy.js#L67)
- Точка рішення — [src/realtime/backpressure-policy.js:98](node-service/src/realtime/backpressure-policy.js#L98)
- Механізм 1: відкидання кадрів-стану — [src/realtime/backpressure-policy.js:71](node-service/src/realtime/backpressure-policy.js#L71)
- Механізм 2: rate limiting — [src/realtime/backpressure-policy.js:131](node-service/src/realtime/backpressure-policy.js#L131)
- Механізм 3: ліміт черги і відключення — [src/realtime/backpressure-policy.js:117](node-service/src/realtime/backpressure-policy.js#L117), [src/realtime/broadcaster.js:108](node-service/src/realtime/broadcaster.js#L108)
- Механізм 4: батчинг — [src/realtime/broadcaster.js:134](node-service/src/realtime/broadcaster.js#L134)
- Закриття повільного клієнта — [src/realtime/broadcaster.js:179](node-service/src/realtime/broadcaster.js#L179)
- Ліміти і налаштування — [src/config.js](node-service/src/config.js#L71)
- Повільний клієнт у досліді — [src/lab/ws-probe.js:156](node-service/src/lab/ws-probe.js#L156), [tools/ws-client.js:137](node-service/tools/ws-client.js#L137)
- Тести всіх механізмів — [tests/ws.backpressure.test.js](node-service/tests/ws.backpressure.test.js)
- Завдання на сторінці — [src/services/lab-demo.service.js → taskWsBackpressure](node-service/src/services/lab-demo.service.js#L1256)

## Інтеграція у структуру лабораторної 4

- Композиція застосунку — [src/app.js](node-service/src/app.js#L29)
- Запуск сервера — [src/server.js](node-service/src/server.js#L30)
- Конфігурація — [src/config.js](node-service/src/config.js)
- Доменні помилки — [src/errors/domain-error.js](node-service/src/errors/domain-error.js)
- Таблиця `kind` → HTTP-статус — [src/middleware/error-handler.js](node-service/src/middleware/error-handler.js#L6)
- Валідація запитів — [src/middleware/validation-stream.js](node-service/src/middleware/validation-stream.js)

## Сторінки і демо

- Сторінка завдань — [public/tasks.html](node-service/public/tasks.html), [public/tasks.js](node-service/public/tasks.js)
- Панель реального часу — [public/index.html](node-service/public/index.html), [public/app.js](node-service/public/app.js)
- Бекенд сторінки завдань — [src/services/lab-demo.service.js](node-service/src/services/lab-demo.service.js), [src/routes/lab.routes.js](node-service/src/routes/lab.routes.js), [src/controllers/lab.controller.js](node-service/src/controllers/lab.controller.js)
- Демо-скрипт — [demo-lab5.ps1](demo-lab5.ps1)
- Звіт — [README-lab5.md](README-lab5.md), [RESULTS-lab5.md](RESULTS-lab5.md)
