#!/bin/bash

DURATION=${1:-10}
INTERVAL=1

echo "Profiling for $DURATION seconds..."
echo "Time, CPU_Load(%), Free_Mem(MB), CPU_Temp(C), GPU_Freq(MHz), GPU_Mem(MB)"

for ((i=0; i<$DURATION; i+=$INTERVAL)); do
    # Time
    NOW=$(date "+%H:%M:%S")
    
    # CPU Load
    # We use top in batch mode to get the idle percentage and subtract from 100
    CPU_IDLE=$(top -b -n 1 | grep "%Cpu(s)" | awk -F',' '{print $4}' | awk '{print $1}')
    if [ -z "$CPU_IDLE" ]; then CPU_IDLE=0; fi
    CPU_LOAD=$(echo "100 - $CPU_IDLE" | bc 2>/dev/null || echo "N/A")
    
    # Memory
    FREE_MEM=$(free -m | grep Mem | awk '{print $4}')
    
    # Temperature
    if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
        TEMP_RAW=$(cat /sys/class/thermal/thermal_zone0/temp)
        TEMP=$(echo "scale=1; $TEMP_RAW / 1000" | bc)
    else
        TEMP="N/A"
    fi
    
    # GPU Freq
    if command -v vcgencmd &> /dev/null; then
        GPU_FREQ_RAW=$(vcgencmd measure_clock v3d | awk -F= '{print $2}')
        GPU_FREQ=$(echo "$GPU_FREQ_RAW / 1000000" | bc)
        
        # GPU Mem
        GPU_MEM_RAW=$(vcgencmd get_mem gpu | awk -F= '{print $2}' | tr -d 'M')
        GPU_MEM=$GPU_MEM_RAW
    else
        GPU_FREQ="N/A"
        GPU_MEM="N/A"
    fi
    
    echo "$NOW, $CPU_LOAD, $FREE_MEM, $TEMP, $GPU_FREQ, $GPU_MEM"
    sleep $INTERVAL
done

