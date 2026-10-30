// Package tests drives the application through its exported API only, which is
// what keeps the layer boundaries honest.
package tests

import (
	"errors"
	"testing"

	"lab4-go/internal/apperr"
	"lab4-go/internal/model"
	"lab4-go/internal/repository"
	"lab4-go/internal/service"
)

func ptr(value string) *string { return &value }

func newService() *service.ItemService {
	return service.NewItemService(repository.NewInMemoryItemRepository())
}

func draft(name string, description ...string) model.Draft {
	d := model.Draft{Name: ptr(name)}
	if len(description) > 0 {
		d.Description = ptr(description[0])
	}
	return d
}

// requireAppError asserts that err is an *apperr.Error of the expected kind and
// code, and that it carries a message a client could read.
func requireAppError(t *testing.T, err error, kind apperr.Kind, code string) {
	t.Helper()

	if err == nil {
		t.Fatalf("expected an error with code %q, got nil", code)
	}

	appError, ok := apperr.As(err)
	if !ok {
		t.Fatalf("expected *apperr.Error, got %T: %v", err, err)
	}
	if appError.Kind != kind {
		t.Errorf("kind = %q, want %q", appError.Kind, kind)
	}
	if appError.Code != code {
		t.Errorf("code = %q, want %q", appError.Code, code)
	}
	if appError.Message == "" {
		t.Error("message must not be empty")
	}
}

var errStore = errors.New("data store is unreachable")

// brokenRepository satisfies the interface but fails on every call. It is how
// the tests show that an infrastructure failure reaches the HTTP layer
// untranslated, and is reported as 500 rather than as a 4xx.
type brokenRepository struct{}

var _ repository.ItemRepository = brokenRepository{}

func (brokenRepository) Create(model.Item) (model.Item, error)       { return model.Item{}, errStore }
func (brokenRepository) FindAll() ([]model.Item, error)              { return nil, errStore }
func (brokenRepository) FindByID(int) (model.Item, error)            { return model.Item{}, errStore }
func (brokenRepository) FindByName(string) (model.Item, bool, error) { return model.Item{}, false, nil }
func (brokenRepository) Update(model.Item) (model.Item, error)       { return model.Item{}, errStore }
func (brokenRepository) Delete(int) error                            { return errStore }
