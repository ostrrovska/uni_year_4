// API-layer tests. The application is wired exactly as cmd/server wires it and
// served over a real loopback socket, so the whole chain - middleware, router,
// controller, service, repository - is exercised end to end.
package tests

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"lab4-go/internal/controller"
	"lab4-go/internal/model"
	"lab4-go/internal/repository"
	"lab4-go/internal/router"
	"lab4-go/internal/service"
)

func newTestServer(t *testing.T, repo repository.ItemRepository) *httptest.Server {
	t.Helper()

	handler := router.New(
		controller.NewItemController(service.NewItemService(repo)),
		controller.NewHealthController("memory"),
	)

	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)

	return server
}

func newMemoryServer(t *testing.T) *httptest.Server {
	t.Helper()
	return newTestServer(t, repository.NewInMemoryItemRepository())
}

type apiResponse struct {
	status   int
	location string
	body     []byte
}

// request sends a raw body, so a malformed-JSON case can be built as easily as
// a well-formed one.
func request(t *testing.T, server *httptest.Server, method, path, contentType, body string) apiResponse {
	t.Helper()

	var reader io.Reader
	if body != "" {
		reader = strings.NewReader(body)
	}

	req, err := http.NewRequest(method, server.URL+path, reader)
	if err != nil {
		t.Fatalf("building %s %s: %v", method, path, err)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}

	res, err := server.Client().Do(req)
	if err != nil {
		t.Fatalf("%s %s: %v", method, path, err)
	}
	defer res.Body.Close()

	payload, err := io.ReadAll(res.Body)
	if err != nil {
		t.Fatalf("reading the body of %s %s: %v", method, path, err)
	}

	return apiResponse{status: res.StatusCode, location: res.Header.Get("Location"), body: payload}
}

func getJSON(t *testing.T, server *httptest.Server, path string) apiResponse {
	t.Helper()
	return request(t, server, http.MethodGet, path, "", "")
}

func postJSON(t *testing.T, server *httptest.Server, path, body string) apiResponse {
	t.Helper()
	return request(t, server, http.MethodPost, path, "application/json", body)
}

func (r apiResponse) requireStatus(t *testing.T, want int) apiResponse {
	t.Helper()

	if r.status != want {
		t.Fatalf("status = %d, want %d; body: %s", r.status, want, r.body)
	}
	return r
}

func (r apiResponse) item(t *testing.T) model.Item {
	t.Helper()

	var item model.Item
	if err := json.Unmarshal(r.body, &item); err != nil {
		t.Fatalf("decoding an item from %s: %v", r.body, err)
	}
	return item
}

func (r apiResponse) errorCode(t *testing.T) string {
	t.Helper()

	var body struct {
		Error   string `json:"error"`
		Message string `json:"message"`
	}
	if err := json.Unmarshal(r.body, &body); err != nil {
		t.Fatalf("decoding an error from %s: %v", r.body, err)
	}
	if body.Message == "" {
		t.Errorf("error %q carries no message", body.Error)
	}
	return body.Error
}

func (r apiResponse) requireError(t *testing.T, status int, code string) {
	t.Helper()

	r.requireStatus(t, status)
	if got := r.errorCode(t); got != code {
		t.Errorf("error = %q, want %q", got, code)
	}
}

func TestAPIHealth(t *testing.T) {
	server := newMemoryServer(t)

	response := getJSON(t, server, "/health").requireStatus(t, http.StatusOK)

	var body map[string]string
	if err := json.Unmarshal(response.body, &body); err != nil {
		t.Fatalf("decoding %s: %v", response.body, err)
	}
	if body["status"] != "ok" {
		t.Errorf("status = %q, want ok", body["status"])
	}
	if body["repository"] != "memory" {
		t.Errorf("repository = %q, want memory", body["repository"])
	}
}

func TestAPICreate(t *testing.T) {
	t.Run("answers 201 with the stored representation", func(t *testing.T) {
		server := newMemoryServer(t)

		response := postJSON(t, server, "/api/items", `{"name":"Keyboard","description":"Mechanical"}`)

		response.requireStatus(t, http.StatusCreated)
		want := model.Item{ID: 1, Name: "Keyboard", Description: "Mechanical"}
		if got := response.item(t); got != want {
			t.Errorf("item = %+v, want %+v", got, want)
		}
		if response.location != "/api/items/1" {
			t.Errorf("Location = %q, want /api/items/1", response.location)
		}
	})

	t.Run("answers 400 when the required field is missing", func(t *testing.T) {
		server := newMemoryServer(t)

		postJSON(t, server, "/api/items", `{"description":"nameless"}`).
			requireError(t, http.StatusBadRequest, "invalid_item")
	})

	t.Run("answers 400 when the name is empty", func(t *testing.T) {
		server := newMemoryServer(t)

		postJSON(t, server, "/api/items", `{"name":"   "}`).
			requireError(t, http.StatusBadRequest, "invalid_item")
	})

	t.Run("answers 400 when a field has the wrong type", func(t *testing.T) {
		server := newMemoryServer(t)

		postJSON(t, server, "/api/items", `{"name":42}`).
			requireError(t, http.StatusBadRequest, "invalid_item")
	})

	t.Run("answers 400 when the body is not valid JSON", func(t *testing.T) {
		server := newMemoryServer(t)

		postJSON(t, server, "/api/items", `{ "name": `).
			requireError(t, http.StatusBadRequest, "invalid_json")
	})

	t.Run("answers 400 when the content type is not JSON", func(t *testing.T) {
		server := newMemoryServer(t)

		request(t, server, http.MethodPost, "/api/items", "text/plain", "name=Keyboard").
			requireError(t, http.StatusBadRequest, "invalid_content_type")
	})

	t.Run("answers 409 when the name is already taken, ignoring case", func(t *testing.T) {
		server := newMemoryServer(t)
		postJSON(t, server, "/api/items", `{"name":"Keyboard"}`).requireStatus(t, http.StatusCreated)

		postJSON(t, server, "/api/items", `{"name":"KEYBOARD"}`).
			requireError(t, http.StatusConflict, "item_name_taken")
	})
}

func TestAPIList(t *testing.T) {
	server := newMemoryServer(t)
	postJSON(t, server, "/api/items", `{"name":"Keyboard"}`).requireStatus(t, http.StatusCreated)
	postJSON(t, server, "/api/items", `{"name":"Mouse"}`).requireStatus(t, http.StatusCreated)

	response := getJSON(t, server, "/api/items").requireStatus(t, http.StatusOK)

	var items []model.Item
	if err := json.Unmarshal(response.body, &items); err != nil {
		t.Fatalf("decoding %s: %v", response.body, err)
	}
	if len(items) != 2 {
		t.Fatalf("len(items) = %d, want 2", len(items))
	}
	if items[0].Name != "Keyboard" || items[1].Name != "Mouse" {
		t.Errorf("items = %+v, want Keyboard then Mouse", items)
	}
}

func TestAPIGetByID(t *testing.T) {
	server := newMemoryServer(t)
	postJSON(t, server, "/api/items", `{"name":"Keyboard"}`).requireStatus(t, http.StatusCreated)

	t.Run("answers 200 for an existing item", func(t *testing.T) {
		response := getJSON(t, server, "/api/items/1").requireStatus(t, http.StatusOK)

		if got := response.item(t); got.Name != "Keyboard" {
			t.Errorf("name = %q, want Keyboard", got.Name)
		}
	})

	t.Run("answers 404 for a missing item", func(t *testing.T) {
		getJSON(t, server, "/api/items/9999").
			requireError(t, http.StatusNotFound, "item_not_found")
	})

	// The id middleware rejects these before the controller runs, so neither
	// the Service nor the Repository is ever reached.
	t.Run("answers 400 for an identifier that is not a number", func(t *testing.T) {
		getJSON(t, server, "/api/items/abc").
			requireError(t, http.StatusBadRequest, "invalid_id")
	})

	t.Run("answers 400 for a zero identifier", func(t *testing.T) {
		getJSON(t, server, "/api/items/0").
			requireError(t, http.StatusBadRequest, "invalid_id")
	})

	t.Run("answers 400 for a negative identifier", func(t *testing.T) {
		getJSON(t, server, "/api/items/-1").
			requireError(t, http.StatusBadRequest, "invalid_id")
	})
}

func TestAPIUpdate(t *testing.T) {
	server := newMemoryServer(t)
	postJSON(t, server, "/api/items", `{"name":"Keyboard","description":"old"}`).
		requireStatus(t, http.StatusCreated)

	t.Run("answers 200 and returns the updated item", func(t *testing.T) {
		response := request(t, server, http.MethodPut, "/api/items/1", "application/json",
			`{"name":"Keypad","description":"Compact"}`)

		response.requireStatus(t, http.StatusOK)
		want := model.Item{ID: 1, Name: "Keypad", Description: "Compact"}
		if got := response.item(t); got != want {
			t.Errorf("item = %+v, want %+v", got, want)
		}
	})

	t.Run("answers 404 for a missing item", func(t *testing.T) {
		request(t, server, http.MethodPut, "/api/items/9999", "application/json", `{"name":"Ghost"}`).
			requireError(t, http.StatusNotFound, "item_not_found")
	})

	t.Run("answers 400 for an invalid identifier", func(t *testing.T) {
		request(t, server, http.MethodPut, "/api/items/abc", "application/json", `{"name":"Ghost"}`).
			requireError(t, http.StatusBadRequest, "invalid_id")
	})
}

func TestAPIDelete(t *testing.T) {
	server := newMemoryServer(t)
	postJSON(t, server, "/api/items", `{"name":"Keyboard"}`).requireStatus(t, http.StatusCreated)

	t.Run("answers 204 with an empty body", func(t *testing.T) {
		response := request(t, server, http.MethodDelete, "/api/items/1", "", "").
			requireStatus(t, http.StatusNoContent)

		if len(response.body) != 0 {
			t.Errorf("body = %q, want empty", response.body)
		}
	})

	t.Run("leaves the item gone, so a second read answers 404", func(t *testing.T) {
		getJSON(t, server, "/api/items/1").
			requireError(t, http.StatusNotFound, "item_not_found")
	})

	t.Run("answers 404 when deleting an item that is already gone", func(t *testing.T) {
		request(t, server, http.MethodDelete, "/api/items/1", "", "").
			requireError(t, http.StatusNotFound, "item_not_found")
	})
}

func TestAPIRoutingEdges(t *testing.T) {
	server := newMemoryServer(t)

	t.Run("an unknown route answers 404 through the same formatter", func(t *testing.T) {
		getJSON(t, server, "/api/nothing-here").
			requireError(t, http.StatusNotFound, "route_not_found")
	})

	// The method is part of the route pattern, so a method the endpoint does
	// not declare matches no route and falls through to the catch-all. It is
	// answered 404 in the same JSON shape as every other error - the same
	// behaviour Express gives for an undeclared method, which keeps the two
	// services equivalent.
	t.Run("a method the endpoint does not declare answers 404", func(t *testing.T) {
		request(t, server, http.MethodPatch, "/api/items", "application/json", `{"name":"x"}`).
			requireError(t, http.StatusNotFound, "route_not_found")
	})
}

// A repository that fails is the honest way to reach the 500 branch: no debug
// route and no special case in the production code.
func TestAPIInternalError(t *testing.T) {
	server := newTestServer(t, brokenRepository{})

	getJSON(t, server, "/api/items").
		requireError(t, http.StatusInternalServerError, "internal_error")
}

func TestAPIErrorShape(t *testing.T) {
	server := newMemoryServer(t)

	failures := []apiResponse{
		getJSON(t, server, "/api/items/abc"),
		getJSON(t, server, "/api/items/9999"),
		postJSON(t, server, "/api/items", `{}`),
		getJSON(t, server, "/api/nothing-here"),
	}

	for _, response := range failures {
		if response.status < 400 {
			t.Errorf("status = %d, want a failure", response.status)
		}
		if code := response.errorCode(t); code == "" {
			t.Errorf("body %s carries no error code", response.body)
		}
	}
}
