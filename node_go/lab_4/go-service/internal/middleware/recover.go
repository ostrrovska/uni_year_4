package middleware

import (
	"fmt"
	"net/http"

	"lab4-go/internal/response"
)

// Recover turns a panic in any handler into the same 500 response the formatter
// produces for an ordinary failure. Express forwards thrown errors to its error
// middleware on its own; net/http would instead drop the connection.
func Recover(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if recovered := recover(); recovered != nil {
				response.WriteError(w, r, fmt.Errorf("panic: %v", recovered))
			}
		}()

		next.ServeHTTP(w, r)
	})
}
