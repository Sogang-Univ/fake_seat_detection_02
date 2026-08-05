# 1. 우리가 궁극적으로 만들려는 것

최종 목표는 KV260의 PL 안에 다음 두 가속기를 동시에 넣는 것입니다.

KV260 PL
├── DPUCZDX8G B4096
└── ROI crop 가속기

그런데 DPU를 단순히 Vivado Block Design에 넣는 게 아니라, AMD가 제공하는 Vitis acceleration flow를 사용하기로 했습니다.

전체 흐름은 다음과 같습니다.

① KV260 기본 하드웨어 설계 생성
        ↓
② Vitis가 사용할 수 있는 플랫폼으로 변환
        ↓
③ DPU를 Vitis kernel 형태로 패키징
        ↓
④ 플랫폼과 DPU를 v++로 연결
        ↓
⑤ DPU가 포함된 bitstream/xclbin 생성
        ↓
⑥ 나중에 ROI kernel도 함께 연결

지금까지는 ②번까지 성공했고, ③~④번을 시도하다 컴퓨터가 죽은 상태입니다.

# 2. 여기서 “플랫폼”이란 무엇인가

Vitis에서 말하는 플랫폼은 단순한 FPGA 보드 이름이 아닙니다.

플랫폼은 Vitis에게 다음 정보를 알려주는 FPGA 기반 설계 틀입니다.

어떤 FPGA인가
어떤 PS가 있는가
DDR에 어떻게 접근하는가
가속기가 사용할 수 있는 AXI 포트는 무엇인가
사용 가능한 클럭은 몇 MHz인가
인터럽트는 어디에 연결하는가

즉 DPU가 들어갈 수 있는 빈 건물의 골조 같은 것입니다.

KV260 platform
├── Zynq UltraScale+ MPSoC
├── DDR 연결
├── PS 설정
├── 100/300/600 MHz 클럭
├── AXI 제어 포트
├── AXI 데이터 포트
└── 인터럽트 포트

DPU는 이 플랫폼 위에 올라가는 가속기입니다.

# 3. 처음 받은 DPU tar 파일의 역할

처음 받은 파일은:

DPUCZDX8G_VAI_v3.0.tar

이었습니다.

이 안에는 다음이 들어 있었습니다.

DPUCZDX8G_VAI_v3.0
├── dpu_ip       DPU의 실제 RTL/IP
├── Vitis        DPU를 Vitis kernel로 만들기 위한 파일
├── prj/Vitis    Vitis 통합 예제
├── prj/Vivado   Vivado 통합 예제
└── dpu_conf.vh  DPU 구조 설정

이 패키지가 제공하는 것은 주로 DPU 자체입니다.

하지만 이 패키지의 완성 예제는 ZCU102/ZCU104 중심이었기 때문에, KV260에서 사용하려면 별도의 KV260 플랫폼이 필요했습니다.

그래서 kria-vitis-platforms 저장소를 받은 것입니다.

# 4. kria-vitis-platforms를 받은 이유

다운로드한 저장소:

~/work/kria-vitis-platforms

이 저장소에는 KV260에 맞는 다음 구성들이 들어 있습니다.

KV260용 Vivado 기반 설계
KV260용 Vitis 플랫폼 생성 스크립트
KV260용 DPU benchmark 예제
firmware 패키징 관련 구조

그중 우리가 선택한 플랫폼은:

kv260_ispMipiRx_vcu_DP

입니다.

이 플랫폼을 선택한 이유는 현재 보드에서 사용 중이던 기존 DPU firmware의 기반 이름도 같은 계열이었기 때문입니다.

기존 firmware:
xilinx_kv260_ispMipiRx_vcu_DP_202210_1

새로 만든 2022.2 platform:
xilinx_kv260_ispMipiRx_vcu_DP_202220_1

즉 같은 KV260 multimedia 기반 설계를 2022.2 환경에서 다시 만든 것입니다.

# 5. 왜 Git 브랜치를 2022.2로 바꿨는가

저장소를 처음 clone했을 때는 main 브랜치였습니다.

하지만 우리는:

Vivado 2022.2
Vitis 2022.2
Vitis AI 3.0

을 사용하므로, 저장소도 같은 버전인:

xlnx_rel_v2022.2

브랜치로 전환했습니다.

git switch -c xlnx_rel_v2022.2 --track origin/xlnx_rel_v2022.2

이유는 Vivado/Vitis 프로젝트가 툴 버전에 민감하기 때문입니다.

예를 들어 2023.x용 플랫폼 Tcl을 2022.2에서 실행하면 IP 버전, 명령 옵션, board preset 등이 맞지 않을 수 있습니다.

따라서 현재 조합은 모두 통일됐습니다.

DPU IP          Vitis AI 3.0 / 2022.2
KV260 platform  xlnx_rel_v2022.2
Vivado          2022.2
Vitis           2022.2
# 6. 첫 번째로 만든 파일: .xsa

우리가 먼저 들어간 폴더는 다음입니다.

kv260/platforms/vivado/kv260_ispMipiRx_vcu_DP

여기에 있던 Makefile은 다음 명령을 제공했습니다.

make xsa

이 명령은 내부적으로:

Vivado 2022.2 실행
→ scripts/main.tcl 실행
→ KV260 Block Design 생성
→ platform interface 지정
→ XSA 작성 및 검증

을 수행했습니다.

생성된 파일:

project/kv260_ispMipiRx_vcu_DP.xsa
XSA란 무엇인가

XSA는 Xilinx Support Archive입니다.

이 파일에는 하드웨어 설계 정보가 들어 있습니다.

사용 FPGA part
PS 설정
Block Design
AXI 인터페이스
클럭
주소 정보
platform interface
필요한 경우 bitstream

이번 XSA는 일반적인 하드웨어 전달용 XSA가 아니라 extensible XSA입니다.

즉 Vitis가 나중에 DPU나 ROI 같은 가속기를 추가할 수 있도록 빈 연결 지점이 정의돼 있습니다.

README에서 확인한 platform interface는 다음과 같습니다.

클럭:
100 MHz
300 MHz
600 MHz

가속기 제어 AXI:
M01_AXI ~ M15_AXI

가속기 데이터 AXI:
HPC1
HP1
HP3
LPD

인터럽트:
pl_ps_irq0[7:0]
# 7. 보드 저장소를 설정한 이유

Vivado가 KV260 보드를 인식하려면 다음 board part가 필요합니다.

xilinx.com:kv260_som:1.4

그래서 XilinxBoardStore를 clone하고 Vivado 초기화 파일에 board repository 경로를 넣었습니다.

set_param board.repoPaths {/home/sogang/work/XilinxBoardStore/boards/Xilinx}

이 설정 덕분에 Vivado가 단순히 FPGA part만 인식한 것이 아니라:

KV260 SOM
xck26-sfvc784-2LV-c

보드 preset까지 사용할 수 있었습니다.

# 8. 두 번째로 만든 파일: .xpfm

XSA가 만들어진 다음 이동한 곳은:

kv260/platforms

입니다.

여기서 실행한 명령은:

make platform

이었습니다.

이 Makefile은 내부적으로 xsct를 실행했습니다.

Vivado XSA
→ XSCT의 platform create
→ Vitis platform generate
→ XPFM 생성

생성된 플랫폼 폴더:

xilinx_kv260_ispMipiRx_vcu_DP_202220_1

생성된 핵심 파일:

xilinx_kv260_ispMipiRx_vcu_DP_202220_1/
└── kv260_ispMipiRx_vcu_DP.xpfm
XPFM이란 무엇인가

XPFM은 Vitis Platform Metadata입니다.

XSA가 하드웨어 설계 자체를 전달한다면, XPFM은 Vitis에게:

이 플랫폼을 사용해라
하드웨어 정보는 여기에 있다
사용 가능한 클럭은 이것이다
사용 가능한 DDR 포트는 이것이다
가속기를 이곳에 연결할 수 있다

라고 알려주는 플랫폼 진입 파일입니다.

그래서 .xpfm 파일 자체 크기가 610바이트로 작아도 정상입니다. 실제 하드웨어 자료는 같은 플랫폼 폴더 안의 다른 파일들과 XSA가 담당합니다.

# 9. platforminfo로 무엇을 확인했는가

우리는 다음 명령으로 플랫폼을 검사했습니다.

platforminfo -p kv260_ispMipiRx_vcu_DP.xpfm

그 결과 다음이 확인됐습니다.

FPGA와 보드
FPGA Family: zynquplus
FPGA Device: xck26
Board Name:  kv260_som
Board Part:  xck26-sfvc784-2LV-c
Generated Version: 2022.2

즉 엉뚱한 ZCU102 플랫폼이 아니라 정확한 KV260 플랫폼입니다.

클럭
Clock 0: 약 300 MHz
Clock 1: 약 600 MHz
Clock 2: 약 100 MHz

DPU는 두 클럭을 사용합니다.

aclk     = 300 MHz
ap_clk_2 = 600 MHz

따라서 플랫폼이 DPU에 필요한 클럭을 제공하고 있습니다.

DDR 접근 포트
HP1
HP3
HPC1
LPD

기존에 정상 동작하던 DPU도 다음 연결을 사용했습니다.

DPU M_AXI_GP0 → HPC1
DPU M_AXI_HP0 → HP1
DPU M_AXI_HP2 → HP3

새로 만든 플랫폼에도 똑같은 포트가 존재합니다.

즉 현재 만든 2022.2 플랫폼은 기존 DPU 연결을 재현할 수 있는 플랫폼입니다. 실제 저장소에도 benchmark용 DPU 패키징 Tcl과 동일 포트 연결 설정이 존재합니다.

# 10. 이제 들어간 benchmark 폴더의 역할

다음 폴더로 이동했습니다.

kv260/overlays/examples/benchmark

여기는 플랫폼 위에 DPU를 올리는 예제입니다.

주요 파일은 다음과 같습니다.

benchmark/
├── Makefile
├── dpu_conf.vh
├── prj_conf/
│   └── prj_config_1dpu
├── scripts/
│   ├── gen_dpu_xo.tcl
│   └── package_dpu_kernel.tcl
└── kernel_xml/dpu/kernel.xml
# 11. dpu_conf.vh의 역할

이 파일은 DPU 내부 구조를 정합니다.

확인한 활성 설정은:

`define B4096
`define URAM_ENABLE
`define RAM_USAGE_LOW
`define CHANNEL_AUGMENTATION_ENABLE
`define DWCV_ENABLE
`define CONV_RELU_LEAKYRELU_RELU6
`define ALU_RELU_RELU6

핵심은:

B4096

입니다.

B4096은 DPU의 병렬 연산 규모입니다.

PP  = 8
ICP = 16
OCP = 16
Peak operations/clock = 4096

현재 사용 중인 기존 KV260 firmware도 B4096이므로 방향이 맞습니다.

URAM_ENABLE은 KV260의 UltraRAM을 DPU 내부 버퍼에 사용한다는 뜻입니다.

# 12. prj_config_1dpu의 역할

이 파일은 DPU 자체의 내부 구조가 아니라, DPU를 플랫폼에 어떻게 연결할지 정합니다.

확인한 설정은:

DPU 인스턴스 수: 1개

aclk     = 300 MHz
ap_clk_2 = 600 MHz

M_AXI_GP0 → HPC1
M_AXI_HP0 → HP1
M_AXI_HP2 → HP3

역할을 나누면:

dpu_conf.vh
→ DPU 내부 구조 결정
→ B4096, URAM, 기능 옵션

prj_config_1dpu
→ DPU 외부 연결 결정
→ 클럭, DDR 포트, 인스턴스 수

둘은 서로 다른 역할입니다.

# 13. dpu.xo는 무엇인가

benchmark의 첫 번째 빌드 단계는 DPU RTL을 Vitis kernel로 포장하는 것입니다.

DPU RTL/IP
+ kernel.xml
+ package Tcl
        ↓ Vivado
binary_container_1/dpu.xo

.xo는 Vitis에서 사용하는 가속기 kernel object 파일입니다.

소프트웨어의 .o object 파일과 비슷한 개념으로 보면 됩니다.

dpu.xo
= 아직 특정 플랫폼에 완전히 배치되지 않은 DPU 가속기 객체

나중에 ROI도 Vitis kernel로 만든다면:

roi_crop.xo

가 됩니다.

# 14. v++ --link가 하는 일

DPU .xo가 만들어지면 다음 단계에서:

KV260 platform.xpfm
+ dpu.xo
+ prj_config_1dpu
        ↓ v++ --link
dpu.xclbin

이 됩니다.

이때 v++가 내부적으로 Vivado를 호출하여:

DPU를 플랫폼에 연결
→ AXI interconnect 구성
→ 클럭 연결
→ 주소 할당
→ 합성
→ 배치배선
→ bitstream 생성

을 수행합니다.

즉 네가 Vivado GUI에서 DPU 블록을 직접 놓고 선을 긋는 일을 Vitis linker가 자동으로 수행하는 것입니다.

# 15. XSA, XPFM, XO, XCLBIN의 관계

이 네 개가 가장 헷갈릴 수 있습니다.

XSA
= KV260 하드웨어 골격

XPFM
= Vitis가 그 골격을 사용하도록 설명하는 플랫폼 파일

XO
= 플랫폼에 올릴 가속기 객체
  예: dpu.xo, roi_crop.xo

XCLBIN
= 플랫폼과 가속기를 실제로 링크한 최종 FPGA 실행 파일

흐름으로 쓰면:

Vivado platform source
        ↓
      XSA
        ↓
Vitis platform generation
        ↓
      XPFM

DPU RTL → dpu.xo
ROI HLS → roi_crop.xo

XPFM + dpu.xo + roi_crop.xo
        ↓ v++ link
      XCLBIN
        +
      bitstream

# 18. 지금 만든 플랫폼은 나중에 ROI와 어떻게 연결되는가

DPU-only 빌드가 성공하면, 최종적으로 다음 구조로 확장합니다.

현재:
KV260.xpfm + dpu.xo
→ dpu.xclbin

최종:
KV260.xpfm + dpu.xo + roi_crop.xo
→ roi_dpu.xclbin

즉 플랫폼은 다시 만들 필요가 없을 가능성이 큽니다.

ROI를 AXI memory-mapped Vitis kernel로 만들면:

DDR 원본 프레임
→ ROI kernel
→ DDR crop 결과
→ PS resize/quantize
→ DPU

구조가 됩니다.

다만 기존 ROI가 AXI-Stream + DMA 구조이므로, 그대로 쓸지 .xo용 memory-mapped 구조로 바꿀지는 DPU-only 성공 후 결정해야 합니다.
