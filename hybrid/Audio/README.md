# Audio (RAAGA / AIO / I2S) Contention Subsystem

## Hardware Engine
- **Hardware Block:** RP1 Audio subsystems (RAAGA / AIO, PDM microphone input, 3 × I2S controllers) and BCM2712 HDMI Audio DMA.
- **Function:** High-resolution digital audio streaming, PCM serialization, and periodic DMA ring-buffer pacing.
- **Interconnect:** Dedicated audio DMA engines on RP1 and BCM2712 with tight low-latency timing requirements.

## Benchmark / Stress Tool
- **`audio_stress.sh` / `audio_workload.py`**: Multi-channel 192 kHz 32-bit periodic DMA ring buffer streaming loop.
- **Contention Mechanism:** High-frequency timer interrupts and constant low-granularity memory transfers competing for bus arbitration cycles.

## Usage
```bash
./audio_stress.sh [duration_sec]
```
