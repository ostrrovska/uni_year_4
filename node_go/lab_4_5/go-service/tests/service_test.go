// Service-layer tests. No HTTP server, no router, no port: the Service is
// constructed directly with a repository, which is the whole point of keeping
// it free of transport concerns.
package tests

import (
	"errors"
	"strings"
	"testing"

	"lab4-go/internal/apperr"
	"lab4-go/internal/model"
	"lab4-go/internal/repository"
	"lab4-go/internal/service"
)

func TestItemServiceCreate(t *testing.T) {
	t.Run("assigns an id and returns the stored item", func(t *testing.T) {
		svc := newService()

		item, err := svc.Create(draft("Keyboard", "Mechanical"))
		if err != nil {
			t.Fatalf("Create: %v", err)
		}

		want := model.Item{ID: 1, Name: "Keyboard", Description: "Mechanical"}
		if item != want {
			t.Errorf("item = %+v, want %+v", item, want)
		}
	})

	t.Run("trims the fields and defaults a missing description", func(t *testing.T) {
		svc := newService()

		item, err := svc.Create(draft("  Mouse  "))
		if err != nil {
			t.Fatalf("Create: %v", err)
		}

		if item.Name != "Mouse" {
			t.Errorf("name = %q, want %q", item.Name, "Mouse")
		}
		if item.Description != "" {
			t.Errorf("description = %q, want empty", item.Description)
		}
	})

	t.Run("numbers items consecutively", func(t *testing.T) {
		svc := newService()

		if _, err := svc.Create(draft("First")); err != nil {
			t.Fatalf("Create: %v", err)
		}
		second, err := svc.Create(draft("Second"))
		if err != nil {
			t.Fatalf("Create: %v", err)
		}

		if second.ID != 2 {
			t.Errorf("id = %d, want 2", second.ID)
		}
	})
}

func TestItemServiceValidation(t *testing.T) {
	cases := []struct {
		name  string
		draft model.Draft
	}{
		{"missing name", model.Draft{}},
		{"empty name", draft("")},
		{"whitespace-only name", draft("   ")},
		{"name too long", draft(strings.Repeat("x", model.MaxNameLength+1))},
		{"description too long", draft("Ok", strings.Repeat("x", model.MaxDescriptionLength+1))},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, err := newService().Create(testCase.draft)

			requireAppError(t, err, apperr.KindValidation, "invalid_item")
		})
	}
}

func TestItemServiceInvalidIdentifier(t *testing.T) {
	for _, id := range []int{0, -1, -100} {
		svc := newService()

		_, err := svc.Get(id)
		requireAppError(t, err, apperr.KindValidation, "invalid_id")

		_, err = svc.Update(id, draft("Name"))
		requireAppError(t, err, apperr.KindValidation, "invalid_id")

		requireAppError(t, svc.Delete(id), apperr.KindValidation, "invalid_id")
	}
}

func TestItemServiceUniqueName(t *testing.T) {
	t.Run("rejects a duplicate name regardless of case", func(t *testing.T) {
		svc := newService()
		if _, err := svc.Create(draft("Keyboard")); err != nil {
			t.Fatalf("Create: %v", err)
		}

		_, err := svc.Create(draft("KEYBOARD"))

		requireAppError(t, err, apperr.KindConflict, "item_name_taken")
	})

	t.Run("rejects renaming an item onto another item name", func(t *testing.T) {
		svc := newService()
		if _, err := svc.Create(draft("Keyboard")); err != nil {
			t.Fatalf("Create: %v", err)
		}
		mouse, err := svc.Create(draft("Mouse"))
		if err != nil {
			t.Fatalf("Create: %v", err)
		}

		_, err = svc.Update(mouse.ID, draft("keyboard"))

		requireAppError(t, err, apperr.KindConflict, "item_name_taken")
	})

	t.Run("allows an item to keep its own name while editing the description", func(t *testing.T) {
		svc := newService()
		item, err := svc.Create(draft("Keyboard", "old"))
		if err != nil {
			t.Fatalf("Create: %v", err)
		}

		updated, err := svc.Update(item.ID, draft("Keyboard", "new"))
		if err != nil {
			t.Fatalf("Update: %v", err)
		}

		if updated.Description != "new" {
			t.Errorf("description = %q, want %q", updated.Description, "new")
		}
	})

	t.Run("frees the name of a deleted item", func(t *testing.T) {
		svc := newService()
		item, err := svc.Create(draft("Keyboard"))
		if err != nil {
			t.Fatalf("Create: %v", err)
		}
		if err := svc.Delete(item.ID); err != nil {
			t.Fatalf("Delete: %v", err)
		}

		if _, err := svc.Create(draft("Keyboard")); err != nil {
			t.Errorf("recreating a deleted name: %v", err)
		}
	})
}

func TestItemServiceRead(t *testing.T) {
	t.Run("returns an empty list for an empty store", func(t *testing.T) {
		items, err := newService().List()
		if err != nil {
			t.Fatalf("List: %v", err)
		}

		if len(items) != 0 {
			t.Errorf("len(items) = %d, want 0", len(items))
		}
	})

	t.Run("lists every stored item", func(t *testing.T) {
		svc := newService()
		for _, name := range []string{"First", "Second"} {
			if _, err := svc.Create(draft(name)); err != nil {
				t.Fatalf("Create %s: %v", name, err)
			}
		}

		items, err := svc.List()
		if err != nil {
			t.Fatalf("List: %v", err)
		}

		if len(items) != 2 || items[0].Name != "First" || items[1].Name != "Second" {
			t.Errorf("items = %+v, want First then Second", items)
		}
	})

	t.Run("finds an item by id", func(t *testing.T) {
		svc := newService()
		created, err := svc.Create(draft("Keyboard"))
		if err != nil {
			t.Fatalf("Create: %v", err)
		}

		found, err := svc.Get(created.ID)
		if err != nil {
			t.Fatalf("Get: %v", err)
		}

		if found != created {
			t.Errorf("found = %+v, want %+v", found, created)
		}
	})

	t.Run("reports a missing item as not found", func(t *testing.T) {
		_, err := newService().Get(404)

		requireAppError(t, err, apperr.KindNotFound, "item_not_found")
	})
}

func TestItemServiceUpdate(t *testing.T) {
	t.Run("updates both fields", func(t *testing.T) {
		svc := newService()
		created, err := svc.Create(draft("Keyboard", "old"))
		if err != nil {
			t.Fatalf("Create: %v", err)
		}

		updated, err := svc.Update(created.ID, draft("Keypad", "new"))
		if err != nil {
			t.Fatalf("Update: %v", err)
		}

		want := model.Item{ID: created.ID, Name: "Keypad", Description: "new"}
		if updated != want {
			t.Errorf("updated = %+v, want %+v", updated, want)
		}

		stored, err := svc.Get(created.ID)
		if err != nil {
			t.Fatalf("Get after update: %v", err)
		}
		if stored != want {
			t.Errorf("stored = %+v, want %+v", stored, want)
		}
	})

	t.Run("reports updating a missing item as not found", func(t *testing.T) {
		_, err := newService().Update(404, draft("Ghost"))

		requireAppError(t, err, apperr.KindNotFound, "item_not_found")
	})
}

func TestItemServiceDelete(t *testing.T) {
	t.Run("deletes an item, after which it can no longer be found", func(t *testing.T) {
		svc := newService()
		created, err := svc.Create(draft("Keyboard"))
		if err != nil {
			t.Fatalf("Create: %v", err)
		}

		if err := svc.Delete(created.ID); err != nil {
			t.Fatalf("Delete: %v", err)
		}

		_, err = svc.Get(created.ID)
		requireAppError(t, err, apperr.KindNotFound, "item_not_found")
	})

	t.Run("reports deleting a missing item as not found", func(t *testing.T) {
		requireAppError(t, newService().Delete(404), apperr.KindNotFound, "item_not_found")
	})
}

func TestItemServiceDependencyInversion(t *testing.T) {
	t.Run("accepts any implementation of the interface", func(t *testing.T) {
		// Neither of the two shipped implementations: the Service accepts it
		// because it depends on the interface, not on a concrete type.
		svc := service.NewItemService(stubRepository{})

		item, err := svc.Create(draft("Stubbed"))
		if err != nil {
			t.Fatalf("Create: %v", err)
		}

		if item.ID != 7 {
			t.Errorf("id = %d, want 7 (the stub assigns it)", item.ID)
		}
	})

	t.Run("passes an infrastructure failure through untranslated", func(t *testing.T) {
		_, err := service.NewItemService(brokenRepository{}).List()

		if !errors.Is(err, errStore) {
			t.Fatalf("err = %v, want the store failure", err)
		}
		if _, isAppError := apperr.As(err); isAppError {
			t.Error("an infrastructure failure must not become an apperr, or it would be reported as 4xx")
		}
	})

	t.Run("translates only the repository not-found sentinel", func(t *testing.T) {
		svc := newService()

		_, err := svc.Get(404)

		if errors.Is(err, repository.ErrNotFound) {
			t.Error("storage vocabulary must not leak above the Service")
		}
		requireAppError(t, err, apperr.KindNotFound, "item_not_found")
	})
}

// stubRepository is a hand-written implementation used to show the Service is
// bound to the interface and nothing else.
type stubRepository struct{}

var _ repository.ItemRepository = stubRepository{}

func (stubRepository) Create(item model.Item) (model.Item, error) {
	item.ID = 7
	return item, nil
}

func (stubRepository) FindAll() ([]model.Item, error)              { return nil, nil }
func (stubRepository) FindByID(int) (model.Item, error)            { return model.Item{}, nil }
func (stubRepository) FindByName(string) (model.Item, bool, error) { return model.Item{}, false, nil }
func (stubRepository) Update(item model.Item) (model.Item, error)  { return item, nil }
func (stubRepository) Delete(int) error                            { return nil }
