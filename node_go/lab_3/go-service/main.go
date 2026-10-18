package main

import (
	"context"
	"flag"
	"fmt"
	"runtime"
	"strconv"
)

type matrixRow struct {
	Tasks, Workers, Buffer int
}

func main() {
	tasks := flag.Int("tasks", 0, "number of jobs to generate (0 = run the preset benchmark matrix)")
	workers := flag.Int("workers", 4, "number of worker goroutines")
	buffer := flag.Int("buffer", 0, "jobs/results channel buffer size (0 = unbuffered)")
	cancelAfter := flag.Duration("cancel-after", 0, "cancel the run after this duration (0 = disabled); exercises the ctx.Done() path")
	flag.Parse()

	if *tasks <= 0 {
		runMatrix()
		return
	}

	ctx := context.Background()
	if *cancelAfter > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, *cancelAfter)
		defer cancel()
	}

	stats := runPipeline(ctx, *tasks, *workers, *buffer)
	printTable("Custom run", []string{"Tasks", "Workers", "Buffer", "Completed", "Time, ms", "Jobs/s", "Sum", "Check"}, [][]string{statRow(stats, true)})
}

func runMatrix() {
	fmt.Printf("lab3-go concurrent pipeline benchmark — numCPU=%d\n\n", runtime.NumCPU())

	printSection("1. Fixed tasks=10000, buffer=0 — scaling by worker count", []matrixRow{
		{10000, 1, 0}, {10000, 2, 0}, {10000, 4, 0}, {10000, 8, 0}, {10000, 16, 0},
	})

	printSection("2. Fixed tasks=10000, workers=8 — scaling by channel buffer", []matrixRow{
		{10000, 8, 0}, {10000, 8, 10}, {10000, 8, 100}, {10000, 8, 1000},
	})

	printSection("3. Fixed workers=8, buffer=100 — scaling by task count", []matrixRow{
		{100, 8, 100}, {1000, 8, 100}, {10000, 8, 100}, {100000, 8, 100},
	})
}

func printSection(title string, configs []matrixRow) {
	headers := []string{"Tasks", "Workers", "Buffer", "Time, ms", "Jobs/s", "Sum", "Check"}
	rows := make([][]string, 0, len(configs))
	for _, c := range configs {
		stats := runPipeline(context.Background(), c.Tasks, c.Workers, c.Buffer)
		rows = append(rows, statRow(stats, false))
	}
	printTable(title, headers, rows)
}

func statRow(s Stats, withCompleted bool) []string {
	// Nanoseconds() can read as 0 for trivially small workloads; report that
	// as "too fast to measure" instead of a misleading 0.0ms / 0 jobs/s.
	elapsedMsStr, throughputStr := "<0.1", "n/a"
	if ns := s.Elapsed.Nanoseconds(); ns > 0 {
		seconds := float64(ns) / 1e9
		elapsedMsStr = fmt.Sprintf("%.1f", seconds*1000)
		throughputStr = fmt.Sprintf("%.0f", float64(s.Completed)/seconds)
	}

	check := "ok"
	switch {
	case s.Completed < s.Tasks:
		check = fmt.Sprintf("partial %d/%d", s.Completed, s.Tasks)
	case s.Sum != expectedSum(s.Tasks):
		check = "MISMATCH"
	}

	row := []string{strconv.Itoa(s.Tasks), strconv.Itoa(s.Workers), strconv.Itoa(s.Buffer)}
	if withCompleted {
		row = append(row, strconv.Itoa(s.Completed))
	}
	row = append(row,
		elapsedMsStr,
		throughputStr,
		strconv.FormatInt(s.Sum, 10),
		check,
	)
	return row
}
