# Learning loop — results

Run `20261111-181207-loop` · model `gpt-6.1-sol` · Hermes Agent v0.23.1+1921.g4ed1425 (2026.9.24) · stable · local 4ed14253ea7b

Six tasks in six brand-new sessions: fetch a record with an awkward CLI whose rules are only revealed by trial and error. Fewer model calls on later tasks means the procedure was remembered.

| Arm | Setup |
|---|---|
| **none** | no memory (stateless) |
| **base** | Hermes built-in memory |
| **raw** | dreaming plugin, no dream |
| **dream** | dreaming plugin + dream after each task |

## Model calls per task (✗ = wrong value)

| Task | record | none | base | raw | dream |
|---|---|---|---|---|---|
| 1 | 4127 | 9 | 9 | 7 | 7 |
| 2 | 5302 | 7 | 7 | 6 | 3 |
| 3 | 6815 | 7 | 7 | 7 | 3 |
| 4 | 7240 | 7 | 7 | 6 | 3 |
| 5 | 8356 | 8 | 8 | 7 | 3 |
| 6 | 9469 | 7 | 8 | 7 | 3 |

## Summary

| | none | base | raw | dream |
|---|---|---|---|---|
| Correct | 6/6 | 6/6 | 6/6 | 6/6 |
| Model calls, task 1 | 9 | 9 | 7 | 7 |
| Model calls, mean of tasks 2–6 | 7.2 | 7.4 | 6.6 | 3.0 |
| Input tokens, mean of tasks 2–6 | 22,127 | 28,056 | 30,528 | 14,446 |
| Seconds, mean of tasks 2–6 | 27.1 | 28.5 | 23.4 | 12.8 |

Dream passes in the `dream` arm: 5, 10 model calls, 93s in total (run between tasks, not counted in the per-task numbers).
