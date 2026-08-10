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

### adapter 및 decode 수정
```
현재

DPU
int8 NHWC 255
   ↓
adapter
255채널 전체 float32
   ↓
reshape/transpose
   ↓
전체 contiguous copy
   ↓
decoder에서 필요한 4개 class 선택
```
```
개선

DPU
int8 NHWC 255
   ↓
adapter
reshape/transpose만 수행
INT8 그대로 유지
   ↓
decoder
x/y/w/h/conf + 필요한 class만 선택
   ↓
선택한 값만 float32/dequant
```

| 단계              |           이전 |          현재 |           변화 |
| --------------- | -----------: | ----------: | -----------: |
| Capture         |      8.31 ms |     8.00 ms |        거의 동일 |
| Crop+Resize     |      5.20 ms |     5.15 ms |        거의 동일 |
| Quantize        |     20.57 ms |    27.40 ms |           증가 |
| DPU             |     17.46 ms |    17.53 ms |           동일 |
| **Adapt heads** | **28.56 ms** | **0.11 ms** |   **거의 제거됨** |
| Decode+NMS      |     38.24 ms |    35.22 ms |        소폭 감소 |
| Postprocess 전체  |     66.88 ms |    35.38 ms | **약 47% 감소** |
| Total           |    118.42 ms |    93.45 ms | **약 21% 감소** |
| FPS             |        약 8.5 |   **10.67** | **약 25% 증가** |

### 더이상 최적화하기 힘들어서 디코드 부분을 파이썬에서 c++로 변경

| 단계               |   Python 후처리 |      C++ 후처리 |
| ---------------- | -----------: | -----------: |
| Crop+Resize      |      5.14 ms |      5.04 ms |
| Quantize         |     21.24 ms |     21.09 ms |
| DPU              |     17.53 ms |     17.56 ms |
| **Decode + NMS** | **32.93 ms** |  **9.10 ms** |
| Flags/State      |    약 0.04 ms |      0.05 ms |
| **Total**        | **85.19 ms** | **67.79 ms** |
| **FPS**          |    **11.71** |    **14.71** |

