#pragma once

#include "ap_int.h"


// ============================================================
// Pixel / Bus type
// ============================================================

// 1 pixel = 32 bit
//
// [ 7: 0] = R
// [15: 8] = G
// [23:16] = B
// [31:24] = unused / alpha
typedef ap_uint<32> pixel_t;


// 4 pixels = 128 bit
typedef ap_uint<128> word_t;


// ============================================================
// Fixed-point parameter
// ============================================================

#define FRAC_BITS 12
#define FRAC_ONE  (1 << FRAC_BITS)


// ============================================================
// Size constants
// ============================================================

#define MAX_SRC_W   640

// 최대 source/ROI width 640 pixels
// 4 pixels / 128-bit word
#define MAX_ROI_W4  160


// 최대 output size
#define MAX_DST     1280


// 현재 프로젝트에서는 YOLO 입력 640x640 고정
#define DST_SIZE    640


// ============================================================
// Padding
// ============================================================

#define PAD_VALUE   114


// ============================================================
// C/RTL cosimulation depth
// ============================================================

// source:
//
// 640 * 480 pixels
// / 4 pixels per 128-bit word
//
// = 76800 words
#define SIM_SRC_DEPTH 76800


// destination:
//
// 640 * 640 pixels
// / 4 pixels per 128-bit word
//
// = 102400 words
//
// ★ 기존 dst가 pixel_t*일 때는 409600이었지만
//   이제 word_t*이므로 element 개수도 1/4이 된다.
#define SIM_DST_DEPTH 102400


// ============================================================
// Top function
// ============================================================
//
// ★ 변경점
//
// 기존:
//     pixel_t* dst
//
// 변경:
//     word_t* dst
//
// source / destination 모두 128-bit AXI word 사용
// ============================================================

void crop_and_resize(
    const word_t* src,
    word_t*       dst,

    int src_w,
    int src_h,

    int x0,
    int y0,

    int roi_w,
    int roi_h,

    int dst_size
);
