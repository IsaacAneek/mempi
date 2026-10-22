import time
import math

def run_task():
    start = time.time()
    val = 0.0
    for i in range(3000000):
        val += math.tan(i) * math.cosh(i % 10)
    end = time.time()
    latency = (end - start) * 1000
    print(f"End-to-end latency: {latency:.2f} ms")
    return latency

if __name__ == "__main__":
    run_task()
