// Package repository owns data access and hides the storage implementation.
package repository

import (
	"errors"
	"fmt"

	"lab4-go/internal/model"
)

// ErrNotFound is the storage-level "row is absent" signal. The Service
// translates it into an apperr, so no layer above the Service ever sees storage
// vocabulary.
var ErrNotFound = errors.New("repository: item not found")

func notFound(id int) error {
	return fmt.Errorf("%w: id %d", ErrNotFound, id)
}

// ItemRepository is the abstraction the Service depends on. Swapping one
// implementation for another requires no change anywhere above this interface -
// which is the whole point of declaring it.
type ItemRepository interface {
	Create(item model.Item) (model.Item, error)
	FindAll() ([]model.Item, error)
	FindByID(id int) (model.Item, error)
	FindByName(name string) (model.Item, bool, error)
	Update(item model.Item) (model.Item, error)
	Delete(id int) error
}
