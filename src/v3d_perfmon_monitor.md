# Detailed explanation of `v3d_perfmon_monitor`

This program is a system-wide sampler for the Raspberry Pi 5's V3D GPU hardware performance counters. It opens the Linux DRM device, asks the kernel which counters are available, activates a selected set of counters, waits for a sampling interval, reads their accumulated values, and writes timestamped measurements to standard output.

For your GPU–CPU memory-interference research, the important distinction is that this program measures GPU hardware events over time windows. It does not directly expose every DRAM transaction, the memory-controller queue depth, or the arbitration decisions between CPU and GPU. Whether a particular counter can reveal something about those mechanisms depends on the actual counters supported by your kernel and V3D hardware.

## 1. Overall execution flow

Initialize

Parse arguments, install signal handlers, open `/dev/dri/renderD128`

Discover hardware capabilities

Check perfmon support, maximum counters and counter names

Select counters and divide into groups

At most 32 counters per group

Repeat for each group

Create perfmon → activate globally → wait → read values → deactivate → destroy

Emit measurements

Print timestamps, group IDs, counter IDs, names and counter deltas

The outer loop runs continuously until you press `Ctrl+C` or send a termination signal. The inner loop visits the counter groups one at a time.

An important implication is that not all counters are necessarily measured simultaneously. If there are more counters than fit in one group, the program time-multiplexes them. That affects how you interpret correlations between counter measurements.

## 2. The Linux interfaces this program uses

The code relies on several layers of the Linux graphics stack.

Your monitoring process

The C program running in user space. It chooses counters, controls sampling intervals and saves results.

DRM ioctl interface

Linux Direct Rendering Manager exposes commands for discovering capabilities, creating performance monitors and retrieving counter values.

V3D kernel driver

The kernel driver manages GPU performance-monitoring resources and communicates with the hardware.

V3D GPU hardware

Hardware performance counters accumulate events associated with the supported GPU subsystems.

The key interface is `ioctl()`, short for input/output control. Unlike a normal file read, an ioctl sends a structured command to a device driver.

For example:

```
ioctl(fd, DRM_IOCTL_V3D_PERFMON_CREATE, &cr);
```

Here, `fd` identifies the opened DRM device, the second argument identifies the requested operation, and `&cr` points to a structure containing the request and, on success, the returned performance-monitor ID.

The kernel validates the request and performs the driver-specific operation. Your program then uses that ID in later calls.

This is how the program can access hardware counters without directly mapping and manipulating GPU registers itself.

## 3. Header files and definitions

The first section includes the C libraries needed for the program.

```
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <time.h>
#include <sys/ioctl.h>
#include <drm/v3d_drm.h>
```

`stdio.h` provides `printf()` and `fprintf()` for output. `stdint.h` provides fixed-width integer types such as `uint64_t`. `stdlib.h` provides `atoi()`, `strtoul()` and `free()`. `string.h` provides string operations and `memset()`. `fcntl.h` and `unistd.h` provide device opening and basic system calls. `errno.h` provides error reporting. `signal.h` handles termination signals, `time.h` provides clocks and sleeping, `sys/ioctl.h` provides the ioctl interface, and `drm/v3d_drm.h` defines the V3D driver's request structures and command constants.

The program also defines a fallback for systems whose installed DRM headers do not yet declare the global performance-monitor ioctl.

```
#ifndef DRM_IOCTL_V3D_PERFMON_SET_GLOBAL
#define DRM_V3D_PERFMON_CLEAR_GLOBAL 0x0001

struct drm_v3d_perfmon_set_global {
    __u32 flags;
    __u32 id;
};

#define DRM_IOCTL_V3D_PERFMON_SET_GLOBAL \
    DRM_IOW(DRM_COMMAND_BASE + 0x0d, \
            struct drm_v3d_perfmon_set_global)
#endif
```

`#ifndef` means “if this macro has not already been defined.” The fallback defines the ioctl request number and its argument structure only when the header lacks the definition.

`DRM_COMMAND_BASE + 0x0d` identifies the driver-specific ioctl command number. `DRM_IOW` constructs a request code indicating that data is passed from user space to the kernel.

The structure has two fields. `flags` indicates the requested operation, while `id` identifies the performance monitor.

The flag `DRM_V3D_PERFMON_CLEAR_GLOBAL` is used later to detach the active monitor. The code assumes the target kernel implements this ioctl with the same ABI. A fallback definition allows compilation against older headers, but it does not guarantee that a particular running kernel implements the command.

The final macro is:

```
#define MAXP DRM_V3D_MAX_PERF_COUNTERS
```

`MAXP` is a shorthand for the maximum number of counters that one monitor can hold. In your program's intended configuration, this is 32. The same value controls the size of each counter group and the temporary array used to retrieve results.

## 4. Global state, signals and time measurement

```
static volatile sig_atomic_t stop_flag;

static void on_sig(int s)
{
    (void)s;
    stop_flag = 1;
}
```

`stop_flag` communicates a shutdown request from a signal handler to the main program.

When you press `Ctrl+C`, the terminal typically sends `SIGINT`. A service manager or another process may send `SIGTERM`. The program registers the same handler for both:

```
struct sigaction sa;
memset(&sa, 0, sizeof sa);
sa.sa_handler = on_sig;
sigaction(SIGINT, &sa, NULL);
sigaction(SIGTERM, &sa, NULL);
```

The `volatile sig_atomic_t` type is appropriate for this simple signal-handler communication: the handler performs only a minimal assignment, rather than doing I/O or manipulating complex state. The return values of `sigaction()` are not checked, however, so a failure to register a handler would go unnoticed.

Why use a signal flag rather than exiting immediately?

The main loop can finish its current cleanup sequence before terminating. That gives the program an opportunity to detach and destroy a performance monitor rather than abruptly abandoning it.

There are two clock functions:

```
static double now_mono(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}
```

```
static double now_wall(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}
```

Both convert a `timespec` structure into a floating-point number of seconds. `tv_sec` is the whole-second component, and `tv_nsec` is the nanosecond component.

`CLOCK_MONOTONIC` measures elapsed time using a clock that does not jump when the system wall clock is adjusted. It is used for measuring duration.

`CLOCK_REALTIME` represents wall-clock time, expressed as seconds since the Unix epoch. It is used to timestamp output so you can align GPU measurements with logs from other programs, such as your memory stress test or DVFS monitor.

This distinction is useful in interference experiments. Use monotonic timestamps for elapsed durations and wall-clock timestamps for correlating independent log files.

The sleep helper is:

```
static void sleep_ms(int ms)
{
    double end = now_mono() + ms / 1000.0;

    while (!stop_flag) {
        double left = end - now_mono();
        if (left <= 0)
            break;

        struct timespec ts = {
            (time_t)left,
            (long)((left - (time_t)left) * 1e9)
        };

        nanosleep(&ts, NULL);
    }
}
```

Suppose `interval_ms` is 1000. The function calculates an end time one second in the future, repeatedly checks the remaining time, and calls `nanosleep()` for that remaining duration.

This approach handles interruptions more gracefully than a single `usleep()` call. If a signal interrupts `nanosleep()`, the function checks the clock again and continues sleeping if time remains and shutdown has not been requested.

One subtlety is that `sleep_ms()` does not guarantee an exact interval. Linux scheduling, the time spent in ioctls, and other work can cause the actual sampling window to be longer than requested.

## 5. Opening the GPU device

The default arguments are initialized here:

```
const char *dev = "/dev/dri/renderD128";
const char *clist = "all";
int interval_ms = 1000, opt;
```

The program defaults to the V3D render node, requests all available counters and uses a nominal one-second interval.

The argument parser is:

```
while ((opt = getopt(argc, argv, "d:i:c:")) != -1) {
    if (opt == 'd') dev = optarg;
    else if (opt == 'i') interval_ms = atoi(optarg);
    else if (opt == 'c') clist = optarg;
    else {
        fprintf(stderr, "usage: %s [-d dev] [-i ms] [-c all|id,id,...]\n",
                argv[0]);
        return 2;
    }
}
```

The colon after each option character means that the option requires an argument. For example, `-d` needs a device path, `-i` needs an interval, and `-c` needs a counter selection.

An example invocation is:

```
./v3d_perfmon_monitor -d /dev/dri/renderD128 -i 1000 -c all
```

The device is opened with:

```
int fd = open(dev, O_RDWR);
```

`O_RDWR` requests read/write access because performance-monitor management involves issuing control operations, not merely reading a regular file.

If opening fails, the program prints the path and the operating-system error message:

```
if (fd < 0) {
    fprintf(stderr, "cannot open %s: %s\n",
            dev, strerror(errno));
    return 1;
}
```

The file descriptor `fd` is the handle passed to every subsequent ioctl. Access permissions and the device's support for the required ioctls determine whether the program can operate successfully.

## 6. Discovering perfmon capabilities

The next function queries a parameter from the kernel:

```
static int get_param(int fd, unsigned int param, uint64_t *value)
{
    struct drm_v3d_get_param p = { .param = param };

    if (ioctl(fd, DRM_IOCTL_V3D_GET_PARAM, &p) < 0)
        return -1;

    *value = p.value;
    return 0;
}
```

The function accepts a device descriptor, a parameter identifier and a pointer where the returned value will be stored.

The structure is initialized with the requested parameter. The ioctl passes the request to the driver. If successful, the driver populates `p.value`, and the function copies that result to the caller's memory.

In `main()`, two parameters are requested:

```
uint64_t supported = 0, maxc = 0;

if (get_param(fd, DRM_V3D_PARAM_SUPPORTS_PERFMON, &supported) < 0 ||
    get_param(fd, DRM_V3D_PARAM_MAX_PERF_COUNTERS, &maxc) < 0 ||
    !supported || !maxc) {
    fprintf(stderr, "perfmon not supported\n");
    return 1;
}
```

`DRM_V3D_PARAM_SUPPORTS_PERFMON` checks whether the driver reports performance-monitor support. `DRM_V3D_PARAM_MAX_PERF_COUNTERS` retrieves the reported maximum number of counters that can be included in a monitor.

The program refuses to continue if either query fails, perfmon support is absent, or the maximum is zero.

It then applies a local upper bound:

```
if (maxc > 256)
    maxc = 256;
```

This is a software safety limit, not a claim that the hardware supports 256 counters. The program stores counter IDs and names in arrays of length 256. The bound prevents the reported count from exceeding those arrays' capacity.

There is an important distinction between the number of counters the driver can select and the number of counters that can be active in one perfmon at once. The first determines the selection range, while the second is limited by `MAXP`.

## 7. Parsing and selecting counter IDs

The program stores the selected IDs in:

```
static uint8_t ids[256];
unsigned nids = 0;
```

Each entry is an unsigned eight-bit integer. Because the program caps the reported counter count at 256, the valid IDs range from 0 through 255.

If the user specifies `-c all`, this loop selects every ID from zero up to `maxc - 1`:

```
if (!strcmp(clist, "all")) {
    for (unsigned i = 0; i < maxc; i++)
        ids[nids++] = (uint8_t)i;
}
```

Otherwise, the program treats the argument as a comma-separated list:

```
char *copy = strdup(clist), *save = NULL;

for (char *tok = strtok_r(copy, ",", &save);
     tok;
     tok = strtok_r(NULL, ",", &save)) {

    unsigned long v = strtoul(tok, NULL, 10);

    if (v < maxc && nids < 256)
        ids[nids++] = (uint8_t)v;
}

free(copy);
```

`strdup()` creates a writable copy of the command-line string because `strtok_r()` modifies its input by replacing delimiters with string terminators.

`strtok_r()` extracts one token at a time, and `strtoul()` converts each token into an unsigned integer. The program accepts IDs that fall below `maxc` and stores them in `ids`.

For example, `-c 0,3,7` requests counters 0, 3 and 7, provided those IDs are within the driver's reported range.

However, this parser has some limitations. It does not validate whether a token contains only digits, does not detect integer-conversion errors, and silently ignores out-of-range IDs. It also permits duplicate IDs. If the user supplies a completely invalid list, the program prints `no valid counters selected` and exits.

For a robust research tool, you would ideally validate every token, reject malformed input and duplicates, and report which counter IDs were rejected. This is especially useful when reproducing experiments across different kernel versions.

## 8. Retrieving counter names

Counter IDs are numeric, so the program asks the kernel for a human-readable name for each selected counter.

```
static char names[256][65];

for (unsigned i = 0; i < nids; i++) {
    struct drm_v3d_perfmon_get_counter c;
    memset(&c, 0, sizeof c);
    c.counter = ids[i];

    if (ioctl(fd, DRM_IOCTL_V3D_PERFMON_GET_COUNTER, &c) == 0)
        snprintf(names[ids[i]], sizeof names[0],
                 "%.64s", (char *)c.name);
    else
        snprintf(names[ids[i]], sizeof names[0],
                 "counter%u", ids[i]);
}
```

The two-dimensional array allocates 256 name slots, each with 65 bytes of storage. Each slot can hold up to 64 characters plus a terminating null byte.

For every selected ID, the code initializes a `drm_v3d_perfmon_get_counter` structure and places the ID in `c.counter`. The ioctl asks the driver for the corresponding counter's metadata.

If successful, the program copies the returned name into its own array. The `%.64s` format limits the copied string to 64 characters, preventing an overlong name from overflowing the destination.

If the query fails, the code generates a fallback name such as `counter7`.

One detail matters here: names are indexed by the actual counter ID, not by the counter's position in the selection list. Therefore, if you select counters 2, 8 and 12, their names are stored in `names[2]`, `names[8]` and `names[12]`.

This makes later output straightforward:

```
names[ids[base + i]]
```

The code assumes the returned `c.name` field contains a null-terminated string, as expected by the driver ABI.

## 9. Dividing counters into groups

The kernel interface limits the number of counters in one monitor. The program calculates the number of groups using:

```
unsigned ngroups = (nids + MAXP - 1) / MAXP;
```

This is integer arithmetic implementing the ceiling operation:

\\[ N\_{\text{groups}} = \left\lceil \frac{N\_{\text{counters}}}{N\_{\text{per group}}} \right\rceil \\]

If there are 75 selected counters and the limit is 32, the result is three groups: 32 counters, another 32 counters, and the remaining 11 counters.

The formula works without floating-point arithmetic because integer division discards the fractional part after the addition has ensured the result is rounded up.

The program prints its configuration:

```
printf("# v3d_perfmon_monitor dev=%s interval_ms=%d counters=%u groups=%u "
       "(each counter sampled once every %u windows)\n",
       dev, interval_ms, nids, ngroups, ngroups);

printf("# columns: wall_epoch elapsed_s window group counter_id "
       "counter_name value(delta over window)\n");
```

The lines begin with `#`, making them recognizable as metadata rather than measurement records.

The phrase “each counter sampled once every `ngroups` windows” describes the intended round-robin schedule. It is exact only in terms of the sequence of requested groups, not necessarily in terms of elapsed time: ioctl overhead, scheduling delays and errors can affect the actual timing.

Why does this matter for your experiments?

When only one group exists, all selected counters are active during the same sampling window. When there are multiple groups, different counter sets are measured at different times. You should not automatically treat those values as simultaneous observations of the same GPU workload phase.

## 10. Understanding the main sampling loop

The program records its starting monotonic time and initializes the window number:

```
double t_start = now_mono();
unsigned window = 0;
```

The outer loop then runs until shutdown is requested:

```
while (!stop_flag) {
    for (unsigned g = 0; g < ngroups && !stop_flag; g++, window++) {
        ...
    }
}
```

The variable `g` identifies the group currently being sampled. The variable `window` identifies the sampling window globally across the entire run.

Unlike `g`, which resets to zero each time the outer loop begins another round, `window` continues increasing. This lets you reconstruct the measurement sequence from the output.

The program determines which counter IDs belong to the current group:

```
unsigned base = g * MAXP;

unsigned n = nids - base < MAXP
           ? nids - base
           : MAXP;
```

`base` is the starting position in the selected-counter array. The variable `n` is the number of counters in this group, limited to `MAXP`.

For example, with 75 selected counters and 32 counters per group, group 0 starts at index 0 and contains 32 counters. Group 1 starts at index 32 and also contains 32. Group 2 starts at index 64 and contains 11.

Notice that `base` is an array position, not a hardware counter ID. The code accesses the actual IDs through `ids[base + i]`.

## 11. Creating a performance monitor

For each group, the program creates a new monitor:

```
struct drm_v3d_perfmon_create cr;
memset(&cr, 0, sizeof cr);

cr.ncounters = n;

for (unsigned i = 0; i < n; i++)
    cr.counters[i] = ids[base + i];
```

The `drm_v3d_perfmon_create` structure contains the requested counter count and the IDs of the counters to include. Zero-initialization prevents uninitialized fields from being sent to the driver.

The actual creation operation is:

```
if (ioctl(fd, DRM_IOCTL_V3D_PERFMON_CREATE, &cr) < 0) {
    fprintf(stderr, "# PERFMON_CREATE failed: %s\n",
            strerror(errno));
    sleep_ms(interval_ms);
    continue;
}
```

On success, the driver returns a monitor ID in `cr.id`. That ID is subsequently used to activate the monitor, read its values and destroy it.

On failure, the program logs the error, waits for the nominal sampling interval, and skips to the next group.

This failure path has a measurement consequence: a group can be skipped entirely, so your logs may have missing counter observations. The program does not currently write an explicit failure record to standard output or retry the same group immediately.

## 12. Activating the global performance monitor

The next operation attaches the new monitor as the global monitor:

```
struct drm_v3d_perfmon_set_global sg;
memset(&sg, 0, sizeof sg);
sg.id = cr.id;

if (ioctl(fd, DRM_IOCTL_V3D_PERFMON_SET_GLOBAL, &sg) < 0) {
    fprintf(stderr, "# PERFMON_SET_GLOBAL failed: %s\n",
            strerror(errno));

    struct drm_v3d_perfmon_destroy d = { .id = cr.id };
    ioctl(fd, DRM_IOCTL_V3D_PERFMON_DESTROY, &d);

    sleep_ms(interval_ms);
    continue;
}
```

The program places the newly created monitor's ID in `sg.id`. Since `sg.flags` was zero-initialized, the request asks to set the monitor globally rather than clear it.

The distinction between creating and activating a monitor is important. Creating it allocates and configures the monitoring resource. Setting it globally makes it the active monitor according to the driver's global-perfmon interface.

Your code assumes that the running kernel supports this interface and that the monitor can be activated successfully. The fallback macro handles compilation against headers without the definition; it cannot resolve runtime incompatibility.

The global nature of the interface also matters for concurrent experiments. Another process attempting to control the same global monitor may interfere with this program's assumptions. The kernel's exact conflict behavior depends on its implementation.

## 13. The actual sampling interval

Once the monitor is active, the program waits:

```
sleep_ms(interval_ms);
```

During this period, the selected hardware counters can accumulate the events they are designed to count.

For a nominal interval of 1000 ms, the intention is to collect one second's worth of counter activity for that group.

The program does not explicitly start and stop each hardware counter around a specific GPU kernel. Instead, it activates a monitor, waits, and reads the resulting accumulated values. Consequently, the observed interval can include activity from other GPU clients or workloads that run during the same period, subject to the driver's counter semantics.

This is what makes the monitor useful for system-wide interference studies, but it also means that measurements cannot automatically be attributed exclusively to your own `gpu_task`.

For cleaner attribution, run controlled idle and workload phases, log their start and end times, and repeat experiments under the same conditions.

## 14. Reading the counter values

After the sampling interval, the program prepares a buffer for the counter values:

```
uint64_t vals[MAXP];
memset(vals, 0, sizeof vals);
```

The array holds one 64-bit value per counter in the active group. Zero-initialization provides a known starting state for the user-space buffer.

The program then requests the values:

```
struct drm_v3d_perfmon_get_values gv;
memset(&gv, 0, sizeof gv);

gv.id = cr.id;
gv.values_ptr = (uintptr_t)vals;

int rc = ioctl(fd, DRM_IOCTL_V3D_PERFMON_GET_VALUES, &gv);
int gerr = errno;
```

The structure contains the monitor ID and a pointer to the user-space array. The cast to `uintptr_t` converts the pointer into an integer type wide enough to represent an address, matching the interface's expected field type.

The ioctl asks the driver to return the accumulated values for the monitor's counters. The values are written into `vals` according to the ordering of the counters in the monitor's creation request.

The result code `rc` indicates whether the request succeeded. The code saves `errno` immediately afterward in `gerr`, preserving the error code before later ioctls can change it.

What does the returned value mean?

The source describes the output as a counter delta accumulated over the window. More precisely, the program prints the value returned by the kernel for that monitor after its activation interval. It does not itself subtract an earlier reading from a later reading.

The exact semantics depend on the V3D driver's performance-monitor implementation. You should verify whether the kernel returns a per-monitor accumulation over the active period and how each particular hardware counter is defined before interpreting it as a precise event count.

For an event counter that counts occurrences, a value may represent an event total during the window. For a counter that measures cycles or another quantity, its meaning and units depend on the hardware definition. A raw counter value is not automatically a bandwidth measurement or a time measurement.

## 15. Deactivating and destroying the monitor

Immediately after attempting to read the values, the program performs cleanup:

```
sg.flags = DRM_V3D_PERFMON_CLEAR_GLOBAL;
ioctl(fd, DRM_IOCTL_V3D_PERFMON_SET_GLOBAL, &sg);

struct drm_v3d_perfmon_destroy d = { .id = cr.id };
ioctl(fd, DRM_IOCTL_V3D_PERFMON_DESTROY, &d);
```

The first ioctl requests that the global monitor be cleared. The second asks the kernel to destroy the monitor identified by `cr.id`.

This sequence separates two distinct operations. Clearing the global monitor detaches the active monitor; destroying it releases the associated monitoring resource.

The program attempts cleanup even if retrieving the values fails. That is a useful design choice.

However, the cleanup ioctl return values are ignored. If clearing the global monitor fails, destroying the monitor may also fail or leave the global state different from what the program expects. A more robust implementation should check both results and report any cleanup failures.

The code also does not check whether `clock_gettime()` succeeds. For research-grade measurement software, checking system-call results is preferable to assuming every operation succeeds.

## 16. Printing the measurements

If reading the values fails, the program reports the saved error:

```
if (rc < 0) {
    fprintf(stderr, "# PERFMON_GET_VALUES failed: %s\n",
            strerror(gerr));
    continue;
}
```

Otherwise, it records the wall-clock timestamp and elapsed time:

```
double w = now_wall();
double el = now_mono() - t_start;
```

It then prints one line for every counter in the current group:

```
for (unsigned i = 0; i < n; i++)
    printf("%.3f %.3f %u %u %u %s %llu\n",
           w, el, window, g,
           ids[base + i],
           names[ids[base + i]],
           (unsigned long long)vals[i]);

fflush(stdout);
```

The seven output fields have the following meanings.

| Field          | Meaning                                                         |
| -------------- | --------------------------------------------------------------- |
| `wall_epoch`   | Wall-clock Unix timestamp in seconds, with three decimal places |
| `elapsed_s`    | Monotonic elapsed time since the monitor started                |
| `window`       | Increasing sampling-window number                               |
| `group`        | Counter group active during this window                         |
| `counter_id`   | Hardware counter identifier                                     |
| `counter_name` | Human-readable name returned by the driver                      |
| `value`        | Value returned by the perfmon read operation                    |

For example, a line might look like this:

```
1792447201.125 3.002 2 0 7 example_counter 123456
```

This is an illustrative example, not a measurement from your Raspberry Pi. It indicates that counter 7 was read in window 2, group 0, at approximately 3.002 seconds of elapsed time.

The `%.3f` format prints three digits after the decimal point. `%u` prints unsigned integers, `%s` prints the name, and `%llu` prints the 64-bit value after casting it to `unsigned long long`.

Finally, `fflush(stdout)` flushes buffered output so that records are visible promptly to a terminal or redirected log file. It does not guarantee that the data has been durably committed to storage.

## 17. What the monitor actually measures during GPU–CPU interference

For your Raspberry Pi 5 experiments, it helps to distinguish what this program directly observes from what you may infer.

Directly observed

Values returned for selected V3D hardware counters, together with the sampling-window timestamps and counter identities.

Potentially inferred

Changes in GPU activity or behavior under CPU memory pressure, provided the selected counters have relevant documented semantics and the experimental controls are sound.

Not directly exposed by this code

Individual DRAM transactions, DRAM-controller queue depth, arbitration decisions, exact CPU–GPU bus contention, or a complete account of GPU memory traffic.

Consider an experiment in which you run your Vulkan or OpenGL compute workload while simultaneously running `sysbench memory`.

If a documented GPU counter changes during the memory stress phase, that is evidence of a change in the measured GPU event. It does not, by itself, prove that DRAM contention caused the change. CPU scheduling, GPU execution differences, cache behavior, DVFS, background GPU activity and other factors may also contribute.

To make the inference stronger, establish an idle baseline, measure the GPU workload alone, measure the CPU stress test alone, and then measure both together. Record the CPU and V3D clock behavior alongside the performance counters. Repeat each condition and compare distributions or time-aligned measurements rather than relying on one run.

There is another critical limitation: because the global monitor is system-wide, your results are not necessarily exclusive to the process you are studying. The monitoring code does not filter counter events by process ID.

## 18. Important limitations and improvements

The interval is not an exact hardware timer. The requested interval controls the sleep duration, but creation, activation, deactivation, readout and scheduling overhead affect the full measurement cycle. The code timestamps the results after readout and cleanup, so `elapsed_s` is an output timestamp rather than the exact start or end of the hardware counting interval.

Multiple groups are not simultaneous. With more than 32 selected counters, the groups are sampled sequentially. If a workload changes rapidly, one group may observe a different phase from another. For short interference events, use a smaller carefully selected counter set so that all important counters fit into one monitor.

Some failures are silently tolerated. The code does not validate that `interval_ms` is positive. It also ignores failures from the global-clear ioctl, monitor-destroy ioctl, signal registration and clock calls. Negative or zero intervals can result in unintended behavior. These are worth fixing before using the program for repeated experiments.

Counter interpretation requires documentation. The program retrieves counter names but does not explain their definitions, units, overflow behavior or hardware scope. A counter named for a memory-related event might count requests, cycles or some other quantity; the name alone is insufficient to determine which. Consult the counter definitions for the actual driver and hardware.

Logging should distinguish failed windows. At present, error messages go to standard error while successful measurements go to standard output. If you redirect both streams separately, a downstream analysis script must combine the information using timestamps or window identifiers. Adding an explicit status field or structured error record would make automated analysis more reliable.

A single monitor instance does not establish causality. If the objective is to identify memory interference, counter changes should be correlated with workload timing, CPU memory traffic, GPU execution time and frequency behavior. For your study, the monitor is one instrument in a larger experimental setup rather than a complete DRAM-bus profiler.

## 19. How to run it and preserve the data

After compiling the program against your installed V3D DRM headers, you can run:

```
./v3d_perfmon_monitor \
    -d /dev/dri/renderD128 \
    -i 1000 \
    -c all \
    > v3d_perfmon.log \
    2> v3d_perfmon_errors.log
```

The first file receives configuration metadata and successful counter measurements. The second receives error messages.

To sample a specific set of counters instead, replace `all` with a comma-separated list of supported IDs. This is particularly useful when you need all counters in a single window for time-aligned comparisons.

For your interference experiment, use the same counter set and interval in every experimental condition. Record when `gpu_task` and `sysbench` start and finish, and capture clock information in parallel. Before interpreting any counter as a measure of memory traffic, verify its precise hardware definition.

The central takeaway: this program is a user-space controller for the V3D driver's global performance-monitor interface. It discovers counters, activates them in groups, reads their accumulated values and timestamps the results. It provides a useful foundation for measuring changes in GPU behavior under CPU memory pressure, but the hardware counters' semantics and the experimental design determine what you can reliably conclude about memory interference.