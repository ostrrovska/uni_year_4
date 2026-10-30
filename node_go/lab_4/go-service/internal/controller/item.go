// Package controller translates between HTTP and the Service.
package controller

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"

	"lab4-go/internal/apperr"
	"lab4-go/internal/middleware"
	"lab4-go/internal/model"
	"lab4-go/internal/response"
	"lab4-go/internal/service"
)

const maxBodyBytes = 1 << 20

// ItemController reads the request, calls one Service method, picks the status
// code and shapes the response. It never touches a repository or the data
// store, and it holds no business rule.
//
// Every method returns its error instead of formatting one, so the single
// formatter in package response decides the status code.
type ItemController struct {
	service *service.ItemService
}

func NewItemController(s *service.ItemService) *ItemController {
	return &ItemController{service: s}
}

func (c *ItemController) List(w http.ResponseWriter, r *http.Request) error {
	items, err := c.service.List()
	if err != nil {
		return err
	}

	return response.WriteJSON(w, http.StatusOK, items)
}

func (c *ItemController) GetByID(w http.ResponseWriter, r *http.Request) error {
	id, err := middleware.ItemID(r)
	if err != nil {
		return err
	}

	item, err := c.service.Get(id)
	if err != nil {
		return err
	}

	return response.WriteJSON(w, http.StatusOK, item)
}

func (c *ItemController) Create(w http.ResponseWriter, r *http.Request) error {
	draft, err := decodeDraft(r)
	if err != nil {
		return err
	}

	item, err := c.service.Create(draft)
	if err != nil {
		return err
	}

	w.Header().Set("Location", fmt.Sprintf("/api/items/%d", item.ID))

	return response.WriteJSON(w, http.StatusCreated, item)
}

func (c *ItemController) Update(w http.ResponseWriter, r *http.Request) error {
	id, err := middleware.ItemID(r)
	if err != nil {
		return err
	}

	draft, err := decodeDraft(r)
	if err != nil {
		return err
	}

	item, err := c.service.Update(id, draft)
	if err != nil {
		return err
	}

	return response.WriteJSON(w, http.StatusOK, item)
}

func (c *ItemController) Delete(w http.ResponseWriter, r *http.Request) error {
	id, err := middleware.ItemID(r)
	if err != nil {
		return err
	}

	if err := c.service.Delete(id); err != nil {
		return err
	}

	w.WriteHeader(http.StatusNoContent)

	return nil
}

// Parsing the body is the controller's job. A syntax error and a wrong field
// type are reported differently, because they are different client mistakes.
func decodeDraft(r *http.Request) (model.Draft, error) {
	var draft model.Draft

	err := json.NewDecoder(io.LimitReader(r.Body, maxBodyBytes)).Decode(&draft)
	if err == nil {
		return draft, nil
	}

	// An empty body is an empty object; the Service then reports the missing
	// required field, exactly as it would for {}.
	if errors.Is(err, io.EOF) {
		return draft, nil
	}

	var typeError *json.UnmarshalTypeError
	if errors.As(err, &typeError) {
		return draft, apperr.Validation("invalid_item",
			"field %q must be of type %s", typeError.Field, typeError.Type)
	}

	return draft, apperr.Validation("invalid_json", "Request body is not valid JSON")
}
