#include "roi_crop_resize.h"


#define ROW_EMPTY (-1000)


// ============================================================
// 128-bit word 안에서
// 32-bit pixel 하나 추출
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
//
// 기존 blend4 연산 그대로 유지
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
//
// 이전 최적화에서 tmp BRAM 제거한 버전
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
// line buffer에서 pixel 하나 읽기
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
// Padding row producer
//
// 기존 out_line BRAM에 쓰는 대신
// 128-bit word를 stream으로 보냄
// ============================================================

static void make_padding_row(
    hls::stream<word_t>& out_stream,

    word_t pad_word,

    int dst_words
)
{
#pragma HLS INLINE off


    padding_row_loop:
    for (
        int w = 0;
        w < dst_words;
        w++
    )
    {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=160 max=160

        out_stream.write(
            pad_word
        );
    }
}


// ============================================================
// Resize row producer
//
// ★ 핵심 변경
//
// 기존:
//
//   pixel
//    ↓
//   out_line[widx]
//
// 변경:
//
//   pixel 4개 pack
//    ↓
//   hls::stream<word_t>
//
// 4픽셀마다 128-bit word 하나 생성
// ============================================================

static void resize_row_to_stream(
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

    hls::stream<word_t>& out_stream
)
{
#pragma HLS INLINE off


    word_t packed_word = 0;


    resize_pixel_loop:
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
        // Horizontal padding
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
        // Bilinear interpolation
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
                (
                    sx0 + 1
                )
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
        // 4 pixel -> 128-bit word
        // ====================================================

        int pidx =
            ox & 3;


        // 새 4-pixel group 시작
        if (pidx == 0)
        {
            packed_word = 0;
        }


        packed_word.range(
            pidx * 32 + 31,
            pidx * 32
        )
            =
            pix;


        // ----------------------------------------------------
        // pixel 4개가 모이면 stream으로 전송
        // ----------------------------------------------------

        if (pidx == 3)
        {
            out_stream.write(
                packed_word
            );
        }
    }
}


// ============================================================
// Stream -> DDR
//
// resize producer와 동시에 실행될 consumer
// ============================================================

static void write_row_from_stream(
    hls::stream<word_t>& out_stream,

    word_t* dst_row,

    int dst_words
)
{
#pragma HLS INLINE off


    write_output:
    for (
        int w = 0;
        w < dst_words;
        w++
    )
    {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=160 max=160


        word_t value =
            out_stream.read();


        dst_row[w] =
            value;
    }
}


// ============================================================
// Padding row DATAFLOW
// ============================================================

static void padding_row_dataflow(
    word_t* dst_row,

    word_t pad_word,

    int dst_words
)
{
#pragma HLS INLINE off
#pragma HLS DATAFLOW


    hls::stream<word_t> row_stream(
        "padding_row_stream"
    );


#pragma HLS STREAM variable=row_stream depth=2


    make_padding_row(
        row_stream,
        pad_word,
        dst_words
    );


    write_row_from_stream(
        row_stream,
        dst_row,
        dst_words
    );
}


// ============================================================
// Resize row DATAFLOW
//
// resize_row_to_stream()
//             |
//             | 128-bit FIFO
//             v
// write_row_from_stream()
//
// 두 함수가 동시에 실행된다.
// ============================================================

static void resize_row_dataflow(
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


    hls::stream<word_t> row_stream(
        "resize_row_stream"
    );


#pragma HLS STREAM variable=row_stream depth=2


    // --------------------------------------------------------
    // Producer
    // --------------------------------------------------------

    resize_row_to_stream(
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


    // --------------------------------------------------------
    // Consumer
    // --------------------------------------------------------

    write_row_from_stream(
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

    // ========================================================
    // AXI MASTER
    // ========================================================

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
    // Letterbox / resize size
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
    // Fixed point resize step
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
    // Output width in 128-bit words
    //
    // 640 pixels / 4 = 160 words
    // ========================================================

    const int dst_words =
        dst_size
        >> 2;


    // ========================================================
    // Row cache state
    // ========================================================

    bool phase =
        false;


    int cached_row =
        ROW_EMPTY;


    // ========================================================
    // Output row loop
    //
    // NOTE:
    //
    // 이 loop 자체에는 PIPELINE을 걸지 않는다.
    //
    // row 내부의
    //
    // resize -> stream -> write
    //
    // 에만 DATAFLOW를 적용한다.
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
        // Destination row address
        //
        // 현재 프로젝트 output stride는 640 pixels
        // = 160 × 128-bit words
        // ====================================================

        word_t* dst_row =
            dst
            +
            oy
            *
            (
                DST_SIZE / 4
            );


        // ====================================================
        // Padding row
        // ====================================================

        if (is_pad)
        {

            padding_row_dataflow(
                dst_row,
                pad_word,
                dst_words
            );
        }


        // ====================================================
        // Resize row
        // ====================================================

        else
        {

            // ------------------------------------------------
            // Vertical coordinate
            // ------------------------------------------------

            ap_uint<32> sy_fix =
                (
                    (ap_uint<32>)
                    (
                        oy
                        -
                        pad_y
                    )
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
                (
                    sy0 + 1
                )
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
            // Required source row load
            //
            // 기존 row reuse / phase 구조 그대로
            // =================================================

            if (
                cached_row
                !=
                sy0
            )
            {

                // ---------------------------------------------
                // 이전 row에서 한 줄만 진행한 경우
                //
                // 기존 한 line을 재사용하고
                // 새로운 line 하나만 DDR에서 읽는다.
                // ---------------------------------------------

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


                // ---------------------------------------------
                // Cache 재사용 불가능
                //
                // 두 source row 모두 load
                // ---------------------------------------------

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
            // ★ Stage-level DATAFLOW
            //
            // resize
            //   ↓
            // stream
            //   ↓
            // DDR write
            //
            // 기존 out_line BRAM이 사라진다.
            // =================================================

            resize_row_dataflow(
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
