#include "roi_crop.hpp"
#include <cstring>   // memcpy

// -----------------------------------------------------------------------------
// depth = cosim이 C TB 배열과 RTL 사이에 주고받을 "128bit 워드 개수".
//         반드시 테스트벤치 배열 크기와 정확히 일치해야 한다.
//         (크게 잡으면 TB 배열 밖을 읽어 cosim이 죽는다)
//
//   src : 640*480 픽셀 / 4 = 76800 워드
//   dst : 480*480 픽셀 / 4 = 57600 워드
//
// ※ 테스트벤치의 SRC_W/SRC_H/ROI_W/ROI_H를 바꾸면 아래 두 값도 반드시 같이 바꿀 것.
// -----------------------------------------------------------------------------
#define SIM_SRC_DEPTH 76800
#define SIM_DST_DEPTH 57600

void roi_crop_wide(
    const ap_uint<128>* src,
    ap_uint<128>*       dst,
    int src_w4,
    int x0_4,
    int y0,
    int roi_w4,
    int roi_h)
{
    // --- 메모리 포트 (DDR 직접 접근) ---
    // 읽기/쓰기를 gmem0/gmem1 로 분리 → 서로 다른 물리 포트 사용
#pragma HLS INTERFACE m_axi     port=src offset=slave bundle=gmem0 \
        depth=SIM_SRC_DEPTH max_read_burst_length=256
#pragma HLS INTERFACE m_axi     port=dst offset=slave bundle=gmem1 \
        depth=SIM_DST_DEPTH max_write_burst_length=256

    // --- 제어 레지스터 (s_axilite): 인자 이름과 반드시 일치 ---
#pragma HLS INTERFACE s_axilite port=src
#pragma HLS INTERFACE s_axilite port=dst
#pragma HLS INTERFACE s_axilite port=src_w4
#pragma HLS INTERFACE s_axilite port=x0_4
#pragma HLS INTERFACE s_axilite port=y0
#pragma HLS INTERFACE s_axilite port=roi_w4
#pragma HLS INTERFACE s_axilite port=roi_h
#pragma HLS INTERFACE s_axilite port=return

    // 한 행을 담는 BRAM 버퍼 (읽기 burst → 여기 → 쓰기 burst)
    ap_uint<128> line[MAX_ROI_W4];

    row_loop: for (int y = 0; y < roi_h; y++) {
#pragma HLS LOOP_TRIPCOUNT min=16 max=480
        int off = (y0 + y) * src_w4 + x0_4;

        // 연속 주소 memcpy → HLS가 burst 로 합성
        memcpy(line, src + off, roi_w4 * sizeof(ap_uint<128>));
        memcpy(dst + y * roi_w4, line, roi_w4 * sizeof(ap_uint<128>));
    }
}
