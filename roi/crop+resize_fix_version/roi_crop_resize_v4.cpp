#include "roi_crop_resize.h"

#define ROW_EMPTY (-1000)


// ============================================================
// 16 pixels × RGB 3 bytes
//
// 16 × 24 bit = 384 bit
//
// 384 bit packet
//     ↓
// 3 × 128 bit DDR words
// ============================================================

typedef ap_uint<384> pack384_t;


// ============================================================
// INT8 quantization
//
// DPU input:
// fix_point = 6
// scale     = 64
//
// Software expression:
//
// q = (pixel * 64 + 127) / 255
//
// pixel = 0~255 범위에서는:
//
// q = (pixel + 2) >> 2
//
// 와 동일.
// ============================================================

static ap_uint<8> quantize_channel(
    ap_uint<8> value
)
{
#pragma HLS INLINE

    ap_uint<9> extended =
        (ap_uint<9>)value + 2;

    return
        (ap_uint<8>)
        (
            extended >> 2
        );
}


// ============================================================
// Bilinear interpolation
//
// 현재는 기존 동작을 그대로 유지하기 위해
// RGBx 4채널 모두 계산한다.
// Packing 최적화 효과부터 독립적으로 확인.
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


        ap_int<48> top =
            (
                (ap_int<48>)a
                << FRAC_BITS
            )
            +
            (
                (ap_int<48>)(b - a)
                * fx
            );


        ap_int<48> bot =
            (
                (ap_int<48>)d
                << FRAC_BITS
            )
            +
            (
                (ap_int<48>)(e - d)
                * fx
            );


        ap_int<64> val =
            (
                (ap_int<64>)top
                << FRAC_BITS
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
// DDR -> line buffer
// ============================================================

static void load_row(
    const word_t* src_row,
    word_t* lbuf,
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
// Read one RGBx pixel
// ============================================================

static pixel_t get_pix(
    const word_t* lbuf,
    int pixel_idx
)
{
#pragma HLS INLINE

    int word_idx =
        pixel_idx >> 2;

    int pixel_pos =
        pixel_idx & 3;

    word_t current =
        lbuf[word_idx];

    return current.range(
        pixel_pos * 32 + 31,
        pixel_pos * 32
    );
}


// ============================================================
// Resize + Quantize + 384-bit packing
//
// 핵심 변경점:
//
// 기존:
//   put_quant_pixel()
//   variable-indexed range
//
// 변경:
//   fixed 24-bit shift
//
// packet 최종 layout:
//
// bits [ 23:  0] = pixel 0  {B,G,R}
// bits [ 47: 24] = pixel 1
// ...
// bits [383:360] = pixel 15
//
// 메모리 byte 순서:
//
// R0 G0 B0 R1 G1 B1 ...
// ============================================================

static void resize_row_to_int8_stream(
    const word_t* line0,
    const word_t* line1,

    bool phase,

    int dst_size,

    int pad_x,
    int scaled_w,

    int roi_w,
    int x_offset,

    ap_uint<32> x_step,

    ap_uint<FRAC_BITS + 1> wy,

    pixel_t pad_pix,

    hls::stream<pack384_t>& out_stream
)
{
#pragma HLS INLINE off

    pack384_t packet = 0;


    resize_quant_loop:
    for (
        int ox = 0;
        ox < dst_size;
        ox++
    )
    {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=640 max=640

        pixel_t pix;


        // ====================================================
        // Padding pixel
        // ====================================================

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


        // ====================================================
        // Resize pixel
        // ====================================================

        else
        {
            ap_uint<32> sx_fix =
                (
                    (ap_uint<32>)
                    (
                        ox - pad_x
                    )
                )
                *
                x_step;


            int sx0 =
                (int)(
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


            if (
                sx0 >=
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
                sx0 + 1
                :
                sx0;


            int idx0 =
                sx0
                +
                x_offset;


            int idx1 =
                sx1
                +
                x_offset;


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


        // ====================================================
        // RGB extraction
        //
        // RGBx:
        //
        // bits [7:0]   = R
        // bits [15:8]  = G
        // bits [23:16] = B
        // ====================================================

        ap_uint<8> r =
            pix.range(
                7,
                0
            );

        ap_uint<8> g =
            pix.range(
                15,
                8
            );

        ap_uint<8> b =
            pix.range(
                23,
                16
            );


        // ====================================================
        // INT8 quantization
        // ====================================================

        ap_uint<8> qr =
            quantize_channel(
                r
            );

        ap_uint<8> qg =
            quantize_channel(
                g
            );

        ap_uint<8> qb =
            quantize_channel(
                b
            );


        // ====================================================
        // RGB 24-bit pixel
        //
        // bits:
        // [7:0]   R
        // [15:8]  G
        // [23:16] B
        //
        // Memory:
        // R G B
        // ====================================================

        ap_uint<24> rgb24 = 0;

        rgb24.range(
            7,
            0
        ) = qr;

        rgb24.range(
            15,
            8
        ) = qg;

        rgb24.range(
            23,
            16
        ) = qb;


        // ====================================================
        // Fixed 24-bit shift
        //
        // variable-indexed .range() 없음.
        // ====================================================

        packet =
            packet >> 24;

        packet.range(
            383,
            360
        ) =
            rgb24;


        // ====================================================
        // 16 pixels accumulated
        //
        // ox:
        // 15,31,47,...,639
        // ====================================================

        if (
            (ox & 15)
            ==
            15
        )
        {
            out_stream.write(
                packet
            );
        }
    }
}


// ============================================================
// Quantized padding packet generator
//
// 기존에는 640개의 pixel 각각에 대해
// put_quant_pixel() 수행.
//
// 변경:
// 동일한 RGB=(29,29,29) 16개로 구성된
// constant 384-bit packet을 만들어
// 40번 전송.
//
// 640 pixels / 16 = 40 packets
// ============================================================

static void make_quantized_padding_row(
    hls::stream<pack384_t>& out_stream,
    int dst_size
)
{
#pragma HLS INLINE off

    const ap_uint<8> qp =
        (ap_uint<8>)PAD_Q_VALUE;


    ap_uint<24> rgb24 = 0;

    rgb24.range(
        7,
        0
    ) = qp;

    rgb24.range(
        15,
        8
    ) = qp;

    rgb24.range(
        23,
        16
    ) = qp;


    // ========================================================
    // Build one 16-pixel constant packet
    // ========================================================

    pack384_t pad_packet = 0;


    build_padding_packet:
    for (
        int i = 0;
        i < 16;
        i++
    )
    {
#pragma HLS UNROLL

        pad_packet =
            pad_packet >> 24;

        pad_packet.range(
            383,
            360
        ) =
            rgb24;
    }


    int groups =
        dst_size >> 4;


    // ========================================================
    // 40 packets for 640 pixels
    // ========================================================

    padding_packet_loop:
    for (
        int g = 0;
        g < groups;
        g++
    )
    {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=40 max=40

        out_stream.write(
            pad_packet
        );
    }
}


// ============================================================
// 384-bit stream -> 128-bit DDR
//
// One packet:
//     384 bit
//
// becomes:
//
//     word 0 = bits 127:0
//     word 1 = bits 255:128
//     word 2 = bits 383:256
//
// 640 RGB pixels:
//
// 40 packet
// ×
// 3 words
// =
// 120 × 128-bit DDR words
//
// writer loop 자체는 120회 II=1 유지.
// ============================================================

static void write_int8_row(
    hls::stream<pack384_t>& out_stream,

    word_t* dst_row,

    int dst_words
)
{
#pragma HLS INLINE off

    pack384_t packet = 0;

    ap_uint<2> phase =
        0;


    write_int8_output:
    for (
        int w = 0;
        w < dst_words;
        w++
    )
    {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=120 max=120

        word_t out_word;


        // ====================================================
        // Every 3 output words:
        // read one 384-bit packet
        // ====================================================

        if (
            phase == 0
        )
        {
            packet =
                out_stream.read();

            out_word =
                packet.range(
                    127,
                    0
                );

            phase =
                1;
        }
        else if (
            phase == 1
        )
        {
            out_word =
                packet.range(
                    255,
                    128
                );

            phase =
                2;
        }
        else
        {
            out_word =
                packet.range(
                    383,
                    256
                );

            phase =
                0;
        }


        dst_row[w] =
            out_word;
    }
}


// ============================================================
// Resize + Quantize + Pack + DDR
// ============================================================

static void resize_quant_row_dataflow(
    const word_t* line0,
    const word_t* line1,

    bool phase,

    int dst_size,

    int pad_x,
    int scaled_w,

    int roi_w,
    int x_offset,

    ap_uint<32> x_step,

    ap_uint<FRAC_BITS + 1> wy,

    pixel_t pad_pix,

    word_t* dst_row,

    int dst_words
)
{
#pragma HLS INLINE off
#pragma HLS DATAFLOW


    hls::stream<pack384_t> row_stream(
        "resize_quant_stream"
    );


#pragma HLS STREAM \
    variable=row_stream \
    depth=2


    resize_row_to_int8_stream(
        line0,
        line1,

        phase,

        dst_size,

        pad_x,
        scaled_w,

        roi_w,
        x_offset,

        x_step,

        wy,

        pad_pix,

        row_stream
    );


    write_int8_row(
        row_stream,

        dst_row,

        dst_words
    );
}


// ============================================================
// Padding + DDR
// ============================================================

static void padding_quant_row_dataflow(
    word_t* dst_row,

    int dst_size,

    int dst_words
)
{
#pragma HLS INLINE off
#pragma HLS DATAFLOW


    hls::stream<pack384_t> row_stream(
        "padding_quant_stream"
    );


#pragma HLS STREAM \
    variable=row_stream \
    depth=2


    make_quantized_padding_row(
        row_stream,

        dst_size
    );


    write_int8_row(
        row_stream,

        dst_row,

        dst_words
    );
}


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
)
{

#pragma HLS INTERFACE m_axi \
    port=src \
    offset=slave \
    bundle=gmem0 \
    depth=SIM_SRC_DEPTH \
    max_read_burst_length=16 \
    max_widen_bitwidth=128


#pragma HLS INTERFACE m_axi \
    port=dst \
    offset=slave \
    bundle=gmem1 \
    depth=SIM_DST_DEPTH \
    max_write_burst_length=16 \
    max_widen_bitwidth=128


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
    // ========================================================

    static word_t line0[
        MAX_SRC_W / 4
    ];

    static word_t line1[
        MAX_SRC_W / 4
    ];


#pragma HLS BIND_STORAGE \
    variable=line0 \
    type=RAM_2P \
    impl=BRAM


#pragma HLS BIND_STORAGE \
    variable=line1 \
    type=RAM_2P \
    impl=BRAM


    // ========================================================
    // ROI alignment
    // ========================================================

    int x0_aligned =
        x0 & ~3;


    int x_offset =
        x0
        -
        x0_aligned;


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
        src_w
        >> 2;


    int x0_4 =
        x0_aligned
        >> 2;


    // ========================================================
    // Resize dimensions
    // ========================================================

    int scaled_w;
    int scaled_h;

    int pad_x;
    int pad_y;


    if (
        roi_w >=
        roi_h
    )
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
    // Padding RGBx pixel
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
    // Output words per row
    //
    // Current target:
    //
    // 640 × RGB 3 bytes
    // = 1920 bytes
    //
    // / 16 bytes
    // = 120 words
    //
    // Current design assumes dst_size*3 is divisible by 16.
    // 640 target에서는 정확히 성립.
    // ========================================================

    const int dst_words =
        (
            dst_size * 3
        )
        >> 4;


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


        word_t* dst_row =
            dst
            +
            oy
            *
            dst_words;


        // ====================================================
        // Padding row
        // ====================================================

        if (is_pad)
        {
            padding_quant_row_dataflow(
                dst_row,

                dst_size,

                dst_words
            );
        }


        // ====================================================
        // Active image row
        // ====================================================

        else
        {
            ap_uint<32> sy_fix =
                (
                    (ap_uint<32>)
                    (
                        oy - pad_y
                    )
                )
                *
                y_step;


            int sy0 =
                (int)(
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


            if (
                sy0 >=
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
                sy0 + 1
                :
                sy0;


            int abs_sy0 =
                y0
                +
                sy0;


            int abs_sy1 =
                y0
                +
                sy1;


            // =================================================
            // Source-row cache
            // =================================================

            if (
                cached_row
                !=
                sy0
            )
            {
                // =============================================
                // Previous row reuse
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
                // Load both rows
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
            // Resize
            // Quantize
            // 384-bit pack
            // 128-bit DDR write
            // =================================================

            resize_quant_row_dataflow(
                line0,
                line1,

                phase,

                dst_size,

                pad_x,
                scaled_w,

                roi_w,
                x_offset,

                x_step,

                wy,

                pad_pix,

                dst_row,

                dst_words
            );
        }
    }
}
