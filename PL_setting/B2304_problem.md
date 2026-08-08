# KV260 B2304 + ROI Crop/Resize 통합 결과 정리
# v.1
## 1. 현재 목표

KV260에서 아래 구조를 하나의 PL 설계로 통합하는 것을 목표로 함.

```text
Camera / Frame
      ↓
ROI Crop + Resize HLS
      ↓
DDR
      ↓
DPU B2304
      ↓
YOLO Inference
      ↓
Post-processing
````

현재는 기존 KV260 플랫폼(XSA/XPFM)은 수정하지 않고,

* DPU: DPUCZDX8G B2304
* 전처리: `crop_and_resize` HLS kernel
* Platform: 기존 `kv260_ispMipiRx_vcu_DP`

구성을 그대로 사용하여 통합을 시도함.

---

## 2. ROI + Resize HLS Kernel 준비

Vitis HLS에서 기존 `crop_and_resize`를 Vitis Kernel Flow로 export하여 `.xo` 생성 완료.

생성 파일:

```text
roi_crop_resize_accel/crop_and_resize.xo
```

크기:

```text
약 423 KB
```

XO 내부 인터페이스 확인 결과:

```text
Kernel name : crop_and_resize

src → M_AXI_GMEM0
dst → M_AXI_GMEM1

Control → S_AXI_CONTROL
```

AXI interface width:

```text
M_AXI_GMEM0 = 128 bit
M_AXI_GMEM1 = 512 bit
```

Clock:

```text
ap_clk = 100 MHz
```

---

## 3. DPU + ROI/Resize 연결 설정

DPU의 기존 연결은 그대로 유지함.

```text
DPUCZDX8G_1.M_AXI_GP0 → HPC1
DPUCZDX8G_1.M_AXI_HP0 → HP1
DPUCZDX8G_1.M_AXI_HP2 → HP3
```

새 ROI + Resize kernel은 다음과 같이 설정함.

```ini
nk=crop_and_resize:1:crop_and_resize_1

sp=crop_and_resize_1.src:HP1
sp=crop_and_resize_1.dst:HP1
```

Clock 설정:

```ini
freqHz=300000000:DPUCZDX8G_1.aclk
freqHz=600000000:DPUCZDX8G_1.ap_clk_2
freqHz=100000000:crop_and_resize_1.ap_clk
```

즉,

```text
DPU             : 300 / 600 MHz
ROI + Resize    : 100 MHz
```

로 구성함.

---

## 4. Vitis Link 구성

기존 B2304 `dpu.xo`는 그대로 재사용하고,

```text
binary_container_1/dpu.xo
+
roi_crop_resize_accel/crop_and_resize.xo
```

두 개의 XO를 `v++ -l`로 동시에 연결함.

즉 이번 빌드는 DPU 자체를 새로 설계한 것이 아니라,

```text
기존 B2304 DPU
        +
새 ROI Crop/Resize HLS Kernel
        ↓
Vitis System Link
        ↓
Vivado Synthesis / Implementation
```

구조임.

---

# 5. 통합 빌드 결과

## 결과: FAIL

통합 자체와 System Link는 진행되었으나,
Vivado implementation 단계에서 BRAM 자원 부족으로 실패함.

핵심 에러:

```text
ERROR: [VPL UTLZ-1] Resource utilization:
RAMB18 and RAMB36/FIFO over-utilized

This design requires 315 of such cell types
but only 288 compatible sites are available.
```

또한:

```text
ERROR: [VPL 4-23] Error(s) found during DRC.
Placer not run.
```

따라서 이번 실패는 Timing 문제가 아니라

> **BRAM 자원 초과로 인해 Placement 자체를 시작하지 못한 것**

임.

---

# 6. 전체 FPGA Resource 결과

통합 설계 Synthesis 결과:

| Resource       |       사용량 |      전체 |         사용률 |
| -------------- | --------: | ------: | ----------: |
| CLB LUT        |    81,468 | 117,120 |      69.56% |
| CLB Register   |   125,919 | 234,240 |      53.76% |
| Block RAM Tile | **158.5** | **144** | **110.07%** |
| RAMB36         |       134 |     144 |      93.06% |
| RAMB18         |        49 |     288 |      17.01% |
| URAM           |        48 |      64 |      75.00% |
| DSP            |       468 |   1,248 |      37.50% |

가장 큰 문제는:

```text
Block RAM Tile = 158.5 / 144
               = 110.07%
```

즉 약 14.5 Block RAM Tile을 초과함.

RAMB18 기준으로 보면:

```text
134 × 2 + 49
= 317 RAMB18-equivalent
```

리소스 DRC에서는 배치 가능한 compatible site 기준 약 315개가 필요하다고 판단했으며,
디바이스의 가용 site 288개를 초과하여 implementation이 중단됨.

---

# 7. DPU B2304 자체 Resource

DPU 단독 synthesis 결과:

| Resource       | B2304 DPU |
| -------------- | --------: |
| LUT            |    41,856 |
| FF             |    69,711 |
| Block RAM Tile |    **55** |
| RAMB36         |        50 |
| RAMB18         |        10 |
| URAM           |        40 |
| DSP            |       438 |

BRAM 계산:

```text
50 RAMB36
+ 10 RAMB18

= 50 + 10/2
= 55 Block RAM Tiles
```

따라서 B2304 DPU 자체는 기존과 동일하게 정상적인 자원 사용량을 보임.

---

# 8. ROI Crop + Resize 자체 Resource

`crop_and_resize` synthesis 결과:

| Resource       | ROI + Resize |
| -------------- | -----------: |
| LUT            |        9,564 |
| FF             |        5,896 |
| Block RAM Tile |     **34.5** |
| RAMB36         |           34 |
| RAMB18         |            1 |
| URAM           |            0 |
| DSP            |           30 |

BRAM 계산:

```text
34 RAMB36
+ 1 RAMB18

= 34 + 1/2
= 34.5 Block RAM Tiles
```

즉 ROI + Resize HLS kernel 하나가 KV260 전체 BRAM의 약 24%를 사용함.

---

# 9. 중요한 분석

DPU와 ROI kernel 자체만 단순 합산하면:

```text
DPU B2304        = 55.0 BRAM Tiles
ROI + Resize     = 34.5 BRAM Tiles
--------------------------------
합계             = 89.5 BRAM Tiles
```

하지만 전체 통합 설계는:

```text
158.5 BRAM Tiles
```

를 사용함.

따라서:

```text
158.5 - 89.5
= 69 BRAM Tiles
```

가 DPU/ROI kernel 이외의 플랫폼 및 연결 구조에서 사용되고 있음.

---

## 기존 B2304 단독 결과와 비교

기존 B2304 전체 설계는 약:

```text
74.5 BRAM Tiles
```

를 사용했음.

DPU 자체가 55 Tile이므로 기존 Platform 등의 overhead는 대략:

```text
74.5 - 55
= 19.5 Tiles
```

임.

그런데 ROI + Resize 통합 후 kernel 이외 영역은:

```text
69 Tiles
```

가 되었음.

따라서 ROI + Resize를 추가하면서 단순 kernel 자체 외에도 약:

```text
69 - 19.5
≈ 49.5 BRAM Tiles
```

수준의 추가적인 memory/interconnect 관련 자원이 발생한 것으로 추정됨.

※ 정확한 원인은 자동 생성된 IP별 utilization report를 추가 분석해야 함.

---

# 10. 추가된 AXI / Interconnect 구조

Vitis Link 과정에서 다음과 같은 IP들이 자동 생성됨.

```text
m00_data_fifo_0
s01_data_fifo_0

auto_us_cc_df_0
auto_us_df_0

auto_cc_0
auto_cc_1

auto_ds_0
auto_us_3

xbar_*
regslice_*
```

특히

```text
data_fifo
df
```

계열 IP는 BRAM을 사용하는 AXI buffering 구조일 가능성이 있으므로
현재 주요 분석 대상임.

ROI + Resize의 AXI interface가

```text
Input  : 128 bit
Output : 512 bit
```

로 구성되어 있기 때문에,

```text
ROI Kernel
    ↓
AXI width conversion
    ↓
Clock conversion
    ↓
AXI FIFO / Buffer
    ↓
SmartConnect / Crossbar
    ↓
HP1
```

과 같은 추가 구조가 생성되면서 BRAM 사용량이 증가했을 가능성이 있음.

---

# 11. 현재 결론

현재 결과만 보면

> **B2304 DPU 자체가 문제라고 바로 판단할 수는 없음.**

현재 Resource 병목은 BRAM이며,

```text
DPU                 : 55.0 Tiles
ROI + Resize        : 34.5 Tiles
Platform/AXI 등     : 약 69 Tiles
---------------------------------
전체                 : 158.5 Tiles
KV260 한계           : 144 Tiles
```

임.

따라서 DPU를 더 작게 변경하기 전에
ROI/Resize 및 AXI 연결 구조의 BRAM 사용량을 먼저 분석하고 최적화할 필요가 있음.

---

# 12. 다음 진행 계획

우선순위는 다음과 같이 설정함.

### 1순위: AXI / FIFO Resource 분석

자동 생성된 IP별 BRAM 사용량 확인.

주요 대상:

```text
m00_data_fifo_0
s01_data_fifo_0
auto_us_cc_df_0
auto_us_df_0
```

목적:

> ROI kernel 추가 시 발생한 약 49.5 BRAM Tile 수준의 추가 overhead가 어디에서 발생했는지 확인

### 2순위: ROI + Resize HLS 최적화

현재 ROI kernel 자체:

```text
34.5 BRAM Tiles
```

사용.

검토 대상:

* Line Buffer 구조
* 임시 Buffer 구조
* AXI burst 설정
* AXI port width
* Output interface 512-bit 사용 필요성
* FIFO depth

### 3순위: DPU 규모 재검토

AXI/HLS 최적화 이후에도 BRAM 사용량이 KV260 한계를 넘으면

```text
B2304 → 더 작은 DPU configuration
```

을 검토.

---

# 13. 현재 상태 요약

```text
[완료] B2304 DPU XO 생성
[완료] ROI Crop + Resize HLS
[완료] crop_and_resize.xo 생성
[완료] B2304 + ROI XO Vitis Link 연결
[완료] System Link
[완료] Synthesis
[실패] Implementation

실패 원인:
BRAM Resource Over-utilization

158.5 / 144 Block RAM Tiles
= 110.07%

→ Placement 불가능
```

현재 다음 작업은

> **자동 생성된 AXI/FIFO IP들의 BRAM 사용량을 분해하여 실제 BRAM 증가 원인을 찾는 것**

임.

# 14. 실제 증가 원인
DPU보다 ROI+Resize 커널과 함께 자동 생성된 AXI Data FIFO가 핵심 문제입니다.

계산해보면 다음과 같습니다.

블록	RAMB36	RAMB18	Block RAM Tile 환산
B2304 DPU	50	10	55.0
crop_and_resize	34	1	34.5
auto_us_cc_df_0	8	16	16.0
auto_us_df_0	0	16	8.0
m00_data_fifo_0	15	2	16.0
s01_data_fifo_0	8	1	8.5

B2304가 너무 큰 것이 아니라, ROI+Resize 추가 시 생성된 AXI Data FIFO 4개가 무려 48.5 BRAM Tile을 사용하고 있으므로, 먼저 HLS의 AXI burst/widening/outstanding 설정을 최적화해야 합니다.

# V.2
좋습니다. 이번 결과로 **어디에서 BRAM이 줄었는지가 명확하게 확인됐습니다.** 핵심은 예상과 조금 다릅니다.

### V1 → V2 비교

| 항목                | V1: Burst 256 | V2: Burst 16 |        변화 |
| ----------------- | ------------: | -----------: | --------: |
| 전체 Block RAM Tile |         158.5 |    **146.0** | **-12.5** |
| 사용률               |       110.07% |  **101.39%** |   -8.68%p |
| RAMB36            |           134 |      **122** |       -12 |
| RAMB18            |            49 |       **48** |        -1 |
| LUT               |        81,468 |   **77,214** |    -4,254 |
| FF                |       125,919 |      125,898 |     거의 동일 |
| URAM              |            48 |           48 |        동일 |
| DSP               |           468 |          468 |        동일 |

즉 `max_*_burst_length=256 → 16`만으로 **BRAM Tile이 12.5개 감소**했습니다.

---

## 그런데 어디가 줄었는지가 중요합니다

이전과 현재 IP별 결과를 비교하면:

| 블록                |       V1 |       V2 |        변화 |
| ----------------- | -------: | -------: | --------: |
| B2304 DPU         |     55.0 |     55.0 |         0 |
| `crop_and_resize` | **34.5** | **22.0** | **-12.5** |
| `auto_us_cc_df_0` |     16.0 |     16.0 |         0 |
| `auto_us_df_0`    |      8.0 |      8.0 |         0 |
| `m00_data_fifo_0` |     16.0 |     16.0 |         0 |
| `s01_data_fifo_0` |      8.5 |      8.5 |         0 |

이게 이번 결과의 핵심입니다.

제가 앞에서 예상했던 것과 달리, **자동 생성된 외부 AXI Data FIFO 48.5 Tile은 전혀 줄지 않았습니다.**

줄어든 12.5 Tile은 전부:

```text
crop_and_resize
34.5 → 22.0
```

에서 발생했습니다.

즉 `max_read_burst_length`와 `max_write_burst_length`를 줄이자 **HLS 커널 내부의 M_AXI adapter/buffering 자원이 감소한 것**으로 해석하는 게 맞습니다.

---

# 현재 상태

이제 전체 BRAM은:

```text
146 / 144
= 101.39%
```

입니다.

처음에는:

```text
158.5 / 144
```

였으니 굉장히 많이 개선됐습니다.

하지만 아직:

```text
146 > 144
```

라서 **2 Block RAM Tile이 초과**합니다.

그래서 Vivado가:

```text
Placer not run.
```

하고 다시 멈춘 것입니다.

로그의:

```text
requires 290 ...
only 288 compatible sites
```

도 같은 문제를 보여줍니다. 다만 `290 compatible sites`와 단순한 `RAMB36×2 + RAMB18` 계산은 Vivado의 BRAM site compatibility 때문에 완전히 같은 숫자로 해석하지 않는 것이 좋습니다.

---

# 다음에는 무엇을 하면 되나?

지금은 **다른 설정을 건드리지 않고 Burst를 한 번 더 낮추는 게 가장 깔끔합니다.**

현재:

```cpp
max_read_burst_length=16
max_write_burst_length=16
```

을:

```cpp
#pragma HLS INTERFACE m_axi port=src offset=slave bundle=gmem0 \
    depth=SIM_SRC_DEPTH max_read_burst_length=8

#pragma HLS INTERFACE m_axi port=dst offset=slave bundle=gmem1 \
    depth=SIM_DST_DEPTH max_write_burst_length=8
```

로 바꾸세요.

즉 실험은 이렇게 이어집니다.

```text
V1
burst = 256
158.5 / 144
FAIL
        ↓
V2
burst = 16
146 / 144
FAIL
        ↓
V3
burst = 8
? / 144
```

**지금은 `max_widen_bitwidth`까지 같이 바꾸지 않는 것을 권합니다.** Burst 하나만 변화시키면서 결과를 보면 어떤 설정이 자원에 영향을 미쳤는지 명확하게 설명할 수 있기 때문입니다.

---

## 다만 목표는 144 이하가 아닙니다

예를 들어 V3에서:

```text
143.5 / 144
```

가 나왔다고 해서 “완료”라고 보면 안 됩니다.

그건 BRAM을 사실상 100% 사용하는 상태라서 이후 placement/routing이나 다른 작은 변화에 매우 취약합니다.

가능하다면:

```text
130대 BRAM Tile
```

정도까지 확보하는 것이 훨씬 낫습니다.

그래서 V3가 예를 들어:

```text
140 / 144
```

로만 내려간다면 placement는 시도해보되, 이후에는 `max_widen_bitwidth` 또는 외부 AXI FIFO 48.5 Tile을 줄이는 최적화도 검토할 가치가 있습니다.

---

### 이번 실험에서 얻은 중요한 결론

보고서에는 이렇게 정리할 수 있습니다.

> 초기 통합 설계에서는 Block RAM 사용량이 158.5/144 Tile(110.07%)로 구현이 불가능하였다. HLS M_AXI의 최대 burst length를 256에서 16으로 축소한 결과, `crop_and_resize` 커널의 BRAM 사용량이 34.5 Tile에서 22 Tile로 감소하였으며 전체 BRAM 사용량도 146 Tile(101.39%)까지 감소하였다. 반면 Vitis가 자동 생성한 AXI Data FIFO의 BRAM 사용량은 변하지 않아, burst length 감소가 주로 HLS 커널 내부 AXI adapter의 buffering 자원에 영향을 준 것으로 확인하였다.

이건 꽤 좋은 최적화 결과입니다. **다음 단계는 Burst 8 버전 XO 생성 → 교체 → 재빌드**입니다.
