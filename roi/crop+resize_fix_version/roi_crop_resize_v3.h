#pragma once

#include "ap_int.h"
#include "hls_stream.h"

// ============================================================
// Pixel / AXI word type
//
// pixel_t : RGBx 1 pixel = 32 bit
// word_t  : 4 pixels = 128 bit
// ============================================================

typedef ap_uint<32>  pixel_t;
typedef ap_uint<128> word_t;


// ============================================================
// Fixed-point
// ============================================================

#define FRAC_BITS  12
#define FRAC_ONE   (1 << FRAC_BITS)


// ============================================================
// Maximum dimensions
// ============================================================

#define MAX_SRC_W   640
#define MAX_ROI_W4  160

#define MAX_DST     1280

// 실제 프로젝트에서는 640x640 고정
#define DST_SIZE    640


// ============================================================
// Letterbox padding
// ============================================================

#define PAD_VALUE   114


// ============================================================
// AXI depth
//
// SRC:
// 640 * 480 pixels
// 4 pixels / 128-bit word
//
// = 76800 words
//
// DST:
// 640 * 640 pixels
// 4 pixels / 128-bit word
//
// = 102400 words
// ============================================================

#define SIM_SRC_DEPTH  76800
#define SIM_DST_DEPTH  102400


// ============================================================
// Top function
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
