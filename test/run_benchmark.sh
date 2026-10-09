#!/bin/bash

# Ensure binary exists
if [ ! -f "../build/meminterf" ]; then
    echo "meminterf not found. Building..."
    cd .. && make && cd test
fi

echo "=== Baseline Profiling (No CPU Interference) ==="
../src/profiler.sh 5 > baseline_metrics.csv
cat baseline_metrics.csv
echo ""

echo "=== Interference Profiling (CPU Memory Stress) ==="
# Run memory interferer in the background
../build/meminterf 5 &
INTERFERER_PID=$!

../src/profiler.sh 5 > interference_metrics.csv
cat interference_metrics.csv

wait $INTERFERER_PID
echo ""
echo "Benchmarking complete. Results saved to baseline_metrics.csv and interference_metrics.csv."

