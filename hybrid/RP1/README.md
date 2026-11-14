# RP1 AXI Interconnect & Co-processor Contention Subsystem

## Hardware Engine
- **Hardware Block:** Raspberry Pi RP1 I/O Controller Southbridge (`0002:01:00.0`).
- **Architecture:** 128-bit internal AXI bus fabric, burst length up to 16 beats, 64 KB shared SRAM, dual Cortex-M3 co-processors, hardware QoS arbiter.
- **Function:** Manages external peripherals (Ethernet, USB, GPIO, I2C, SPI, UART, PWM, CSI, DSI, Audio).

## Benchmark / Stress Tool
- **`rp1_stress.sh` / `rp1_workload.py`**: Multi-threaded AXI crossbar and shared SRAM arbitration contention test.
- **Contention Mechanism:** Concurrent burst transactions competing for the 128-bit RP1 internal data bus and SRAM access cycles, exercising QoS priority reordering.

## Usage
```bash
./rp1_stress.sh [duration_sec] [threads]
```
