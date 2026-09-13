# Lab 1: HTTP services in Node.js and Go

This repository contains two identical in-memory HTTP CRUD services:

- `node-service/` — Node.js service using the built-in `http` module
- `go-service/` — Go service using the standard `net/http` package

## Run both services

> Use these commands in Git Bash. Do not use PowerShell syntax like `&` in bash.

### 1) Start the Node service

```bash
cd /c/uni_year_4/node_go/lab_1/node-service
npm start
```

Expected output:

```text
Node service running on http://localhost:3000
```

### 2) Start the Go service

```bash
cd /c/uni_year_4/node_go/lab_1/go-service
/c/Program\ Files/Go/bin/go.exe run .
```

Expected output:

```text
Go service running on http://localhost:8080
```

> Note: the `&` operator is a PowerShell feature, not a bash feature. In Git Bash, call the Go executable directly.
> Also, do not run `cd "C:\Program Files\Go\bin\go.exe"` because that is a file, not a directory.

## Endpoints

### Node service (`http://localhost:3000`)

- `GET /health`
- `GET /items`
- `GET /items/:id`
- `POST /items`
- `PUT /items/:id`
- `DELETE /items/:id`

### Go service (`http://localhost:8080`)

- `GET /health`
- `GET /items`
- `GET /items/:id`
- `POST /items`
- `PUT /items/:id`
- `DELETE /items/:id`

## Notes

- The data is stored only in memory, so it resets when the server restarts.
- Node uses port `3000`.
- Go uses port `8080`.
- The services are intentionally separate to compare runtime behavior and port management.
