package repository

import (
	"strings"
	"sync"

	"lab4-go/internal/model"
)

// InMemoryItemRepository keeps items in a slice guarded by a mutex. Everything
// is lost when the process exits.
type InMemoryItemRepository struct {
	mu     sync.RWMutex
	items  []model.Item
	nextID int
}

// Compile-time proof that this type satisfies the interface.
var _ ItemRepository = (*InMemoryItemRepository)(nil)

func NewInMemoryItemRepository() *InMemoryItemRepository {
	return &InMemoryItemRepository{nextID: 1}
}

func (r *InMemoryItemRepository) Create(item model.Item) (model.Item, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	item.ID = r.nextID
	r.nextID++
	r.items = append(r.items, item)

	return item, nil
}

func (r *InMemoryItemRepository) FindAll() ([]model.Item, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	// A copy, so a caller cannot mutate stored state through the slice.
	items := make([]model.Item, len(r.items))
	copy(items, r.items)

	return items, nil
}

func (r *InMemoryItemRepository) FindByID(id int) (model.Item, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	for _, item := range r.items {
		if item.ID == id {
			return item, nil
		}
	}

	return model.Item{}, notFound(id)
}

func (r *InMemoryItemRepository) FindByName(name string) (model.Item, bool, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	needle := strings.ToLower(name)
	for _, item := range r.items {
		if strings.ToLower(item.Name) == needle {
			return item, true, nil
		}
	}

	return model.Item{}, false, nil
}

func (r *InMemoryItemRepository) Update(item model.Item) (model.Item, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	for i := range r.items {
		if r.items[i].ID == item.ID {
			r.items[i] = item
			return item, nil
		}
	}

	return model.Item{}, notFound(item.ID)
}

func (r *InMemoryItemRepository) Delete(id int) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	for i := range r.items {
		if r.items[i].ID == id {
			r.items = append(r.items[:i], r.items[i+1:]...)
			return nil
		}
	}

	return notFound(id)
}
