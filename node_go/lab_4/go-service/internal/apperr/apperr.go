// Package apperr defines the error vocabulary the Service layer speaks. It
// deliberately knows nothing about HTTP: mapping a Kind onto a status code is
// the HTTP layer's job, in package response.
package apperr

import (
	"errors"
	"fmt"
)

type Kind string

const (
	KindValidation Kind = "validation"
	KindNotFound   Kind = "not_found"
	KindConflict   Kind = "conflict"
)

// Error carries a kind, a machine-readable code and a message meant for the
// client.
type Error struct {
	Kind    Kind
	Code    string
	Message string
}

func (e *Error) Error() string {
	return fmt.Sprintf("%s (%s): %s", e.Kind, e.Code, e.Message)
}

func Validation(code, format string, args ...any) *Error {
	return newError(KindValidation, code, format, args...)
}

func NotFound(code, format string, args ...any) *Error {
	return newError(KindNotFound, code, format, args...)
}

func Conflict(code, format string, args ...any) *Error {
	return newError(KindConflict, code, format, args...)
}

func newError(kind Kind, code, format string, args ...any) *Error {
	return &Error{Kind: kind, Code: code, Message: fmt.Sprintf(format, args...)}
}

// As reports whether err is, or wraps, an *Error.
func As(err error) (*Error, bool) {
	var appError *Error
	if errors.As(err, &appError) {
		return appError, true
	}
	return nil, false
}
