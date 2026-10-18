// Package model holds the Item shape and the rules for its fields, so Service,
// repositories and tests all agree on a single definition.
package model

import (
	"fmt"
	"strings"
)

const (
	MaxNameLength        = 100
	MaxDescriptionLength = 500
)

// Item is the stored entity. The struct tags are the only place the wire format
// is described.
type Item struct {
	ID          int    `json:"id"`
	Name        string `json:"name"`
	Description string `json:"description"`
}

// Draft is an incoming item, before it has an id. The pointers distinguish
// "field absent" from "field present but empty", which is what lets validation
// report a missing name separately from an empty one.
type Draft struct {
	Name        *string `json:"name"`
	Description *string `json:"description"`
}

// Validate returns one message per broken rule. Turning them into an error with
// a kind is the Service's job, and picking a status code is the HTTP layer's, so
// the model carries no error-handling policy.
func (d Draft) Validate() []string {
	problems := make([]string, 0, 2)

	switch {
	case d.Name == nil:
		problems = append(problems, "name is required and must be a string")
	case strings.TrimSpace(*d.Name) == "":
		problems = append(problems, "name must not be empty")
	case len(strings.TrimSpace(*d.Name)) > MaxNameLength:
		problems = append(problems, fmt.Sprintf("name must be at most %d characters", MaxNameLength))
	}

	if d.Description != nil && len(*d.Description) > MaxDescriptionLength {
		problems = append(problems, fmt.Sprintf("description must be at most %d characters", MaxDescriptionLength))
	}

	return problems
}

// Normalize trims the fields and fills in the optional one. Only valid drafts
// may be normalized.
func (d Draft) Normalize() Item {
	item := Item{Name: strings.TrimSpace(*d.Name)}
	if d.Description != nil {
		item.Description = strings.TrimSpace(*d.Description)
	}
	return item
}
