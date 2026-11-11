
## 1. Тестове джерело даних

- Генератор — [tools/generate-dataset.js:103](node-service/tools/generate-dataset.js#L103)
- Запис із backpressure — [tools/generate-dataset.js:152](node-service/tools/generate-dataset.js#L152)

## 2. Readable Stream і розмір порцій

- `createReadStream` з `highWaterMark` — [src/streams/pipeline.runner.js:103](node-service/src/streams/pipeline.runner.js#L103)
- Межі порцій і UTF-8 — [src/streams/line-split.transform.js:39](node-service/src/streams/line-split.transform.js#L39)

## 3. Transform Stream і новий файл

- Парсинг, фільтр, статистика — [src/streams/event-analyzer.transform.js:68](node-service/src/streams/event-analyzer.transform.js#L68)
- Writable у файл — [src/streams/pipeline.runner.js:116](node-service/src/streams/pipeline.runner.js#L116)

## 4. Звʼязування через pipe()

- Ланцюг `pipe()` — [src/streams/pipeline.runner.js:62](node-service/src/streams/pipeline.runner.js#L62)

## 5. Backpressure у Streams

- Повільний Writable — [src/streams/slow-writable.js:21](node-service/src/streams/slow-writable.js#L21)
- Сценарій A — [src/streams/pipeline.runner.js:325](node-service/src/streams/pipeline.runner.js#L325)
- Сценарій B — [src/streams/pipeline.runner.js:331](node-service/src/streams/pipeline.runner.js#L331)
- Сценарій C — [src/streams/pipeline.runner.js:320](node-service/src/streams/pipeline.runner.js#L320)
- Таблиця — [docs/lab5/backpressure.md](docs/lab5/backpressure.md)

## 6. WebSocket-сервер

- HTTP `upgrade` — [src/realtime/ws-server.js:63](node-service/src/realtime/ws-server.js#L63)
- `broadcast` — [src/realtime/broadcaster.js:81](node-service/src/realtime/broadcaster.js#L81)

## 7. Реєстр клієнтів і обмін повідомленнями

- Реєстр активних зʼєднань — [src/realtime/client-registry.js:72](node-service/src/realtime/client-registry.js#L72)
- Розсилка повідомлення іншим — [src/realtime/ws-server.js:231](node-service/src/realtime/ws-server.js#L231)

## 8. Життєвий цикл зʼєднання

- Автентифікація і таймаут — [src/realtime/ws-server.js:182](node-service/src/realtime/ws-server.js#L182)
- Невалідний кадр — [src/realtime/ws-server.js:248](node-service/src/realtime/ws-server.js#L248)
- Heartbeat і `terminate()` — [src/realtime/ws-server.js:262](node-service/src/realtime/ws-server.js#L262)
- Коди закриття — [src/realtime/ws-protocol.js:185](node-service/src/realtime/ws-protocol.js#L185)

## 9. Інтеграція Streams і WebSockets

- Звʼязка двох модулів — [src/realtime/job-bridge.js:15](node-service/src/realtime/job-bridge.js#L15)
- Кадр `chunk` — [src/realtime/ws-protocol.js:147](node-service/src/realtime/ws-protocol.js#L147)

## 10. Backpressure у WebSocket

- Класифікація кадрів — [src/realtime/backpressure-policy.js:37](node-service/src/realtime/backpressure-policy.js#L37)
- Точка рішення — [src/realtime/backpressure-policy.js:98](node-service/src/realtime/backpressure-policy.js#L98)
- Відключення повільного клієнта — [src/realtime/broadcaster.js:179](node-service/src/realtime/broadcaster.js#L179)

## Інтеграція у структуру лабораторної 4

- Композиція застосунку — [src/app.js:29](node-service/src/app.js#L29)
- Сервіс задач — [src/services/stream.service.js:38](node-service/src/services/stream.service.js#L38)
- Тести — [tests/](node-service/tests/)
