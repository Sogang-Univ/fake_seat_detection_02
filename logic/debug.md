| 단계               |         평균 시간 |
| ---------------- | ------------: |
| Capture          |      11.25 ms |
| Crop+Resize      |       5.24 ms |
| Quantize         |      20.34 ms |
| DPU              |      17.48 ms |
| Adapt heads      |      28.05 ms |
| **Decode + NMS** | **174.82 ms** |
| Flags            |       0.02 ms |
| State machine    |       0.04 ms |
| 전체               |     257.25 ms |
| 실제 FPS           |      3.86 FPS |
