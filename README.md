# 1. GPU interference monitoring on Raspberry Pi 5

Runs `./build/gpu_task` while a CPU/memory stressor (mostly `sysbench`) creates
interference, and records at the same time:

- the stressor's output (`sysbench.txt`)
- V3D hardware performance counters (`v3d_counters.txt`)
- DVFS / thermal / throttling data (`dvfs.txt` plus `rpi5-dvfs-logs/`)
- the `gpu_task` output (`gpu_task.txt`)

Each experiment writes into its own folder, `/data/<name>/`, for example `/data/4mr`
(4 MB block, read) or `/data/8mw` (8 MB block, write).

## 2. Install dependencies

set `DVFS_SCRIPT=/path/to/rpi5-dvfs-monitor.sh`.

```bash
sudo apt update
sudo apt install -y build-essential libdrm-dev sysbench libegl-dev libgles-dev
sudo apt install -y stress-ng        # optional: enables the ng_* page-fault experiments
```

- `vcgencmd` ships with Raspberry Pi OS (needed by the DVFS profiler).
- `libdrm-dev` provides `drm/v3d_drm.h`, which the V3D tools include.
- `libegl-dev` and `libgles-dev` are needed for your `gpu_task` link flags (`-lEGL -lGLESv2`).

## 3. Build

```bash
make                         # builds everything into build/
make build/v3d_perfmon_monitor   # or just the V3D counter sampler
make clean                   # rm -rf build/*
```

Targets:

| Binary | Source | Purpose |
|---|---|---|
| `build/gpu_task` | `src/gpu_task.c` | the GPU workload |
| `build/meminterf` | `src/meminterf.c` | your memory interference tool |
| `build/cpu_spinner` | `src/cpu_spinner.c` | your CPU spinner |
| `build/v3d_perfmon_monitor` | `src/v3d_perfmon_monitor.c` | samples V3D counters during a run |
| `build/v3d_counters` | `src/v3d_counters.c` | lists the counters the kernel exposes |

Check the counters your kernel exposes:

```bash
./build/v3d_counters | head -20
```

## 4. Make the scripts executable

```bash
chmod +x monitor_interference.sh scripts/*.sh
```

## 5. Look before you run

```bash
./monitor_interference.sh -l                          # table of all experiments
./monitor_interference.sh -l -c dram_stream           # only one category
./monitor_interference.sh -n -f '^(4mr|8mw)$'         # dry run: prints the commands, runs nothing
```

## 6. Run

Run from the project root, so `./build/gpu_task` resolves. Use `sudo` so it can write to
`/data` and drop the page cache between runs.

```bash
# a couple of experiments first
sudo ./monitor_interference.sh -f '^(baseline|4mr|8mw)$'

# one category
sudo ./monitor_interference.sh -c dram_random

# everything (88 experiments with default settings)
sudo ./monitor_interference.sh
```

For a long run, keep it alive after you disconnect:

```bash
nohup sudo ./monitor_interference.sh > run.log 2>&1 &
tail -f run.log
```

Finished experiments get a `DONE` marker and are skipped on re-run, so you can stop
and resume. Use `-F` to redo them.

### Options

| Option | Meaning |
|---|---|
| `-l` | list experiments and exit |
| `-n` | dry run |
| `-f REGEX` | only experiments whose folder name matches the regex |
| `-c CATS` | only these categories, comma separated |
| `-F` | re-run even if `DONE` exists |
| `-h` | help |

### What happens in each experiment

1. Run `run_stress.sh --check` (skips the experiment if it can't run, e.g. not enough RAM or `stress-ng` is missing).
2. Drop page cache (root only) and wait until the SoC is at or below `SETTLE_TEMP` (default 70 C, at most `SETTLE_MAX` = 60 s).
3. Start the DVFS profiler and the V3D counter sampler.
4. Start the stressor (not for `baseline`).
5. Wait `WARMUP` seconds (default 3).
6. Run `gpu_task` in the foreground.
7. Wait `COOLDOWN` seconds (default 3), then stop the stressor and both monitors.
8. Write `meta.txt` and the `DONE` marker.

## 7. Experiments

Folder name format: `<block><op>[_rnd][_t<threads>][_g]`

| Part | Meaning |
|---|---|
| `4m`, `32k`, `256m` | block size (`--memory-block-size`) |
| `r`, `w`, `n` | `--memory-oper` read / write / none |
| `_rnd` | random access (default is sequential) |
| `_t8` | 8 threads (default = number of CPU cores) |
| `_g` | `--memory-scope=global`: all threads share one buffer (default is `local`, one buffer per thread) |

| Category | Folders (examples) | What it stresses |
|---|---|---|
| `baseline` | `baseline` | `gpu_task` alone, monitors still running |
| `cache_resident` | `16kr`, `256kw_rnd`, `1mr` | working set fits in L1/L2/L3, almost no DRAM traffic |
| `cache_evict` | `2mr`, `4mw_rnd` | spills the shared 2 MB L3, evicts lines |
| `dram_stream` | `8mr`, `64mw`, `256mr` | sustained sequential DRAM bandwidth |
| `dram_random` | `8mr_rnd`, `64mw_rnd` | random DRAM access (prefetcher-hostile) |
| `coherence` | `32kw_t2_g`, `256kw_g` | shared buffer, cache lines bounce between cores |
| `thread_sweep` | `4mr_t2`, `64mw_t8` | bandwidth intensity vs thread count |
| `cpu_side` | `32kn`, `cpu_prime_t8`, `mutex1_t4`, `threads_t16` | CPU load without memory-bandwidth pressure |
| `pagefault` | `pf_64mw_t4`, `ng_fault_t4` | repeated page faults (see below) |

Cache sizes used for these choices (Cortex-A76): L1D 64 KB/core, L2 512 KB/core, L3 2 MB shared.

**Page-fault experiments.** `sysbench memory` allocates once, so it can't fault pages
repeatedly in a single run. The `pf_*` experiments re-launch sysbench in a loop with
`total-size == block-size`, so every pass maps and first-touches fresh pages. The `ng_*`
experiments use `stress-ng` fault/mmap/vm stressors and are skipped if it isn't installed.

## 8. Output files

```
/data/4mr/
├── gpu_task.txt          stdout/stderr of gpu_task
├── sysbench.txt          stdout/stderr of the stressor (per-second report lines)
├── v3d_counters.txt      V3D counter samples
├── dvfs.txt              live status lines from the DVFS profiler
├── rpi5-dvfs-logs/<ts>/  full DVFS logs (monitor.csv, cpu_policies.csv, thermal_zones.csv, ...)
├── meta.txt              exact commands, timings, exit code, temperatures, CPU/cache info
└── DONE
```

**`sysbench.txt`**: the stressor is stopped with SIGTERM when `gpu_task` ends, so there's
no final summary. Use the per-second `--report-interval` lines instead.

**`v3d_counters.txt`** (plain text, one counter per line):

```
# columns: wall_epoch elapsed_s window group counter_id counter_name value(delta over window)
1760000000.123 1.002 0 0 0 cycle-count 123456
```

- One V3D perfmon holds at most 32 counters, so the 93 counters are split into 3 groups
  that are sampled round-robin, one window (`V3D_INTERVAL_MS`, default 1 s) per group.
  Each counter is therefore sampled once every 3 windows.
- To sample every counter every window, select 32 or fewer, for example the memory-related ones:

  ```bash
  V3D_COUNTERS="22,23,28,29,39,43,44,45,46,47,48,49,54,55,60,61,62,66,67,75,76,77,78,79,80,87" \
  sudo -E ./monitor_interference.sh -f '^64mr$'
  ```

**Aligning the logs.** `v3d_counters.txt` uses wall-clock epoch seconds. `meta.txt` records
`stress_start`, `gpu_start` and `gpu_end` in the same epoch format, and the DVFS logs carry
ISO timestamps. Use these to cut every file to the `gpu_task` window.

## 9. Configuration (environment variables)

All defaults are in `scripts/lib.sh`. Override them on the command line. With `sudo`,
pass them through with `sudo -E` or `sudo VAR=value ./monitor_interference.sh`.

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `/data` | where result folders are created |
| `GPU_CMD` | `./build/gpu_task` | gpu_task command, including arguments |
| `GPU_TIMEOUT` | `900` | seconds before a gpu_task run is killed (exit code 124) |
| `GPU_CPUS` / `STRESS_CPUS` | empty | `taskset` CPU lists, e.g. `GPU_CPUS=0 STRESS_CPUS=1-3` |
| `DVFS_SCRIPT` | auto | path to `rpi5-dvfs-monitor.sh` |
| `DVFS_INTERVAL` | `0.5` | DVFS sampling interval, seconds |
| `V3D_DEV` | `/dev/dri/renderD128` | DRM render node |
| `V3D_INTERVAL_MS` | `1000` | V3D window length |
| `V3D_COUNTERS` | `all` | `all` or comma-separated counter IDs |
| `SB_THREADS` | `nproc` | default thread count (also changes folder names) |
| `SB_REPORT` | `1` | sysbench `--report-interval` |
| `SB_MAX_TIME` | `3600` | safety cap on stressor run time |
| `WARMUP` / `COOLDOWN` | `3` / `3` | seconds before / after gpu_task |
| `DROP_CACHES` | `1` | drop page cache before each run (root only) |
| `SETTLE_TEMP` / `SETTLE_MAX` | `70` / `60` | temperature target (C) and max wait in seconds before each run; `SETTLE_TEMP=` disables the wait |

Examples:

```bash
# gpu_task with arguments, pinned to core 0; stressors on cores 1-3
sudo GPU_CMD="./build/gpu_task --size 1024" GPU_CPUS=0 STRESS_CPUS=1-3 ./monitor_interference.sh -c dram_stream

# faster V3D sampling
sudo V3D_INTERVAL_MS=250 ./monitor_interference.sh -f '^8mw$'
```

## 10. Run the pieces on their own

Every launcher works standalone, which helps with debugging:

```bash
bash scripts/experiments.sh -l                                   # experiment table
bash scripts/run_stress.sh --print "4mr|cache_evict|mem|4m|read|seq|4|local"   # show the command
bash scripts/run_stress.sh "4mr|cache_evict|mem|4m|read|seq|4|local"           # run the stressor (Ctrl+C to stop)
bash scripts/run_v3d_monitor.sh | head -20                       # V3D counters to the terminal
mkdir -p /tmp/dvfs && bash scripts/run_dvfs.sh /tmp/dvfs         # DVFS profiler (Ctrl+C to stop)
bash scripts/run_gpu_task.sh                                     # just gpu_task
```

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `ERROR: 'sysbench' not found` | `sudo apt install sysbench` |
| `ERROR: cannot write /data` | run with `sudo`, or `sudo mkdir /data && sudo chown $USER /data` |
| `rpi5-dvfs-monitor.sh not found` | copy it to `scripts/` or set `DVFS_SCRIPT` |
| `make` fails with `drm/v3d_drm.h: No such file` | `sudo apt install libdrm-dev` |
| `v3d_counters.txt` says `PERFMON_SET_GLOBAL failed` | another process may hold the global perfmon (EBUSY), or the kernel lacks the ioctl; send the first lines of the file for diagnosis |
| `v3d_counters.txt` is all zeros | counters only accumulate while the GPU is busy; check that `gpu_task` really submits jobs and that the window overlaps it |
| `cannot open /dev/dri/renderD128` | check `ls /dev/dri`, then set `V3D_DEV`; make sure the user can access the node (`video`/`render` group, or use `sudo`) |
| Experiment skipped: not enough free RAM | large blocks need `block x threads` of free RAM (up to 70% of `MemAvailable`); lower `SB_THREADS` or free memory |
| Experiment skipped: `stress-ng` not installed | `sudo apt install stress-ng` |
| `gpu_exit_code: 124` in `meta.txt` | `gpu_task` hit `GPU_TIMEOUT`; raise it |
| `[settle] ... waiting` repeats on every run | your idle temperature is above `SETTLE_TEMP`; raise it (e.g. `SETTLE_TEMP=75`) or disable with `SETTLE_TEMP=` |
| Want to repeat a finished experiment | add `-F`, or delete its `DONE` file |

## 12. Notes

- Total time is roughly `(gpu_task time + WARMUP + COOLDOWN + up to SETTLE_MAX) x number of experiments`.
  Use `-c` / `-f` to run a subset first.
- `sysbench memory --memory-oper=none` (the `*n` folders) generates CPU load with no
  memory traffic. It is the "CPU-side contention" control.
- Throttling matters on a Pi 5: compare `throttled_flags` and clocks in the DVFS logs
  against GPU performance before blaming memory contention.