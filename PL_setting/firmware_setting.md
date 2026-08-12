좋아. 지금까지 우리가 했던 걸 기준으로, **“어떤 DPU든 KV260에서 쓸 수 있게 환경을 만들고, 그 결과물 중 무엇을 보드로 가져가서 firmware app으로 등록했는가”**를 처음부터 끝까지 흐름으로 정리해줄게.

핵심은 이거야.

```text
DPU 설정 선택
    ↓
Vitis/Vivado로 전체 PL design build
    ↓
.bit / .hwh / .xclbin / arch.json 생성
    ↓
.bit → .bit.bin 변환
    ↓
dtbo + shell.json과 함께 firmware 폴더 구성
    ↓
KV260의 /lib/firmware/xilinx/<app-name>/ 에 복사
    ↓
xmutil loadapp <app-name>
```

## 1. 먼저 DPU 환경을 어디서 설정했는가

우리가 사용한 기반 프로젝트는 `kria-vitis-platforms`였고, KV260용 플랫폼 위에 DPU와 네 HLS 전처리 IP를 같이 넣었어.

예를 들면 B2304 V5 프로젝트는:

```text
/DATA/home/edu014/work/kria-vitis-platforms/kv260/overlays/examples/
benchmark_b2304_roi_resize_v5
```

B3136은:

```text
benchmark_b3136_roi_resize_v5
```

B4096은:

```text
benchmark_b4096_roi_resize_v5
```

처럼 DPU별로 프로젝트를 따로 만들어서 비교했지.

---

# 2. DPU 종류는 어디서 바꿨는가

프로젝트 안의:

```text
dpu_conf.vh
```

파일에서 DPU architecture를 선택했어.

예를 들어 B2304:

```verilog
`define B2304
```

B3136:

```verilog
`define B3136
```

B4096:

```verilog
`define B4096
```

이렇게 바꿨어.

중요한 점은 **architecture define만 바꾸고 다른 DPU 옵션은 그대로 유지**했다는 거야.

즉 비교 조건은:

```text
B2304 / B3136 / B4096
```

만 바꾸고,

```text
URAM_ENABLE
RAM_USAGE_LOW
CHANNEL_AUGMENTATION_ENABLE
DWCV_ENABLE
DSP48_USAGE_HIGH
...
```

같은 나머지 설정은 동일하게 유지했어.

---

# 3. HLS 전처리 IP도 같이 넣었다

DPU만 있는 게 아니라 지금 최종 구조는:

```text
KV260 PL

DPUCZDX8G
+
crop_and_resize HLS IP
```

야.

V5 전처리의 XO는:

```text
/DATA/home/edu014/prj/roi_crop_resize/solution2/impl/export.xo
```

에서 만들어졌고, DPU 프로젝트 안에서는:

```text
roi_crop_resize_accel/crop_and_resize.xo
```

로 넣었어.

즉 전체 build 관점에서는:

```text
DPU RTL/XO
+
crop_and_resize.xo
+
KV260 base platform
```

을 합쳐서 하나의 PL design을 만든 거야.

---

# 4. clock과 connectivity도 설정했다

우리가 고정해서 사용한 clock은:

```text
DPU aclk     = 300 MHz
DPU ap_clk_2 = 600 MHz
HLS          = 100 MHz
```

였고 connectivity는 대략:

```text
DPU GP0 → HPC1
DPU HP0 → HP1
DPU HP2 → HP3

crop src → HP1
crop dst → HP1
```

로 잡았어.

이 설정은 프로젝트의 `prj_conf` 쪽 configuration file에 들어가 있었고, timing 때문에 implementation strategy도:

```text
prop=run.impl_1.strategy=Performance_EarlyBlockPlacement
```

로 활성화했어.

이건 RTL을 바꾸는 게 아니라 **Vivado의 placement/routing 전략을 timing 중심으로 바꾸는 설정**이었지.

---

# 5. DPU를 바꿀 때 stale XO를 제거했다

이게 중요했어.

`dpu_conf.vh`만 바꿔도 기존 `dpu.xo`가 남아 있으면 이전 architecture가 재사용될 수 있어서, DPU 변경 때마다:

```bash
rm -f binary_container_1/dpu.xo

rm -rf packaged_kernel_DPUCZDX8G_hw_mpsoc
rm -rf tmp_kernel_pack_DPUCZDX8G_hw_mpsoc

rm -rf binary_container_1/link
```

를 지우고 다시 build했어.

그래야 실제로:

```text
B2304 → B3136
```

혹은:

```text
B3136 → B4096
```

가 반영된 새 DPU XO가 만들어졌어.

---

# 6. 전체 build는 어떻게 했나

우리가 사용한 KV260 platform은:

```text
/DATA/home/edu014/xilinx_platforms/
xilinx_kv260_ispMipiRx_vcu_DP_202220_1/
kv260_ispMipiRx_vcu_DP.xpfm
```

이었고 build는:

```bash
make all \
PLATFORM=/DATA/home/edu014/xilinx_platforms/xilinx_kv260_ispMipiRx_vcu_DP_202220_1/kv260_ispMipiRx_vcu_DP.xpfm
```

로 했어.

이 과정에서:

```text
HLS kernel
DPU
KV260 base platform
```

을 link하고 Vivado implementation까지 수행해서 실제 FPGA에 올릴 수 있는 bitstream을 만든 거야.

---

# 7. build가 끝나면 어떤 산출물이 생성됐는가

여기가 제일 중요해.

전체 build가 성공하면 주요 산출물은 크게 네 종류였어.

### ① `.bit`

실제 FPGA configuration bitstream.

경로는 보통:

```text
binary_container_1/link/vivado/vpl/prj/prj.runs/impl_1/
kv260_ispMipiRx_vcu_DP_wrapper.bit
```

이었어.

이게 **실제 FPGA PL logic을 구성하는 핵심 파일**이야.

---

### ② `.hwh`

하드웨어 handoff metadata.

경로는:

```text
binary_container_1/link/vivado/vpl/prj/prj.gen/sources_1/bd/
kv260_ispMipiRx_vcu_DP/hw_handoff/
kv260_ispMipiRx_vcu_DP.hwh
```

이었어.

`.hwh`에는:

```text
IP 구성
주소 맵
AXI 연결
register 정보
hardware block 정보
```

등이 들어 있어.

PYNQ나 하드웨어 구조 확인할 때 유용하지.

다만 **xmutil firmware app으로 보드에 load하기 위해 반드시 필요한 파일은 아니었어.**

---

### ③ `.xclbin`

XRT가 kernel 정보를 알기 위한 container야.

생성되는 기본 파일:

```text
binary_container_1/dpu.xclbin
```

그리고 build 과정에서 bitstream section을 제거한:

```text
strip.xclbin
```

도 만들었어.

예:

```bash
xclbinutil \
--remove-section BITSTREAM \
--force \
--input binary_container_1/dpu.xclbin \
--output strip.xclbin
```

이 stripped xclbin은 대략 60~70 KB 정도였지.

이 파일에는 XRT가 필요한:

```text
kernel metadata
kernel argument
memory connectivity
UUID
```

같은 정보가 들어 있어.

---

### ④ `arch.json`

DPU architecture description이야.

build 끝나면 DPU IP 쪽에서 생성되고:

```text
.../ip/*DPUCZDX8G_1_0/arch.json
```

또는 `sd_card` 쪽으로 복사됐어.

이건 **xmodel compile할 때 매우 중요**해.

즉:

```text
B2304 arch.json
→ B2304용 xmodel compile

B3136 arch.json
→ B3136용 xmodel compile

B4096 arch.json
→ B4096용 xmodel compile
```

에 사용해.

---

# 8. `.bit`는 그대로 보드에 가져간 게 아니었다

여기서 한 단계가 더 있었어.

KV260 firmware app에서는 `.bit` 대신:

```text
.bit.bin
```

형태를 사용했어.

그래서 `.bit`를 `bootgen`으로 변환했지.

예:

```bash
BIT_FILE=binary_container_1/link/vivado/vpl/prj/prj.runs/impl_1/kv260_ispMipiRx_vcu_DP_wrapper.bit
```

BIF 작성:

```bash
cat > bitstream.bif <<EOF
all:
{
    $BIT_FILE
}
EOF
```

그리고:

```bash
bootgen \
-arch zynqmp \
-image bitstream.bif \
-w \
-o i kv260-b2304-roi-resize-v5.bit.bin
```

이렇게 해서:

```text
kv260-b2304-roi-resize-v5.bit.bin
```

을 만들었어.

---

# 9. 보드로 실제 가져간 파일은 무엇인가

보드의 firmware app에는 최종적으로 보통 네 파일을 넣었어.

```text
*.bit.bin
*.dtbo
*.xclbin
shell.json
```

예를 들어 B2304 V5 firmware app이면:

```text
/lib/firmware/xilinx/kv260-b2304-roi-resize-v5/
```

안에:

```text
kv260-b2304-roi-resize.bit.bin
kv260-b2304-roi-resize.dtbo
kv260-b2304-roi-resize.xclbin
shell.json
```

형태로 구성했어.

### 각 파일 역할

```text
.bit.bin
→ 실제 FPGA PL configuration
→ DPU + crop_and_resize IP가 들어 있음

.dtbo
→ Linux device tree overlay
→ FPGA hardware를 Linux/XRT 쪽에 등록

.xclbin
→ XRT kernel metadata
→ crop_and_resize 같은 kernel을 host code가 찾을 수 있게 함

shell.json
→ xmutil이 이 폴더를 firmware app으로 인식하도록 하는 정보
```

네 `shell.json`은 아주 단순했지.

```json
{
    "shell_type" : "XRT_FLAT",
    "num_slots": "1"
}
```

---

# 10. `.hwh`는 firmware app에는 안 넣었다

이 부분이 헷갈리기 쉬워.

우리가 생성한:

```text
.bit
.hwh
.xclbin
arch.json
```

중에서 실제 `xmutil` firmware app에 넣은 핵심은:

```text
.bit.bin
.dtbo
.xclbin
shell.json
```

이었어.

즉:

```text
.hwh
```

는 보드 firmware app에 꼭 필요하지 않았어.

그리고:

```text
arch.json
```

도 firmware를 load하는 데 필요한 파일은 아니야.

`arch.json`은 **모델 compile용**이야.

---

# 11. 보드에서는 어떻게 firmware를 load했는가

보드에 파일을 넣은 다음:

```bash
sudo xmutil listapps
```

로 확인하고,

기존 firmware가 올라가 있으면:

```bash
sudo xmutil unloadapp
```

그다음:

```bash
sudo xmutil loadapp kv260-b2304-roi-resize-v5
```

처럼 load했어.

그리고 FPGA 상태:

```bash
cat /sys/class/fpga_manager/fpga0/state
```

가:

```text
operating
```

이면 정상.

---

# 12. firmware가 load되면 실제 구조는 어떻게 되는가

보드에서는:

```text
Linux / Python host
        │
        │ XRT
        ▼
.xclbin metadata
        │
        ▼
FPGA PL
 ┌───────────────────────┐
 │ crop_and_resize V5    │
 │                       │
 │ DPUCZDX8G Bxxxx       │
 └───────────────────────┘
        │
       DDR
```

이렇게 돼.

그리고 Python에서는:

```text
hls_crop_resize_pl_quant.py
        ↓
libhls_crop.so
        ↓
XRT
        ↓
crop_and_resize kernel
```

을 호출하고,

DPU는:

```text
VART
 ↓
xmodel
 ↓
DPUCZDX8G
```

로 실행해.

---

# 13. xmodel은 firmware와 별도다

이것도 매우 중요해.

firmware app을 만들었다고 해서 YOLO model까지 FPGA 안에 들어간 건 아니야.

구조는:

```text
Firmware
→ DPU hardware architecture

xmodel
→ DPU에서 실행할 neural network
```

로 별도야.

예를 들어:

```text
B2304 firmware
+
B2304 arch.json으로 compile된 xmodel
```

이 한 쌍이어야 해.

B3136이면:

```text
B3136 firmware
+
B3136용 xmodel
```

이어야 하고.

---

# 전체 과정을 한 장으로 정리하면

```text
                [SGP2 Build Server]

dpu_conf.vh
 B2304 / B3136 / B4096
         │
         │
V5 crop_and_resize.xo
         │
         │
KV260 .xpfm platform
         │
         ▼
      make all
         │
         ▼
 ┌─────────────────────────────┐
 │ Vivado/Vitis implementation │
 └─────────────────────────────┘
         │
         ├──── .bit
         │
         ├──── .hwh
         │
         ├──── .xclbin
         │
         └──── arch.json
                │
                │
.bit ──bootgen──┘
 ↓
.bit.bin


                [Firmware package]

.bit.bin
.dtbo
.xclbin
shell.json
    │
    ▼

        [KV260]

/lib/firmware/xilinx/
kv260-bxxxx-roi-resize-v5/
    │
    ▼
xmutil loadapp
    │
    ▼
FPGA configured

crop_and_resize V5
+
DPUCZDX8G Bxxxx
```

## 그래서 딱 기억해야 할 산출물

| 파일           | 무엇인가                  | 보드 firmware에 필요? | 용도                  |
| ------------ | --------------------- | ---------------- | ------------------- |
| `.bit`       | FPGA bitstream 원본     | 직접 X             | `.bit.bin` 생성       |
| `.bit.bin`   | KV260용 FPGA image     | **O**            | 실제 PL configuration |
| `.hwh`       | Hardware handoff      | X                | PYNQ/주소맵/구조 확인      |
| `.xclbin`    | XRT kernel metadata   | **O**            | XRT host 실행         |
| `.dtbo`      | Device Tree Overlay   | **O**            | Linux hardware 등록   |
| `shell.json` | xmutil app 정보         | **O**            | firmware app 등록     |
| `arch.json`  | DPU architecture 정보   | X                | **xmodel compile용** |
| `.xo`        | HLS/DPU kernel object | X                | build/link 입력       |

그러니까 네가 팀원에게 **“보드에서 나와 같은 firmware를 load해라”**라고 줄 때 핵심 패키지는:

```text
.bit.bin
.dtbo
.xclbin
shell.json
```

이고,

**모델까지 같은 동작을 하게 하려면 추가로:**

```text
compatible xmodel
Python host code
libhls_crop.so
```

까지 같이 줘야 해.
