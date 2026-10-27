import numpy as np
import time

def run_cache_thrash(size_mb=8, stride=4096, duration_sec=15):
    print(f"Running cache-thrashing stress test ({size_mb}MB buffer)...")
    element_count = (size_mb * 1024 * 1024) // 4
    data = np.random.rand(element_count).astype(np.float32)

    end_time = time.time() + duration_sec
    while time.time() < end_time:
        for i in range(0, element_count, stride):
            data[i] = data[i] * 1.00001
    print("Cache-thrash stress test finished.")

if __name__ == "__main__":
    run_cache_thrash()