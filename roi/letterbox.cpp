#include "letterbox.hpp"
#include <cstring>

// cosim용 depth (테스트벤치 배열 크기와 반드시 일치)
//   src : 640*480 = 307200
//   dst : 640*640 = 409600
#define SIM_SRC_DEPTH 307200
#define SIM_DST_DEPTH 409600

// 캐시가 비어 있음을 나타내는 값.
//   -1 을 쓰면 sy0==0 일 때 (cached_row == sy0-1) 이 참이 되어
//   비어 있는 버퍼를 재사용해 버린다. 충분히 작은 음수를 쓴다.
#define ROW_EMPTY (-1000)

// -----------------------------------------------------------------------------
// 채널별 bilinear 보간
//   (b-a) 가 음수가 될 수 있으므로 중간 계산은 반드시 부호 있는 타입으로.
// -----------------------------------------------------------------------------
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

        // 가로 방향: top = a + (b-a)*wx,  bot = d + (e-d)*wx
        ap_int<48> top = ((ap_int<48>)a << FRAC_BITS) + (ap_int<48>)(b - a) * fx;
        ap_int<48> bot = ((ap_int<48>)d << FRAC_BITS) + (ap_int<48>)(e - d) * fx;

        // 세로 방향: val = top + (bot-top)*wy
        ap_int<64> val = ((ap_int<64>)top << FRAC_BITS)
                       + ((ap_int<64>)bot - (ap_int<64>)top) * (ap_int<64>)fy;

        // 소수부 2회분 제거 + 반올림
        ap_int<64> r = (val + ((ap_int<64>)1 << (FRAC_BITS*2 - 1)))
                       >> (FRAC_BITS * 2);

        if (r < 0)   r = 0;
        if (r > 255) r = 255;

        out.range(c*8+7, c*8) = (ap_uint<8>)r;
    }
    return out;
}

void letterbox_resize(
    const pixel_t* src,
    pixel_t*       dst,
    int src_w,
    int src_h,
    int scaled_w,
    int scaled_h,
    int pad_x,
    int pad_y)
{
    // --- 메모리 포트 ---
#pragma HLS INTERFACE m_axi     port=src offset=slave bundle=gmem0 \
        depth=SIM_SRC_DEPTH max_read_burst_length=256
#pragma HLS INTERFACE m_axi     port=dst offset=slave bundle=gmem1 \
        depth=SIM_DST_DEPTH max_write_burst_length=256

    // --- 제어 레지스터 ---
#pragma HLS INTERFACE s_axilite port=src
#pragma HLS INTERFACE s_axilite port=dst
#pragma HLS INTERFACE s_axilite port=src_w
#pragma HLS INTERFACE s_axilite port=src_h
#pragma HLS INTERFACE s_axilite port=scaled_w
#pragma HLS INTERFACE s_axilite port=scaled_h
#pragma HLS INTERFACE s_axilite port=pad_x
#pragma HLS INTERFACE s_axilite port=pad_y
#pragma HLS INTERFACE s_axilite port=return

    // [핵심] 두 행 버퍼를 "별개 배열"로 유지한다.
    //   → 각 배열에서 2번씩만 읽으므로 RAM_2P 포트로 II=1 달성 가능.
    //   2D 배열([2][W])로 합치면 한 메모리에서 4번 읽게 되어 II가 2 이상으로 떨어진다.
    static pixel_t line0[MAX_SRC_W];
    static pixel_t line1[MAX_SRC_W];
#pragma HLS BIND_STORAGE variable=line0 type=RAM_2P impl=BRAM
#pragma HLS BIND_STORAGE variable=line1 type=RAM_2P impl=BRAM

    pixel_t out_line[DST_SIZE];

    // 스케일 계수 (고정소수점)
    const ap_uint<32> x_step = ((ap_uint<64>)src_w << FRAC_BITS) / scaled_w;
    const ap_uint<32> y_step = ((ap_uint<64>)src_h << FRAC_BITS) / scaled_h;

    const pixel_t pad_pix = ((ap_uint<32>)PAD_VALUE << 16)
                          | ((ap_uint<32>)PAD_VALUE <<  8)
                          |  (ap_uint<32>)PAD_VALUE;

    // phase = 0 : line0 이 위 행(sy0), line1 이 아래 행(sy1)
    // phase = 1 : line1 이 위 행(sy0), line0 이 아래 행(sy1)
    //   한 행 전진할 때 데이터를 복사하지 않고 phase 만 뒤집는다.
    bool phase      = false;
    int  cached_row = ROW_EMPTY;

    out_row_loop: for (int oy = 0; oy < DST_SIZE; oy++) {
#pragma HLS LOOP_TRIPCOUNT min=640 max=640

        // ---- 패딩 행은 계산 없이 채우고 넘어감 ----
        if (oy < pad_y || oy >= pad_y + scaled_h) {
            pad_fill: for (int ox = 0; ox < DST_SIZE; ox++) {
#pragma HLS PIPELINE II=1
                out_line[ox] = pad_pix;
            }
            memcpy(dst + oy * DST_SIZE, out_line, DST_SIZE * sizeof(pixel_t));
            continue;
        }

        // ---- 대응하는 입력 행 위치 ----
        ap_uint<32> sy_fix = (ap_uint<32>)(oy - pad_y) * y_step;
        int         sy0    = sy_fix >> FRAC_BITS;
        ap_uint<FRAC_BITS+1> wy = sy_fix & (FRAC_ONE - 1);

        if (sy0 > src_h - 1) sy0 = src_h - 1;
        int sy1 = (sy0 + 1 < src_h) ? (sy0 + 1) : sy0;

        // ---- 입력 행 로드 ----
        if (cached_row != sy0) {
            if (cached_row != ROW_EMPTY && cached_row == sy0 - 1) {
                // 한 칸 전진: 복사 없이 역할만 교체하고 새 행 하나만 읽는다.
                phase = !phase;
                // 교체 후 "아래 행" 자리에 sy1 을 적재.
                // if/else 로 대상을 컴파일 타임에 확정해야 burst 가 보장된다.
                if (!phase) memcpy(line1, src + sy1 * src_w, src_w * sizeof(pixel_t));
                else        memcpy(line0, src + sy1 * src_w, src_w * sizeof(pixel_t));
            } else {
                // 첫 진입 또는 점프: 두 행 모두 새로 읽고 phase 를 초기화
                phase = false;
                memcpy(line0, src + sy0 * src_w, src_w * sizeof(pixel_t));
                memcpy(line1, src + sy1 * src_w, src_w * sizeof(pixel_t));
            }
            cached_row = sy0;
        }

        // ---- 가로 보간 ----
        out_col_loop: for (int ox = 0; ox < DST_SIZE; ox++) {
#pragma HLS PIPELINE II=1

            if (ox < pad_x || ox >= pad_x + scaled_w) {
                out_line[ox] = pad_pix;
                continue;
            }

            ap_uint<32> sx_fix = (ap_uint<32>)(ox - pad_x) * x_step;
            int         sx0    = sx_fix >> FRAC_BITS;
            ap_uint<FRAC_BITS+1> wx = sx_fix & (FRAC_ONE - 1);

            if (sx0 > src_w - 1) sx0 = src_w - 1;
            int sx1 = (sx0 + 1 < src_w) ? (sx0 + 1) : sx0;

            // 각 배열에서 2번씩만 읽는다 (포트 2개로 충분 → II=1)
            pixel_t a0 = line0[sx0];
            pixel_t a1 = line0[sx1];
            pixel_t b0 = line1[sx0];
            pixel_t b1 = line1[sx1];

            // phase 에 따라 위/아래 행을 선택 (메모리 접근이 아닌 단순 mux)
            pixel_t p00 = phase ? b0 : a0;
            pixel_t p01 = phase ? b1 : a1;
            pixel_t p10 = phase ? a0 : b0;
            pixel_t p11 = phase ? a1 : b1;

            out_line[ox] = blend4(p00, p01, p10, p11, wx, wy);
        }

        memcpy(dst + oy * DST_SIZE, out_line, DST_SIZE * sizeof(pixel_t));
    }
}
