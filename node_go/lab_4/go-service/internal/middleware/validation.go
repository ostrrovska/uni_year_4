package middleware

import (
	"context"
	"mime"
	"net/http"
	"regexp"
	"strconv"

	"lab4-go/internal/apperr"
	"lab4-go/internal/response"
)

// Middleware 2: validation shared by several endpoints. It runs before any
// controller, so a malformed request never reaches the Service or the
// Repository - and the parsed id is put on the request context, so no
// controller repeats the parsing.

type contextKey string

const itemIDKey contextKey = "itemID"

var positiveInteger = regexp.MustCompile(`^[1-9][0-9]*$`)

// ValidateID guards every route that carries the {id} wildcard.
func ValidateID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw := r.PathValue("id")

		if !positiveInteger.MatchString(raw) {
			response.WriteError(w, r,
				apperr.Validation("invalid_id", "Item id must be a positive integer, got %q", raw))
			return
		}

		id, err := strconv.Atoi(raw)
		if err != nil {
			response.WriteError(w, r,
				apperr.Validation("invalid_id", "Item id is out of range: %q", raw))
			return
		}

		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), itemIDKey, id)))
	})
}

// ItemID returns the identifier ValidateID parsed. A controller reached without
// that middleware is a wiring mistake, reported as such.
func ItemID(r *http.Request) (int, error) {
	id, ok := r.Context().Value(itemIDKey).(int)
	if !ok {
		return 0, apperr.Validation("invalid_id", "Item id is missing from the request")
	}
	return id, nil
}

// RequireJSONBody guards the write endpoints. Malformed JSON is not its
// business: the decoder in the controller reports that as 400 invalid_json.
func RequireJSONBody(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
		if err != nil || mediaType != "application/json" {
			response.WriteError(w, r,
				apperr.Validation("invalid_content_type", "Content-Type must be application/json"))
			return
		}

		next.ServeHTTP(w, r)
	})
}
