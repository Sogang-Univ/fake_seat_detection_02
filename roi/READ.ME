# Seat Occupancy Detection on AMD Kria KV260

FPGA(KV260) 기반 실시간 좌석 점유 감지 시스템. 영상 입력부터 ROI 크롭/리사이즈(PL, HLS IP), YOLOv5n 추론(PL, DPU), 점유 판정(PS, Python)까지 이어지는 하이브리드 PL/PS 파이프라인입니다.

> 본 저장소는 파이프라인 전체(입력 → ROI 크롭/리사이즈 → DPU 추론 → 점유 판정)의 통합과 크롭/리사이즈 HLS IP 개발을 다룹니다.

---

## 1. 개요

- **목표**: 카메라(또는 녹화 영상)로 촬영된 좌석 1개 영역의 점유 여부를 실시간으로 판정
- **개발 기간**: 3주 학사 프로젝트
- **팀 구성**: 5인 팀 (모델 학습, ROI/판정 로직, 배포, 성능 측정, 문서화로 역할 분담)
- **본인 담당**: ROI 크롭/리사이즈 HLS IP 개발, 파이프라인 통합, 점유 판정 로직

### 용어 정리

| 용어 | 의미 |
|---|---|
| **Internal (PL)** | Kria KV260의 FPGA Fabric(Programmable Logic). HLS로 합성한 커스텀 IP, DPU가 위치 |
| **External (PS)** | ARM Cortex-A53 기반 Processing System. PYNQ/Python 실행 환경 |

PL과 PS는 별도 컴퓨터가 아니라 **하나의 SoC 안에서 AXI 버스로 연결된 두 도메인**입니다.

---

## 2. 시스템 아키텍처

```
[영상 입력]
     │
     ▼
[ROI 크롭 + Bilinear 리사이즈 + 레터박스 패딩]   ← PL, 커스텀 HLS IP (crop_and_resize)
     │  (AXI4-Master, DDR ↔ DDR)
     ▼
[YOLOv5n 추론]                                    ← PL, DPU (별도 오버레이)
     │
     ▼
[점유 판정 로직 (좌석 영역 겹침 비율 기반)]        ← PS, Python (PYNQ)
     │
     ▼
[점유 / 비점유 출력]
```

### 2.1 크롭+리사이즈 IP (`crop_and_resize`)

- 원본 프레임에서 ROI(좌석 영역)를 잘라내고, YOLO 입력 크기(예: 640×640)로 **bilinear 보간 리사이즈 + 레터박스 패딩**까지 PL에서 한 번에 처리
- 초기 설계는 "PL=크롭만, PS=리사이즈"였으나, PS 연산 부하와 AXI 트래픽을 줄이기 위해 **리사이즈까지 PL로 통합**하는 방향으로 변경 (자세한 배경은 [6. 설계 결정 및 개선 과정](#6-설계-결정-및-개선-과정) 참고)

### 2.2 DPU (YOLOv5n 추론)

- 크롭 IP와 **동일한 비트스트림에 통합하지 않고, 별도의 DPU-PYNQ 오버레이(.bit/.hwh)를 순차 로드하여 사용**
- 구성: **DPU B3136** (KV260 공식 검증 구성, 추천 근거는 [6.3](#63-dpu-구성-b4096-→-b3136) 참고)
- 모델: **YOLOv5n** (Xilinx Model Zoo 기반 xmodel)
- DPU 관련 코드/오버레이는 별도 저장소(AMD/Xilinx 공식 Kria-PYNQ DPU 예제)를 그대로 받아서 사용

### 2.3 점유 판정 로직

- 좌석은 **1개로 고정**
- DPU가 반환한 사람 바운딩박스와 **미리 정의한 좌석 영역(ROI)의 겹침 비율(overlap ratio)**을 계산
- 겹침 비율이 임계값 이상이면 "점유", 미만이면 "비점유"로 판정
- (임계값 및 세부 수식은 팀 내 로직 담당과 협의된 값을 문서화 예정 — TBD)

---

## 3. 저장소 구조

```
.
├── hls/
│   ├── crop_resize.cpp        # crop_and_resize 커널 구현
│   ├── crop_resize.hpp        # 타입/상수 정의, 함수 선언
│   ├── crop_resize_tb.cpp     # C 시뮬레이션 / cosim 테스트벤치
│   └── run_hls.tcl            # Vitis HLS 배치 빌드 스크립트
├── vivado/
│   ├── design_1_wrapper33.v   # Block Design 최상위 wrapper (자동 생성)
│   └── (block design tcl / 스크린샷 등)
├── pynq/
│   ├── design_1_wrapper33.bit
│   ├── design_1_wrapper33.hwh
│   └── occupancy_demo.ipynb   # 실행 노트북 (예정)
├── models/
│   └── yolov5n.xmodel         # (DPU 오버레이 저장소에서 별도 확보)
└── README.md
```

---

## 4. 요구 환경

| 항목 | 버전/사양 |
|---|---|
| HLS 툴 | Vitis HLS 2022.2 (Tool Version Limit 2019.12) |
| 구현 툴 | Vivado 2022.2 |
| 보드 | AMD Kria KV260 (`xck26-sfvc784-2LV-c`) |
| PL 클럭 | 100MHz (10ns period) |
| 런타임 | PYNQ (Linux, VART 필요) |
| DPU 구성 | B3136 (권장, [6.3](#63-dpu-구성-b4096-→-b3136) 참고) |
| 검출 모델 | YOLOv5n (Vitis AI Model Zoo) |

---

## 5. 빌드 방법

### 5.1 HLS IP 빌드

`run_hls.tcl`은 csim / synth / cosim / export 단계를 인자로 선택 실행할 수 있습니다.

```bash
cd hls
vitis_hls -f run_hls.tcl -tclargs csim     # C 시뮬레이션만
vitis_hls -f run_hls.tcl -tclargs synth    # C 합성만
vitis_hls -f run_hls.tcl -tclargs cosim    # RTL 코시뮬레이션까지
vitis_hls -f run_hls.tcl -tclargs export   # IP 카탈로그 export까지
vitis_hls -f run_hls.tcl                   # 인자 없으면 all(전체 단계) 실행
```

- Top function: `crop_and_resize`
- 대상 파트: `xck26-sfvc784-2LV-c`
- `export_design -format ip_catalog`로 Vivado IP Catalog용 IP 생성

### 5.2 Vivado Block Design

1. Vivado에서 새 프로젝트 생성 (Part: `xck26-sfvc784-2LV-c`)
2. 위에서 export한 `crop_and_resize` IP를 IP Repository로 등록
3. Block Design 구성:
   - `zynq_ultra_ps_e_0` (PS)
   - `crop_and_resize_0` (크롭+리사이즈 IP)
     - `m_axi_gmem0` (읽기 전용, 소스 이미지) → HP 포트 1
     - `m_axi_gmem1` (쓰기 전용, 출력 이미지) → HP 포트 2 (서로 다른 HP 포트로 분리하여 동시 R/W)
   - Clocking Wizard, Reset 관리 IP, SmartConnect, AXI Interconnect 등
4. `Generate Bitstream` → `design_1_wrapper33.bit` / `.hwh` 생성
5. `.bit`, `.hwh`를 동일 파일명으로 `pynq/` 폴더에 위치

### 5.3 레지스터 맵 (참고용)

`crop_and_resize`는 `s_axilite` 인터페이스로 아래 레지스터를 노출합니다 (`xcrop_and_resize_hw.h` 참고).

| Offset | 필드 | 설명 |
|---|---|---|
| 0x00 | `CTRL` | ap_start / ap_done / ap_idle / ap_ready |
| 0x10, 0x14 | `src` | 소스 이미지 버퍼 물리주소 (64bit) |
| 0x1c, 0x20 | `dst` | 출력 이미지 버퍼 물리주소 (64bit) |
| 0x28 | `src_w` | 소스 이미지 너비 |
| 0x30 | `src_h` | 소스 이미지 높이 |
| 0x38 | `x0` | ROI 시작 x좌표 |
| 0x40 | `y0` | ROI 시작 y좌표 |
| 0x48 | `roi_w` | ROI 너비 |
| 0x50 | `roi_h` | ROI 높이 |
| 0x58 | `dst_size` | 출력 정사각형 크기 (예: 640) |

---

## 6. 설계 결정 및 개선 과정

### 6.1 파이프라인 구조 변경

| 항목 | 초기 설계 | 변경 후 | 이유 |
|---|---|---|---|
| 리사이즈 처리 위치 | PS(Python/OpenCV)에서 처리 | PL(HLS)로 통합 (`crop_and_resize`) | PS 연산 부하 감소, AXI 트래픽 절감, 파이프라인 지연시간 단축 |
| 크롭-DPU 결합 방식 | (미정) | 하나의 비트스트림으로 통합하지 않고, **별도 오버레이 순차 로드**로 분리 | KV260 PL 자원 제약, DPU와 커스텀 IP 동시 구현 시 자원/타이밍 리스크 회피 |
| 인터커넥트 | AXI4-Stream 후보 | **AXI4-Master (DDR↔DDR)** 채택 | 실시간 스트리밍이 아닌 녹화 영상 기반 데모이므로 프레임 단위 랜덤 액세스가 더 적합 |
| DMA 포트 | 단일 HP 포트 | `gmem0`/`gmem1`을 **서로 다른 HP 포트로 분리** | 읽기(src)/쓰기(dst) 동시 처리로 처리량 향상 |

### 6.2 HLS 커널 최적화 (`crop_resize.cpp`)

| 항목 | 초기 설계 | 변경 후 | 이유 |
|---|---|---|---|
| 라인버퍼 단위 | `pixel_t`(32bit) 단위 접근 | `word_t`(128bit) 단위 접근 (`get_pix()`로 픽셀 추출) | `II=1` 파이프라이닝 확보, BRAM 포트 충돌 방지 |
| 라인버퍼 저장소 | 미지정 | `RAM_2P` (BRAM) 명시 | 한 사이클에 2픽셀 동시 읽기 가능 |
| 출력 버스트 | 가변 크기 memcpy | `DST_SIZE` 상수로 고정 | HLS가 컴파일 타임에 burst 길이를 확정 → 파이프라이닝 이슈 해결 |
| 더블 버퍼링 | 없음 | `line0`/`line1` + `phase` 플래그로 핑퐁 버퍼링 | 다음 출력 row의 소스 row가 이전과 겹칠 때 재사용, DDR 접근 최소화 |
| 좌표 정렬 | 임의 x0 허용 | `x0_aligned = x0 & ~3`로 4의 배수 정렬 후 오프셋 보정 | 128bit(4픽셀) 버스 정렬 요구사항 충족 |

### 6.3 DPU 구성: B4096 → B3136

| 항목 | 검토 | 결론 |
|---|---|---|
| 자원 여유 | KV260은 ZCU104/102 대비 PL 자원 제약 | B3136이 AMD 공식 KV260 검증 구성 |
| 모델 크기 | YOLOv5n은 경량 모델 | B4096의 추가 처리량 이득이 크지 않음 |
| 개발 리스크 | 3주 일정, 커스텀 IP와 병행 개발 | 공식 검증된 구성을 택해 트러블슈팅 리스크 최소화 |

**→ B3136 + YOLOv5n 조합 채택**

### 6.4 개발 중 발견한 버그 및 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| Pragma가 적용되지 않음 | `#pragma HLS` 위치가 함수 시그니처 밖 | 함수 **바디 내부**로 이동 |
| csim/cosim 함수 못 찾음 | 커널 함수명(`roi_crop_wide`)과 테스트벤치 호출명(`roi_crop`) 불일치 | 함수명 통일 |
| 헤더 인식 안 됨 | `roi_crop.hpp`가 HLS 프로젝트 Includes에 미등록 | 프로젝트 Includes에 명시적으로 추가 |
| Cosim 데이터 불일치 | `m_axi depth`가 실제 배열 크기와 불일치 | 전체 프레임 픽셀 수가 아닌 **실제 접근 배열 크기**로 depth 수정 |
| Cosim 값 깨짐 | `uint32_t → ap_uint<128>` `reinterpret_cast` 사용 | cosim에서 unsafe하므로 비트 단위 조립 방식으로 변경 |
| tcl 인자 파싱 오류 | Vitis HLS 2022.2에서 `lindex $argv 0`가 `-f`를 잡음 | `lindex $argv end`로 변경 (`run_hls.tcl`에 반영됨) |

---

## 7. 실행 방법 (PYNQ)

```python
from pynq import Overlay, allocate
import numpy as np

# 1. 오버레이 로드 (.bit와 .hwh는 동일 파일명, 같은 폴더)
ol = Overlay("design_1_wrapper33.bit")
ip = ol.crop_and_resize_0

# 2. DDR 버퍼 할당 및 소스 이미지 packing (128bit = 4픽셀 단위)
src_buf = allocate(shape=(SIM_SRC_DEPTH,), dtype=np.uint32)  # word 단위 packing 필요
dst_buf = allocate(shape=(SIM_DST_DEPTH,), dtype=np.uint32)
# ... 이미지 데이터를 src_buf에 4픽셀씩 packing ...

# 3. 레지스터 설정 및 실행
ip.register_map.src = src_buf.physical_address
ip.register_map.dst = dst_buf.physical_address
ip.register_map.src_w, ip.register_map.src_h = 640, 480
ip.register_map.x0, ip.register_map.y0 = X0, Y0
ip.register_map.roi_w, ip.register_map.roi_h = ROI_W, ROI_H
ip.register_map.dst_size = 640
ip.register_map.CTRL.AP_START = 1
while not ip.register_map.CTRL.AP_DONE:
    pass

# 4. 결과(dst_buf)를 DPU 오버레이로 전달하여 YOLOv5n 추론
# 5. 추론 결과(bbox)와 좌석 ROI의 겹침 비율 계산 → 점유 판정
```

> 크롭+리사이즈 오버레이와 DPU 오버레이는 **동일 비트스트림이 아니므로**, 두 단계 사이에 오버레이 전환(재로드)이 필요합니다. 현재는 순차 실행 구조이며, 실시간성이 중요해질 경우 하나의 Block Design으로 통합하는 것을 검토할 수 있습니다.

---

## 8. 현재 상태 및 진행 중 이슈

- [x] HLS 커널(`crop_and_resize`) csim / csynth / cosim / export IP 완료
- [x] Vivado Block Design 구성 및 bitstream 생성 완료
- [x] KV260 보드에서 오버레이 로드 및 1차 실행 확인
- [ ] **[진행 중]** PYNQ에서 얻은 결과(`.npy`)를 `ffplay`로 재생 시 화면이 깨져서 출력되는 이슈 디버깅 중
  - 확인 후보: `ffplay` 실행 시 pixel format(`-pixel_format rgba`)/해상도 옵션 누락, 128bit word 언패킹 시 바이트 순서(endianness) 불일치, DDR 버퍼 cache flush/invalidate 누락
- [ ] DPU(B3136) 오버레이 + YOLOv5n 통합 테스트
- [ ] 점유 판정 임계값(겹침 비율) 확정 및 문서화
- [ ] End-to-end 파이프라인 성능 측정 (FPS, 지연시간)

---

## 9. 개발자

- 본 저장소(크롭/리사이즈 HLS IP, 파이프라인 통합, 점유 판정 로직): 본인 개발
- DPU 추론 오버레이: AMD/Xilinx 공식 Kria-PYNQ DPU 예제 기반 (별도 저장소)
- 전체 프로젝트는 5인 팀 협업으로 진행 (모델 학습 / ROI·판정 로직 / 배포 / 성능 측정 / 문서화 역할 분담)

---

## 10. License

TBD
