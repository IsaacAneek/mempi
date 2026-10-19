/*
 * v3d_counters: list all V3D performance counters exposed by the kernel.
 * (Your reference program, unchanged in behaviour.)
 */
#include <stdio.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <errno.h>
#include <string.h>
#include <drm/v3d_drm.h>

static int get_param(int fd, unsigned int param, uint64_t *value)
{
    struct drm_v3d_get_param p = {
        .param = param,
        .pad = 0,
        .value = 0
    };

    if (ioctl(fd, DRM_IOCTL_V3D_GET_PARAM, &p) < 0)
        return -1;

    *value = p.value;
    return 0;
}

int main(void)
{
    int fd = open("/dev/dri/renderD128", O_RDWR);
    if (fd < 0) {
        fprintf(stderr, "Cannot open renderD128: %s\n", strerror(errno));
        return 1;
    }

    uint64_t supported = 0;
    uint64_t max_counters = 0;

    if (get_param(fd, DRM_V3D_PARAM_SUPPORTS_PERFMON, &supported) < 0) {
        fprintf(stderr, "SUPPORTS_PERFMON query failed: %s\n", strerror(errno));
        close(fd);
        return 1;
    }

    if (get_param(fd, DRM_V3D_PARAM_MAX_PERF_COUNTERS, &max_counters) < 0) {
        fprintf(stderr, "MAX_PERF_COUNTERS query failed: %s\n", strerror(errno));
        close(fd);
        return 1;
    }

    printf("Hardware performance monitoring: %s\n",
           supported ? "supported" : "not supported");
    printf("Maximum counter IDs: %llu\n", (unsigned long long)max_counters);

    if (!supported || max_counters == 0) {
        close(fd);
        return 0;
    }

    for (uint64_t i = 0; i < max_counters; i++) {
        struct drm_v3d_perfmon_get_counter c = {0};
        c.counter = (uint8_t)i;

        if (ioctl(fd, DRM_IOCTL_V3D_PERFMON_GET_COUNTER, &c) < 0) {
            fprintf(stderr, "Counter %llu query failed: %s\n",
                    (unsigned long long)i, strerror(errno));
            continue;
        }

        printf("\nID: %llu\n", (unsigned long long)i);
        printf("  Name:        %.64s\n", c.name);
        printf("  Category:    %.32s\n", c.category);
        printf("  Description: %.256s\n", c.description);
    }

    close(fd);
    return 0;
}
