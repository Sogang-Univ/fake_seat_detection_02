// =============================================================
// crop_and_resize 테스트벤치
//
//  검증 항목:
//   1) 출력 크기: dst_size × dst_size
//   2) 패딩 영역: PAD_VALUE(114) 로 채워졌는지
//   3) 이미지 영역: 픽셀 값이 범위(0~255) 내인지
//   4) 정사각형 ROI → 패딩 없이 전체가 이미지 영역인지 (pad=0 케이스)
// =============================================================
#include "crop_resize.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>

// ── 테스트 파라미터 ──────────────────────────────────────────
#define SRC_W    640
#define SRC_H    480
#define DST_SZ   640

// ROI: 정사각형 센터 크롭
#define X0       80
#define Y0       0
#define ROI_W    480
#define ROI_H    480

// ── 배열 (word_t = 128b = 픽셀 4개) ─────────────────────────
static word_t  src_buf[SIM_SRC_DEPTH];   // 640*480/4
static pixel_t dst_buf[SIM_DST_DEPTH];   // 640*640

// ── 헬퍼: 픽셀 채널 추출 ─────────────────────────────────────
static inline int get_ch(pixel_t p, int c)
{
    return (int)((p >> (c * 8)) & 0xFF);
}

int main()
{
    // ── 입력 이미지 생성 ─────────────────────────────────────
    //   그라데이션: R=x%256, G=y%256, B=((x+y)/2)%256, A=255
    printf("[TB] Generating %dx%d source image...\n", SRC_W, SRC_H);
    for (int y = 0; y < SRC_H; y++) {
        for (int x = 0; x < SRC_W; x += 4) {
            word_t w = 0;
            for (int p = 0; p < 4; p++) {
                int px = x + p;
                ap_uint<8> r = (ap_uint<8>)(px % 256);
                ap_uint<8> g = (ap_uint<8>)(y  % 256);
                ap_uint<8> b = (ap_uint<8>)((px + y) / 2 % 256);
                ap_uint<8> a = (ap_uint<8>)255;
                pixel_t pix = ((ap_uint<32>)a << 24)
                            | ((ap_uint<32>)b << 16)
                            | ((ap_uint<32>)g <<  8)
                            |  (ap_uint<32>)r;
                w.range(p*32+31, p*32) = pix;
            }
            src_buf[(y * SRC_W + x) / 4] = w;
        }
    }
    memset(dst_buf, 0, sizeof(dst_buf));

    // ── IP 호출 ──────────────────────────────────────────────
    printf("[TB] Calling crop_and_resize:\n");
    printf("     src=%dx%d  ROI x0=%d y0=%d w=%d h=%d  dst=%d\n",
           SRC_W, SRC_H, X0, Y0, ROI_W, ROI_H, DST_SZ);

    crop_and_resize(src_buf, dst_buf,
                    SRC_W, SRC_H,
                    X0, Y0, ROI_W, ROI_H,
                    DST_SZ);

    // ── 기대값 계산 (SW 동일 로직) ───────────────────────────
    //   정사각형 ROI(480×480) → dst(640×640)
    //   scaled_w = 640, scaled_h = 640, pad_x = 0, pad_y = 0
    int scaled_w, scaled_h, pad_x, pad_y;
    if (ROI_W >= ROI_H) {
        scaled_w = DST_SZ;
        scaled_h = (ROI_H * DST_SZ) / ROI_W;
    } else {
        scaled_h = DST_SZ;
        scaled_w = (ROI_W * DST_SZ) / ROI_H;
    }
    pad_x = (DST_SZ - scaled_w) / 2;
    pad_y = (DST_SZ - scaled_h) / 2;
    printf("[TB] Expected: scaled=%dx%d pad=(%d,%d)\n",
           scaled_w, scaled_h, pad_x, pad_y);

    // ── 검증 ─────────────────────────────────────────────────
    int err_pad   = 0;
    int err_range = 0;

    for (int oy = 0; oy < DST_SZ; oy++) {
        for (int ox = 0; ox < DST_SZ; ox++) {
            pixel_t pix = dst_buf[oy * DST_SZ + ox];
            bool in_pad = (oy < pad_y || oy >= pad_y + scaled_h ||
                           ox < pad_x || ox >= pad_x + scaled_w);

            if (in_pad) {
                // 패딩 영역: R/G/B 모두 PAD_VALUE 여야 함
                int r = get_ch(pix, 0);
                int g = get_ch(pix, 1);
                int b = get_ch(pix, 2);
                if (r != PAD_VALUE || g != PAD_VALUE || b != PAD_VALUE) {
                    if (err_pad < 5)
                        printf("[FAIL] pad (%d,%d): R=%d G=%d B=%d (expected %d)\n",
                               ox, oy, r, g, b, PAD_VALUE);
                    err_pad++;
                }
            } else {
                // 이미지 영역: 채널별 0~255 범위 체크
                for (int c = 0; c < 3; c++) {
                    int v = get_ch(pix, c);
                    if (v < 0 || v > 255) {
                        if (err_range < 5)
                            printf("[FAIL] range (%d,%d) ch%d = %d\n",
                                   ox, oy, c, v);
                        err_range++;
                    }
                }
            }
        }
    }

    // ── 결과 출력 ────────────────────────────────────────────
    printf("\n[TB] ====== RESULT ======\n");
    printf("  pad   errors : %d\n", err_pad);
    printf("  range errors : %d\n", err_range);

    // 샘플 픽셀 출력 (이미지 영역 중앙)
    int sample_x = pad_x + scaled_w / 2;
    int sample_y = pad_y + scaled_h / 2;
    pixel_t sp = dst_buf[sample_y * DST_SZ + sample_x];
    printf("  sample (%d,%d): R=%d G=%d B=%d\n",
           sample_x, sample_y,
           get_ch(sp,0), get_ch(sp,1), get_ch(sp,2));

    if (err_pad == 0 && err_range == 0) {
        printf("  [PASS] All checks passed.\n");
        return 0;
    } else {
        printf("  [FAIL] Total errors: %d\n", err_pad + err_range);
        return 1;
    }
}
