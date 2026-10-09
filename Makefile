CC=gcc
CFLAGS=-Wall -O2

all: build/meminterf build/gpu_task

build/meminterf: src/meminterf.c
	mkdir -p build
	$(CC) $(CFLAGS) -o build/meminterf src/meminterf.c

build/gpu_task: src/gpu_task.c
	mkdir -p build
	$(CC) $(CFLAGS) -o build/gpu_task src/gpu_task.c -lEGL -lGLESv2

clean:
	rm -rf build/*

