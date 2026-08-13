#include <iostream>
#include <memory>
#include <cstdint>
#include <cstring>
#include <chrono>

#include <xrt/xrt_device.h>
#include <xrt/xrt_bo.h>
#include <xrt/xrt_kernel.h>
#include <xrt/xrt_uuid.h>


// ============================================================
// 최대 크기
// ============================================================

static constexpr int MAX_SRC_W = 640;
static constexpr int MAX_SRC_H = 480;

static constexpr int MAX_DST_SIZE = 640;


// ============================================================
// XRT 전역 객체
// ============================================================

static bool g_initialized = false;

static std::unique_ptr<xrt::device> g_device;
static std::unique_ptr<xrt::kernel> g_kernel;

static std::unique_ptr<xrt::bo> g_src_bo;
static std::unique_ptr<xrt::bo> g_dst_bo;


// ============================================================
// BO mapped pointer
//
// INPUT:
// uint32_t RGBx
//
// [ 7: 0] = R
// [15: 8] = G
// [23:16] = B
// [31:24] = 0
//
// OUTPUT:
// RGB INT8 byte stream
//
// R0 G0 B0 R1 G1 B1 ...
// ============================================================

static uint32_t* g_src_map = nullptr;
static uint8_t*  g_dst_map = nullptr;


// ============================================================
// BO 크기
// ============================================================

static constexpr size_t SRC_BO_BYTES =
    static_cast<size_t>(MAX_SRC_W) *
    static_cast<size_t>(MAX_SRC_H) *
    sizeof(uint32_t);


// 현재 HLS 실제 출력은:
//
// 640 × 640 × 3
// = 1,228,800 bytes
//
// 하지만 기존 코드와 비교하기 위해
// BO 자체 크기는 기존처럼 4 byte/pixel 크기를 유지한다.
//
static constexpr size_t DST_BO_BYTES =
    static_cast<size_t>(MAX_DST_SIZE) *
    static_cast<size_t>(MAX_DST_SIZE) *
    sizeof(uint32_t);


// ============================================================
// 초기화
// ============================================================

extern "C"
int hls_crop_init(
    const char* xclbin_path
)
{
    try
    {
        if (g_initialized)
        {
            return 0;
        }


        if (xclbin_path == nullptr)
        {
            std::cerr
                << "xclbin_path is null"
                << std::endl;

            return -1;
        }


        std::cout
            << "Loading XCLBIN: "
            << xclbin_path
            << std::endl;


        // ----------------------------------------------------
        // Device 0
        // ----------------------------------------------------

        g_device =
            std::make_unique<xrt::device>(
                0
            );


        // ----------------------------------------------------
        // XCLBIN load
        // ----------------------------------------------------

        auto uuid =
            g_device->load_xclbin(
                xclbin_path
            );


        // ----------------------------------------------------
        // Kernel open
        // ----------------------------------------------------

        g_kernel =
            std::make_unique<xrt::kernel>(
                *g_device,
                uuid,
                "crop_and_resize"
            );


        // ----------------------------------------------------
        // Source BO
        //
        // 기존 방식 그대로 유지
        // ----------------------------------------------------

        g_src_bo =
            std::make_unique<xrt::bo>(
                *g_device,
                SRC_BO_BYTES,
                g_kernel->group_id(0)
            );


        // ----------------------------------------------------
        // Destination BO
        //
        // ★ 이번 실험의 유일한 핵심 변경
        //
        // 기존:
        //
        // xrt::bo(
        //     device,
        //     size,
        //     group_id
        // )
        //
        // 변경:
        //
        // xrt::bo(
        //     device,
        //     size,
        //     xrt::bo::flags::cacheable,
        //     group_id
        // )
        //
        // ----------------------------------------------------

        g_dst_bo =
            std::make_unique<xrt::bo>(
                *g_device,
                DST_BO_BYTES,
                xrt::bo::flags::cacheable,
                g_kernel->group_id(1)
            );


        // ----------------------------------------------------
        // CPU virtual address mapping
        // ----------------------------------------------------

        g_src_map =
            g_src_bo->map<uint32_t*>();


        g_dst_map =
            g_dst_bo->map<uint8_t*>();


        if (
            g_src_map == nullptr ||
            g_dst_map == nullptr
        )
        {
            std::cerr
                << "BO map failed"
                << std::endl;

            return -2;
        }


        g_initialized = true;


        std::cout
            << "HLS crop_and_resize initialized"
            << std::endl;


        std::cout
            << "SRC BO bytes = "
            << SRC_BO_BYTES
            << std::endl;


        std::cout
            << "DST BO bytes = "
            << DST_BO_BYTES
            << std::endl;


        std::cout
            << "DST BO mode  = cacheable"
            << std::endl;


        return 0;
    }

    catch (
        const std::exception& e
    )
    {
        std::cerr
            << "hls_crop_init exception: "
            << e.what()
            << std::endl;

        return -100;
    }
}


// ============================================================
// 초기화 여부
// ============================================================

extern "C"
int hls_crop_is_initialized()
{
    return g_initialized ? 1 : 0;
}


// ============================================================
// 공통 입력 검사
// ============================================================

static int validate_args(
    const uint8_t* src_bgr,

    int src_w,
    int src_h,

    int x0,
    int y0,

    int roi_w,
    int roi_h,

    int dst_size
)
{
    if (!g_initialized)
    {
        std::cerr
            << "HLS kernel is not initialized"
            << std::endl;

        return -1;
    }


    if (src_bgr == nullptr)
    {
        return -2;
    }


    if (
        src_w <= 0 ||
        src_h <= 0 ||
        dst_size <= 0
    )
    {
        return -3;
    }


    if (
        src_w > MAX_SRC_W ||
        src_h > MAX_SRC_H ||
        dst_size > MAX_DST_SIZE
    )
    {
        return -4;
    }


    if (
        x0 < 0 ||
        y0 < 0 ||
        roi_w <= 0 ||
        roi_h <= 0
    )
    {
        return -5;
    }


    if (
        x0 + roi_w > src_w ||
        y0 + roi_h > src_h
    )
    {
        return -6;
    }


    return 0;
}


// ============================================================
// Camera BGR → HLS RGBx packing
//
// Camera / OpenCV:
// B G R B G R ...
//
// HLS:
// uint32_t pixel
//
// [7:0]   = R
// [15:8]  = G
// [23:16] = B
// [31:24] = 0
// ============================================================

static inline void pack_bgr_to_rgbx(
    const uint8_t* src_bgr,
    int pixel_count
)
{
    for (
        int i = 0;
        i < pixel_count;
        ++i
    )
    {
        const int idx =
            i * 3;


        const uint8_t b =
            src_bgr[idx + 0];

        const uint8_t g =
            src_bgr[idx + 1];

        const uint8_t r =
            src_bgr[idx + 2];


        const uint32_t pixel =
            static_cast<uint32_t>(r)
            |
            (
                static_cast<uint32_t>(g)
                << 8
            )
            |
            (
                static_cast<uint32_t>(b)
                << 16
            );


        g_src_map[i] =
            pixel;
    }
}


// ============================================================
// LEGACY
//
// 과거 RGBx 출력 HLS용 unpack 함수.
//
// 현재 PL quant HLS에서는 사용하지 않는다.
// ============================================================

static inline void unpack_rgbx_to_bgr(
    uint8_t* dst_bgr,
    int pixel_count
)
{
    const uint32_t* dst32 =
        reinterpret_cast<
            const uint32_t*
        >(
            g_dst_map
        );


    for (
        int i = 0;
        i < pixel_count;
        ++i
    )
    {
        const uint32_t p =
            dst32[i];


        const uint8_t r =
            static_cast<uint8_t>(
                p & 0xFF
            );


        const uint8_t g =
            static_cast<uint8_t>(
                (p >> 8)
                & 0xFF
            );


        const uint8_t b =
            static_cast<uint8_t>(
                (p >> 16)
                & 0xFF
            );


        const int idx =
            i * 3;


        dst_bgr[idx + 0] = b;
        dst_bgr[idx + 1] = g;
        dst_bgr[idx + 2] = r;
    }
}


// ============================================================
// ★ 현재 사용할 함수
//
// Camera BGR
// ↓
// RGBx packing
// ↓
// H2D
// ↓
// FPGA:
//   crop
//   resize
//   quantization
// ↓
// RGB INT8
// ↓
// memcpy
//
// 출력:
//
// [dst_size][dst_size][3]
// RGB INT8
// ============================================================

extern "C"
int hls_crop_run_int8_rgb(
    const uint8_t* src_bgr,

    int src_w,
    int src_h,

    int x0,
    int y0,

    int roi_w,
    int roi_h,

    int dst_size,

    int8_t* dst_rgb_int8
)
{
    try
    {
        const int valid =
            validate_args(
                src_bgr,
                src_w,
                src_h,
                x0,
                y0,
                roi_w,
                roi_h,
                dst_size
            );


        if (valid != 0)
        {
            return valid;
        }


        if (dst_rgb_int8 == nullptr)
        {
            return -10;
        }


        const int src_pixels =
            src_w * src_h;


        // ----------------------------------------------------
        // ① BGR → RGBx
        // ----------------------------------------------------

        pack_bgr_to_rgbx(
            src_bgr,
            src_pixels
        );


        // ----------------------------------------------------
        // ② H2D
        // ----------------------------------------------------

        const size_t src_bytes =
            static_cast<size_t>(
                src_pixels
            )
            *
            sizeof(uint32_t);


        g_src_bo->sync(
            XCL_BO_SYNC_BO_TO_DEVICE,
            src_bytes,
            0
        );


        // ----------------------------------------------------
        // ③ FPGA HLS kernel
        // ----------------------------------------------------

        auto run =
            (*g_kernel)(
                *g_src_bo,
                *g_dst_bo,

                src_w,
                src_h,

                x0,
                y0,

                roi_w,
                roi_h,

                dst_size
            );


        run.wait();


        // ----------------------------------------------------
        // ④ D2H
        //
        // 실제 FPGA 출력:
        //
        // RGB = 3 bytes / pixel
        // ----------------------------------------------------

        const size_t dst_bytes =
            static_cast<size_t>(
                dst_size
            )
            *
            static_cast<size_t>(
                dst_size
            )
            *
            3;


        g_dst_bo->sync(
            XCL_BO_SYNC_BO_FROM_DEVICE,
            dst_bytes,
            0
        );


        // ----------------------------------------------------
        // ⑤ BO → 사용자 buffer
        // ----------------------------------------------------

        std::memcpy(
            dst_rgb_int8,
            g_dst_map,
            dst_bytes
        );


        return 0;
    }

    catch (
        const std::exception& e
    )
    {
        std::cerr
            << "hls_crop_run_int8_rgb exception: "
            << e.what()
            << std::endl;

        return -100;
    }
}


// ============================================================
// ★ 현재 사용할 프로파일링 함수
//
// timing_ms:
//
// [0] Packing
// [1] H2D
// [2] HLS
// [3] D2H
// [4] Memcpy
// ============================================================

extern "C"
int hls_crop_run_int8_rgb_profile(
    const uint8_t* src_bgr,

    int src_w,
    int src_h,

    int x0,
    int y0,

    int roi_w,
    int roi_h,

    int dst_size,

    int8_t* dst_rgb_int8,

    double* timing_ms
)
{
    try
    {
        const int valid =
            validate_args(
                src_bgr,
                src_w,
                src_h,
                x0,
                y0,
                roi_w,
                roi_h,
                dst_size
            );


        if (valid != 0)
        {
            return valid;
        }


        if (
            dst_rgb_int8 == nullptr ||
            timing_ms == nullptr
        )
        {
            return -10;
        }


        using Clock =
            std::chrono::steady_clock;


        const int src_pixels =
            src_w * src_h;


        // ====================================================
        // ① Packing
        // ====================================================

        const auto t0 =
            Clock::now();


        pack_bgr_to_rgbx(
            src_bgr,
            src_pixels
        );


        const auto t1 =
            Clock::now();


        // ====================================================
        // ② H2D
        // ====================================================

        const size_t src_bytes =
            static_cast<size_t>(
                src_pixels
            )
            *
            sizeof(uint32_t);


        g_src_bo->sync(
            XCL_BO_SYNC_BO_TO_DEVICE,
            src_bytes,
            0
        );


        const auto t2 =
            Clock::now();


        // ====================================================
        // ③ HLS
        // ====================================================

        auto run =
            (*g_kernel)(
                *g_src_bo,
                *g_dst_bo,

                src_w,
                src_h,

                x0,
                y0,

                roi_w,
                roi_h,

                dst_size
            );


        run.wait();


        const auto t3 =
            Clock::now();


        // ====================================================
        // ④ D2H
        // ====================================================

        const size_t dst_bytes =
            static_cast<size_t>(
                dst_size
            )
            *
            static_cast<size_t>(
                dst_size
            )
            *
            3;


        g_dst_bo->sync(
            XCL_BO_SYNC_BO_FROM_DEVICE,
            dst_bytes,
            0
        );


        const auto t4 =
            Clock::now();


        // ====================================================
        // ⑤ Memcpy
        // ====================================================

        std::memcpy(
            dst_rgb_int8,
            g_dst_map,
            dst_bytes
        );


        const auto t5 =
            Clock::now();


        // ====================================================
        // Timing
        // ====================================================

        timing_ms[0] =
            std::chrono::duration<
                double,
                std::milli
            >(
                t1 - t0
            ).count();


        timing_ms[1] =
            std::chrono::duration<
                double,
                std::milli
            >(
                t2 - t1
            ).count();


        timing_ms[2] =
            std::chrono::duration<
                double,
                std::milli
            >(
                t3 - t2
            ).count();


        timing_ms[3] =
            std::chrono::duration<
                double,
                std::milli
            >(
                t4 - t3
            ).count();


        timing_ms[4] =
            std::chrono::duration<
                double,
                std::milli
            >(
                t5 - t4
            ).count();


        return 0;
    }

    catch (
        const std::exception& e
    )
    {
        std::cerr
            << "hls_crop_run_int8_rgb_profile exception: "
            << e.what()
            << std::endl;

        return -100;
    }
}


// ============================================================
// LEGACY API
//
// 현재 PL quant 하드웨어에서는 사용하지 않는다.
// ============================================================

extern "C"
int hls_crop_run_bgr(
    const uint8_t* src_bgr,

    int src_w,
    int src_h,

    int x0,
    int y0,

    int roi_w,
    int roi_h,

    int dst_size,

    uint8_t* dst_bgr
)
{
    try
    {
        const int valid =
            validate_args(
                src_bgr,
                src_w,
                src_h,
                x0,
                y0,
                roi_w,
                roi_h,
                dst_size
            );


        if (valid != 0)
        {
            return valid;
        }


        if (dst_bgr == nullptr)
        {
            return -10;
        }


        const int src_pixels =
            src_w * src_h;

        const int dst_pixels =
            dst_size * dst_size;


        pack_bgr_to_rgbx(
            src_bgr,
            src_pixels
        );


        const size_t src_bytes =
            static_cast<size_t>(
                src_pixels
            )
            *
            sizeof(uint32_t);


        g_src_bo->sync(
            XCL_BO_SYNC_BO_TO_DEVICE,
            src_bytes,
            0
        );


        auto run =
            (*g_kernel)(
                *g_src_bo,
                *g_dst_bo,

                src_w,
                src_h,

                x0,
                y0,

                roi_w,
                roi_h,

                dst_size
            );


        run.wait();


        const size_t dst_bytes =
            static_cast<size_t>(
                dst_pixels
            )
            *
            sizeof(uint32_t);


        g_dst_bo->sync(
            XCL_BO_SYNC_BO_FROM_DEVICE,
            dst_bytes,
            0
        );


        unpack_rgbx_to_bgr(
            dst_bgr,
            dst_pixels
        );


        return 0;
    }

    catch (
        const std::exception& e
    )
    {
        std::cerr
            << "hls_crop_run_bgr exception: "
            << e.what()
            << std::endl;

        return -100;
    }
}


// ============================================================
// LEGACY PROFILE
// ============================================================

extern "C"
int hls_crop_run_bgr_profile(
    const uint8_t* src_bgr,

    int src_w,
    int src_h,

    int x0,
    int y0,

    int roi_w,
    int roi_h,

    int dst_size,

    uint8_t* dst_bgr,

    double* timing_ms
)
{
    try
    {
        const int valid =
            validate_args(
                src_bgr,
                src_w,
                src_h,
                x0,
                y0,
                roi_w,
                roi_h,
                dst_size
            );


        if (valid != 0)
        {
            return valid;
        }


        if (
            dst_bgr == nullptr ||
            timing_ms == nullptr
        )
        {
            return -10;
        }


        using Clock =
            std::chrono::steady_clock;


        const int src_pixels =
            src_w * src_h;

        const int dst_pixels =
            dst_size * dst_size;


        const auto t0 =
            Clock::now();


        pack_bgr_to_rgbx(
            src_bgr,
            src_pixels
        );


        const auto t1 =
            Clock::now();


        const size_t src_bytes =
            static_cast<size_t>(
                src_pixels
            )
            *
            sizeof(uint32_t);


        g_src_bo->sync(
            XCL_BO_SYNC_BO_TO_DEVICE,
            src_bytes,
            0
        );


        const auto t2 =
            Clock::now();


        auto run =
            (*g_kernel)(
                *g_src_bo,
                *g_dst_bo,

                src_w,
                src_h,

                x0,
                y0,

                roi_w,
                roi_h,

                dst_size
            );


        run.wait();


        const auto t3 =
            Clock::now();


        const size_t dst_bytes =
            static_cast<size_t>(
                dst_pixels
            )
            *
            sizeof(uint32_t);


        g_dst_bo->sync(
            XCL_BO_SYNC_BO_FROM_DEVICE,
            dst_bytes,
            0
        );


        const auto t4 =
            Clock::now();


        unpack_rgbx_to_bgr(
            dst_bgr,
            dst_pixels
        );


        const auto t5 =
            Clock::now();


        timing_ms[0] =
            std::chrono::duration<
                double,
                std::milli
            >(
                t1 - t0
            ).count();


        timing_ms[1] =
            std::chrono::duration<
                double,
                std::milli
            >(
                t2 - t1
            ).count();


        timing_ms[2] =
            std::chrono::duration<
                double,
                std::milli
            >(
                t3 - t2
            ).count();


        timing_ms[3] =
            std::chrono::duration<
                double,
                std::milli
            >(
                t4 - t3
            ).count();


        timing_ms[4] =
            std::chrono::duration<
                double,
                std::milli
            >(
                t5 - t4
            ).count();


        return 0;
    }

    catch (
        const std::exception& e
    )
    {
        std::cerr
            << "hls_crop_run_bgr_profile exception: "
            << e.what()
            << std::endl;

        return -100;
    }
}


// ============================================================
// 종료
// ============================================================

extern "C"
void hls_crop_close()
{
    try
    {
        g_dst_map = nullptr;
        g_src_map = nullptr;


        g_dst_bo.reset();
        g_src_bo.reset();


        g_kernel.reset();
        g_device.reset();


        g_initialized = false;
    }

    catch (...)
    {
        // shutdown 예외 무시
    }
}
