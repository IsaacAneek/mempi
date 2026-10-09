#!/bin/bash

# Ensure binaries exist
if [ ! -f "../build/meminterf" ] || [ ! -f "../build/gpu_task" ]; then
    echo "Binaries not found. Building..."
    cd .. && make && cd test
fi

echo "=================================================="
echo "    ISOLATED RUN (GPU ONLY)                       "
echo "=================================================="
../build/gpu_task
echo ""

echo "=================================================="
echo "    INTERFERENCE RUN (GPU + CPU MEMORY STRESS)    "
echo "=================================================="
echo "Starting CPU memory stressors in background (Saturating 3 CPU Cores)..."
# We spawn 3 instances of the interferer to fully saturate the Pi 5's LPDDR4X bandwidth
../build/meminterf 20 > /dev/null &
PID1=$!
../build/meminterf 20 > /dev/null &
PID2=$!
../build/meminterf 20 > /dev/null &
PID3=$!

# Give the interferers a moment to spin up to full bandwidth
sleep 1

# Run the GPU task again, while CPU is saturating memory
../build/gpu_task

# Stop the interferers
kill $PID1 $PID2 $PID3 2>/dev/null
wait $PID1 $PID2 $PID3 2>/dev/null

echo ""
echo "Done! Compare the 'Total GPU time' between the two runs."
echo "If memory interference is happening, the second run will take noticeably longer."
