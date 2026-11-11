package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"

	"lab4-go/internal/controller"
	"lab4-go/internal/repository"
	"lab4-go/internal/router"
	"lab4-go/internal/service"
)

func main() {
	port := envOr("PORT", "8180")
	repositoryName := envOr("ITEM_REPO", "memory")
	dataFile := envOr("ITEM_DATA_FILE", filepath.Join("data", "items.json"))

	itemRepository, err := newRepository(repositoryName, dataFile)
	if err != nil {
		log.Fatal(err)
	}

	// Composition root: the only place that knows which repository
	// implementation is in use. Service, Controller and Router code is
	// identical in both modes.
	handler := router.New(
		controller.NewItemController(service.NewItemService(itemRepository)),
		controller.NewHealthController(repositoryName),
	)

	fmt.Printf("Go service running on http://localhost:%s (repository: %s)\n", port, repositoryName)
	if repositoryName == "file" {
		fmt.Printf("Data store: %s\n", dataFile)
	}

	if err := http.ListenAndServe(":"+port, handler); err != nil {
		log.Fatal(err)
	}
}

// The return type is the interface, not a concrete struct: this signature is
// the dependency inversion the lab asks for.
func newRepository(kind, dataFile string) (repository.ItemRepository, error) {
	switch kind {
	case "memory":
		return repository.NewInMemoryItemRepository(), nil
	case "file":
		return repository.NewFileItemRepository(dataFile), nil
	default:
		return nil, fmt.Errorf("unknown ITEM_REPO %q, expected memory or file", kind)
	}
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
