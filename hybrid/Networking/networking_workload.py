#!/usr/bin/env python3
"""
hybrid/Networking/networking_workload.py
Targets: Ethernet / Network stack, SKB socket buffer DMA, PCIe network packet traffic.
"""

import sys
import os
import time
import socket
import threading
import argparse

def udp_sink(port, stop_event):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", port))
    sock.settimeout(0.5)
    while not stop_event.is_set():
        try:
            sock.recv(65536)
        except socket.timeout:
            continue
        except Exception:
            break
    sock.close()

def stress_network(duration=30, port=19876, threads=2):
    print(f"[Networking] Launching socket traffic generator on 127.0.0.1:{port} (threads={threads})...")
    stop_event = threading.Event()
    sink_thread = threading.Thread(target=udp_sink, args=(port, stop_event), daemon=True)
    sink_thread.start()

    payload = b"X" * 32768
    total_bytes = [0] * threads

    def sender(idx):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        local_bytes = 0
        while not stop_event.is_set():
            try:
                sock.sendto(payload, ("127.0.0.1", port))
                local_bytes += len(payload)
            except Exception:
                pass
        sock.close()
        total_bytes[idx] = local_bytes

    senders = [threading.Thread(target=sender, args=(i,), daemon=True) for i in range(threads)]
    for s in senders:
        s.start()

    time.sleep(duration)
    stop_event.set()
    for s in senders:
        s.join()
    sink_thread.join()

    total = sum(total_bytes)
    mb_s = (total / (1024 * 1024)) / duration
    print(f"[Networking] Transferred {total / (1024*1024):.1f} MB in {duration}s ({mb_s:.2f} MB/s packet throughput)")

def main():
    parser = argparse.ArgumentParser(description="Network DMA & Socket Stressor")
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    print(f"=== Networking / Packet DMA Stressor (Duration: {args.duration}s) ===")
    stress_network(args.duration, threads=args.threads)

if __name__ == "__main__":
    main()
