# DPU 기반 YOLO 추론 모듈

> PYNQ-DPU 환경에서 INT8 양자화된 YOLOv5 모델을 실행하고, 출력 Feature Map을 후처리하여 객체 탐지 결과를 생성한다.

## 개요

추론 모듈은 ROI Crop 및 Resize가 완료된 입력 데이터를 받아 DPU에서 YOLO 추론을 수행한다. 추론 결과는 역양자화와 YOLO 후처리를 거쳐 Bounding Box 및 객체 정보로 변환된다.

## 데이터 흐름

```mermaid
flowchart LR
    A[ROI Crop 결과<br/>640×640 NPY] --> B[INT8] [Quantize & Compile]
    B --> C[DPU Overlay]
    C --> D[YOLOv5 추론]
    D --> E[Output Dequantization]
    E --> F[YOLO Decode]
    F --> G[NMS]
    G --> H[객체 탐지 결과]
```

## 모듈 구성

| 구성 요소 | 역할 |
|-----------|------|
| `DpuOverlay` | FPGA Overlay 및 DPU 초기화 |
| `load_model()` | 컴파일된 `.xmodel` 로드 |
| `execute_async()` | DPU 추론 실행 |
| `decode_yolo_output()` | YOLO 출력 Feature Map 해석 |
| `nms()` | 중복 Bounding Box 제거 |
| `build_results()` | 최종 탐지 결과 생성 |

## 주요 변수

| 변수 | 설명 |
|------|------|
| `XMODEL_PATH` | 컴파일된 YOLOv5 xmodel |
| `BIT_PATH` | DPU Overlay(bitstream) |
| `CONF_THRESHOLD` | Confidence Threshold |
| `IOU_THRESHOLD` | NMS IoU Threshold |
| `CLASS_NAMES` | COCO 클래스 |
| `INTERESTED_CLASSES` | 후처리 대상 객체 클래스 |

## 동작 과정

1. FPGA Overlay 및 DPU Runner 초기화
2. 입력 영상을 INT8 형식으로 변환
3. `execute_async()`를 이용한 DPU 추론
4. Output Tensor 역양자화
5. YOLO Decode 수행
6. Confidence Filtering 및 NMS
7. 객체 탐지 결과 생성

---

# 현재 이슈

현재 추론 파이프라인은 구현되었으나, DPU 추론 결과가 정상적으로 생성되지 않는 문제를 확인하였다.

### 증상

- 입력 데이터와 관계없이 DPU 출력이 항상 동일한 값으로 고정됨
- 다양한 입력(실영상, 단색 영상, 무작위 노이즈)에서도 동일한 출력 발생

### 원인 분석 과정

초기에는 하드웨어 및 메모리 문제를 의심하여 다음 항목을 확인하였다.

- DMA 버퍼 및 Cache Flush/Invalidate 검증
- Device Tree 및 DPU Driver 설정 확인
- 입력 데이터 및 메모리 전달 방식 검증

이후 동일한 DPU 환경에서 다른 모델이 정상 동작하는 것을 확인하여, 시스템 문제가 아닌 **컴파일된 `xmodel` 자체의 문제**로 분석하였다.

현재는 양자화(PTQ) 과정에서 생성된 `xmodel`의 이상 여부를 가장 유력한 원인으로 판단하고 있다.

---

# 개선 방향

현재는 양자화 파이프라인을 중심으로 다음 사항을 검증하고 있다.

- Calibration(양자화 보정 과정) 입력 데이터의 정규화 과정 재검토
- Calibration 데이터 수 증가 및 통계 안정화
- 새로운 xmodel 생성 후 DPU 재검증
- 필요 시 Layer Dump를 이용한 레이어별 출력 분석
