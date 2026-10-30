// Package response is the single place in the program that knows HTTP status
// codes. The Service raises errors in its own vocabulary; the mapping happens
// here, so no handler and no middleware builds an error response of its own.
//
// It is a package of its own rather than part of controller because the
// validation middleware needs the same formatter, and the controller already
// imports the middleware.
package response

import (
	"encoding/json"
	"log"
	"net/http"

	"lab4-go/internal/apperr"
)

var kindToStatus = map[apperr.Kind]int{
	apperr.KindValidation: http.StatusBadRequest,
	apperr.KindNotFound:   http.StatusNotFound,
	apperr.KindConflict:   http.StatusConflict,
}

type errorBody struct {
	Error   string `json:"error"`
	Message string `json:"message"`
}

// HandlerFunc is an http.HandlerFunc that is allowed to fail.
type HandlerFunc func(http.ResponseWriter, *http.Request) error

// Handle adapts a failable handler to net/http. It is the Go counterpart of
// Express's next(err): a handler returns its error to one place instead of
// formatting a response itself.
func Handle(fn HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if err := fn(w, r); err != nil {
			WriteError(w, r, err)
		}
	}
}

func WriteJSON(w http.ResponseWriter, status int, payload any) error {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	return json.NewEncoder(w).Encode(payload)
}

func WriteError(w http.ResponseWriter, r *http.Request, err error) {
	if appError, ok := apperr.As(err); ok {
		status, known := kindToStatus[appError.Kind]
		if !known {
			status = http.StatusInternalServerError
		}
		_ = WriteJSON(w, status, errorBody{Error: appError.Code, Message: appError.Message})
		return
	}

	// Anything unrecognised is an infrastructure failure: logged in full, while
	// the client is told only that the server failed.
	log.Printf("unhandled error on %s %s: %v", r.Method, r.URL.Path, err)
	_ = WriteJSON(w, http.StatusInternalServerError, errorBody{
		Error:   "internal_error",
		Message: "Internal server error",
	})
}

// NotFound answers every request that matched no route, through the same
// formatter as every other error.
func NotFound() http.HandlerFunc {
	return Handle(func(w http.ResponseWriter, r *http.Request) error {
		return apperr.NotFound("route_not_found", "No route for %s %s", r.Method, r.URL.Path)
	})
}
