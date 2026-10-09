#!/bin/bash

echo "=================================================="
echo "    Raspberry Pi 5 Local Execution Pipeline       "
echo "=================================================="

# Check if we are actually on a Raspberry Pi or an ARM device
if [ "$(uname -m)" != "aarch64" ] && [ "$(uname -m)" != "armv7l" ]; then
    echo "Warning: You do not appear to be running on an ARM-based Raspberry Pi."
    echo "This benchmark uses EGL/GLES and Broadcom specific drivers which may fail on this host."
    read -p "Press Enter to continue anyway, or Ctrl+C to abort..."
fi

# Ensure dependencies are installed
echo "Checking dependencies..."
if ! dpkg -l | grep -q libegl1-mesa-dev; then
    echo "Installing required EGL/GLES development headers..."
    sudo apt-get update && sudo apt-get install -y libegl1-mesa-dev libgles2-mesa-dev
else
    echo "Dependencies are already installed."
fi

# Build the binaries
echo ""
echo "Compiling project binaries..."
make

if [ $? -ne 0 ]; then
    echo "Compilation failed! Aborting."
    exit 1
fi

# Run the benchmark
echo ""
echo "Starting the Memory Interference Benchmark Suite..."
cd test
./run_cpu_gpu_interference.sh

echo "Pipeline complete."

