#include "letterbox.hpp"
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cassert>

// ---- 테스트 설정: 640x480 → 640x640 (위아래 80px 패딩) ----
#define SRC_W 640
#define SRC_H 480

static pixel_t g_src[SRC_W * SRC_H];
static pixel_t g_dst[DST_SIZE * DST_SIZE];

static inline uint8_t ch(pixel_t p, int c) {
    return (uint8_t)((uint32_t)p >> (c * 8));
}

int main() {
    // -------------------------------------------------------------
    // letterbox 파라미터 계산 (소프트웨어가 하는 일과 동일)
    //   gain = min(DST/src_w, DST/src_h)
    // -------------------------------------------------------------
    double gain_w  = (double)DST_SIZE / SRC_W;
    double gain_h  = (double)DST_SIZE / SRC_H;
    double gain    = (gain_w < gain_h) ? gain_w : gain_h;

    int scaled_w = (int)(SRC_W * gain);
    int scaled_h = (int)(SRC_H * gain);
    int pad_x    = (DST_SIZE - scaled_w) / 2;
    int pad_y    = (DST_SIZE - scaled_h) / 2;

    printf("letterbox: %dx%d -> %dx%d (scaled %dx%d, pad %d,%d)\n",
           SRC_W, SRC_H, DST_SIZE, DST_SIZE,
           scaled_w, scaled_h, pad_x, pad_y);

    // -------------------------------------------------------------
    // 입력: 가로/세로 그라디언트
    //   R = x 비례, G = y 비례 → 보간 결과를 수식으로 예측 가능
    // -------------------------------------------------------------
    for (int y = 0; y < SRC_H; y++) {
        for (int x = 0; x < SRC_W; x++) {
            uint8_t r = (uint8_t)(x * 255 / (SRC_W - 1));
            uint8_t g = (uint8_t)(y * 255 / (SRC_H - 1));
            g_src[y * SRC_W + x] = ((uint32_t)g << 8) | (uint32_t)r;
        }
    }

    for (int i = 0; i < DST_SIZE * DST_SIZE; i++) g_dst[i] = 0;

    // -------------------------------------------------------------
    // 커널 실행
    // -------------------------------------------------------------
    letterbox_resize(g_src, g_dst,
                     SRC_W, SRC_H, scaled_w, scaled_h, pad_x, pad_y);

    int errors = 0;

    // -------------------------------------------------------------
    // 검증 1: 패딩 영역이 PAD_VALUE 로 채워졌는가
    // -------------------------------------------------------------
    for (int oy = 0; oy < DST_SIZE; oy++) {
        for (int ox = 0; ox < DST_SIZE; ox++) {
            bool is_pad = (oy < pad_y) || (oy >= pad_y + scaled_h) ||
                          (ox < pad_x) || (ox >= pad_x + scaled_w);
            if (!is_pad) continue;

            pixel_t p = g_dst[oy * DST_SIZE + ox];
            if (ch(p,0) != PAD_VALUE || ch(p,1) != PAD_VALUE ||
                ch(p,2) != PAD_VALUE) {
                if (errors < 5)
                    printf("  PAD MISMATCH at (%3d,%3d): %08x\n",
                           ox, oy, (uint32_t)p);
                errors++;
            }
        }
    }

    // -------------------------------------------------------------
    // 검증 2: 이미지 영역의 보간 값이 기대 그라디언트와 맞는가
    //   고정소수점 반올림 오차를 허용 (tolerance 2)
    // -------------------------------------------------------------
    const int TOL = 2;
    int max_diff = 0;

    for (int oy = pad_y; oy < pad_y + scaled_h; oy++) {
        for (int ox = pad_x; ox < pad_x + scaled_w; ox++) {
            double sx = (double)(ox - pad_x) * SRC_W / scaled_w;
            double sy = (double)(oy - pad_y) * SRC_H / scaled_h;
            if (sx > SRC_W - 1) sx = SRC_W - 1;
            if (sy > SRC_H - 1) sy = SRC_H - 1;

            int exp_r = (int)(sx * 255 / (SRC_W - 1) + 0.5);
            int exp_g = (int)(sy * 255 / (SRC_H - 1) + 0.5);

            pixel_t p = g_dst[oy * DST_SIZE + ox];
            int dr = abs((int)ch(p,0) - exp_r);
            int dg = abs((int)ch(p,1) - exp_g);

            if (dr > max_diff) max_diff = dr;
            if (dg > max_diff) max_diff = dg;

            if (dr > TOL || dg > TOL) {
                if (errors < 10)
                    printf("  PIX MISMATCH at (%3d,%3d): "
                           "got R=%3d G=%3d, exp R=%3d G=%3d\n",
                           ox, oy, ch(p,0), ch(p,1), exp_r, exp_g);
                errors++;
            }
        }
    }

    printf("max channel diff = %d (tolerance %d)\n", max_diff, TOL);

    if (errors == 0) {
        printf("PASS: letterbox %dx%d -> %dx%d verified\n",
               SRC_W, SRC_H, DST_SIZE, DST_SIZE);
        return 0;
    }
    printf("FAIL: %d mismatches\n", errors);
    return 1;
}
