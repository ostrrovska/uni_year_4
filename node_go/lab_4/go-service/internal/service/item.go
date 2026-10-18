// Package service holds the business logic.
package service

import (
	"errors"
	"strings"

	"lab4-go/internal/apperr"
	"lab4-go/internal/model"
	"lab4-go/internal/repository"
)

// ItemService depends on the ItemRepository interface, never on a concrete
// store, and mentions no HTTP concept at all - which is what lets the tests
// drive it without starting a server.
type ItemService struct {
	repository repository.ItemRepository
}

func NewItemService(repo repository.ItemRepository) *ItemService {
	return &ItemService{repository: repo}
}

func (s *ItemService) List() ([]model.Item, error) {
	return s.repository.FindAll()
}

func (s *ItemService) Get(id int) (model.Item, error) {
	if err := validateID(id); err != nil {
		return model.Item{}, err
	}

	item, err := s.repository.FindByID(id)
	if err != nil {
		return model.Item{}, translate(err, id)
	}

	return item, nil
}

func (s *ItemService) Create(draft model.Draft) (model.Item, error) {
	item, err := validateDraft(draft)
	if err != nil {
		return model.Item{}, err
	}

	if err := s.assertNameAvailable(item.Name, 0); err != nil {
		return model.Item{}, err
	}

	return s.repository.Create(item)
}

func (s *ItemService) Update(id int, draft model.Draft) (model.Item, error) {
	if err := validateID(id); err != nil {
		return model.Item{}, err
	}

	item, err := validateDraft(draft)
	if err != nil {
		return model.Item{}, err
	}

	if err := s.assertNameAvailable(item.Name, id); err != nil {
		return model.Item{}, err
	}

	item.ID = id
	updated, err := s.repository.Update(item)
	if err != nil {
		return model.Item{}, translate(err, id)
	}

	return updated, nil
}

func (s *ItemService) Delete(id int) error {
	if err := validateID(id); err != nil {
		return err
	}

	if err := s.repository.Delete(id); err != nil {
		return translate(err, id)
	}

	return nil
}

// The validation middleware already rejects a bad id at the HTTP edge. This
// guard is for every other caller: the Service defends its own contract.
func validateID(id int) error {
	if id < 1 {
		return apperr.Validation("invalid_id", "Item id must be a positive integer, got %d", id)
	}
	return nil
}

func validateDraft(draft model.Draft) (model.Item, error) {
	if problems := draft.Validate(); len(problems) > 0 {
		return model.Item{}, apperr.Validation("invalid_item", "%s", strings.Join(problems, "; "))
	}
	return draft.Normalize(), nil
}

// Business rule: names are unique, compared case-insensitively. It lives here
// and not in the Controller, which cannot know it without querying data.
// ownID is 0 on create, so no stored row can match itself.
func (s *ItemService) assertNameAvailable(name string, ownID int) error {
	existing, found, err := s.repository.FindByName(name)
	if err != nil {
		return err
	}

	if found && existing.ID != ownID {
		return apperr.Conflict("item_name_taken", "Item with name %q already exists", name)
	}

	return nil
}

// Storage vocabulary stops here: "row absent" becomes a domain not-found.
// Anything else is an infrastructure failure and travels on untouched, so the
// HTTP layer reports 500 instead of inventing a 4xx.
func translate(err error, id int) error {
	if errors.Is(err, repository.ErrNotFound) {
		return apperr.NotFound("item_not_found", "Item with id %d was not found", id)
	}
	return err
}
