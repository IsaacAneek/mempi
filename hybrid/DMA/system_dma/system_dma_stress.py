#!/usr/bin/env python3
"""
hybrid/DMA/system_dma/system_dma_stress.py
Targets: BCM2712 System DMA subsystem & Linux DMA-buf Heap (/dev/dma_heap/system).
"""

import sys
import os
import time
import fcntl
import struct
import mmap
import argparse

DMA_HEAP_IOCTL_ALLOC = 0xc0184800
# struct dma_buf_sync { __u64 flags; }
DMA_BUF_SYNC_READ = 1
DMA_BUF_SYNC_WRITE = 2
DMA_BUF_SYNC_START = 0
DMA_BUF_SYNC_END = 4
DMA_BUF_IOCTL_SYNC = 0x40086200

def stress_system_dma(duration=30, buffer_mb=16):
    heap_dev = "/dev/dma_heap/system"
    print(f"[System DMA] Opening {heap_dev} and allocating {buffer_mb} MB DMA-buf...")
    try:
        fd_heap = os.open(heap_dev, os.O_RDWR)
    except Exception as e:
        print(f"[System DMA] Cannot open heap device: {e}")
        return

    buf_len = buffer_mb * 1024 * 1024
    alloc_req = struct.pack('QIIQ', buf_len, 0, os.O_RDWR | os.O_CLOEXEC, 0)

    try:
        ret = fcntl.ioctl(fd_heap, DMA_HEAP_IOCTL_ALLOC, alloc_req)
        alloc_len, buf_fd, _, _ = struct.unpack('QIIQ', ret)
        print(f"[System DMA] Allocated DMA buffer: fd={buf_fd}, size={alloc_len / (1024*1024):.1f} MB")

        # Memory map the DMA-buf
        mem = mmap.mmap(buf_fd, alloc_len, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        sync_start = struct.pack('Q', DMA_BUF_SYNC_START | DMA_BUF_SYNC_WRITE)
        sync_end = struct.pack('Q', DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE)

        start = time.time()
        cycles = 0

        while time.time() - start < duration:
            # Trigger hardware DMA cache synchronization ioctls
            try:
                fcntl.ioctl(buf_fd, DMA_BUF_IOCTL_SYNC, sync_start)
            except Exception:
                pass

            # Write buffer pattern
            mem[:4096] = b"D" * 4096

            try:
                fcntl.ioctl(buf_fd, DMA_BUF_IOCTL_SYNC, sync_end)
            except Exception:
                pass

            cycles += 1
            if cycles % 1000 == 0:
                time.sleep(0.001)

        mem.close()
        os.close(buf_fd)
        elapsed = time.time() - start
        print(f"[System DMA] Completed {cycles} DMA cache-sync cycles in {elapsed:.2f}s ({cycles/elapsed:.1f} syncs/sec)")
    finally:
        os.close(fd_heap)

def main():
    parser = argparse.ArgumentParser(description="BCM2712 System DMA Stressor")
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--size-mb", type=int, default=16)
    args = parser.parse_args()

    print(f"=== System DMA Stressor (Duration: {args.duration}s, Size: {args.size_mb}MB) ===")
    stress_system_dma(args.duration, args.size_mb)

if __name__ == "__main__":
    main()
