#pragma once
#include "ap_int.h"

// ── 픽셀 / 버스 타입 ──────────────────────────────────────
typedef ap_uint<32>  pixel_t;   // RGBA 1픽셀
typedef ap_uint<128> word_t;    // 픽셀 4개 묶음 (128b 버스)

// ── 고정소수점 파라미터 ────────────────────────────────────
#define FRAC_BITS  12
#define FRAC_ONE   (1 << FRAC_BITS)

// ── 크기 상수 ─────────────────────────────────────────────
#define MAX_SRC_W   640    // src 최대 너비 (픽셀)
#define MAX_ROI_W4  160    // ROI 최대 너비 (128b 워드 = 픽셀/4)
#define MAX_DST     1280   // dst_size 최대값 (픽셀)
#define DST_SIZE    640    // [문제2-A] 출력 고정 크기 — memcpy 상수화용

// ── 패딩 색상 ─────────────────────────────────────────────
#define PAD_VALUE   114

// ── cosim depth ───────────────────────────────────────────
#define SIM_SRC_DEPTH  76800    // 640*480 / 4  (128b 워드)
#define SIM_DST_DEPTH  409600   // 640*640       (32b 픽셀)

// ── 함수 선언 ─────────────────────────────────────────────
void crop_and_resize(
    const word_t* src,
    pixel_t*      dst,
    int src_w,
    int src_h,
    int x0,
    int y0,
    int roi_w,
    int roi_h,
    int dst_size
);
