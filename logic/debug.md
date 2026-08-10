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

### decode_yolov5n.py를 우리가 사용하는 클래스만 하도록 수정

| 항목               |         최적화 전 |        최적화 후 |             개선 |
| ---------------- | ------------: | -----------: | -------------: |
| Adapt heads      |      28.05 ms |     28.56 ms |          거의 동일 |
| **Decode + NMS** | **174.82 ms** | **38.24 ms** | **약 4.6배 빨라짐** |
| Postprocess 전체   |     202.94 ms |     66.88 ms |   **약 3배 빨라짐** |
| 전체 frame latency |     257.25 ms |    118.42 ms |   **약 54% 감소** |
| FPS              |      3.86 FPS |    약 8.5 FPS |  **약 2.2배 증가** |
