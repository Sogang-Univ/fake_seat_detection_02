#ifndef LETTERBOX_HPP
#define LETTERBOX_HPP

#include "ap_int.h"

// -----------------------------------------------------------------------------
// Letterbox Resize (bilinear)  --  데이터 흐름 3단계를 PL로 이전
//
//   입력 : crop IP 출력 (임의 크기, XRGB8888)
//   출력 : DST_SIZE x DST_SIZE (YOLO 입력)
//
//   비율을 유지한 채 축소하고, 남는 영역은 회색(114)으로 채운다.
//   → 화면이 잘리지 않으므로 좌석 전체가 보존된다.
//
//   예) 640x480 입력 → 640x480 유지 + 위아래 80px 패딩 → 640x640
//       480x480 입력 → 640x640 로 확대 (패딩 없음)
//
//   ★ 후처리(step 5)에서 박스를 원본 좌표로 되돌리려면
//     gain, pad_x, pad_y 가 필요하다. 커널이 계산한 값과 동일하게
//     소프트웨어에서도 계산하거나, 소프트웨어에서 넘긴 값을 보관할 것.
//
//     x_src = (x_dst - pad_x) / gain
//     y_src = (y_dst - pad_y) / gain
// -----------------------------------------------------------------------------

#define DST_SIZE   640            // YOLO 입력 크기 (정사각)
#define MAX_SRC_W  1920           // 지원하는 최대 입력 폭
#define PAD_VALUE  114            // letterbox 패딩 색상 (YOLO 관례)

// 고정소수점 설정: 좌표/가중치를 16비트 소수부로 표현
#define FRAC_BITS  16
#define FRAC_ONE   (1 << FRAC_BITS)

typedef ap_uint<32>  pixel_t;     // XRGB8888
typedef ap_uint<64>  fixed_t;     // 고정소수점 누산용

void letterbox_resize(
    const pixel_t* src,   // 입력 이미지 (DDR) - crop IP 출력
    pixel_t*       dst,   // 출력 DST_SIZE x DST_SIZE (DDR)
    int src_w,            // 입력 폭
    int src_h,            // 입력 높이
    int scaled_w,         // 비율 유지 축소 후 폭   (소프트웨어에서 계산)
    int scaled_h,         // 비율 유지 축소 후 높이 (소프트웨어에서 계산)
    int pad_x,            // 좌측 패딩 = (DST_SIZE - scaled_w) / 2
    int pad_y);           // 상단 패딩 = (DST_SIZE - scaled_h) / 2

#endif // LETTERBOX_HPP
