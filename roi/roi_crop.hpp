#ifndef ROI_CROP_HPP
#define ROI_CROP_HPP

#include "ap_int.h"

// -----------------------------------------------------------------------------
// ROI Crop (128-bit wide)  --  데이터 흐름 2단계 (내부 / PL)
//
//   프레임 포맷 : XRGB8888 (픽셀당 32bit, uint32 하나. A/X 채널은 미사용 0)
//   전송 단위   : 128bit 워드 = 가로로 인접한 픽셀 4개
//
//   *_4 로 끝나는 인자는 모두 "128bit 워드 개수" 단위 (= 픽셀 수 / 4)
//   정렬 전제   : x0, roi_w, src_w 가 모두 4의 배수여야 한다.
//   폭 상한     : roi_w <= MAX_ROI_W (line 버퍼가 컴파일 타임 고정이므로)
//
//   출력(dst)은 이후 단계(letterbox 또는 DPU 전처리)가 읽어가는 DDR 버퍼가 된다.
//   crop에 쓴 (x0, y0, roi_w, roi_h)는 후처리에서 박스를 원본 좌표로
//   되돌릴 때 필요하므로 소프트웨어 쪽에 반드시 보관할 것.
//
//   현재 확정된 운용값 (좌석 고정):
//     src_w=640, src_h=480, x0=80, y0=0, roi_w=480, roi_h=480
// -----------------------------------------------------------------------------

#define MAX_ROI_W  1920           // 쓸 수 있는 최대 ROI 폭(픽셀)
#define MAX_ROI_W4 (MAX_ROI_W/4)  // 워드 단위 상한

void roi_crop_wide(
    const ap_uint<128>* src,   // 입력 프레임 (DDR)
    ap_uint<128>*       dst,   // crop 결과   (DDR)
    int src_w4,                // 원본 한 행의 워드 수 (= src_w / 4)
    int x0_4,                  // ROI 좌상단 x, 워드   (= x0 / 4)
    int y0,                    // ROI 좌상단 y, 행
    int roi_w4,                // ROI 폭, 워드         (= roi_w / 4)
    int roi_h);                // ROI 높이, 행

#endif // ROI_CROP_HPP
