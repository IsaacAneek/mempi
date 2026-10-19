CC=gcc
CFLAGS=-Wall -O2

all: build/meminterf build/gpu_task build/cpu_spinner build/v3d_perfmon_monitor build/v3d_counters

build/meminterf: src/meminterf.c
	mkdir -p build
	$(CC) $(CFLAGS) -o build/meminterf src/meminterf.c

build/gpu_task: src/gpu_task.c
	mkdir -p build
	$(CC) $(CFLAGS) -o build/gpu_task src/gpu_task.c -lEGL -lGLESv2

build/cpu_spinner: src/cpu_spinner.c
	mkdir -p build
	$(CC) $(CFLAGS) -o build/cpu_spinner src/cpu_spinner.c

build/v3d_perfmon_monitor: src/v3d_perfmon_monitor.c
	mkdir -p build
	$(CC) $(CFLAGS) -o build/v3d_perfmon_monitor src/v3d_perfmon_monitor.c

build/v3d_counters: src/v3d_counters.c
	mkdir -p build
	$(CC) $(CFLAGS) -o build/v3d_counters src/v3d_counters.c

clean:
	rm -rf build/*
