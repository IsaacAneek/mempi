#!/bin/bash

# Ensure binary exists
if [ ! -f "../build/meminterf" ]; then
    echo "meminterf not found. Building..."
    cd .. && make && cd test
fi

echo "Checking for vkcube..."
if ! command -v vkcube &> /dev/null; then
    echo "Warning: 'vkcube' could not be found."
    echo "To test deliberate CPU-GPU interference with a real GPU workload, please install it:"
    echo "  sudo apt install vulkan-tools"
    echo "Falling back to CPU-only interference run..."
    ./run_benchmark.sh
    exit 0
fi

echo "=== GPU Workload with NO CPU Interference ==="
echo "Launching vkcube in the background..."
# We launch vkcube to stress the GPU. We redirect output to null.
vkcube > /dev/null 2>&1 &
VKCUBE_PID=$!

../src/profiler.sh 5 > gpu_only_metrics.csv
cat gpu_only_metrics.csv
echo ""

echo "=== GPU Workload WITH CPU Memory Interference ==="
echo "Launching CPU memory interferer..."
../build/meminterf 5 > /dev/null 2>&1 &
INTERFERER_PID=$!

../src/profiler.sh 5 > cpu_gpu_interference_metrics.csv
cat cpu_gpu_interference_metrics.csv
echo ""

# Clean up
kill $VKCUBE_PID 2>/dev/null
wait $INTERFERER_PID 2>/dev/null

echo "Benchmarking complete. Results saved to gpu_only_metrics.csv and cpu_gpu_interference_metrics.csv."

