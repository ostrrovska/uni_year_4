// Both implementations are run through the same table. Passing it is what makes
// the memory -> file swap safe: the Service cannot tell them apart, because by
// this contract they behave identically.
package tests

import (
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"testing"

	"lab4-go/internal/model"
	"lab4-go/internal/repository"
	"lab4-go/internal/service"
)

// Each case gets its own file, so one case cannot see another one's rows.
func newFileRepository(t *testing.T) *repository.FileItemRepository {
	t.Helper()
	return repository.NewFileItemRepository(filepath.Join(t.TempDir(), "items.json"))
}

func implementations() []struct {
	name string
	make func(t *testing.T) repository.ItemRepository
} {
	return []struct {
		name string
		make func(t *testing.T) repository.ItemRepository
	}{
		{"InMemoryItemRepository", func(t *testing.T) repository.ItemRepository {
			return repository.NewInMemoryItemRepository()
		}},
		{"FileItemRepository", func(t *testing.T) repository.ItemRepository {
			return newFileRepository(t)
		}},
	}
}

func TestRepositoryContract(t *testing.T) {
	for _, implementation := range implementations() {
		t.Run(implementation.name, func(t *testing.T) {
			t.Run("starts empty", func(t *testing.T) {
				items, err := implementation.make(t).FindAll()
				if err != nil {
					t.Fatalf("FindAll: %v", err)
				}
				if len(items) != 0 {
					t.Errorf("len(items) = %d, want 0", len(items))
				}
			})

			t.Run("assigns consecutive ids on create", func(t *testing.T) {
				repo := implementation.make(t)

				first, err := repo.Create(model.Item{Name: "First"})
				if err != nil {
					t.Fatalf("Create: %v", err)
				}
				second, err := repo.Create(model.Item{Name: "Second"})
				if err != nil {
					t.Fatalf("Create: %v", err)
				}

				if first.ID != 1 || second.ID != 2 {
					t.Errorf("ids = %d, %d, want 1, 2", first.ID, second.ID)
				}
			})

			t.Run("finds a stored row by id", func(t *testing.T) {
				repo := implementation.make(t)
				created, err := repo.Create(model.Item{Name: "Keyboard", Description: "Mechanical"})
				if err != nil {
					t.Fatalf("Create: %v", err)
				}

				found, err := repo.FindByID(created.ID)
				if err != nil {
					t.Fatalf("FindByID: %v", err)
				}
				if found != created {
					t.Errorf("found = %+v, want %+v", found, created)
				}
			})

			t.Run("signals a missing row with ErrNotFound", func(t *testing.T) {
				repo := implementation.make(t)

				if _, err := repo.FindByID(404); !errors.Is(err, repository.ErrNotFound) {
					t.Errorf("FindByID err = %v, want ErrNotFound", err)
				}
				if _, err := repo.Update(model.Item{ID: 404, Name: "Ghost"}); !errors.Is(err, repository.ErrNotFound) {
					t.Errorf("Update err = %v, want ErrNotFound", err)
				}
				if err := repo.Delete(404); !errors.Is(err, repository.ErrNotFound) {
					t.Errorf("Delete err = %v, want ErrNotFound", err)
				}
			})

			t.Run("matches FindByName case-insensitively", func(t *testing.T) {
				repo := implementation.make(t)
				if _, err := repo.Create(model.Item{Name: "Keyboard"}); err != nil {
					t.Fatalf("Create: %v", err)
				}

				found, ok, err := repo.FindByName("KEYBOARD")
				if err != nil {
					t.Fatalf("FindByName: %v", err)
				}
				if !ok || found.Name != "Keyboard" {
					t.Errorf("FindByName = %+v, %v, want the stored row", found, ok)
				}

				if _, ok, err := repo.FindByName("Mouse"); err != nil || ok {
					t.Errorf("FindByName for an absent name = %v, %v, want false, nil", ok, err)
				}
			})

			t.Run("updates a row in place", func(t *testing.T) {
				repo := implementation.make(t)
				created, err := repo.Create(model.Item{Name: "Keyboard", Description: "old"})
				if err != nil {
					t.Fatalf("Create: %v", err)
				}

				want := model.Item{ID: created.ID, Name: "Keypad", Description: "new"}
				updated, err := repo.Update(want)
				if err != nil {
					t.Fatalf("Update: %v", err)
				}
				if updated != want {
					t.Errorf("updated = %+v, want %+v", updated, want)
				}

				stored, err := repo.FindByID(created.ID)
				if err != nil {
					t.Fatalf("FindByID: %v", err)
				}
				if stored != want {
					t.Errorf("stored = %+v, want %+v", stored, want)
				}
			})

			t.Run("removes a row", func(t *testing.T) {
				repo := implementation.make(t)
				created, err := repo.Create(model.Item{Name: "Keyboard"})
				if err != nil {
					t.Fatalf("Create: %v", err)
				}

				if err := repo.Delete(created.ID); err != nil {
					t.Fatalf("Delete: %v", err)
				}

				items, err := repo.FindAll()
				if err != nil {
					t.Fatalf("FindAll: %v", err)
				}
				if len(items) != 0 {
					t.Errorf("len(items) = %d, want 0", len(items))
				}
			})

			t.Run("serves the same ItemService without a single change to it", func(t *testing.T) {
				svc := service.NewItemService(implementation.make(t))

				item, err := svc.Create(draft("Keyboard", "Mechanical"))
				if err != nil {
					t.Fatalf("Create: %v", err)
				}

				found, err := svc.Get(item.ID)
				if err != nil {
					t.Fatalf("Get: %v", err)
				}
				if found != item {
					t.Errorf("found = %+v, want %+v", found, item)
				}

				if _, err := svc.Create(draft("keyboard")); err == nil {
					t.Error("the uniqueness rule must hold whichever repository is wired in")
				}
			})
		})
	}
}

func TestRepositoryFileSpecifics(t *testing.T) {
	t.Run("survives being reopened, which the in-memory one cannot", func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "items.json")

		if _, err := repository.NewFileItemRepository(path).Create(model.Item{Name: "Persisted"}); err != nil {
			t.Fatalf("Create: %v", err)
		}

		reopened, err := repository.NewFileItemRepository(path).FindAll()
		if err != nil {
			t.Fatalf("FindAll after reopening: %v", err)
		}

		want := model.Item{ID: 1, Name: "Persisted"}
		if len(reopened) != 1 || reopened[0] != want {
			t.Errorf("reopened = %+v, want exactly %+v", reopened, want)
		}
	})

	t.Run("serializes concurrent writes instead of losing them", func(t *testing.T) {
		repo := newFileRepository(t)

		var group sync.WaitGroup
		for i := range 10 {
			group.Add(1)
			go func(index int) {
				defer group.Done()
				if _, err := repo.Create(model.Item{Name: "Item " + strconv.Itoa(index)}); err != nil {
					t.Errorf("Create: %v", err)
				}
			}(i)
		}
		group.Wait()

		items, err := repo.FindAll()
		if err != nil {
			t.Fatalf("FindAll: %v", err)
		}
		if len(items) != 10 {
			t.Errorf("len(items) = %d, want 10 - a write was lost", len(items))
		}
	})

	t.Run("reports a corrupt store as an ordinary failure, not as a missing row", func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "items.json")
		if err := os.WriteFile(path, []byte("{ not json"), 0o644); err != nil {
			t.Fatalf("writing the corrupt file: %v", err)
		}

		_, err := repository.NewFileItemRepository(path).FindAll()

		if err == nil {
			t.Fatal("a corrupt store must fail")
		}
		if errors.Is(err, repository.ErrNotFound) {
			t.Error("a corrupt store must not look like a missing row, or it would be reported as 404")
		}
	})

	t.Run("treats a missing file as an empty store", func(t *testing.T) {
		repo := repository.NewFileItemRepository(filepath.Join(t.TempDir(), "nothing-here.json"))

		items, err := repo.FindAll()
		if err != nil {
			t.Fatalf("FindAll: %v", err)
		}
		if len(items) != 0 {
			t.Errorf("len(items) = %d, want 0", len(items))
		}
	})
}
