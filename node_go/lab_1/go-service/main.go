package main

import (
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "net/http"
    "strconv"
    "strings"
)

const port = 8080

type Item struct {
    ID          int    `json:"id"`
    Name        string `json:"name"`
    Description string `json:"description"`
}

var items []Item
var nextID = 1

func writeJSON(w http.ResponseWriter, status int, payload any) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(status)
    _ = json.NewEncoder(w).Encode(payload)
}

func readJSON(r *http.Request) (map[string]any, error) {
    defer r.Body.Close()
    body, err := io.ReadAll(r.Body)
    if err != nil {
        return nil, err
    }

    if len(strings.TrimSpace(string(body))) == 0 {
        return map[string]any{}, nil
    }

    var payload map[string]any
    if err := json.Unmarshal(body, &payload); err != nil {
        return nil, err
    }
    return payload, nil
}

func findItemByID(id int) (*Item, error) {
    for i := range items {
        if items[i].ID == id {
            return &items[i], nil
        }
    }
    return nil, errors.New("item not found")
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "Method not allowed"})
        return
    }
    writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func itemsHandler(w http.ResponseWriter, r *http.Request) {
    path := strings.TrimPrefix(r.URL.Path, "/items")

    switch {
    case r.Method == http.MethodGet && path == "":
        writeJSON(w, http.StatusOK, items)
    case r.Method == http.MethodGet && strings.HasPrefix(path, "/"):
        idStr := strings.TrimPrefix(path, "/")
        id, err := strconv.Atoi(idStr)
        if err != nil {
            writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid item id"})
            return
        }

        item, err := findItemByID(id)
        if err != nil {
            writeJSON(w, http.StatusNotFound, map[string]string{"error": "Item not found"})
            return
        }
        writeJSON(w, http.StatusOK, item)
    case r.Method == http.MethodPost && path == "":
        payload, err := readJSON(r)
        if err != nil {
            writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON"})
            return
        }

        name, ok := payload["name"].(string)
        if !ok || strings.TrimSpace(name) == "" {
            writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Name is required"})
            return
        }

        description := ""
        if desc, ok := payload["description"].(string); ok {
            description = desc
        }

        item := Item{ID: nextID, Name: strings.TrimSpace(name), Description: description}
        nextID++
        items = append(items, item)
        writeJSON(w, http.StatusCreated, item)
    case r.Method == http.MethodPut && strings.HasPrefix(path, "/"):
        idStr := strings.TrimPrefix(path, "/")
        id, err := strconv.Atoi(idStr)
        if err != nil {
            writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid item id"})
            return
        }

        _, err = findItemByID(id)
        if err != nil {
            writeJSON(w, http.StatusNotFound, map[string]string{"error": "Item not found"})
            return
        }

        payload, err := readJSON(r)
        if err != nil {
            writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON"})
            return
        }

        name, ok := payload["name"].(string)
        if !ok || strings.TrimSpace(name) == "" {
            writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Name is required"})
            return
        }

        for i := range items {
            if items[i].ID == id {
                items[i].Name = strings.TrimSpace(name)
                if desc, ok := payload["description"].(string); ok {
                    items[i].Description = desc
                }
                writeJSON(w, http.StatusOK, items[i])
                return
            }
        }
    case r.Method == http.MethodDelete && strings.HasPrefix(path, "/"):
        idStr := strings.TrimPrefix(path, "/")
        id, err := strconv.Atoi(idStr)
        if err != nil {
            writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid item id"})
            return
        }

        for i := range items {
            if items[i].ID == id {
                items = append(items[:i], items[i+1:]...)
                w.WriteHeader(http.StatusNoContent)
                return
            }
        }
        writeJSON(w, http.StatusNotFound, map[string]string{"error": "Item not found"})
    default:
        writeJSON(w, http.StatusNotFound, map[string]string{"error": "Not found"})
    }
}

func main() {
    http.HandleFunc("/health", healthHandler)
    http.HandleFunc("/items", itemsHandler)
    http.HandleFunc("/items/", itemsHandler)

    fmt.Printf("Go service running on http://localhost:%d\n", port)
    if err := http.ListenAndServe(fmt.Sprintf(":%d", port), nil); err != nil {
        panic(err)
    }
}
