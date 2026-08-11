// =============================================================
// crop_and_resize Test Bench
//
// Current HLS output:
//   crop + resize + INT8 quantization
//
// Input:
//   RGBx 32-bit/pixel
//
//   [ 7: 0] = R
//   [15: 8] = G
//   [23:16] = B
//   [31:24] = A/X
//
// Output:
//   INT8 RGB NHWC
//
//   R0 G0 B0 R1 G1 B1 ...
//
//   640 x 640 x 3 bytes
//   = 1,228,800 bytes
//   = 76,800 x 128-bit words
//
// Part 1:
//   - output RGB byte order
//   - INT8 range
//   - padding value = PAD_Q_VALUE
//
// Part 2:
//   - float bilinear golden
//   - then quantize golden result
//   - compare with HLS INT8 output
//
// Important:
//   Only one main() must exist in the Test Bench group.
// =============================================================

#include "roi_crop_resize.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>


// =============================================================
// Dimensions
// =============================================================

#define SRC_W 640
#define SRC_H 480

#define TEST_DST 640


// =============================================================
// Buffers
// =============================================================

// Input:
// 640 * 480 pixels
// 4 pixels / 128-bit word
//
// = 76,800 words
static word_t src_buf[SIM_SRC_DEPTH];


// Output:
// 640 * 640 * 3 bytes
// / 16 bytes per 128-bit word
//
// = 76,800 words
static word_t dst_buf[SIM_DST_DEPTH];


// Golden source image
//
// [0] R
// [1] G
// [2] B
// [3] A
static unsigned char srcimg[SRC_H][SRC_W][4];


// =============================================================
// Software quantization reference
//
// HLS:
// q = (value + 2) >> 2
// =============================================================

static inline int quant_ref(int value)
{
    int q = (value + 2) >> 2;

    if (q < 0)
        q = 0;

    if (q > 127)
        q = 127;

    return q;
}


// =============================================================
// Read one byte from packed 128-bit output
// =============================================================

static inline int get_output_byte(
    int byte_index
)
{
    int word_index =
        byte_index >> 4;       // / 16

    int byte_pos =
        byte_index & 15;       // % 16

    word_t w =
        dst_buf[word_index];

    ap_uint<8> v =
        w.range(
            byte_pos * 8 + 7,
            byte_pos * 8
        );

    return (int)v;
}


// =============================================================
// Read output channel
//
// Memory layout:
//
// pixel 0 : R G B
// pixel 1 : R G B
// ...
//
// NHWC
// =============================================================

static inline int get_out_ch(
    int x,
    int y,
    int dst_size,
    int c
)
{
    long pixel_index =
        (long)y * dst_size + x;

    long byte_index =
        pixel_index * 3 + c;

    return get_output_byte(
        (int)byte_index
    );
}


// =============================================================
// Generate source image
//
// R = x % 256
// G = y % 256
// B = ((x+y)/2) % 256
// A = 255
//
// Input RGBx byte layout:
//
// [7:0]   R
// [15:8]  G
// [23:16] B
// [31:24] A
// =============================================================

static void gen_source()
{
    printf(
        "[TB] Generating %dx%d source image...\n",
        SRC_W,
        SRC_H
    );


    for (
        int y = 0;
        y < SRC_H;
        y++
    )
    {
        for (
            int x = 0;
            x < SRC_W;
            x += 4
        )
        {
            word_t w = 0;


            for (
                int p = 0;
                p < 4;
                p++
            )
            {
                int px =
                    x + p;


                int r =
                    px % 256;

                int g =
                    y % 256;

                int b =
                    ((px + y) / 2) % 256;

                int a =
                    255;


                srcimg[y][px][0] =
                    (unsigned char)r;

                srcimg[y][px][1] =
                    (unsigned char)g;

                srcimg[y][px][2] =
                    (unsigned char)b;

                srcimg[y][px][3] =
                    (unsigned char)a;


                pixel_t pix =
                    (
                        (ap_uint<32>)a
                        << 24
                    )
                    |
                    (
                        (ap_uint<32>)b
                        << 16
                    )
                    |
                    (
                        (ap_uint<32>)g
                        << 8
                    )
                    |
                    (ap_uint<32>)r;


                w.range(
                    p * 32 + 31,
                    p * 32
                )
                    =
                    pix;
            }


            src_buf[
                (y * SRC_W + x) / 4
            ]
                =
                w;
        }
    }
}


// =============================================================
// PART 1
// Basic output / channel / padding verification
// =============================================================

static bool run_basic_check()
{
    const int DST_SZ =
        640;

    const int X0 =
        80;

    const int Y0 =
        0;

    const int ROI_W =
        480;

    const int ROI_H =
        480;


    memset(
        dst_buf,
        0,
        sizeof(dst_buf)
    );


    printf(
        "\n[TB] Calling crop_and_resize:\n"
    );

    printf(
        "     src=%dx%d "
        "ROI x0=%d y0=%d w=%d h=%d "
        "dst=%d\n",

        SRC_W,
        SRC_H,

        X0,
        Y0,

        ROI_W,
        ROI_H,

        DST_SZ
    );


    crop_and_resize(
        src_buf,
        dst_buf,

        SRC_W,
        SRC_H,

        X0,
        Y0,

        ROI_W,
        ROI_H,

        DST_SZ
    );


    int scaled_w;
    int scaled_h;

    int pad_x;
    int pad_y;


    if (
        ROI_W >=
        ROI_H
    )
    {
        scaled_w =
            DST_SZ;

        scaled_h =
            (
                ROI_H
                *
                DST_SZ
            )
            /
            ROI_W;
    }
    else
    {
        scaled_h =
            DST_SZ;

        scaled_w =
            (
                ROI_W
                *
                DST_SZ
            )
            /
            ROI_H;
    }


    pad_x =
        (
            DST_SZ
            -
            scaled_w
        )
        / 2;


    pad_y =
        (
            DST_SZ
            -
            scaled_h
        )
        / 2;


    printf(
        "[TB] Expected: "
        "scaled=%dx%d "
        "pad=(%d,%d)\n",

        scaled_w,
        scaled_h,

        pad_x,
        pad_y
    );


    int err_pad =
        0;

    int err_range =
        0;


    for (
        int oy = 0;
        oy < DST_SZ;
        oy++
    )
    {
        for (
            int ox = 0;
            ox < DST_SZ;
            ox++
        )
        {
            bool in_pad =
                (
                    oy < pad_y
                    ||
                    oy >=
                    pad_y + scaled_h
                    ||
                    ox < pad_x
                    ||
                    ox >=
                    pad_x + scaled_w
                );


            int r =
                get_out_ch(
                    ox,
                    oy,
                    DST_SZ,
                    0
                );

            int g =
                get_out_ch(
                    ox,
                    oy,
                    DST_SZ,
                    1
                );

            int b =
                get_out_ch(
                    ox,
                    oy,
                    DST_SZ,
                    2
                );


            if (in_pad)
            {
                if (
                    r != PAD_Q_VALUE
                    ||
                    g != PAD_Q_VALUE
                    ||
                    b != PAD_Q_VALUE
                )
                {
                    if (
                        err_pad < 5
                    )
                    {
                        printf(
                            "[FAIL] pad (%d,%d): "
                            "R=%d G=%d B=%d "
                            "(expected %d)\n",

                            ox,
                            oy,

                            r,
                            g,
                            b,

                            PAD_Q_VALUE
                        );
                    }

                    err_pad++;
                }
            }
            else
            {
                // Current input is unsigned INT8 representation.
                //
                // Pixel 0~255 is quantized approximately to
                // 0~64.

                if (
                    r < 0
                    ||
                    r > 127
                    ||
                    g < 0
                    ||
                    g > 127
                    ||
                    b < 0
                    ||
                    b > 127
                )
                {
                    if (
                        err_range < 5
                    )
                    {
                        printf(
                            "[FAIL] range (%d,%d): "
                            "R=%d G=%d B=%d\n",

                            ox,
                            oy,

                            r,
                            g,
                            b
                        );
                    }

                    err_range++;
                }
            }
        }
    }


    printf(
        "\n[TB] ====== PART 1 RESULT ======\n"
    );


    printf(
        "  pad errors   : %d\n",
        err_pad
    );


    printf(
        "  range errors : %d\n",
        err_range
    );


    int sample_x =
        pad_x
        +
        scaled_w / 2;


    int sample_y =
        pad_y
        +
        scaled_h / 2;


    int sr =
        get_out_ch(
            sample_x,
            sample_y,
            DST_SZ,
            0
        );

    int sg =
        get_out_ch(
            sample_x,
            sample_y,
            DST_SZ,
            1
        );

    int sb =
        get_out_ch(
            sample_x,
            sample_y,
            DST_SZ,
            2
        );


    printf(
        "  sample (%d,%d): "
        "qR=%d qG=%d qB=%d\n",

        sample_x,
        sample_y,

        sr,
        sg,
        sb
    );


    bool ok =
        (
            err_pad == 0
            &&
            err_range == 0
        );


    if (ok)
    {
        printf(
            "  [PASS] Basic checks passed.\n"
        );
    }
    else
    {
        printf(
            "  [FAIL] Basic checks: %d errors\n",
            err_pad + err_range
        );
    }


    return ok;
}


// =============================================================
// Golden test case
//
// 1. float bilinear reference
// 2. round to UINT8 pixel
// 3. quantize
// 4. compare against HLS output
// =============================================================

static int golden_case(
    const char* nm,

    int X0,
    int Y0,

    int RW,
    int RH,

    int DST
)
{
    memset(
        dst_buf,
        0,
        sizeof(dst_buf)
    );


    crop_and_resize(
        src_buf,
        dst_buf,

        SRC_W,
        SRC_H,

        X0,
        Y0,

        RW,
        RH,

        DST
    );


    int scaled_w;
    int scaled_h;

    int pad_x;
    int pad_y;


    if (
        RW >= RH
    )
    {
        scaled_w =
            DST;

        scaled_h =
            (
                RH
                *
                DST
            )
            /
            RW;
    }
    else
    {
        scaled_h =
            DST;

        scaled_w =
            (
                RW
                *
                DST
            )
            /
            RH;
    }


    pad_x =
        (
            DST
            -
            scaled_w
        )
        / 2;


    pad_y =
        (
            DST
            -
            scaled_h
        )
        / 2;


    long x_step =
        (
            (long)RW
            <<
            FRAC_BITS
        )
        /
        scaled_w;


    long y_step =
        (
            (long)RH
            <<
            FRAC_BITS
        )
        /
        scaled_h;


    int maxd =
        0;

    int paderr =
        0;

    long ncmp =
        0;

    double sum =
        0.0;


    for (
        int oy = 0;
        oy < DST;
        oy++
    )
    {
        for (
            int ox = 0;
            ox < DST;
            ox++
        )
        {
            bool in_pad =
                (
                    oy < pad_y
                    ||
                    oy >=
                    pad_y + scaled_h
                    ||
                    ox < pad_x
                    ||
                    ox >=
                    pad_x + scaled_w
                );


            if (in_pad)
            {
                int r =
                    get_out_ch(
                        ox,
                        oy,
                        DST,
                        0
                    );

                int g =
                    get_out_ch(
                        ox,
                        oy,
                        DST,
                        1
                    );

                int b =
                    get_out_ch(
                        ox,
                        oy,
                        DST,
                        2
                    );


                if (
                    r != PAD_Q_VALUE
                    ||
                    g != PAD_Q_VALUE
                    ||
                    b != PAD_Q_VALUE
                )
                {
                    paderr++;
                }


                continue;
            }


            // =================================================
            // Y coordinate
            // =================================================

            long syf =
                (long)(
                    oy - pad_y
                )
                *
                y_step;


            int sy0 =
                syf
                >>
                FRAC_BITS;


            int wy =
                syf
                &
                (
                    FRAC_ONE - 1
                );


            if (
                sy0 >=
                RH - 1
            )
            {
                sy0 =
                    RH - 1;
            }


            int sy1 =
                (
                    sy0 + 1
                    <
                    RH
                )
                ?
                sy0 + 1
                :
                sy0;


            // =================================================
            // X coordinate
            // =================================================

            long sxf =
                (long)(
                    ox - pad_x
                )
                *
                x_step;


            int sx0 =
                sxf
                >>
                FRAC_BITS;


            int wx =
                sxf
                &
                (
                    FRAC_ONE - 1
                );


            if (
                sx0 >=
                RW - 1
            )
            {
                sx0 =
                    RW - 1;
            }


            int sx1 =
                (
                    sx0 + 1
                    <
                    RW
                )
                ?
                sx0 + 1
                :
                sx0;


            // =================================================
            // RGB
            // =================================================

            for (
                int c = 0;
                c < 3;
                c++
            )
            {
                double a =
                    srcimg[
                        Y0 + sy0
                    ][
                        X0 + sx0
                    ][c];


                double b =
                    srcimg[
                        Y0 + sy0
                    ][
                        X0 + sx1
                    ][c];


                double d =
                    srcimg[
                        Y0 + sy1
                    ][
                        X0 + sx0
                    ][c];


                double e =
                    srcimg[
                        Y0 + sy1
                    ][
                        X0 + sx1
                    ][c];


                double fx =
                    (double)wx
                    /
                    FRAC_ONE;


                double fy =
                    (double)wy
                    /
                    FRAC_ONE;


                double top =
                    a
                    +
                    (
                        b - a
                    )
                    *
                    fx;


                double bot =
                    d
                    +
                    (
                        e - d
                    )
                    *
                    fx;


                int ref_pixel =
                    (int)floor(
                        top
                        +
                        (
                            bot - top
                        )
                        *
                        fy
                        +
                        0.5
                    );


                if (
                    ref_pixel < 0
                )
                {
                    ref_pixel =
                        0;
                }


                if (
                    ref_pixel > 255
                )
                {
                    ref_pixel =
                        255;
                }


                // =============================================
                // Quantize golden pixel
                // =============================================

                int ref_q =
                    quant_ref(
                        ref_pixel
                    );


                // =============================================
                // Read HLS quantized result
                // =============================================

                int hls_q =
                    get_out_ch(
                        ox,
                        oy,
                        DST,
                        c
                    );


                int dd =
                    abs(
                        hls_q
                        -
                        ref_q
                    );


                if (
                    dd > maxd
                )
                {
                    maxd =
                        dd;
                }


                sum +=
                    dd;

                ncmp++;
            }
        }
    }


    // A 1-LSB difference is tolerated because the HLS
    // interpolator uses fixed-point arithmetic.
    bool ok =
        (
            maxd <= 1
            &&
            paderr == 0
        );


    printf(
        "%-22s "
        "scaled=%dx%d "
        "pad=(%d,%d) "
        "q_maxd=%d "
        "q_mean=%.4f "
        "paderr=%d  %s\n",

        nm,

        scaled_w,
        scaled_h,

        pad_x,
        pad_y,

        maxd,

        sum
        /
        (
            ncmp
            ?
            ncmp
            :
            1
        ),

        paderr,

        ok
        ?
        "OK"
        :
        "*** CHECK ***"
    );


    return
        ok
        ?
        0
        :
        1;
}


// =============================================================
// PART 2
// Edge cases
// =============================================================

static bool run_golden_checks()
{
    printf(
        "\n"
        "[TB] ====== PART 2 RESULT "
        "(quantized golden + edge cases) ======\n"
    );


    int f =
        0;


    f += golden_case(
        "center 480x480",
        80,
        0,
        480,
        480,
        640
    );


    f += golden_case(
        "wide ROI 480x240",
        80,
        120,
        480,
        240,
        640
    );


    f += golden_case(
        "tall ROI 240x480",
        200,
        0,
        240,
        480,
        640
    );


    f += golden_case(
        "small ROI 100x100",
        270,
        190,
        100,
        100,
        640
    );


    f += golden_case(
        "unaligned x0=83",
        83,
        0,
        480,
        480,
        640
    );


    f += golden_case(
        "unaligned x0=81",
        81,
        10,
        320,
        300,
        640
    );


    f += golden_case(
        "full frame 640x480",
        0,
        0,
        640,
        480,
        640
    );


    f += golden_case(
        "tiny 8x8",
        300,
        200,
        8,
        8,
        640
    );


    if (f)
    {
        printf(
            "\n=== %d case(s) flagged ===\n",
            f
        );
    }
    else
    {
        printf(
            "\n=== all edge cases OK ===\n"
        );
    }


    return
        f == 0;
}


// =============================================================
// PART 3
// Explicit RGB byte-order check
//
// 첫 출력 몇 pixel을 직접 출력해서
//
// R G B R G B ...
//
// 순서인지 쉽게 확인.
// =============================================================

static void print_first_output_pixels()
{
    printf(
        "\n"
        "[TB] ====== FIRST OUTPUT PIXELS ======\n"
    );


    for (
        int x = 0;
        x < 8;
        x++
    )
    {
        int r =
            get_out_ch(
                x,
                0,
                TEST_DST,
                0
            );

        int g =
            get_out_ch(
                x,
                0,
                TEST_DST,
                1
            );

        int b =
            get_out_ch(
                x,
                0,
                TEST_DST,
                2
            );


        printf(
            "pixel[%d] : "
            "R=%3d G=%3d B=%3d\n",

            x,
            r,
            g,
            b
        );
    }
}


// =============================================================
// main()
// =============================================================

int main()
{
    gen_source();


    bool part1_ok =
        run_basic_check();


    // PART 1에서 실행한 center ROI 결과를 그대로
    // 첫 pixel 확인에 사용.
    print_first_output_pixels();


    bool part2_ok =
        run_golden_checks();


    if (
        part1_ok
        &&
        part2_ok
    )
    {
        printf(
            "\n"
            "[TB] ================ "
            "ALL PASS "
            "================\n"
        );

        return 0;
    }
    else
    {
        printf(
            "\n"
            "[TB] ================ "
            "FAILED "
            "================\n"
        );

        return 1;
    }
}
