#include "roi_crop_resize.h"


#define ROW_EMPTY (-1000)


// ============================================================
// 128-bit word 안에서 32-bit pixel 하나 추출
// ============================================================

static inline pixel_t unpack(
    word_t w,
    int idx
)
{
#pragma HLS INLINE

    return (pixel_t)(
        w >> (idx * 32)
    );
}


// ============================================================
// Bilinear interpolation
// ============================================================

static pixel_t blend4(
    pixel_t p00,
    pixel_t p01,
    pixel_t p10,
    pixel_t p11,

    ap_uint<FRAC_BITS + 1> wx,
    ap_uint<FRAC_BITS + 1> wy
)
{
#pragma HLS INLINE


    pixel_t out = 0;


ch_loop:
    for (
        int c = 0;
        c < 4;
        c++
    )
    {
#pragma HLS UNROLL


        ap_int<32> a =
            (ap_int<32>)
            (ap_uint<8>)
            p00.range(
                c * 8 + 7,
                c * 8
            );


        ap_int<32> b =
            (ap_int<32>)
            (ap_uint<8>)
            p01.range(
                c * 8 + 7,
                c * 8
            );


        ap_int<32> d =
            (ap_int<32>)
            (ap_uint<8>)
            p10.range(
                c * 8 + 7,
                c * 8
            );


        ap_int<32> e =
            (ap_int<32>)
            (ap_uint<8>)
            p11.range(
                c * 8 + 7,
                c * 8
            );


        ap_int<32> fx =
            (ap_int<32>)wx;


        ap_int<32> fy =
            (ap_int<32>)wy;


        // ----------------------------------------------------
        // horizontal interpolation - top
        // ----------------------------------------------------

        ap_int<48> top =
            (
                (ap_int<48>)a
                <<
                FRAC_BITS
            )
            +
            (
                (ap_int<48>)(b - a)
                *
                fx
            );


        // ----------------------------------------------------
        // horizontal interpolation - bottom
        // ----------------------------------------------------

        ap_int<48> bot =
            (
                (ap_int<48>)d
                <<
                FRAC_BITS
            )
            +
            (
                (ap_int<48>)(e - d)
                *
                fx
            );


        // ----------------------------------------------------
        // vertical interpolation
        // ----------------------------------------------------

        ap_int<64> val =
            (
                (ap_int<64>)top
                <<
                FRAC_BITS
            )
            +
            (
                (
                    (ap_int<64>)bot
                    -
                    (ap_int<64>)top
                )
                *
                (ap_int<64>)fy
            );


        // ----------------------------------------------------
        // rounding
        // ----------------------------------------------------

        ap_int<64> r =
            (
                val
                +
                (
                    (ap_int<64>)1
                    <<
                    (
                        FRAC_BITS * 2
                        - 1
                    )
                )
            )
            >>
            (
                FRAC_BITS * 2
            );


        // ----------------------------------------------------
        // clamp
        // ----------------------------------------------------

        if (r < 0)
        {
            r = 0;
        }


        if (r > 255)
        {
            r = 255;
        }


        out.range(
            c * 8 + 7,
            c * 8
        )
            =
            (ap_uint<8>)r;
    }


    return out;
}


// ============================================================
// DDR 한 행 읽기
//
// ★ 1차 최적화
//
// 기존:
//
// DDR
//  ↓
// tmp[]
//  ↓
// line buffer
//
// 변경:
//
// DDR
//  ↓
// line buffer
//
// 기존 copy_loop 제거
// ============================================================

static void load_row(
    const word_t* src_row,
    word_t*       lbuf,

    int roi_w4
)
{
#pragma HLS INLINE off


load_row_loop:
    for (
        int w = 0;
        w < MAX_ROI_W4;
        w++
    )
    {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=160 max=160


        if (w < roi_w4)
        {
            lbuf[w] =
                src_row[w];
        }
        else
        {
            lbuf[w] =
                (word_t)0;
        }
    }
}


// ============================================================
// line buffer에서 pixel 하나 추출
// ============================================================

static inline pixel_t get_pix(
    const word_t* lbuf,
    int pixel_idx
)
{
#pragma HLS INLINE


    int w =
        pixel_idx >> 2;


    int pidx =
        pixel_idx & 3;


    word_t current_word =
        lbuf[w];


    pixel_t result =
        current_word.range(
            pidx * 32 + 31,
            pidx * 32
        );


    return result;
}


// ============================================================
// TOP
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
)
{

    // ========================================================
    // AXI MASTER
    //
    // ★ src / dst 모두 128-bit native
    // ========================================================

#pragma HLS INTERFACE m_axi port=src \
    offset=slave \
    bundle=gmem0 \
    depth=SIM_SRC_DEPTH \
    max_read_burst_length=16 \
    max_widen_bitwidth=128


#pragma HLS INTERFACE m_axi port=dst \
    offset=slave \
    bundle=gmem1 \
    depth=SIM_DST_DEPTH \
    max_write_burst_length=16 \
    max_widen_bitwidth=128


    // ========================================================
    // AXI-LITE
    // ========================================================

#pragma HLS INTERFACE s_axilite port=src
#pragma HLS INTERFACE s_axilite port=dst

#pragma HLS INTERFACE s_axilite port=src_w
#pragma HLS INTERFACE s_axilite port=src_h

#pragma HLS INTERFACE s_axilite port=x0
#pragma HLS INTERFACE s_axilite port=y0

#pragma HLS INTERFACE s_axilite port=roi_w
#pragma HLS INTERFACE s_axilite port=roi_h

#pragma HLS INTERFACE s_axilite port=dst_size

#pragma HLS INTERFACE s_axilite port=return


    // ========================================================
    // Line buffers
    //
    // 한 line = 640 pixels
    //          = 160 × 128-bit words
    // ========================================================

    static word_t line0[
        MAX_SRC_W / 4
    ];


    static word_t line1[
        MAX_SRC_W / 4
    ];


#pragma HLS BIND_STORAGE variable=line0 \
    type=RAM_2P impl=BRAM

#pragma HLS BIND_STORAGE variable=line1 \
    type=RAM_2P impl=BRAM


    // ========================================================
    // Output line buffer
    //
    // 4 pixels per word
    //
    // 640 output pixels
    // = 160 words
    // ========================================================

    word_t out_line[
        MAX_DST / 4
    ];


#pragma HLS BIND_STORAGE variable=out_line \
    type=RAM_2P impl=BRAM


    // ========================================================
    // ROI alignment
    // ========================================================

    int x0_aligned =
        x0 & ~3;


    int x_offset =
        x0 - x0_aligned;


    int roi_w4 =
        (
            x_offset
            +
            roi_w
            +
            3
        )
        >> 2;


    int src_w4 =
        src_w >> 2;


    int x0_4 =
        x0_aligned >> 2;


    // ========================================================
    // Letterbox / resize size
    // ========================================================

    int scaled_w;
    int scaled_h;

    int pad_x;
    int pad_y;


    if (roi_w >= roi_h)
    {
        scaled_w =
            dst_size;


        scaled_h =
            (
                roi_h
                *
                dst_size
            )
            /
            roi_w;
    }
    else
    {
        scaled_h =
            dst_size;


        scaled_w =
            (
                roi_w
                *
                dst_size
            )
            /
            roi_h;
    }


    pad_x =
        (
            dst_size
            -
            scaled_w
        )
        >> 1;


    pad_y =
        (
            dst_size
            -
            scaled_h
        )
        >> 1;


    // ========================================================
    // Fixed-point resize step
    // ========================================================

    const ap_uint<32> x_step =
        (
            (
                (ap_uint<64>)roi_w
                <<
                FRAC_BITS
            )
            /
            scaled_w
        );


    const ap_uint<32> y_step =
        (
            (
                (ap_uint<64>)roi_h
                <<
                FRAC_BITS
            )
            /
            scaled_h
        );


    // ========================================================
    // Padding pixel
    // ========================================================

    const pixel_t pad_pix =
        (
            (ap_uint<32>)PAD_VALUE
            << 16
        )
        |
        (
            (ap_uint<32>)PAD_VALUE
            << 8
        )
        |
        (ap_uint<32>)PAD_VALUE;


    // ========================================================
    // 4 padding pixels = one 128-bit word
    // ========================================================

    const word_t pad_word =
        (
            (word_t)pad_pix
            << 96
        )
        |
        (
            (word_t)pad_pix
            << 64
        )
        |
        (
            (word_t)pad_pix
            << 32
        )
        |
        (word_t)pad_pix;


    // ========================================================
    // Row cache state
    // ========================================================

    bool phase =
        false;


    int cached_row =
        ROW_EMPTY;


    // ========================================================
    // Output row loop
    // ========================================================

out_row_loop:
    for (
        int oy = 0;
        oy < dst_size;
        oy++
    )
    {
#pragma HLS LOOP_TRIPCOUNT min=640 max=640


        bool is_pad =
            (
                oy < pad_y
                ||
                oy >=
                pad_y + scaled_h
            );


        // ====================================================
        // Padding row
        // ====================================================

        if (is_pad)
        {

pad_fill:
            for (
                int ox4 = 0;
                ox4 < DST_SIZE / 4;
                ox4++
            )
            {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=160 max=160


                out_line[ox4] =
                    pad_word;
            }
        }


        // ====================================================
        // Resize row
        // ====================================================

        else
        {

            // =================================================
            // Y source position
            // =================================================

            ap_uint<32> sy_fix =
                (
                    ap_uint<32>
                )
                (
                    oy
                    -
                    pad_y
                )
                *
                y_step;


            int sy0 =
                (
                    int
                )
                (
                    sy_fix
                    >>
                    FRAC_BITS
                );


            ap_uint<
                FRAC_BITS + 1
            > wy =
                sy_fix
                &
                (
                    ap_uint<
                        FRAC_BITS + 1
                    >
                )
                (
                    FRAC_ONE - 1
                );


            // =================================================
            // Boundary clamp
            // =================================================

            if (
                sy0
                >=
                roi_h - 1
            )
            {
                sy0 =
                    roi_h - 1;
            }


            int sy1 =
                (
                    sy0 + 1
                    <
                    roi_h
                )
                ?
                (
                    sy0 + 1
                )
                :
                sy0;


            int abs_sy0 =
                y0 + sy0;


            int abs_sy1 =
                y0 + sy1;


            // =================================================
            // 필요한 source row 두 줄 cache
            // =================================================

            if (
                cached_row
                !=
                sy0
            )
            {

                // =============================================
                // 이전 row와 연속되는 경우
                //
                // 기존 line 하나를 재사용하고
                // 새로운 row 하나만 읽는다.
                // =============================================

                if (
                    cached_row
                    !=
                    ROW_EMPTY
                    &&
                    cached_row
                    ==
                    sy0 - 1
                )
                {

                    phase =
                        !phase;


                    if (!phase)
                    {

                        load_row(
                            src
                            +
                            abs_sy1
                            *
                            src_w4
                            +
                            x0_4,

                            line1,

                            roi_w4
                        );
                    }

                    else
                    {

                        load_row(
                            src
                            +
                            abs_sy1
                            *
                            src_w4
                            +
                            x0_4,

                            line0,

                            roi_w4
                        );
                    }
                }


                // =============================================
                // cache를 재사용할 수 없는 경우
                //
                // 두 row 모두 다시 읽는다.
                // =============================================

                else
                {

                    phase =
                        false;


                    load_row(
                        src
                        +
                        abs_sy0
                        *
                        src_w4
                        +
                        x0_4,

                        line0,

                        roi_w4
                    );


                    load_row(
                        src
                        +
                        abs_sy1
                        *
                        src_w4
                        +
                        x0_4,

                        line1,

                        roi_w4
                    );
                }


                cached_row =
                    sy0;
            }


            // =================================================
            // Horizontal resize
            //
            // ★ 기존 II=1 구조 유지
            //
            // csynth.rpt에서 실제 Interval=1 확인됨.
            // =================================================

out_col_loop:
            for (
                int ox = 0;
                ox < dst_size;
                ox++
            )
            {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=640 max=640


                pixel_t pix;


                // =============================================
                // Horizontal padding
                // =============================================

                if (
                    ox < pad_x
                    ||
                    ox >=
                    pad_x + scaled_w
                )
                {

                    pix =
                        pad_pix;
                }


                // =============================================
                // Bilinear interpolation
                // =============================================

                else
                {

                    // -----------------------------------------
                    // Source X fixed-point position
                    // -----------------------------------------

                    ap_uint<32> sx_fix =
                        (
                            ap_uint<32>
                        )
                        (
                            ox
                            -
                            pad_x
                        )
                        *
                        x_step;


                    int sx0 =
                        (
                            int
                        )
                        (
                            sx_fix
                            >>
                            FRAC_BITS
                        );


                    ap_uint<
                        FRAC_BITS + 1
                    > wx =
                        sx_fix
                        &
                        (
                            ap_uint<
                                FRAC_BITS + 1
                            >
                        )
                        (
                            FRAC_ONE - 1
                        );


                    // -----------------------------------------
                    // Boundary clamp
                    // -----------------------------------------

                    if (
                        sx0
                        >=
                        roi_w - 1
                    )
                    {
                        sx0 =
                            roi_w - 1;
                    }


                    int sx1 =
                        (
                            sx0 + 1
                            <
                            roi_w
                        )
                        ?
                        (
                            sx0 + 1
                        )
                        :
                        sx0;


                    // -----------------------------------------
                    // ROI aligned buffer index
                    // -----------------------------------------

                    int idx0 =
                        sx0
                        +
                        x_offset;


                    int idx1 =
                        sx1
                        +
                        x_offset;


                    // -----------------------------------------
                    // Top row
                    // -----------------------------------------

                    pixel_t a0 =
                        get_pix(
                            phase
                            ?
                            line1
                            :
                            line0,

                            idx0
                        );


                    pixel_t a1 =
                        get_pix(
                            phase
                            ?
                            line1
                            :
                            line0,

                            idx1
                        );


                    // -----------------------------------------
                    // Bottom row
                    // -----------------------------------------

                    pixel_t b0 =
                        get_pix(
                            phase
                            ?
                            line0
                            :
                            line1,

                            idx0
                        );


                    pixel_t b1 =
                        get_pix(
                            phase
                            ?
                            line0
                            :
                            line1,

                            idx1
                        );


                    // -----------------------------------------
                    // Bilinear
                    // -----------------------------------------

                    pix =
                        blend4(
                            a0,
                            a1,
                            b0,
                            b1,

                            wx,
                            wy
                        );
                }


                // =============================================
                // 4 pixels → one 128-bit output word
                // =============================================

                int widx =
                    ox >> 2;


                int pidx =
                    ox & 3;


                word_t cur =
                    out_line[widx];


                cur.range(
                    pidx * 32 + 31,
                    pidx * 32
                )
                    =
                    pix;


                out_line[widx] =
                    cur;
            }
        }


        // ====================================================
        // ★ 1차 최적화 핵심
        //
        // 기존:
        //
        // pixel_t* dst
        //
        // memcpy / 32→128 widening
        //
        // write_output:
        //   Trip = 320
        //   II   = 3
        //   Latency = 960 cycles
        //
        //
        // 변경:
        //
        // word_t* dst
        //
        // 128-bit word 그대로 write
        //
        // 목표:
        //   Trip = 160
        //   II   = 1
        // ====================================================

write_output:
        for (
            int w = 0;
            w < DST_SIZE / 4;
            w++
        )
        {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=160 max=160


            dst[
                oy
                *
                (
                    DST_SIZE / 4
                )
                +
                w
            ]
                =
                out_line[w];
        }
    }
}
