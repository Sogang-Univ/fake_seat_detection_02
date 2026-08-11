#include "roi_crop_resize_v5.h"

#define ROW_EMPTY (-1000)


// ============================================================
// 16 RGB pixels
//
// 16 x 24 bit = 384 bit
// ============================================================

typedef ap_uint<384> pack384_t;


// ============================================================
// INT8 quantization
//
// q = round(pixel * 64 / 255)
//
// integer pixel 0~255:
// q = (pixel + 2) >> 2
// ============================================================

static ap_uint<8> quantize_channel(
    ap_uint<8> value
)
{
#pragma HLS INLINE

    ap_uint<9> extended =
        (ap_uint<9>)value + 2;

    return (ap_uint<8>)(extended >> 2);
}


// ============================================================
// RGB 3-channel Bilinear
//
// 기존 blend4:
// R,G,B,X 4채널
//
// V5:
// R,G,B만 계산
// ============================================================

static pixel_t blend3(
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

blend_channel_loop:
    for (
        int c = 0;
        c < 3;
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
        ) =
            (ap_uint<8>)r;
    }


    // X channel은 사용하지 않음
    out.range(31, 24) = 0;

    return out;
}


// ============================================================
// DDR -> line buffer
//
// V4:
// 160 iterations
//
// V5:
// ROI 480 고정
// 120 x 128-bit word만 읽음
// ============================================================

static void load_row_480(
    const word_t* src_row,
    word_t* lbuf
)
{
#pragma HLS INLINE off

load_row_loop:
    for (
        int w = 0;
        w < ROI_WORDS;
        w++
    )
    {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=120 max=120

        lbuf[w] =
            src_row[w];
    }
}


// ============================================================
// 128-bit word 안에서 32-bit pixel 하나 추출
//
// variable range 대신 switch 사용.
// ============================================================

static pixel_t extract_pixel(
    word_t word,
    int pixel_pos
)
{
#pragma HLS INLINE

    switch (pixel_pos)
    {
        case 0:
            return word.range(31, 0);

        case 1:
            return word.range(63, 32);

        case 2:
            return word.range(95, 64);

        default:
            return word.range(127, 96);
    }
}


// ============================================================
// Two-word window에서 pixel 추출
//
// base_word     = 첫 번째 word index
// word0         = line[base_word]
// word1         = line[base_word + 1]
//
// 해당 pixel이 word0인지 word1인지 선택.
// ============================================================

static pixel_t get_pixel_from_window(
    word_t word0,
    word_t word1,

    int base_word,
    int pixel_idx
)
{
#pragma HLS INLINE

    int word_idx =
        pixel_idx >> 2;

    int pixel_pos =
        pixel_idx & 3;


    word_t selected =
        (
            word_idx ==
            base_word
        )
        ?
        word0
        :
        word1;


    return extract_pixel(
        selected,
        pixel_pos
    );
}


// ============================================================
// RGB -> quantized RGB24
// ============================================================

static ap_uint<24> quantize_rgb(
    pixel_t pix
)
{
#pragma HLS INLINE

    ap_uint<8> r =
        pix.range(7, 0);

    ap_uint<8> g =
        pix.range(15, 8);

    ap_uint<8> b =
        pix.range(23, 16);


    ap_uint<24> rgb24 = 0;


    rgb24.range(7, 0) =
        quantize_channel(r);

    rgb24.range(15, 8) =
        quantize_channel(g);

    rgb24.range(23, 16) =
        quantize_channel(b);


    return rgb24;
}


// ============================================================
// Resize + Quantize
//
// V5 핵심:
//
// loop 1 iteration에서
// output pixel 2개 계산
//
// 640 pixels
// /2
// = 320 iterations
//
// 목표:
// II = 1
// → 2 pixels / cycle
// ============================================================

static void resize_row_2pixel_stream(
    const word_t* line0,
    const word_t* line1,

    bool phase,

    int dst_size,

    int pad_x,
    int scaled_w,

    int roi_w,

    ap_uint<32> x_step,

    ap_uint<FRAC_BITS + 1> wy,

    pixel_t pad_pix,

    hls::stream<pack384_t>& out_stream
)
{
#pragma HLS INLINE off

    pack384_t packet = 0;


    const int pair_count =
        dst_size >> 1;


resize_2pixel_loop:
    for (
        int pair = 0;
        pair < pair_count;
        pair++
    )
    {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=320 max=320


        // ====================================================
        // Two output coordinates
        // ====================================================

        int ox0 =
            pair << 1;

        int ox1 =
            ox0 + 1;


        pixel_t pix0;
        pixel_t pix1;


        // ====================================================
        // Padding cases
        // ====================================================

        bool pad0 =
            (
                ox0 < pad_x
                ||
                ox0 >=
                pad_x + scaled_w
            );


        bool pad1 =
            (
                ox1 < pad_x
                ||
                ox1 >=
                pad_x + scaled_w
            );


        // ====================================================
        // Both padding
        // ====================================================

        if (
            pad0
            &&
            pad1
        )
        {
            pix0 = pad_pix;
            pix1 = pad_pix;
        }


        // ====================================================
        // Resize path
        //
        // 현재 프로젝트는
        // ROI=480
        // DST=640
        // pad_x=0
        //
        // 따라서 실제 실행에서는 대부분 여기로 들어옴.
        // ====================================================

        else
        {
            // ------------------------------------------------
            // pixel 0 coordinate
            // ------------------------------------------------

            ap_uint<32> sx_fix0 =
                (
                    (ap_uint<32>)
                    (
                        ox0 - pad_x
                    )
                )
                *
                x_step;


            int sx00 =
                (int)(
                    sx_fix0
                    >>
                    FRAC_BITS
                );


            ap_uint<
                FRAC_BITS + 1
            > wx0 =
                sx_fix0
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
                sx00 >=
                roi_w - 1
            )
            {
                sx00 =
                    roi_w - 1;
            }


            int sx01 =
                (
                    sx00 + 1
                    <
                    roi_w
                )
                ?
                sx00 + 1
                :
                sx00;


            // ------------------------------------------------
            // pixel 1 coordinate
            // ------------------------------------------------

            ap_uint<32> sx_fix1 =
                (
                    (ap_uint<32>)
                    (
                        ox1 - pad_x
                    )
                )
                *
                x_step;


            int sx10 =
                (int)(
                    sx_fix1
                    >>
                    FRAC_BITS
                );


            ap_uint<
                FRAC_BITS + 1
            > wx1 =
                sx_fix1
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
                sx10 >=
                roi_w - 1
            )
            {
                sx10 =
                    roi_w - 1;
            }


            int sx11 =
                (
                    sx10 + 1
                    <
                    roi_w
                )
                ?
                sx10 + 1
                :
                sx10;


            // =================================================
            // Source word window
            //
            // 480 -> 640에서는 연속 output 두 개가
            // 최대 약 3개의 연속 source pixel을 사용.
            //
            // 따라서 한 line에서 128-bit word
            // 최대 2개만 읽으면 충분.
            // =================================================

            int first_pixel =
                sx00;


            int last_pixel =
                sx11;


            int base_word =
                first_pixel >> 2;


            int last_word =
                last_pixel >> 2;


            // =================================================
            // line0 BRAM
            //
            // 최대 2 read
            // =================================================

            word_t l0_word0 =
                line0[
                    base_word
                ];


            word_t l0_word1 =
                (
                    last_word ==
                    base_word
                )
                ?
                l0_word0
                :
                line0[
                    base_word + 1
                ];


            // =================================================
            // line1 BRAM
            //
            // 최대 2 read
            // =================================================

            word_t l1_word0 =
                line1[
                    base_word
                ];


            word_t l1_word1 =
                (
                    last_word ==
                    base_word
                )
                ?
                l1_word0
                :
                line1[
                    base_word + 1
                ];


            // =================================================
            // Extract source pixels
            // =================================================

            pixel_t l0_a0 =
                get_pixel_from_window(
                    l0_word0,
                    l0_word1,
                    base_word,
                    sx00
                );


            pixel_t l0_a1 =
                get_pixel_from_window(
                    l0_word0,
                    l0_word1,
                    base_word,
                    sx01
                );


            pixel_t l0_b0 =
                get_pixel_from_window(
                    l0_word0,
                    l0_word1,
                    base_word,
                    sx10
                );


            pixel_t l0_b1 =
                get_pixel_from_window(
                    l0_word0,
                    l0_word1,
                    base_word,
                    sx11
                );


            pixel_t l1_a0 =
                get_pixel_from_window(
                    l1_word0,
                    l1_word1,
                    base_word,
                    sx00
                );


            pixel_t l1_a1 =
                get_pixel_from_window(
                    l1_word0,
                    l1_word1,
                    base_word,
                    sx01
                );


            pixel_t l1_b0 =
                get_pixel_from_window(
                    l1_word0,
                    l1_word1,
                    base_word,
                    sx10
                );


            pixel_t l1_b1 =
                get_pixel_from_window(
                    l1_word0,
                    l1_word1,
                    base_word,
                    sx11
                );


            // =================================================
            // top / bottom row selection
            // =================================================

            pixel_t p00_0 =
                phase
                ?
                l1_a0
                :
                l0_a0;

            pixel_t p01_0 =
                phase
                ?
                l1_a1
                :
                l0_a1;

            pixel_t p10_0 =
                phase
                ?
                l0_a0
                :
                l1_a0;

            pixel_t p11_0 =
                phase
                ?
                l0_a1
                :
                l1_a1;


            pixel_t p00_1 =
                phase
                ?
                l1_b0
                :
                l0_b0;

            pixel_t p01_1 =
                phase
                ?
                l1_b1
                :
                l0_b1;

            pixel_t p10_1 =
                phase
                ?
                l0_b0
                :
                l1_b0;

            pixel_t p11_1 =
                phase
                ?
                l0_b1
                :
                l1_b1;


            // =================================================
            // Two bilinear calculations in parallel
            // =================================================

            pixel_t resized0 =
                blend3(
                    p00_0,
                    p01_0,
                    p10_0,
                    p11_0,

                    wx0,
                    wy
                );


            pixel_t resized1 =
                blend3(
                    p00_1,
                    p01_1,
                    p10_1,
                    p11_1,

                    wx1,
                    wy
                );


            pix0 =
                pad0
                ?
                pad_pix
                :
                resized0;


            pix1 =
                pad1
                ?
                pad_pix
                :
                resized1;
        }


        // ====================================================
        // Quantize two pixels
        // ====================================================

        ap_uint<24> rgb0 =
            quantize_rgb(
                pix0
            );


        ap_uint<24> rgb1 =
            quantize_rgb(
                pix1
            );


        // ====================================================
        // Insert two pixels at once
        //
        // 기존:
        // shift 24 bit x 2
        //
        // 변경:
        // shift 48 bit once
        //
        // Sequential equivalent:
        //
        // pixel0 -> [359:336]
        // pixel1 -> [383:360]
        // ====================================================

        packet =
            packet >> 48;


        packet.range(
            359,
            336
        ) =
            rgb0;


        packet.range(
            383,
            360
        ) =
            rgb1;


        // ====================================================
        // 8 pair
        // =
        // 16 pixels
        //
        // 384-bit packet output
        // ====================================================

        if (
            (pair & 7)
            ==
            7
        )
        {
            out_stream.write(
                packet
            );
        }
    }
}


// ============================================================
// Quantized padding packet
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

    rgb24.range(7, 0) =
        qp;

    rgb24.range(15, 8) =
        qp;

    rgb24.range(23, 16) =
        qp;


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
// ============================================================

static void write_int8_row(
    hls::stream<pack384_t>& out_stream,

    word_t* dst_row,

    int dst_words
)
{
#pragma HLS INLINE off

    pack384_t packet = 0;

    ap_uint<2> phase = 0;


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

            phase = 1;
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

            phase = 2;
        }

        else
        {
            out_word =
                packet.range(
                    383,
                    256
                );

            phase = 0;
        }


        dst_row[w] =
            out_word;
    }
}


// ============================================================
// Resize + write DATAFLOW
// ============================================================

static void resize_quant_row_dataflow(
    const word_t* line0,
    const word_t* line1,

    bool phase,

    int dst_size,

    int pad_x,
    int scaled_w,

    int roi_w,

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


    resize_row_2pixel_stream(
        line0,
        line1,

        phase,

        dst_size,

        pad_x,
        scaled_w,

        roi_w,

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
// Padding DATAFLOW
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
    // Fixed 480-pixel line buffers
    //
    // 120 x 128 bit
    // ========================================================

    static word_t line0[
        ROI_WORDS
    ];

    static word_t line1[
        ROI_WORDS
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
    // Current experiment assumption
    //
    // x0 = 80
    // therefore 4-pixel aligned
    // ========================================================

    int x0_4 =
        x0 >> 2;


    int src_w4 =
        src_w >> 2;


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
    // Fixed point step
    //
    // 480 -> 640:
    //
    // 480/640 = 0.75
    //
    // x_step = 3072
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
    // Padding RGBx
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
    // Output rows
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
                y0 + sy0;


            int abs_sy1 =
                y0 + sy1;


            // =================================================
            // Source row cache
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
                        load_row_480(
                            src
                            +
                            abs_sy1
                            *
                            src_w4
                            +
                            x0_4,

                            line1
                        );
                    }
                    else
                    {
                        load_row_480(
                            src
                            +
                            abs_sy1
                            *
                            src_w4
                            +
                            x0_4,

                            line0
                        );
                    }
                }


                // =============================================
                // Initial / discontinuous:
                // load both rows
                // =============================================

                else
                {
                    phase =
                        false;


                    load_row_480(
                        src
                        +
                        abs_sy0
                        *
                        src_w4
                        +
                        x0_4,

                        line0
                    );


                    load_row_480(
                        src
                        +
                        abs_sy1
                        *
                        src_w4
                        +
                        x0_4,

                        line1
                    );
                }


                cached_row =
                    sy0;
            }


            // =================================================
            // 2 pixels/cycle resize
            // + quant
            // + 384 pack
            // + DDR write
            // =================================================

            resize_quant_row_dataflow(
                line0,
                line1,

                phase,

                dst_size,

                pad_x,
                scaled_w,

                roi_w,

                x_step,
                wy,

                pad_pix,

                dst_row,

                dst_words
            );
        }
    }
}
