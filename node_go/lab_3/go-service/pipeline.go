package main

import (
	"context"
	"sync"
	"time"
)

// workerIterations controls the simulated per-job CPU cost, so results scale
// visibly with worker count instead of being dominated by channel overhead.
const workerIterations = 5000

type Job struct {
	ID    int
	Value int
}

type Result struct {
	JobID int
	Value int
}

type Stats struct {
	Tasks     int
	Workers   int
	Buffer    int
	Completed int
	Sum       int64
	Elapsed   time.Duration
}

// burn is deliberately not optimized away: its result feeds into process's
// return value, so the Go compiler cannot drop the loop as dead code.
func burn(iterations int) int {
	sum := 0
	for i := 0; i < iterations; i++ {
		sum += i % 7
	}
	return sum
}

func process(value int) int {
	return value*value + burn(workerIterations)
}

// expectedSum is the deterministic total a correct, uncancelled run must
// produce for a given task count; used to sanity-check aggregator output.
func expectedSum(tasks int) int64 {
	n := int64(tasks)
	sumOfSquares := n * (n + 1) * (2*n + 1) / 6
	return sumOfSquares + n*int64(burn(workerIterations))
}

func producer(ctx context.Context, jobs chan<- Job, tasks int) {
	defer close(jobs)
	for i := 1; i <= tasks; i++ {
		select {
		case jobs <- Job{ID: i, Value: i}:
		case <-ctx.Done():
			return
		}
	}
}

func worker(ctx context.Context, jobs <-chan Job, results chan<- Result) {
	for {
		select {
		case job, ok := <-jobs:
			if !ok {
				return
			}
			result := Result{JobID: job.ID, Value: process(job.Value)}
			select {
			case results <- result:
			case <-ctx.Done():
				return
			}
		case <-ctx.Done():
			return
		}
	}
}

func runPipeline(ctx context.Context, tasks, workers, buffer int) Stats {
	jobs := make(chan Job, buffer)
	results := make(chan Result, buffer)

	start := time.Now()
	go producer(ctx, jobs, tasks)

	var wg sync.WaitGroup
	wg.Add(workers)
	for i := 0; i < workers; i++ {
		go func() {
			defer wg.Done()
			worker(ctx, jobs, results)
		}()
	}

	// results can only be closed once every worker is done sending to it.
	go func() {
		wg.Wait()
		close(results)
	}()

	// Aggregation happens on this single goroutine, so no mutex is needed.
	var completed int
	var sum int64
	for r := range results {
		completed++
		sum += int64(r.Value)
	}

	return Stats{
		Tasks:     tasks,
		Workers:   workers,
		Buffer:    buffer,
		Completed: completed,
		Sum:       sum,
		Elapsed:   time.Since(start),
	}
}
