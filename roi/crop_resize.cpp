#include "crop_resize.hpp"
#include <cstring>

#define ROW_EMPTY (-1000)

static inline pixel_t unpack(word_t w, int idx)
{
#pragma HLS INLINE
    return (pixel_t)(w >> (idx * 32));
}

static pixel_t blend4(pixel_t p00, pixel_t p01,
                      pixel_t p10, pixel_t p11,
                      ap_uint<FRAC_BITS+1> wx,
                      ap_uint<FRAC_BITS+1> wy)
{
#pragma HLS INLINE
    pixel_t out = 0;
    ch_loop: for (int c = 0; c < 4; c++) {
#pragma HLS UNROLL
        ap_int<32> a = (ap_int<32>)(ap_uint<8>)p00.range(c*8+7, c*8);
        ap_int<32> b = (ap_int<32>)(ap_uint<8>)p01.range(c*8+7, c*8);
        ap_int<32> d = (ap_int<32>)(ap_uint<8>)p10.range(c*8+7, c*8);
        ap_int<32> e = (ap_int<32>)(ap_uint<8>)p11.range(c*8+7, c*8);
        ap_int<32> fx = (ap_int<32>)wx;
        ap_int<32> fy = (ap_int<32>)wy;
        ap_int<48> top = ((ap_int<48>)a << FRAC_BITS) + (ap_int<48>)(b - a) * fx;
        ap_int<48> bot = ((ap_int<48>)d << FRAC_BITS) + (ap_int<48>)(e - d) * fx;
        ap_int<64> val = ((ap_int<64>)top << FRAC_BITS)
                       + ((ap_int<64>)bot - (ap_int<64>)top) * (ap_int<64>)fy;
        ap_int<64> r = (val + ((ap_int<64>)1 << (FRAC_BITS*2 - 1)))
                       >> (FRAC_BITS * 2);
        if (r < 0)   r = 0;
        if (r > 255) r = 255;
        out.range(c*8+7, c*8) = (ap_uint<8>)r;
    }
    return out;
}

// =============================================================
// [문제1-C] load_row: lbuf를 word_t 단위로 통일
//   - unpack 없이 tmp[w] → lbuf[w] 1:1 복사 → II=1 확실
//   - out_col_loop에서 픽셀 꺼낼 때 word 안에서 비트 추출
// =============================================================
static void load_row(const word_t* src_row, word_t* lbuf, int roi_w4)
{
#pragma HLS INLINE off

    word_t tmp[MAX_ROI_W4];
#pragma HLS BIND_STORAGE variable=tmp type=RAM_2P impl=BRAM

    // AXI burst read → tmp
    burst_read: for (int w = 0; w < MAX_ROI_W4; w++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=MAX_ROI_W4 max=MAX_ROI_W4
        tmp[w] = (w < roi_w4) ? src_row[w] : (word_t)0;
    }

    // tmp → lbuf: 1워드 읽기 → 1워드 쓰기 → II=1 확실
    copy_loop: for (int w = 0; w < MAX_ROI_W4; w++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=MAX_ROI_W4 max=MAX_ROI_W4
        lbuf[w] = tmp[w];
    }
}

// =============================================================
// [문제1-C] word_t 라인버퍼에서 픽셀 1개 추출
//   w    = 워드 인덱스 (= pixel_idx / 4)
//   pidx = 워드 내 픽셀 위치 (0~3)
// =============================================================
static inline pixel_t get_pix(const word_t* lbuf, int pixel_idx)
{
#pragma HLS INLINE
    int w    = pixel_idx >> 2;
    int pidx = pixel_idx &  3;
    return (pixel_t)(lbuf[w] >> (pidx * 32));
}

void crop_and_resize(
    const word_t* src,
    pixel_t*      dst,
    int src_w,
    int src_h,
    int x0,
    int y0,
    int roi_w,
    int roi_h,
    int dst_size)
{
#pragma HLS INTERFACE m_axi port=src offset=slave bundle=gmem0 \
        depth=SIM_SRC_DEPTH max_read_burst_length=256
#pragma HLS INTERFACE m_axi port=dst offset=slave bundle=gmem1 \
        depth=SIM_DST_DEPTH max_write_burst_length=256
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

    // [문제1-C] 라인버퍼를 word_t 단위로 변경
    //   MAX_SRC_W(640) 픽셀 / 4 = 160 워드
    //   RAM_2P: out_col_loop에서 2개 픽셀 주소를 동시에 읽기 위해
    //   (get_pix에서 word 단위로 읽으므로 실제 포트 접근은 1~2회/사이클)
    static word_t line0[MAX_SRC_W / 4];
    static word_t line1[MAX_SRC_W / 4];
#pragma HLS BIND_STORAGE variable=line0 type=RAM_2P impl=BRAM
#pragma HLS BIND_STORAGE variable=line1 type=RAM_2P impl=BRAM

    word_t out_line[MAX_DST / 4];
#pragma HLS BIND_STORAGE variable=out_line type=RAM_1P impl=BRAM

    int x0_aligned = x0 & ~3;
    int x_offset   = x0 - x0_aligned;
    int roi_w4     = (x_offset + roi_w + 3) >> 2;
    int src_w4     = src_w >> 2;
    int x0_4       = x0_aligned >> 2;

    int scaled_w, scaled_h, pad_x, pad_y;
    if (roi_w >= roi_h) {
        scaled_w = dst_size;
        scaled_h = (roi_h * dst_size) / roi_w;
    } else {
        scaled_h = dst_size;
        scaled_w = (roi_w * dst_size) / roi_h;
    }
    pad_x = (dst_size - scaled_w) >> 1;
    pad_y = (dst_size - scaled_h) >> 1;

    const ap_uint<32> x_step = ((ap_uint<64>)roi_w << FRAC_BITS) / scaled_w;
    const ap_uint<32> y_step = ((ap_uint<64>)roi_h << FRAC_BITS) / scaled_h;
    const pixel_t pad_pix = ((ap_uint<32>)PAD_VALUE << 16)
                          | ((ap_uint<32>)PAD_VALUE <<  8)
                          |  (ap_uint<32>)PAD_VALUE;
    const word_t pad_word = ((word_t)pad_pix << 96)
                          | ((word_t)pad_pix << 64)
                          | ((word_t)pad_pix << 32)
                          | (word_t)pad_pix;

    bool phase      = false;
    int  cached_row = ROW_EMPTY;

    out_row_loop: for (int oy = 0; oy < dst_size; oy++) {
#pragma HLS LOOP_TRIPCOUNT min=640 max=640

        bool is_pad = (oy < pad_y || oy >= pad_y + scaled_h);

        if (is_pad) {
            pad_fill: for (int ox4 = 0; ox4 < MAX_DST/4; ox4++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=160 max=160
                out_line[ox4] = pad_word;
            }
        } else {
            ap_uint<32> sy_fix = (ap_uint<32>)(oy - pad_y) * y_step;
            int sy0 = (int)(sy_fix >> FRAC_BITS);
            ap_uint<FRAC_BITS+1> wy = sy_fix & (ap_uint<FRAC_BITS+1>)(FRAC_ONE - 1);
            if (sy0 >= roi_h - 1) sy0 = roi_h - 1;
            int sy1 = (sy0 + 1 < roi_h) ? (sy0 + 1) : sy0;
            int abs_sy0 = y0 + sy0;
            int abs_sy1 = y0 + sy1;

            if (cached_row != sy0) {
                if (cached_row != ROW_EMPTY && cached_row == sy0 - 1) {
                    phase = !phase;
                    if (!phase) load_row(src + abs_sy1 * src_w4 + x0_4,
                                         line1, roi_w4);
                    else        load_row(src + abs_sy1 * src_w4 + x0_4,
                                         line0, roi_w4);
                } else {
                    phase = false;
                    load_row(src + abs_sy0 * src_w4 + x0_4, line0, roi_w4);
                    load_row(src + abs_sy1 * src_w4 + x0_4, line1, roi_w4);
                }
                cached_row = sy0;
            }

            // [문제1-C] get_pix()로 word에서 픽셀 추출
            // sx0+x_offset, sx1+x_offset 두 주소가 같은 워드에 있으면
            // line0[w] 1번 읽기로 2픽셀 → RAM_2P 포트 충돌 없음 → II=1
            out_col_loop: for (int ox = 0; ox < dst_size; ox++) {
#pragma HLS PIPELINE II=1
                pixel_t pix;
                if (ox < pad_x || ox >= pad_x + scaled_w) {
                    pix = pad_pix;
                } else {
                    ap_uint<32> sx_fix = (ap_uint<32>)(ox - pad_x) * x_step;
                    int sx0 = (int)(sx_fix >> FRAC_BITS);
                    ap_uint<FRAC_BITS+1> wx = sx_fix & (ap_uint<FRAC_BITS+1>)(FRAC_ONE - 1);
                    if (sx0 >= roi_w - 1) sx0 = roi_w - 1;
                    int sx1 = (sx0 + 1 < roi_w) ? (sx0 + 1) : sx0;

                    int idx0 = sx0 + x_offset;
                    int idx1 = sx1 + x_offset;

                    // word_t 라인버퍼에서 픽셀 추출
                    pixel_t a0 = get_pix(phase ? line1 : line0, idx0);
                    pixel_t a1 = get_pix(phase ? line1 : line0, idx1);
                    pixel_t b0 = get_pix(phase ? line0 : line1, idx0);
                    pixel_t b1 = get_pix(phase ? line0 : line1, idx1);

                    pix = blend4(a0, a1, b0, b1, wx, wy);
                }

                // 4픽셀을 1워드로 pack
                int widx = ox >> 2;
                int pidx = ox &  3;
                word_t cur = out_line[widx];
                cur.range(pidx*32+31, pidx*32) = pix;
                out_line[widx] = cur;
            }
        }

        // [문제2-A] memcpy 크기를 상수(DST_SIZE)로 고정
        // → HLS가 burst 길이를 컴파일 타임에 확정 → Pipeline_3 해결
        memcpy(dst + oy * DST_SIZE,
               (pixel_t*)out_line,
               DST_SIZE * sizeof(pixel_t));
    }
}
