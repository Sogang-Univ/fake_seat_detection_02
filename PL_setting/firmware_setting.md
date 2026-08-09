'''
Vitis/Vivado에서
DPU + ROI/Resize 통합 빌드
        ↓
.bit + .xclbin 생성
        ↓
.bit → .bit.bin 변환
        ↓
/lib/firmware/xilinx/
    kv260-b2304-roi-resize/
        ↓
bit.bin
dtbo
xclbin
shell.json
        ↓
DTBO의 firmware-name 수정
        ↓
xmutil이 앱으로 인식
        ↓
sudo xmutil loadapp
        ↓
FPGA PL 구성 + XRT 커널 사용 가능
'''
