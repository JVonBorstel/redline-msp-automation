# Load benchmark (B-84)

> **MEASURED ON THIS MACHINE ONLY, ONCE. Synthetic harness on temporary SQLite files; fixture-based; not a capacity claim for any real deployment.**
>
> Basis: fixture-based: synthetic clients and lever calls, a seeded fault plan, a local SQLite file standing in for the external adapter, stores in synchronous=FULL mode (one fsync per commit).

Generated 2026-10-28T00:03:43+00:00 by `tools/bench_load.py`. Machine: platform Windows-11-10.0.26300-SP0, python 3.12.15, sqlite 3.53.1, cpu_count 16.

Config: seed 84, clients 300, jobs 10000, threads 4, workers 8.

## Results

| Scenario | Mode | Faults | Calls | Done | Dead-lettered | Wall (s) | Calls per second | Chain breaks | Cross-client | Double applies | Lost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| clean-sequential | sequential | no | 10000 | 10000 | 0 | 280.528 | 35.65 | 0 | 0 | 0 | 0 |
| faulty-sequential | sequential | yes | 10000 | 9797 | 203 | 342.695 | 29.18 | 0 | 0 | 0 | 0 |
| faulty-threaded | threaded | yes | 10000 | 9797 | 203 | 265.096 | 37.72 | 0 | 0 | 0 | 0 |

Calls per second is jobs created divided by total wall time of the scenario, which includes submitting, working, and verifying every audit chain.

## Latency per store call: clean-sequential

| Call | Count | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | Mean (ms) |
|---|---|---|---|---|---|---|
| enqueue | 10000 | 5.514 | 6.471 | 7.649 | 170.406 | 5.62 |
| claim | 10000 | 4.408 | 5.213 | 11.52 | 28.482 | 4.635 |
| adapter | 10000 | 2.908 | 3.36 | 3.696 | 26.166 | 2.958 |
| audit | 10000 | 5.335 | 6.468 | 12.6 | 25.902 | 5.584 |
| complete | 10000 | 5.163 | 6.087 | 12.308 | 27.762 | 5.392 |
| fail | 0 | n/a | n/a | n/a | n/a | n/a |

## Latency per store call: faulty-sequential

| Call | Count | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | Mean (ms) |
|---|---|---|---|---|---|---|
| enqueue | 10000 | 5.391 | 6.765 | 13.044 | 44.311 | 5.69 |
| claim | 14998 | 4.366 | 5.25 | 11.913 | 33.376 | 4.332 |
| adapter | 13197 | 2.832 | 3.327 | 3.693 | 17.319 | 2.304 |
| audit | 12535 | 5.333 | 6.61 | 13.036 | 29.286 | 5.612 |
| complete | 9797 | 5.164 | 6.29 | 13.294 | 33.192 | 5.459 |
| fail | 2535 | 5.128 | 5.971 | 12.136 | 16.361 | 5.327 |

## Latency per store call: faulty-threaded

| Call | Count | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | Mean (ms) |
|---|---|---|---|---|---|---|
| enqueue | 10000 | 5.481 | 7.343 | 12.066 | 173.176 | 5.801 |
| claim | 13316 | 9.387 | 53.384 | 115.242 | 542.934 | 18.19 |
| adapter | 13223 | 3.051 | 5.023 | 15.441 | 909.831 | 4.743 |
| audit | 12558 | 5.885 | 16.024 | 33.371 | 1702.921 | 10.806 |
| complete | 9818 | 10.21 | 54.176 | 122.99 | 440.138 | 18.714 |
| fail | 2537 | 9.917 | 53.606 | 128.31 | 448.546 | 18.535 |

## Read this before quoting a number

- One run per scenario, no repeats, no variance estimate: treat differences under about 2x as noise.
- Latency is wall time around each store call (time.perf_counter), including the fsync. It depends on this machine's disk and the temp folder's filesystem; a CI runner or a server will differ, possibly a lot.
- The adapter is a local SQLite file with synchronous=OFF, so its latency says nothing about a real adapter (Graph, PSA, RMM) which would add network time and rate limits.
- Backoff and lease waits run on a simulated clock and cost no wall time, so end-to-end jobs per second is the cost of the work, not what a deployment waiting out real backoff would see.
- SQLite allows one writer at a time. The threaded scenario shows lock contention on one file; it is not a claim that more threads give more throughput.
- The real LeverRunner (identity, approval and registry checks) is not in this loop.
- Not measured: memory, CPU use, database size, multi-process contention on this scale, Linux behaviour.
