/*
 * v3d_perfmon_monitor: system-wide V3D hardware counter sampler.
 *
 * A V3D perfmon holds at most DRM_V3D_MAX_PERF_COUNTERS (32) counters, and only
 * one *global* perfmon can be active at a time, so the requested counters are
 * split into groups of 32 and the groups are sampled round-robin, one window
 * of -i milliseconds each. Each window uses a fresh perfmon, so the value
 * printed is the counter delta accumulated during that window.
 *
 * usage: v3d_perfmon_monitor [-d /dev/dri/renderD128] [-i interval_ms] [-c all|id,id,...]
 *
 * Output (plain text, one counter per line):
 *   wall_epoch  elapsed_s  window  group  counter_id  counter_name  value
 */
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

/* Fallback for older userspace headers that predate the global-perfmon ioctl
 * (RPi kernels have it: DRM_V3D_PERFMON_SET_GLOBAL = 0x0d). */
#ifndef DRM_IOCTL_V3D_PERFMON_SET_GLOBAL
#define DRM_V3D_PERFMON_CLEAR_GLOBAL 0x0001
struct drm_v3d_perfmon_set_global {
    __u32 flags;
    __u32 id;
};
#define DRM_IOCTL_V3D_PERFMON_SET_GLOBAL \
    DRM_IOW(DRM_COMMAND_BASE + 0x0d, struct drm_v3d_perfmon_set_global)
#endif

#define MAXP DRM_V3D_MAX_PERF_COUNTERS

static volatile sig_atomic_t stop_flag;
static void on_sig(int s) { (void)s; stop_flag = 1; }

static double now_mono(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static double now_wall(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static void sleep_ms(int ms)
{
    double end = now_mono() + ms / 1000.0;
    while (!stop_flag) {
        double left = end - now_mono();
        if (left <= 0)
            break;
        struct timespec ts = { (time_t)left, (long)((left - (time_t)left) * 1e9) };
        nanosleep(&ts, NULL);
    }
}

static int get_param(int fd, unsigned int param, uint64_t *value)
{
    struct drm_v3d_get_param p = { .param = param };
    if (ioctl(fd, DRM_IOCTL_V3D_GET_PARAM, &p) < 0)
        return -1;
    *value = p.value;
    return 0;
}

int main(int argc, char **argv)
{
    const char *dev = "/dev/dri/renderD128", *clist = "all";
    int interval_ms = 1000, opt;

    while ((opt = getopt(argc, argv, "d:i:c:")) != -1) {
        if (opt == 'd') dev = optarg;
        else if (opt == 'i') interval_ms = atoi(optarg);
        else if (opt == 'c') clist = optarg;
        else {
            fprintf(stderr, "usage: %s [-d dev] [-i ms] [-c all|id,id,...]\n", argv[0]);
            return 2;
        }
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_sig;           /* no SA_RESTART: sleep gets interrupted */
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    int fd = open(dev, O_RDWR);
    if (fd < 0) {
        fprintf(stderr, "cannot open %s: %s\n", dev, strerror(errno));
        return 1;
    }

    uint64_t supported = 0, maxc = 0;
    if (get_param(fd, DRM_V3D_PARAM_SUPPORTS_PERFMON, &supported) < 0 ||
        get_param(fd, DRM_V3D_PARAM_MAX_PERF_COUNTERS, &maxc) < 0 ||
        !supported || !maxc) {
        fprintf(stderr, "perfmon not supported\n");
        return 1;
    }
    if (maxc > 256)
        maxc = 256;

    /* Which counters to sample */
    static uint8_t ids[256];
    unsigned nids = 0;
    if (!strcmp(clist, "all")) {
        for (unsigned i = 0; i < maxc; i++)
            ids[nids++] = (uint8_t)i;
    } else {
        char *copy = strdup(clist), *save = NULL;
        for (char *tok = strtok_r(copy, ",", &save); tok; tok = strtok_r(NULL, ",", &save)) {
            unsigned long v = strtoul(tok, NULL, 10);
            if (v < maxc && nids < 256)
                ids[nids++] = (uint8_t)v;
        }
        free(copy);
    }
    if (!nids) {
        fprintf(stderr, "no valid counters selected\n");
        return 1;
    }

    /* Counter names */
    static char names[256][65];
    for (unsigned i = 0; i < nids; i++) {
        struct drm_v3d_perfmon_get_counter c;
        memset(&c, 0, sizeof c);
        c.counter = ids[i];
        if (ioctl(fd, DRM_IOCTL_V3D_PERFMON_GET_COUNTER, &c) == 0)
            snprintf(names[ids[i]], sizeof names[0], "%.64s", (char *)c.name);
        else
            snprintf(names[ids[i]], sizeof names[0], "counter%u", ids[i]);
    }

    unsigned ngroups = (nids + MAXP - 1) / MAXP;
    printf("# v3d_perfmon_monitor dev=%s interval_ms=%d counters=%u groups=%u "
           "(each counter sampled once every %u windows)\n",
           dev, interval_ms, nids, ngroups, ngroups);
    printf("# columns: wall_epoch elapsed_s window group counter_id counter_name value(delta over window)\n");
    fflush(stdout);

    double t_start = now_mono();
    unsigned window = 0;

    while (!stop_flag) {
        for (unsigned g = 0; g < ngroups && !stop_flag; g++, window++) {
            unsigned base = g * MAXP;
            unsigned n = nids - base < MAXP ? nids - base : MAXP;

            struct drm_v3d_perfmon_create cr;
            memset(&cr, 0, sizeof cr);
            cr.ncounters = n;
            for (unsigned i = 0; i < n; i++)
                cr.counters[i] = ids[base + i];
            if (ioctl(fd, DRM_IOCTL_V3D_PERFMON_CREATE, &cr) < 0) {
                fprintf(stderr, "# PERFMON_CREATE failed: %s\n", strerror(errno));
                sleep_ms(interval_ms);
                continue;
            }

            struct drm_v3d_perfmon_set_global sg;
            memset(&sg, 0, sizeof sg);
            sg.id = cr.id;
            if (ioctl(fd, DRM_IOCTL_V3D_PERFMON_SET_GLOBAL, &sg) < 0) {
                fprintf(stderr, "# PERFMON_SET_GLOBAL failed: %s\n", strerror(errno));
                struct drm_v3d_perfmon_destroy d = { .id = cr.id };
                ioctl(fd, DRM_IOCTL_V3D_PERFMON_DESTROY, &d);
                sleep_ms(interval_ms);
                continue;
            }

            sleep_ms(interval_ms);

            uint64_t vals[MAXP];
            memset(vals, 0, sizeof vals);
            struct drm_v3d_perfmon_get_values gv;
            memset(&gv, 0, sizeof gv);
            gv.id = cr.id;
            gv.values_ptr = (uintptr_t)vals;
            int rc = ioctl(fd, DRM_IOCTL_V3D_PERFMON_GET_VALUES, &gv);
            int gerr = errno;

            sg.flags = DRM_V3D_PERFMON_CLEAR_GLOBAL;
            ioctl(fd, DRM_IOCTL_V3D_PERFMON_SET_GLOBAL, &sg);
            struct drm_v3d_perfmon_destroy d = { .id = cr.id };
            ioctl(fd, DRM_IOCTL_V3D_PERFMON_DESTROY, &d);

            if (rc < 0) {
                fprintf(stderr, "# PERFMON_GET_VALUES failed: %s\n", strerror(gerr));
                continue;
            }

            double w = now_wall(), el = now_mono() - t_start;
            for (unsigned i = 0; i < n; i++)
                printf("%.3f %.3f %u %u %u %s %llu\n", w, el, window, g,
                       ids[base + i], names[ids[base + i]],
                       (unsigned long long)vals[i]);
            fflush(stdout);
        }
    }

    close(fd);
    return 0;
}
