package repository

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"lab4-go/internal/model"
)

// FileItemRepository keeps items in a JSON file. It satisfies exactly the same
// interface as the in-memory one, so wiring this one in instead changes nothing
// in the Service, the Controller or the Router.
type FileItemRepository struct {
	// Serializes read-modify-write cycles. Two concurrent writes would
	// otherwise both read the same snapshot and one would overwrite the other.
	mu   sync.Mutex
	path string
}

type fileState struct {
	Items  []model.Item `json:"items"`
	NextID int          `json:"nextId"`
}

var _ ItemRepository = (*FileItemRepository)(nil)

func NewFileItemRepository(path string) *FileItemRepository {
	return &FileItemRepository{path: path}
}

func (r *FileItemRepository) Create(item model.Item) (model.Item, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	state, err := r.load()
	if err != nil {
		return model.Item{}, err
	}

	item.ID = state.NextID
	state.NextID++
	state.Items = append(state.Items, item)

	if err := r.save(state); err != nil {
		return model.Item{}, err
	}

	return item, nil
}

func (r *FileItemRepository) FindAll() ([]model.Item, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	state, err := r.load()
	if err != nil {
		return nil, err
	}

	return state.Items, nil
}

func (r *FileItemRepository) FindByID(id int) (model.Item, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	state, err := r.load()
	if err != nil {
		return model.Item{}, err
	}

	for _, item := range state.Items {
		if item.ID == id {
			return item, nil
		}
	}

	return model.Item{}, notFound(id)
}

func (r *FileItemRepository) FindByName(name string) (model.Item, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	state, err := r.load()
	if err != nil {
		return model.Item{}, false, err
	}

	needle := strings.ToLower(name)
	for _, item := range state.Items {
		if strings.ToLower(item.Name) == needle {
			return item, true, nil
		}
	}

	return model.Item{}, false, nil
}

func (r *FileItemRepository) Update(item model.Item) (model.Item, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	state, err := r.load()
	if err != nil {
		return model.Item{}, err
	}

	for i := range state.Items {
		if state.Items[i].ID == item.ID {
			state.Items[i] = item
			if err := r.save(state); err != nil {
				return model.Item{}, err
			}
			return item, nil
		}
	}

	return model.Item{}, notFound(item.ID)
}

func (r *FileItemRepository) Delete(id int) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	state, err := r.load()
	if err != nil {
		return err
	}

	for i := range state.Items {
		if state.Items[i].ID == id {
			state.Items = append(state.Items[:i], state.Items[i+1:]...)
			return r.save(state)
		}
	}

	return notFound(id)
}

// A missing file is an empty store. A corrupt one is an infrastructure failure:
// it travels up untranslated, and the HTTP layer reports 500.
func (r *FileItemRepository) load() (fileState, error) {
	raw, err := os.ReadFile(r.path)
	if errors.Is(err, os.ErrNotExist) {
		return fileState{Items: []model.Item{}, NextID: 1}, nil
	}
	if err != nil {
		return fileState{}, err
	}

	if len(bytes.TrimSpace(raw)) == 0 {
		return fileState{Items: []model.Item{}, NextID: 1}, nil
	}

	var state fileState
	if err := json.Unmarshal(raw, &state); err != nil {
		return fileState{}, fmt.Errorf("corrupt data store at %s: %w", r.path, err)
	}
	if state.Items == nil {
		return fileState{}, fmt.Errorf("corrupt data store at %s: items array is missing", r.path)
	}
	if state.NextID < 1 {
		state.NextID = len(state.Items) + 1
	}

	return state, nil
}

// Write to a temporary file and rename, so a crash mid-write cannot leave a
// half-written store behind.
func (r *FileItemRepository) save(state fileState) error {
	if err := os.MkdirAll(filepath.Dir(r.path), 0o755); err != nil {
		return err
	}

	encoded, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}

	temp := r.path + ".tmp"
	if err := os.WriteFile(temp, append(encoded, '\n'), 0o644); err != nil {
		return err
	}

	return os.Rename(temp, r.path)
}
