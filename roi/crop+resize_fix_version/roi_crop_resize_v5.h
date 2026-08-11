#pragma once

#include "ap_int.h"
#include "hls_stream.h"


// ============================================================
// Types
// ============================================================

// RGBx 1 pixel = 32 bit
typedef ap_uint<32> pixel_t;

// DDR AXI bus = 128 bit = 4 pixels
typedef ap_uint<128> word_t;


// ============================================================
// Bilinear fixed point
// ============================================================

#define FRAC_BITS  12
#define FRAC_ONE   (1 << FRAC_BITS)


// ============================================================
// Fixed dimensions
//
// 이번 실험 버전은:
//
// Camera = 640 x 480
// ROI    = 480 x 480
// Output = 640 x 640
//
// x0는 반드시 4 pixel aligned라고 가정.
// 현재 x0=80이므로 만족.
// ============================================================

#define SRC_W_FIXED     640
#define SRC_H_FIXED     480

#define ROI_W_FIXED     480
#define ROI_H_FIXED     480

#define ROI_WORDS       120
// 480 pixels / 4 pixels per 128-bit word = 120

#define DST_SIZE        640


// ============================================================
// Padding
// ============================================================

#define PAD_VALUE       114
#define PAD_Q_VALUE     29


// ============================================================
// DDR depth
//
// INPUT:
// 640 x 480 x 4 bytes = 1,228,800 bytes
// /16 = 76,800 words
//
// OUTPUT:
// 640 x 640 x 3 bytes = 1,228,800 bytes
// /16 = 76,800 words
// ============================================================

#define SIM_SRC_DEPTH   76800
#define SIM_DST_DEPTH   76800


// ============================================================
// TOP
// ============================================================

void crop_and_resize(
    const word_t* src,
    word_t* dst,

    int src_w,
    int src_h,

    int x0,
    int y0,

    int roi_w,
    int roi_h,

    int dst_size
);
