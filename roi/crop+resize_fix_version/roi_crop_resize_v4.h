#pragma once

#include "ap_int.h"
#include "hls_stream.h"


// ============================================================
// Types
// ============================================================

// 입력:
// 한 pixel = RGBx 32 bit
typedef ap_uint<32> pixel_t;

// AXI bus:
// 128 bit
typedef ap_uint<128> word_t;


// ============================================================
// Fixed-point parameters for bilinear interpolation
// ============================================================

#define FRAC_BITS  12
#define FRAC_ONE   (1 << FRAC_BITS)


// ============================================================
// Dimension limits
// ============================================================

#define MAX_SRC_W   640
#define MAX_ROI_W4  160
#define MAX_DST     1280

#define DST_SIZE    640


// ============================================================
// Padding
// ============================================================

#define PAD_VALUE   114

// round(114 * 64 / 255) = 29
#define PAD_Q_VALUE 29


// ============================================================
// AXI depth
//
// INPUT:
//
// 640 × 480 × 4 bytes
// = 1,228,800 bytes
//
// / 16 bytes per 128-bit word
// = 76,800 words
//
// OUTPUT:
//
// 640 × 640 × 3 bytes
// = 1,228,800 bytes
//
// / 16 bytes
// = 76,800 words
// ============================================================

#define SIM_SRC_DEPTH  76800
#define SIM_DST_DEPTH  76800


// ============================================================
// Top
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
