package main

import (
	"fmt"
	"strings"
)

func printTable(title string, headers []string, rows [][]string) {
	widths := make([]int, len(headers))
	for i, h := range headers {
		widths[i] = len([]rune(h))
	}
	for _, row := range rows {
		for i, cell := range row {
			if l := len([]rune(cell)); l > widths[i] {
				widths[i] = l
			}
		}
	}

	fmt.Println(title)
	fmt.Println(rule(widths, "┌", "┬", "┐"))
	fmt.Println(formatRow(headers, widths))
	fmt.Println(rule(widths, "├", "┼", "┤"))
	for _, row := range rows {
		fmt.Println(formatRow(row, widths))
	}
	fmt.Println(rule(widths, "└", "┴", "┘"))
	fmt.Println()
}

func rule(widths []int, left, mid, right string) string {
	parts := make([]string, len(widths))
	for i, w := range widths {
		parts[i] = strings.Repeat("─", w+2)
	}
	return left + strings.Join(parts, mid) + right
}

// formatRow right-aligns every cell; all columns in this report are numeric.
func formatRow(cells []string, widths []int) string {
	parts := make([]string, len(cells))
	for i, c := range cells {
		pad := widths[i] - len([]rune(c))
		parts[i] = " " + strings.Repeat(" ", pad) + c + " "
	}
	return "│" + strings.Join(parts, "│") + "│"
}
