// Package router maps endpoints to controller methods and attaches middleware.
package router

import (
	"net/http"

	"lab4-go/internal/controller"
	"lab4-go/internal/middleware"
	"lab4-go/internal/response"
)

// New defines endpoints, HTTP methods, middleware and the binding to controller
// methods. Nothing else - no parsing, no validation logic, no business rules.
func New(items *controller.ItemController, health *controller.HealthController) http.Handler {
	mux := http.NewServeMux()

	// Go 1.22 patterns carry the method and the wildcard, so the method and the
	// path are matched by the router itself instead of inside a handler. A
	// method that does not match a registered pattern yields 405 from ServeMux.
	mux.Handle("GET /health", response.Handle(health.Check))

	mux.Handle("GET /api/items", response.Handle(items.List))
	mux.Handle("POST /api/items", middleware.RequireJSONBody(response.Handle(items.Create)))

	// One id check, shared by the three routes that take {id}.
	mux.Handle("GET /api/items/{id}", middleware.ValidateID(response.Handle(items.GetByID)))
	mux.Handle("PUT /api/items/{id}",
		middleware.ValidateID(middleware.RequireJSONBody(response.Handle(items.Update))))
	mux.Handle("DELETE /api/items/{id}", middleware.ValidateID(response.Handle(items.Delete)))

	mux.Handle("/", response.NotFound())

	// Outermost first: Logging measures everything below it, Recover catches a
	// panic from anywhere inside.
	return middleware.Logging(middleware.Recover(mux))
}
