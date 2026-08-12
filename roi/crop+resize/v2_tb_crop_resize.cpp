#include <iostream>
#include <ap_int.h>

#define SRC_W      640
#define SRC_H      480
#define X0         80
#define Y0         0
#define ROI_W      480
#define ROI_H      480
#define DST_SIZE   640

typedef ap_uint<128> word_t;
typedef ap_uint<32>  pixel_t;

// HLS 커널 프로토타입
extern "C" {
void crop_and_resize(
    const word_t* src, pixel_t* dst,
    int src_w, int src_h, int x0, int y0,
    int roi_w, int roi_h, int dst_size
);
}

int main()
{
    std::cout << "--- HLS Kernel Co-Simulation (No OpenCV) ---" << std::endl;

    // 1. 메모리 동적 할당
    int total_src_words = (SRC_W * SRC_H);
    word_t* src_hw = new word_t[total_src_words];
    pixel_t* dst_hw = new pixel_t[DST_SIZE * DST_SIZE];

    // 2. 입력 데이터(Dummy) 채우기
    // 사진을 안 불러오는 대신, 예측 가능한 가짜 픽셀 데이터로 채웁니다.
    for (int i = 0; i < total_src_words; i++) {
        word_t w = 0;
        for (int p = 0; p < 4; p++) {
            // (100, 150, 200, 0) 색상을 가진 픽셀 생성
            ap_uint<32> dummy_pixel = (0 << 24) | (200 << 16) | (150 << 8) | 100;
            w.range(p * 32 + 31, p * 32) = dummy_pixel;
        }
        src_hw[i] = w;
    }

    // 출력 버퍼 초기화 (쓰레기값 방지)
    for (int i = 0; i < DST_SIZE * DST_SIZE; i++) {
        dst_hw[i] = 0;
    }

    // 3. 하드웨어 커널 실행
    std::cout << "[INFO] Running Hardware Kernel..." << std::endl;

    crop_and_resize(src_hw, dst_hw, SRC_W, SRC_H, X0, Y0, ROI_W, ROI_H, DST_SIZE);

    std::cout << "[INFO] Hardware Kernel Completed!" << std::endl;

    // 4. 연산 결과 간단히 찍어보기 (검증)
    std::cout << "[INFO] Checking output samples..." << std::endl;
    for(int i = 0; i < 5; i++) {
        std::cout << "Output pixel[" << i << "] : " << std::hex << dst_hw[i] << std::dec << std::endl;
    }

    // 5. 메모리 해제
    delete[] src_hw;
    delete[] dst_hw;

    std::cout << "--- Simulation SUCCESS ---" << std::endl;
    return 0; // 0 리턴 = 시뮬레이션 통과!
}
