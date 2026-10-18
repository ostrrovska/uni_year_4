package controller

import (
	"net/http"

	"lab4-go/internal/response"
)

// HealthController answers the liveness probe. It also reports which repository
// implementation is wired in, which makes the memory -> file swap observable
// from outside without reading the logs.
type HealthController struct {
	repositoryName string
}

func NewHealthController(repositoryName string) *HealthController {
	return &HealthController{repositoryName: repositoryName}
}

func (c *HealthController) Check(w http.ResponseWriter, r *http.Request) error {
	return response.WriteJSON(w, http.StatusOK, map[string]string{
		"status":     "ok",
		"repository": c.repositoryName,
	})
}
