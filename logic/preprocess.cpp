#include <cstdint>


// ============================================================
// C++ BGR -> RGB + INT8 Quantization
//
// 입력:
//   src_bgr
//     OpenCV resized image
//     uint8 HWC BGR
//
// 출력:
//   dst_rgb_int8
//     DPU input
//     int8 HWC RGB
//
// LUT:
//   Python에서 이미 검증한 256-entry quantization LUT
//
// 동작:
//   B G R
//     ↓
//   R G B
//     ↓
//   LUT lookup
//     ↓
//   INT8
//
// 한 번의 loop에서 색상 변환과 quantization을 동시에 수행.
// ============================================================

extern "C"
void bgr_to_rgb_int8(
    const uint8_t* src_bgr,
    int8_t* dst_rgb_int8,
    int width,
    int height,
    const int8_t* quant_lut
)
{
    if (
        src_bgr == nullptr ||
        dst_rgb_int8 == nullptr ||
        quant_lut == nullptr ||
        width <= 0 ||
        height <= 0
    )
    {
        return;
    }


    const int pixel_count =
        width * height;


    for (
        int i = 0;
        i < pixel_count;
        ++i
    )
    {
        const int base =
            i * 3;


        // OpenCV input
        //
        // src[base + 0] = B
        // src[base + 1] = G
        // src[base + 2] = R

        const uint8_t b =
            src_bgr[
                base + 0
            ];

        const uint8_t g =
            src_bgr[
                base + 1
            ];

        const uint8_t r =
            src_bgr[
                base + 2
            ];


        // ----------------------------------------------------
        // DPU input은 RGB 순서
        //
        // 동시에 LUT quantization 수행
        // ----------------------------------------------------

        dst_rgb_int8[
            base + 0
        ] =
            quant_lut[
                r
            ];


        dst_rgb_int8[
            base + 1
        ] =
            quant_lut[
                g
            ];


        dst_rgb_int8[
            base + 2
        ] =
            quant_lut[
                b
            ];
    }
}
