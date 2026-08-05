방법 A는 실제로 다음 3단계로 진행합니다.

1단계: AMD가 제공한 KV260 DPU 기준 설계를 그대로 재빌드
2단계: 그 기준 설계에 ROI HLS 가속기를 추가
3단계: DPU + ROI가 들어 있는 firmware를 KV260에 설치

여기서 중요한 수정이 하나 있습니다.

공식 Kria DPU 기준 설계는 일반적으로 Vivado Block Design을 직접 열어 DPU에 ROI를 붙이는 방식보다, Kria Vitis platform에 DPU와 HLS accelerator를 함께 링크하는 방식으로 생성됩니다. 공식 SmartCam 설계도 전처리 IP와 DPU를 하나의 platform/overlay에 통합합니다.

0. 먼저 툴 버전을 결정해야 함

현재 네 환경은:

ROI 설계: Vivado/Vitis HLS 2022.2
현재 보드 DPU runtime: Vitis AI 2.5

그런데 공식 KV260 Kria DPU 재빌드 자료는 xlnx_rel_v2022.1 branch와 Vitis 2022.1 흐름을 기준으로 제공됩니다. 공식 문서도 해당 저장소의 xlnx_rel_v2022.1 branch를 clone하도록 안내합니다.

따라서 가장 안전한 선택은:

DPU 통합 프로젝트: Vitis/Vivado 2022.1
ROI HLS 소스: 2022.1에서 다시 합성 및 export

입니다.

2022.2에서 만든 ROI IP를 2022.1 DPU 프로젝트에 그대로 넣는 것은 권장하지 않습니다. IP 버전이 다르면 upgrade, synthesis 또는 interface metadata 문제가 발생할 수 있습니다.

선택지
선택	판단
Vitis/Vivado 2022.1을 추가 설치하고 공식 flow 사용	가장 안전
공식 2022.1 프로젝트를 2022.2로 upgrade	가능성은 있지만 위험 증가
현재 ROI 프로젝트에 DPU를 직접 추가	방법 B에 가까움

따라서 아래 설명은 2022.1 공식 flow 기준으로 보는 것이 좋습니다.

1단계: 개발 PC에 필요한 환경 준비

KV260 보드에서 작업하는 것이 아니라, Vivado/Vitis가 설치된 Ubuntu 개발 PC에서 진행합니다.

필요한 것:

Vivado 2022.1
Vitis 2022.1
Vitis HLS 2022.1
PetaLinux 2022.1
Vitis AI 2.5 관련 DPU integration files
KV260 Kria platform source

PetaLinux까지 필요한 이유는 최종 결과가 .bit 하나가 아니라:

bitstream 또는 xclbin
device-tree overlay
firmware metadata

를 포함하는 Kria application firmware이기 때문입니다.

2단계: KV260 기준 설계 source 확보

개발 PC의 작업 폴더에서 다음과 같이 clone합니다.

mkdir -p ~/kv260_dpu_work
cd ~/kv260_dpu_work

git clone \
  --branch xlnx_rel_v2022.1 \
  --recursive \
  https://github.com/Xilinx/kria-vitis-platforms.git

공식 문서에서도 이 repository와 branch를 사용해 KV260 Vitis platform을 구성합니다.

clone이 끝나면:

cd kria-vitis-platforms
git submodule status

를 실행합니다.

--recursive를 빠뜨리면 DPU IP 또는 하위 저장소가 비어 있을 수 있으므로 반드시 확인합니다.

3단계: source 구조 이해

대략 다음 종류의 파일을 찾게 됩니다.

kria-vitis-platforms/
├── kv260/
│   ├── platforms/
│   │   └── ...
│   └── overlays/
│       └── examples/
│           └── smartcam/
├── DPU 관련 IP
├── Vitis kernel 설정
├── platform 설정
└── Makefile

공식 Kria DPU 추가 튜토리얼에서는 DPU 통합에 다음 두 종류가 필요하다고 설명합니다.

DPU IP
Vitis DPU integration files

이것이 바로 방법 A의 핵심입니다. 네가 DPU의 모든 AXI와 클럭을 새로 그리는 것이 아니라, AMD가 준비한 DPU integration files를 사용합니다.

4단계: 기준 KV260 platform만 먼저 빌드

아직 ROI를 넣지 않습니다.

먼저 AMD가 제공한 기준 platform을 그대로 빌드해야 합니다.

공식 문서의 KV260 SmartCam platform 예시는 다음과 같은 platform을 사용합니다.

xilinx_kv260_ispMipiRx_vcu_DP

공식 build 문서는 clone한 repository 안에서 KV260 platform을 생성하는 흐름을 제공합니다.

여기서 네가 해야 할 일은 해당 branch의 README 또는 Makefile에 따라:

platform 생성
→ DPU overlay build
→ firmware package 생성

을 수정 없이 수행하는 것입니다.

왜 수정 없이 먼저 빌드하는가

ROI를 처음부터 추가하면 오류가 났을 때 다음 중 무엇 때문인지 알 수 없습니다.

개발환경 오류
DPU source 오류
platform build 오류
ROI IP 오류
DPU-ROI 통합 오류

먼저 DPU 기준 설계가 재현되면:

기준 DPU build 성공
→ 이후 오류는 ROI 추가 과정에서 발생

이라고 구분할 수 있습니다.

5단계: DPU overlay 생성 흐름

공식 Kria acceleration flow는 개념적으로 다음과 같이 동작합니다.

KV260 base platform
        +
DPU kernel/integration files
        ↓
Vitis linker
        ↓
Vivado implementation 자동 실행
        ↓
DPU 포함 bitstream/xclbin 생성

즉, 내부적으로 Vivado가 실행되지만 네가 처음부터 Block Design을 그리는 것은 아닙니다.

공식 튜토리얼도 기존 image resizing hardware pipeline에 DPU inference unit을 추가해 SmartCam application을 완성하는 흐름을 사용합니다.

생성 과정에서 실제로 일어나는 것
DPU IP 배치
DPU AXI master 연결
DDR 연결
DPU clock/reset 연결
DPU interrupt 연결
implementation
bitstream 생성
xclbin packaging

이 대부분을 Makefile과 Vitis linker configuration이 처리합니다.

6단계: 기준 DPU firmware를 보드에서 시험

생성된 firmware를 KV260으로 복사합니다.

최종 산출물 이름은 사용하는 예제와 설정에 따라 달라질 수 있으므로, 특정 파일명을 미리 고정하면 안 됩니다.

일반적으로 설치 위치는 다음 계열입니다.

/lib/firmware/xilinx/<application-name>/

설치 후:

sudo xmutil unloadapp
sudo xmutil listapps
sudo xmutil loadapp <새로-빌드한-DPU-앱>

으로 로드합니다.

공식 SmartCam 배포 흐름도 firmware 설치 후 xmutil listapps로 등록 상태를 확인하고 xmutil loadapp으로 application을 로드합니다.

검증

현재 성공했던 코드를 그대로 사용합니다.

python3 camera_dpu_stream_test.py \
  --model /home/ubuntu/work/prj/yolov8_head_included.xmodel

확인할 것:

DPU Runner 생성 성공
입출력 tensor shape 출력
Segmentation fault 없음
300프레임 연속 실행
DPU 시간 약 9.6 ms와 큰 차이 없음

이 단계까지 성공해야 기준 설계 확보가 끝난 것입니다.

7단계: ROI HLS 코드를 Vitis kernel 형태로 준비

방법 A에서는 기존 Vivado용 HLS IP를 그대로 Block Design에 끌어다 놓는 것보다, ROI crop을 Vitis accelerator kernel로 만들어 DPU와 함께 링크하는 방식이 공식 flow에 더 잘 맞습니다.

현재 네 ROI 함수는 AXI Stream 기반으로 되어 있을 가능성이 큽니다.

기존 구조:

void preprocess_top(
    hls::stream<axis_t>& src,
    hls::stream<axis_t>& dst
)

하지만 Vitis kernel로 DDR buffer를 직접 받으려면 보통 다음처럼 memory-mapped interface를 사용합니다.

void roi_crop_accel(
    const ap_uint<24>* input,
    ap_uint<24>* output
)

그리고 pragma는 개념적으로:

#pragma HLS INTERFACE m_axi port=input  bundle=gmem0
#pragma HLS INTERFACE m_axi port=output bundle=gmem1
#pragma HLS INTERFACE s_axilite port=return

형태가 됩니다.

두 구조의 차이
현재 Vivado IP 방식
DDR → AXI DMA → AXI Stream → ROI IP → AXI DMA → DDR
Vitis kernel 방식
DDR → ROI kernel AXI master → DDR

Vitis kernel 방식이면 별도의 AXI DMA가 필요하지 않습니다.

따라서 방법 A를 가장 단순하게 구성하면:

DPU
+ memory-mapped ROI HLS kernel

구성이 됩니다.

8단계: 기존 AXI-Stream ROI를 유지할 수도 있음

현재 검증한 AXI-Stream ROI IP를 반드시 유지하려면:

ROI HLS IP
+ AXI DMA

를 DPU platform의 Vivado 설계에 추가해야 합니다.

하지만 이 경우는 공식 Vitis kernel 통합에서 약간 벗어나고, platform hardware를 직접 수정해야 합니다.

즉 방법 A 안에서도 두 가지가 있습니다.

A-1 — 더 권장
DPU 기준 Vitis platform
+ ROI를 memory-mapped Vitis kernel로 변경
→ Vitis linker가 함께 통합

장점:

DMA IP를 직접 추가할 필요 없음
Vitis/XRT buffer 방식 사용 가능
공식 Kria acceleration flow와 잘 맞음
DPU와 custom kernel을 함께 package하기 쉬움
A-2 — 기존 ROI IP 유지
DPU 기준 platform의 Vivado source
+ 기존 AXI DMA
+ 기존 AXI-Stream ROI IP
→ platform 재생성

장점:

이미 검증한 ROI HLS 코드를 거의 그대로 사용

단점:

Vivado platform 내부 수정 필요
AXI 주소/클럭/리셋/interrupt 직접 연결
device tree에 DMA/ROI 노드 추가 가능성

현재 네가 DMA와 ROI IP를 이미 독립적으로 검증했기 때문에 A-2도 가능하지만, 통합 난도는 A-1보다 높습니다.

9단계: 추천하는 실제 선택

현재 프로젝트 기간과 목적을 고려하면 다음 구조를 추천합니다.

KV260 DPU 기준 platform
+
ROI crop memory-mapped HLS kernel
→ Vitis로 함께 link

최종 구조:

USB 카메라
    ↓
PS/OpenCV frame
    ↓ DDR input buffer
ROI HLS kernel
    ↓ DDR crop buffer
PS resize 및 DPU 입력 준비
    ↓ DDR DPU input tensor
DPU
    ↓
PS 후처리와 상태머신

여기에는 ROI와 DPU가 같은 bitstream/xclbin에 들어 있지만, 서로 AXI-Stream으로 직접 연결되지는 않습니다.

10단계: ROI kernel을 DPU overlay에 추가

기준 DPU overlay의 Makefile 또는 Vitis linker 설정에 ROI kernel을 추가합니다.

개념적으로 linker 입력이:

기존:
DPU kernel

수정:
DPU kernel
ROI crop kernel

이 됩니다.

Vitis 명령의 개념은 다음과 같습니다.

v++ -c ... roi_crop_accel.cpp -o roi_crop_accel.xo

그다음 DPU kernel object와 ROI kernel object를 함께 링크합니다.

v++ -l \
  <DPU kernel objects> \
  roi_crop_accel.xo \
  --platform <KV260 platform> \
  --config <link configuration> \
  -o roi_dpu.xclbin

실제 DPU object 이름과 옵션은 clone한 reference Makefile을 그대로 따라야 합니다. DPU는 일반 custom kernel보다 integration file이 많으므로 위 명령을 독립적으로 새로 작성하지 말고, 기준 Makefile에 ROI .xo만 추가하는 방식이 안전합니다.

11단계: Vivado 결과 확인

Vitis linker가 완료되면 내부적으로 Vivado implementation project가 생성됩니다.

그 프로젝트를 Vivado에서 열어 다음을 확인할 수 있습니다.

Zynq UltraScale+ MPSoC
DPUCZDX8G
ROI crop kernel
AXI SmartConnect
clock/reset
interrupt

여기서 Vivado는 주로 검토와 debug 용도로 사용합니다.

확인 보고서:

Report Utilization
Report Timing Summary
Report DRC

특히:

LUT
FF
BRAM
URAM
DSP
WNS
TNS

를 확인합니다.

AMD의 KV260 예제에서도 preprocessing IP와 DPU를 같은 platform에 통합한 뒤 전체 resource utilization을 확인합니다.

12단계: 통합 firmware 생성

링크 결과를 Kria firmware 형식으로 package합니다.

최종 application 이름 예:

kv260-roi-dpu-b4096

결과 디렉터리는 개념적으로:

kv260-roi-dpu-b4096/
├── kv260-roi-dpu-b4096.xclbin
├── shell.json 또는 metadata
├── device-tree overlay
└── 기타 firmware 파일

가 됩니다.

정확한 구성은 기준 SmartCam Makefile의 package target을 그대로 사용해야 합니다.

13단계: 보드 시험 순서

통합 firmware를 올린 후 절대로 한 번에 전체를 시험하지 않습니다.

시험 1 — DPU만
PS 전처리
→ DPU
→ raw tensor

기존 성공 코드로 확인합니다.

시험 2 — ROI만
입력 buffer
→ ROI HLS kernel
→ 출력 buffer

중앙 480×480 crop이 맞는지 확인합니다.

시험 3 — 순차 통합
카메라
→ ROI HLS
→ crop buffer
→ DPU 전처리
→ DPU
→ Detection
→ 상태머신

을 실행합니다.

네가 지금 바로 해야 하는 범위

아직 ROI를 수정하거나 추가하지 말고 아래까지만 먼저 진행하는 것이 맞습니다.

1. 개발 PC에 Vitis/Vivado 2022.1 환경 확인
2. kria-vitis-platforms xlnx_rel_v2022.1 clone
3. 공식 KV260 platform build
4. DPU overlay를 수정 없이 build
5. 생성 firmware를 KV260에 설치
6. 현재 xmodel로 DPU 동작 확인

여기까지 성공한 뒤에:

7. ROI를 Vitis memory-mapped kernel로 변환할지
8. 기존 AXI-Stream ROI + DMA를 유지할지

를 결정하면 됩니다.

추천 최종 방향
공식 KV260 DPU reference flow
+ memory-mapped ROI HLS kernel

이 가장 관리하기 쉽습니다.

기존 DMA 기반 ROI 설계는 ROI 알고리즘과 HLS 동작 검증용 설계로 보존하고, 최종 DPU 통합본에서는 ROI 함수를 memory-mapped Vitis kernel로 한 번 재포장하는 방식이 좋습니다.
