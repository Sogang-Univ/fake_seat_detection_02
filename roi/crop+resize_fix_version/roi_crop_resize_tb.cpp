// =============================================================
// crop_and_resize 테스트벤치 (단일 파일, main() 1개)
//
//  파트 1 (기본 검증) :
//   1) 출력 크기: dst_size × dst_size
//   2) 패딩 영역: PAD_VALUE(114) 로 채워졌는지
//   3) 이미지 영역: 픽셀 값이 범위(0~255) 내인지
//
//  파트 2 (golden 검증) :
//   float bilinear 로 계산한 정답값과 픽셀 단위로 비교.
//   비정사각 ROI, 비정렬 x0, 큰 확대율, 전체 프레임, 초소형 ROI 등
//   8가지 경계 조건을 추가로 검증한다.
//
//  주의: Vitis HLS 는 Test Bench 그룹의 모든 파일을 한 실행파일로
//  링크하므로 main() 은 프로젝트 전체에서 이 파일 하나에만 있어야 한다.
//  별도의 golden_tb.cpp 파일을 프로젝트에 추가하지 말 것.
// =============================================================
#include "roi_crop_resize.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>

// ── 공통 소스 이미지 버퍼 ────────────────────────────────────
#define SRC_W 640
#define SRC_H 480
static word_t  src_buf[SIM_SRC_DEPTH];   // 640*480/4
static pixel_t dst_buf[SIM_DST_DEPTH];   // 최대 640*640

// golden 비교용 원본 RGB 참조 이미지 (파트 1, 2 모두 같은 패턴 사용)
static unsigned char srcimg[SRC_H][SRC_W][4];

// ── 헬퍼: 픽셀 채널 추출 ─────────────────────────────────────
static inline int get_ch(pixel_t p, int c)
{
    return (int)((p >> (c * 8)) & 0xFF);
}

// ── 소스 이미지 생성 : R=x%256, G=y%256, B=((x+y)/2)%256, A=255 ─────
static void gen_source()
{
    printf("[TB] Generating %dx%d source image...\n", SRC_W, SRC_H);
    for (int y = 0; y < SRC_H; y++) {
        for (int x = 0; x < SRC_W; x += 4) {
            word_t w = 0;
            for (int p = 0; p < 4; p++) {
                int px = x + p;
                int r = px % 256;
                int g = y % 256;
                int b = (px + y) / 2 % 256;
                int a = 255;
                srcimg[y][px][0] = (unsigned char)r;
                srcimg[y][px][1] = (unsigned char)g;
                srcimg[y][px][2] = (unsigned char)b;
                srcimg[y][px][3] = (unsigned char)a;

                pixel_t pix = ((ap_uint<32>)a << 24)
                            | ((ap_uint<32>)b << 16)
                            | ((ap_uint<32>)g <<  8)
                            |  (ap_uint<32>)r;
                w.range(p*32+31, p*32) = pix;
            }
            src_buf[(y * SRC_W + x) / 4] = w;
        }
    }
}

// =============================================================
// 파트 1 : 기본 검증 (원본 팀원 TB 로직)
// =============================================================
static bool run_basic_check()
{
    const int DST_SZ = 640;
    const int X0 = 80, Y0 = 0, ROI_W = 480, ROI_H = 480;

    memset(dst_buf, 0, sizeof(dst_buf));

    printf("[TB] Calling crop_and_resize:\n");
    printf("     src=%dx%d  ROI x0=%d y0=%d w=%d h=%d  dst=%d\n",
           SRC_W, SRC_H, X0, Y0, ROI_W, ROI_H, DST_SZ);

    crop_and_resize(src_buf, dst_buf,
                    SRC_W, SRC_H,
                    X0, Y0, ROI_W, ROI_H,
                    DST_SZ);

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

    int err_pad = 0, err_range = 0;

    for (int oy = 0; oy < DST_SZ; oy++) {
        for (int ox = 0; ox < DST_SZ; ox++) {
            pixel_t pix = dst_buf[oy * DST_SZ + ox];
            bool in_pad = (oy < pad_y || oy >= pad_y + scaled_h ||
                           ox < pad_x || ox >= pad_x + scaled_w);

            if (in_pad) {
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

    printf("\n[TB] ====== PART 1 RESULT (basic) ======\n");
    printf("  pad   errors : %d\n", err_pad);
    printf("  range errors : %d\n", err_range);

    int sample_x = pad_x + scaled_w / 2;
    int sample_y = pad_y + scaled_h / 2;
    pixel_t sp = dst_buf[sample_y * DST_SZ + sample_x];
    printf("  sample (%d,%d): R=%d G=%d B=%d\n",
           sample_x, sample_y,
           get_ch(sp,0), get_ch(sp,1), get_ch(sp,2));

    bool ok = (err_pad == 0 && err_range == 0);
    printf(ok ? "  [PASS] Basic checks passed.\n"
              : "  [FAIL] Basic checks: %d errors\n", err_pad + err_range);
    return ok;
}

// =============================================================
// 파트 2 : golden(float bilinear) 대비 정밀 검증 + 경계 조건 8종
// =============================================================
static int golden_case(const char* nm, int X0, int Y0, int RW, int RH, int DST)
{
    memset(dst_buf, 0, sizeof(dst_buf));
    crop_and_resize(src_buf, dst_buf, SRC_W, SRC_H, X0, Y0, RW, RH, DST);

    int scaled_w, scaled_h, pad_x, pad_y;
    if (RW >= RH) { scaled_w = DST; scaled_h = (RH * DST) / RW; }
    else          { scaled_h = DST; scaled_w = (RW * DST) / RH; }
    pad_x = (DST - scaled_w) / 2;
    pad_y = (DST - scaled_h) / 2;

    long x_step = ((long)RW << FRAC_BITS) / scaled_w;
    long y_step = ((long)RH << FRAC_BITS) / scaled_h;

    int maxd = 0, paderr = 0;
    long ncmp = 0;
    double sum = 0;

    for (int oy = 0; oy < DST; oy++) {
        for (int ox = 0; ox < DST; ox++) {
            pixel_t pix = dst_buf[oy * DST + ox];
            bool in_pad = (oy < pad_y || oy >= pad_y + scaled_h ||
                           ox < pad_x || ox >= pad_x + scaled_w);
            if (in_pad) {
                if (get_ch(pix,0) != PAD_VALUE || get_ch(pix,1) != PAD_VALUE ||
                    get_ch(pix,2) != PAD_VALUE) paderr++;
                continue;
            }
            long syf = (long)(oy - pad_y) * y_step;
            int sy0 = syf >> FRAC_BITS;
            int wy  = syf & (FRAC_ONE - 1);
            if (sy0 >= RH - 1) sy0 = RH - 1;
            int sy1 = (sy0 + 1 < RH) ? sy0 + 1 : sy0;

            long sxf = (long)(ox - pad_x) * x_step;
            int sx0 = sxf >> FRAC_BITS;
            int wx  = sxf & (FRAC_ONE - 1);
            if (sx0 >= RW - 1) sx0 = RW - 1;
            int sx1 = (sx0 + 1 < RW) ? sx0 + 1 : sx0;

            for (int c = 0; c < 3; c++) {
                double a = srcimg[Y0+sy0][X0+sx0][c], b = srcimg[Y0+sy0][X0+sx1][c];
                double d = srcimg[Y0+sy1][X0+sx0][c], e = srcimg[Y0+sy1][X0+sx1][c];
                double fx = (double)wx / FRAC_ONE, fy = (double)wy / FRAC_ONE;
                double top = a + (b - a) * fx, bot = d + (e - d) * fx;
                int ref = (int)floor(top + (bot - top) * fy + 0.5);
                if (ref < 0) ref = 0; if (ref > 255) ref = 255;
                int dd = abs(get_ch(pix, c) - ref);
                if (dd > maxd) maxd = dd;
                sum += dd; ncmp++;
            }
        }
    }

    bool ok = (maxd <= 1 && paderr == 0);
    printf("%-22s scaled=%dx%d pad=(%d,%d) maxd=%d mean=%.3f paderr=%d  %s\n",
           nm, scaled_w, scaled_h, pad_x, pad_y, maxd,
           sum / (ncmp ? ncmp : 1), paderr, ok ? "OK" : "*** CHECK ***");
    return ok ? 0 : 1;
}

static bool run_golden_checks()
{
    printf("\n[TB] ====== PART 2 RESULT (golden + edge cases) ======\n");
    int f = 0;
    f += golden_case("center 480x480",     80,  0, 480, 480, 640);
    f += golden_case("wide ROI 480x240",   80,120, 480, 240, 640); // 가로가 긴 -> 상하 패딩
    f += golden_case("tall ROI 240x480",  200,  0, 240, 480, 640); // 세로가 긴 -> 좌우 패딩
    f += golden_case("small ROI 100x100", 270,190, 100, 100, 640); // 큰 확대율
    f += golden_case("unaligned x0=83",    83,  0, 480, 480, 640); // x0 4정렬 안됨
    f += golden_case("unaligned x0=81",    81, 10, 320, 300, 640); // 비정렬+비정사각
    f += golden_case("full frame 640x480",  0,  0, 640, 480, 640); // 전체 프레임
    f += golden_case("tiny 8x8",          300,200,   8,   8, 640); // 초소형 ROI

    printf(f ? "\n=== %d case(s) flagged ===\n" : "\n=== all edge cases OK ===\n", f);
    return f == 0;
}

// =============================================================
// main() — 프로젝트 전체에서 유일한 main
// =============================================================
int main()
{
    gen_source();

    bool part1_ok = run_basic_check();
    bool part2_ok = run_golden_checks();

    if (part1_ok && part2_ok) {
        printf("\n[TB] ================ ALL PASS ================\n");
        return 0;
    } else {
        printf("\n[TB] ================ FAILED ================\n");
        return 1;
    }
}
