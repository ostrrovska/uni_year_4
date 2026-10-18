// Package middleware holds logic shared by several endpoints, applied by the
// router.
package middleware

import (
	"log"
	"net/http"
	"os"
	"time"
)

// The access log is written without a timestamp prefix, so a line reads exactly
// as the specification asks: "GET /api/items/10 200 4ms". log.Logger is used
// rather than fmt.Printf because it serializes concurrent writes.
var accessLog = log.New(os.Stdout, "", 0)

// statusRecorder captures the status code, which http.ResponseWriter does not
// expose after the fact.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (w *statusRecorder) WriteHeader(status int) {
	w.status = status
	w.ResponseWriter.WriteHeader(status)
}

// A handler that writes a body without calling WriteHeader implies 200.
func (w *statusRecorder) Write(b []byte) (int, error) {
	if w.status == 0 {
		w.status = http.StatusOK
	}
	return w.ResponseWriter.Write(b)
}

// Logging is middleware 1: one line per request with method, path, status code
// and duration. It is the outermost wrapper, so it measures the whole chain,
// including the error handling.
func Logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		recorder := &statusRecorder{ResponseWriter: w}

		next.ServeHTTP(recorder, r)

		if recorder.status == 0 {
			recorder.status = http.StatusOK
		}

		accessLog.Printf("%s %s %d %dms",
			r.Method, r.URL.RequestURI(), recorder.status, time.Since(started).Milliseconds())
	})
}
