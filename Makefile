CC=gcc
CFLAGS=-Wall -O2

all: build/meminterf

build/meminterf: src/meminterf.c
	mkdir -p build
	$(CC) $(CFLAGS) -o build/meminterf src/meminterf.c

clean:
	rm -rf build/*

