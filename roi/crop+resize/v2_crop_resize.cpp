#include <string.h>
#include <ap_int.h>
#include <ap_fixed.h>

// =========================================================
// 매크로 및 상수 정의
// =========================================================
 #define MAX_SRC_W     640
#define MAX_DST        640
#define MAX_ROI_W4     (MAX_SRC_W / 4)
#define SIM_SRC_DEPTH  (640 * 480)
#define SIM_DST_DEPTH  (640 * 640)
#define DST_SIZE       640
#define ROW_EMPTY      (-1000)

// =========================================================
// 데이터 타입 정의
// =========================================================
typedef ap_uint<128> word_t;
typedef ap_uint<32>  pixel_t;

// Vitis HLS 네이티브 고정소수점 (16비트 소수점, 반올림 적용)
typedef ap_ufixed<16, 1, AP_RND, AP_SAT> frac_t;

// =============================================================
// Bilinear interpolation 및 AI 정규화(INT8) 처리 함수
// =============================================================
static pixel_t blend4(
    pixel_t p00,
    pixel_t p01,
    pixel_t p10,
    pixel_t p11,
    frac_t wx,
    frac_t wy
)
{
#pragma HLS INLINE
    pixel_t out = 0;

    ch_loop:
    for (int c = 0; c < 3; c++) // B, G, R 3채널만 연산 (A채널 생략)
    {
#pragma HLS UNROLL
        // 1. 각 채널의 8-bit 색상 추출
        ap_uint<8> a = p00.range(c * 8 + 7, c * 8);
        ap_uint<8> b = p01.range(c * 8 + 7, c * 8);
        ap_uint<8> d = p10.range(c * 8 + 7, c * 8);
        ap_uint<8> e = p11.range(c * 8 + 7, c * 8);

        // 2. 고정소수점 보간 연산 (Bilinear Interpolation)
        frac_t inv_wx = (frac_t)1.0 - wx;
        frac_t inv_wy = (frac_t)1.0 - wy;

        ap_ufixed<24, 8> top = a * inv_wx + b * wx;
        #pragma HLS BIND_OP variable=top op=mul impl=dsp latency=3
        ap_ufixed<24, 8> bot = d * inv_wx + e * wx;
        #pragma HLS BIND_OP variable=bot op=mul impl=dsp latency=3
        ap_ufixed<24, 8> val = top * inv_wy + bot * wy;
        #pragma HLS BIND_OP variable=val op=mul impl=dsp latency=3

        ap_uint<8> r_uint = (ap_uint<8>)val; // 0 ~ 255 픽셀값

        // 3. AI DPU 정규화: UINT8(0~255) -> INT8(-128~127)로 변환
        ap_int<8> r_int8 = (ap_int<8>)((int)r_uint - 128);

        // 4. BGR 순서 스왑 (OpenCV BGR -> 모델 학습 포맷 BGR)
        int oc = c;
        if (c == 0) oc = 2;      // R 채널은 byte2로
        else if (c == 2) oc = 0; // B 채널은 byte0으로

        // 32비트 버퍼에 해당 위치(byte)에 삽입
        out.range(oc * 8 + 7, oc * 8) = (ap_uint<8>)r_int8;
    }

    // 5. 4번째 바이트(Alpha)는 사용하지 않으므로 0으로 초기화
    out.range(31, 24) = 0;

    return out;
}

// =============================================================
// DDR 한 행 읽기 (Burst 추론 최적화)
// =============================================================
static void load_row(
    const word_t* src_row,
    word_t* lbuf,
    int roi_w4
)
{
#pragma HLS INLINE off

    read_loop:
    for (int w = 0; w < roi_w4; w++)
    {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_ROI_W4
        lbuf[w] = src_row[w];
    }

    pad_loop:
    for (int w = roi_w4; w < MAX_ROI_W4; w++)
    {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=0 max=MAX_ROI_W4
        lbuf[w] = (word_t)0;
    }
}

// =============================================================
// Line buffer에서 pixel 하나 추출
// =============================================================
static inline pixel_t get_pix(
    const word_t* lbuf,
    int pixel_idx
)
{
#pragma HLS INLINE
    int w = pixel_idx >> 2;
    int pidx = pixel_idx & 3;
    word_t current_word = lbuf[w];
    return current_word.range(pidx * 32 + 31, pidx * 32);
}

// =============================================================
// 하드웨어 커널 TOP 함수
// =============================================================
extern "C" {
void crop_and_resize(
    const word_t* src,
    pixel_t* dst,
    int src_w,
    int src_h,
    int x0,
    int y0,
    int roi_w,
    int roi_h,
    int dst_size
)
{
#pragma HLS INTERFACE m_axi port=src offset=slave bundle=gmem0 depth=SIM_SRC_DEPTH max_read_burst_length=256 max_widen_bitwidth=128
#pragma HLS INTERFACE m_axi port=dst offset=slave bundle=gmem1 depth=SIM_DST_DEPTH max_write_burst_length=256 max_widen_bitwidth=128

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

    // Line buffer 할당 (BRAM)
    static word_t line0[MAX_SRC_W / 4];
    static word_t line1[MAX_SRC_W / 4];
#pragma HLS BIND_STORAGE variable=line0 type=RAM_2P impl=BRAM
#pragma HLS BIND_STORAGE variable=line1 type=RAM_2P impl=BRAM

    // 출력 버퍼 (BRAM, 32-bit 배열로 통일)
    pixel_t out_line[MAX_DST];
#pragma HLS BIND_STORAGE variable=out_line type=RAM_2P impl=BRAM

    // 128-bit 정렬 오프셋 계산
    int x0_aligned = x0 & ~3;
    int x_offset = x0 - x0_aligned;
    int roi_w4 = (x_offset + roi_w + 3) >> 2;
    int src_w4 = src_w >> 2;
    int x0_4 = x0_aligned >> 2;

    // 리사이즈 픽셀 간격 스텝 계산 (고정소수점)
    ap_ufixed<32, 16> x_step = (ap_ufixed<32, 16>)roi_w / dst_size;
    ap_ufixed<32, 16> y_step = (ap_ufixed<32, 16>)roi_h / dst_size;

    bool phase = false;
    int cached_row = ROW_EMPTY;

    // Y축 누적 덧셈 변수 초기화 (곱셈기 완전 제거)
    ap_ufixed<32, 16> sy_fix = 0;

    // 출력 영상의 세로축(Y) 루프
    out_row_loop:
    for (int oy = 0; oy < dst_size; oy++)
    {
#pragma HLS LOOP_TRIPCOUNT min=640 max=640

        int sy0 = (int)sy_fix;
        frac_t wy = sy_fix - sy0;

        if (sy0 >= roi_h - 1) sy0 = roi_h - 1;
        int sy1 = (sy0 + 1 < roi_h) ? (sy0 + 1) : sy0;

        int abs_sy0 = y0 + sy0;
        int abs_sy1 = y0 + sy1;

        // DDR에서 버퍼로 데이터 불러오기 (Ping-Pong 로직)
        if (cached_row != sy0) {
            if (cached_row != ROW_EMPTY && cached_row == sy0 - 1) {
                phase = !phase;
                if (!phase) load_row(src + abs_sy1 * src_w4 + x0_4, line1, roi_w4);
                else        load_row(src + abs_sy1 * src_w4 + x0_4, line0, roi_w4);
            } else {
                phase = false;
                load_row(src + abs_sy0 * src_w4 + x0_4, line0, roi_w4);
                load_row(src + abs_sy1 * src_w4 + x0_4, line1, roi_w4);
            }
            cached_row = sy0;
        }

        // X축 누적 덧셈 변수 초기화
        ap_ufixed<32, 16> sx_fix = 0;

        // 출력 영상의 가로축(X) 루프
        out_col_loop:
        for (int ox = 0; ox < dst_size; ox++)
        {
#pragma HLS PIPELINE II=1

            int sx0 = (int)sx_fix;
            frac_t wx = sx_fix - sx0;

            if (sx0 >= roi_w - 1) sx0 = roi_w - 1;
            int sx1 = (sx0 + 1 < roi_w) ? (sx0 + 1) : sx0;

            int idx0 = sx0 + x_offset;
            int idx1 = sx1 + x_offset;

            // 주변 4개 픽셀 읽어오기
            pixel_t w0_0 = get_pix(line0, idx0);
            pixel_t w0_1 = get_pix(line0, idx1);
            pixel_t w1_0 = get_pix(line1, idx0);
            pixel_t w1_1 = get_pix(line1, idx1);

            pixel_t a0 = phase ? w1_0 : w0_0;
            pixel_t a1 = phase ? w1_1 : w0_1;
            pixel_t b0 = phase ? w0_0 : w1_0;
            pixel_t b1 = phase ? w0_1 : w1_1;

            // 보간 및 정규화 수행 후 버퍼에 삽입
            out_line[ox] = blend4(a0, a1, b0, b1, wx, wy);

            // 🚀 가로 좌표 누적 덧셈 (곱셈기 제거)
            sx_fix += x_step;
        }

        // 버스트 쓰기 루프
        burst_write_loop:
        for (int i = 0; i < dst_size; i++) {
#pragma HLS PIPELINE II=1
            dst[oy * dst_size + i] = out_line[i];
        }

        // 🚀 세로 좌표 누적 덧셈 (곱셈기 제거)
        sy_fix += y_step;
    }
}
}
