#include "roi_crop.hpp"
#include <cstdio>
#include <cstdint>
#include <cassert>

// ---- 테스트 프레임/ROI (가로 관련 값은 모두 4의 배수) ----
//   실제 운용값과 동일: 640x480 프레임에서 중앙 480x480 crop
#define SRC_W 640
#define SRC_H 480
#define X0    80
#define Y0    0
#define ROI_W 480
#define ROI_H 480

// 워드 단위 크기 → 커널의 depth 값과 반드시 일치해야 함
#define SRC_WORDS (SRC_W * SRC_H / 4)   // 76800
#define DST_WORDS (ROI_W * ROI_H / 4)   // 57600

// ap_uint<128> 배열을 직접 사용한다.
// (uint32 배열을 reinterpret_cast 하면 cosim에서 깨질 수 있음)
static ap_uint<128> g_src[SRC_WORDS];
static ap_uint<128> g_dst[DST_WORDS];

// 픽셀 값에 (x,y) 좌표를 인코딩 → 한 픽셀이라도 어긋나면 즉시 드러남
static inline uint32_t make_pixel(int x, int y) {
    return ((uint32_t)(y & 0xFFFF) << 16) | (uint32_t)(x & 0xFFFF);
}

// 128bit 워드 = 가로 픽셀 4개. lane = 워드 내 위치(0~3)
static inline void set_pixel(ap_uint<128>* buf, int w, int x, int y, uint32_t v) {
    int idx  = (y * w + x) / 4;
    int lane = x % 4;
    buf[idx].range(lane * 32 + 31, lane * 32) = v;
}

static inline uint32_t get_pixel(const ap_uint<128>* buf, int w, int x, int y) {
    int idx  = (y * w + x) / 4;
    int lane = x % 4;
    return (uint32_t)buf[idx].range(lane * 32 + 31, lane * 32);
}

int main() {
    // wide 커널의 전제 조건
    assert(SRC_W % 4 == 0 && X0 % 4 == 0 && ROI_W % 4 == 0);
    assert(X0 + ROI_W <= SRC_W && Y0 + ROI_H <= SRC_H);
    assert(ROI_W <= MAX_ROI_W);

    // 소스 프레임 채우기
    for (int y = 0; y < SRC_H; y++)
        for (int x = 0; x < SRC_W; x++)
            set_pixel(g_src, SRC_W, x, y, make_pixel(x, y));

    // 출력 버퍼 초기화
    for (int i = 0; i < DST_WORDS; i++)
        g_dst[i] = 0;

    // 커널 호출: 가로 관련 인자는 워드 단위(/4)로 변환
    roi_crop_wide(g_src, g_dst,
                  SRC_W / 4, X0 / 4, Y0, ROI_W / 4, ROI_H);

    // 검증: crop 결과의 모든 픽셀이 원본의 대응 좌표와 일치하는가
    int errors = 0;
    for (int oy = 0; oy < ROI_H; oy++) {
        for (int ox = 0; ox < ROI_W; ox++) {
            uint32_t got = get_pixel(g_dst, ROI_W, ox, oy);
            uint32_t exp = make_pixel(X0 + ox, Y0 + oy);
            if (got != exp) {
                if (errors < 10)
                    printf("  MISMATCH at (%3d,%3d): got=%08x exp=%08x\n",
                           ox, oy, got, exp);
                errors++;
            }
        }
    }

    if (errors == 0) {
        printf("PASS: %dx%d ROI crop verified (%d pixels)\n",
               ROI_W, ROI_H, ROI_W * ROI_H);
        return 0;
    }
    printf("FAIL: %d mismatches\n", errors);
    return 1;   // csim/cosim은 이 반환값으로 성공/실패를 판정
}
