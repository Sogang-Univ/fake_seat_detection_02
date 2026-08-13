#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>


// ============================================================
// Python으로 돌려줄 Detection 구조체
//
// cpp_yolo_decode.py의 ctypes.Structure와
// 필드 순서가 반드시 같아야 한다.
// ============================================================

extern "C" {

struct DetectionC
{
    int cls;

    float score;

    float x1;
    float y1;
    float x2;
    float y2;
};

}


// ============================================================
// YOLOv5 10-class 설정
//
// 현재 새 모델:
//
// 0 person
// 1 backpack
// 2 handbag
// 3 suitcase
// 4 bottle
// 5 cup
// 6 chair
// 7 laptop
// 8 cell_phone
// 9 book
//
// anchor당:
//
// x y w h obj + 10 class
// = 15
//
// head channel:
//
// 3 anchors * 15
// = 45
// ============================================================

static constexpr int NUM_ANCHORS = 3;

static constexpr int NUM_CLASSES = 10;

static constexpr int NO =
    5 + NUM_CLASSES;          // 15

static constexpr int CHANNELS =
    NUM_ANCHORS * NO;         // 45


// ============================================================
// Candidate
//
// 새 모델에서는 이미 class ID가 0~9로 연속이므로
// 기존 coco_cls / our_cls 이중 mapping이 필요 없다.
// ============================================================

struct Candidate
{
    int cls;

    float score;

    float x1;
    float y1;
    float x2;
    float y2;
};


// ============================================================
// Sigmoid
// ============================================================

static inline float sigmoid_f(
    float x
)
{
    // 지나치게 큰 exp 계산 방지
    if (x >= 50.0f)
    {
        return 1.0f;
    }

    if (x <= -50.0f)
    {
        return 0.0f;
    }


    return

        1.0f

        /

        (
            1.0f

            +

            std::exp(-x)
        );
}


// ============================================================
// IoU
// ============================================================

static inline float calc_iou(

    const Candidate& a,

    const Candidate& b
)
{
    const float xx1 = std::max(
        a.x1,
        b.x1
    );


    const float yy1 = std::max(
        a.y1,
        b.y1
    );


    const float xx2 = std::min(
        a.x2,
        b.x2
    );


    const float yy2 = std::min(
        a.y2,
        b.y2
    );


    const float w = std::max(
        0.0f,
        xx2 - xx1
    );


    const float h = std::max(
        0.0f,
        yy2 - yy1
    );


    const float inter =
        w * h;


    const float area_a =

        std::max(
            0.0f,
            a.x2 - a.x1
        )

        *

        std::max(
            0.0f,
            a.y2 - a.y1
        );


    const float area_b =

        std::max(
            0.0f,
            b.x2 - b.x1
        )

        *

        std::max(
            0.0f,
            b.y2 - b.y1
        );


    const float union_area =

        area_a

        +

        area_b

        -

        inter;


    if (
        union_area
        <=
        0.0f
    )
    {
        return 0.0f;
    }


    return

        inter

        /

        union_area;
}


// ============================================================
// YOLOv5 anchors
// ============================================================

static constexpr float ANCHORS_8[3][2] =
{
    {10.0f, 13.0f},

    {16.0f, 30.0f},

    {33.0f, 23.0f}
};


static constexpr float ANCHORS_16[3][2] =
{
    {30.0f, 61.0f},

    {62.0f, 45.0f},

    {59.0f, 119.0f}
};


static constexpr float ANCHORS_32[3][2] =
{
    {116.0f, 90.0f},

    {156.0f, 198.0f},

    {373.0f, 326.0f}
};


// ============================================================
// 하나의 DPU head decode
//
// raw:
//
// [1,H,W,45]
// NHWC INT8
//
// 중요한 최적화:
//
// 1. 전체 tensor를 float32로 변환하지 않는다.
// 2. raw INT8에서 필요한 값만 바로 읽는다.
// 3. objectness를 먼저 계산한다.
// 4. 10개 class 중 최고 class 하나만 선택한다.
// 5. threshold 통과할 때만 bbox를 decode한다.
//
// Python debug decoder:
//
// cls_id = argmax(obj * class_probability)
//
// 와 동일한 의미.
// ============================================================

static void decode_head(

    const int8_t* raw,

    int H,

    int W,

    int stride,

    int fix_point,

    const float anchors[3][2],

    float score_thresh,

    int crop_x0,

    int crop_y0,

    int crop_size,

    std::vector<Candidate>& candidates
)
{
    // ========================================================
    // DPU dequantization
    //
    // float = INT8 * 2^(-fix_point)
    //
    // fix=2 → /4
    // fix=3 → /8
    // ========================================================

    const float dequant_scale =

        std::ldexp(
            1.0f,
            -fix_point
        );


    // ========================================================
    // Model 640x640 coordinate
    // ->
    // ROI 480x480 coordinate
    // ========================================================

    const float coord_scale =

        static_cast<float>(
            crop_size
        )

        /

        640.0f;


    // ========================================================
    // Grid
    // ========================================================

    for (
        int y = 0;
        y < H;
        ++y
    )
    {
        for (
            int x = 0;
            x < W;
            ++x
        )
        {
            // =================================================
            // NHWC cell base
            //
            // 기존 255가 아니라 새 모델은 45
            // =================================================

            const int pixel_base =

                (
                    y * W
                    +
                    x
                )

                *

                CHANNELS;


            // =================================================
            // 3 anchors
            // =================================================

            for (
                int a = 0;
                a < NUM_ANCHORS;
                ++a
            )
            {
                // =============================================
                // anchor당 15 values
                // =============================================

                const int base =

                    pixel_base

                    +

                    a * NO;


                // =============================================
                // 1. Objectness
                // =============================================

                const float obj_logit =

                    static_cast<float>(
                        raw[
                            base + 4
                        ]
                    )

                    *

                    dequant_scale;


                const float objectness =

                    sigmoid_f(
                        obj_logit
                    );


                // =============================================
                // 빠른 early reject
                //
                // class probability 최대값은 1 이하이므로
                //
                // objectness < threshold
                //
                // 이면 최종 score도 절대 threshold를
                // 넘을 수 없다.
                //
                // 이 경우 class sigmoid 10번도 생략한다.
                // =============================================

                if (
                    objectness
                    <
                    score_thresh
                )
                {
                    continue;
                }


                // =============================================
                // 2. 가장 높은 class 하나 찾기
                // =============================================

                int best_cls = 0;

                float best_cls_prob =
                    0.0f;


                for (
                    int cls = 0;
                    cls < NUM_CLASSES;
                    ++cls
                )
                {
                    const float cls_logit =

                        static_cast<float>(

                            raw[
                                base
                                +
                                5
                                +
                                cls
                            ]
                        )

                        *

                        dequant_scale;


                    const float cls_prob =

                        sigmoid_f(
                            cls_logit
                        );


                    if (
                        cls_prob
                        >
                        best_cls_prob
                    )
                    {
                        best_cls_prob =
                            cls_prob;

                        best_cls =
                            cls;
                    }
                }


                // =============================================
                // YOLO confidence
                //
                // obj * class probability
                // =============================================

                const float score =

                    objectness

                    *

                    best_cls_prob;


                if (
                    score
                    <
                    score_thresh
                )
                {
                    continue;
                }


                // =============================================
                // 3. Threshold를 통과했을 때만
                // bbox 값 읽기/계산
                // =============================================

                const float tx =

                    static_cast<float>(
                        raw[
                            base + 0
                        ]
                    )

                    *

                    dequant_scale;


                const float ty =

                    static_cast<float>(
                        raw[
                            base + 1
                        ]
                    )

                    *

                    dequant_scale;


                const float tw =

                    static_cast<float>(
                        raw[
                            base + 2
                        ]
                    )

                    *

                    dequant_scale;


                const float th =

                    static_cast<float>(
                        raw[
                            base + 3
                        ]
                    )

                    *

                    dequant_scale;


                const float sx =
                    sigmoid_f(tx);

                const float sy =
                    sigmoid_f(ty);

                const float sw =
                    sigmoid_f(tw);

                const float sh =
                    sigmoid_f(th);


                // =============================================
                // YOLOv5 XY decode
                //
                // (sigmoid * 2 - 0.5 + grid) * stride
                // =============================================

                const float bx =

                    (
                        sx * 2.0f

                        -

                        0.5f

                        +

                        static_cast<float>(
                            x
                        )
                    )

                    *

                    static_cast<float>(
                        stride
                    );


                const float by =

                    (
                        sy * 2.0f

                        -

                        0.5f

                        +

                        static_cast<float>(
                            y
                        )
                    )

                    *

                    static_cast<float>(
                        stride
                    );


                // =============================================
                // YOLOv5 WH decode
                //
                // (sigmoid*2)^2 * anchor
                // =============================================

                const float sw2 =
                    sw * 2.0f;


                const float sh2 =
                    sh * 2.0f;


                const float bw =

                    sw2

                    *

                    sw2

                    *

                    anchors[a][0];


                const float bh =

                    sh2

                    *

                    sh2

                    *

                    anchors[a][1];


                // =============================================
                // Model 640 coordinate
                // =============================================

                float x1 =

                    bx

                    -

                    bw * 0.5f;


                float y1 =

                    by

                    -

                    bh * 0.5f;


                float x2 =

                    bx

                    +

                    bw * 0.5f;


                float y2 =

                    by

                    +

                    bh * 0.5f;


                // =============================================
                // 640x640 model
                //
                // ->
                //
                // 480x480 ROI
                //
                // ->
                //
                // original 640x480 frame
                // =============================================

                x1 =

                    x1
                    *
                    coord_scale

                    +

                    static_cast<float>(
                        crop_x0
                    );


                x2 =

                    x2
                    *
                    coord_scale

                    +

                    static_cast<float>(
                        crop_x0
                    );


                y1 =

                    y1
                    *
                    coord_scale

                    +

                    static_cast<float>(
                        crop_y0
                    );


                y2 =

                    y2
                    *
                    coord_scale

                    +

                    static_cast<float>(
                        crop_y0
                    );


                // =============================================
                // Candidate 추가
                // =============================================

                Candidate c;


                c.cls =
                    best_cls;


                c.score =
                    score;


                c.x1 =
                    x1;


                c.y1 =
                    y1;


                c.x2 =
                    x2;


                c.y2 =
                    y2;


                candidates.push_back(
                    c
                );
            }
        }
    }
}


// ============================================================
// 한 class에 대한 NMS
// ============================================================

static void nms_for_class(

    const std::vector<Candidate>& input,

    int target_cls,

    float iou_thresh,

    std::vector<Candidate>& output
)
{
    // ========================================================
    // 해당 class candidate만 수집
    // ========================================================

    std::vector<Candidate>
        cls_candidates;


    for (
        const Candidate& c :
        input
    )
    {
        if (
            c.cls
            ==
            target_cls
        )
        {
            cls_candidates.push_back(
                c
            );
        }
    }


    if (
        cls_candidates.empty()
    )
    {
        return;
    }


    // ========================================================
    // score descending
    // ========================================================

    std::sort(

        cls_candidates.begin(),

        cls_candidates.end(),

        [](
            const Candidate& a,
            const Candidate& b
        )
        {
            return
                a.score
                >
                b.score;
        }
    );


    // ========================================================
    // Greedy NMS
    // ========================================================

    std::vector<uint8_t> removed(

        cls_candidates.size(),

        0
    );


    for (
        std::size_t i = 0;
        i < cls_candidates.size();
        ++i
    )
    {
        if (
            removed[i]
        )
        {
            continue;
        }


        output.push_back(
            cls_candidates[i]
        );


        for (
            std::size_t j = i + 1;
            j < cls_candidates.size();
            ++j
        )
        {
            if (
                removed[j]
            )
            {
                continue;
            }


            const float iou =

                calc_iou(

                    cls_candidates[i],

                    cls_candidates[j]
                );


            if (
                iou
                >
                iou_thresh
            )
            {
                removed[j] =
                    1;
            }
        }
    }
}


// ============================================================
// Python ctypes가 호출하는 최종 C 함수
//
// Python wrapper에서 이미:
//
// head0 = 80x80
// head1 = 40x40
// head2 = 20x20
//
// 순서로 정렬해서 전달함.
//
// 함수 signature는 기존 wrapper와 완전히 동일하게 유지.
// 따라서 cpp_yolo_decode.py의 ctypes argtypes도
// 변경할 필요 없음.
// ============================================================

extern "C"
int decode_yolov5(

    const int8_t* head0,

    const int8_t* head1,

    const int8_t* head2,


    int fix0,

    int fix1,

    int fix2,


    float score_thresh,

    float nms_iou_thresh,


    int crop_x0,

    int crop_y0,

    int crop_size,


    DetectionC* output,

    int max_output
)
{
    // ========================================================
    // Pointer safety
    // ========================================================

    if (
        head0 == nullptr

        ||

        head1 == nullptr

        ||

        head2 == nullptr

        ||

        output == nullptr

        ||

        max_output <= 0
    )
    {
        return -1;
    }


    // ========================================================
    // Candidates
    // ========================================================

    std::vector<Candidate>
        candidates;


    // 현재 threshold=0.20에서도
    // 일반적으로 후보는 많지 않음.
    candidates.reserve(
        256
    );


    // ========================================================
    // P3
    //
    // [1,80,80,45]
    // stride 8
    // fix_point 실제 = 2
    // ========================================================

    decode_head(

        head0,

        80,

        80,

        8,

        fix0,

        ANCHORS_8,

        score_thresh,

        crop_x0,

        crop_y0,

        crop_size,

        candidates
    );


    // ========================================================
    // P4
    //
    // [1,40,40,45]
    // stride 16
    // fix_point 실제 = 3
    // ========================================================

    decode_head(

        head1,

        40,

        40,

        16,

        fix1,

        ANCHORS_16,

        score_thresh,

        crop_x0,

        crop_y0,

        crop_size,

        candidates
    );


    // ========================================================
    // P5
    //
    // [1,20,20,45]
    // stride 32
    // fix_point 실제 = 3
    // ========================================================

    decode_head(

        head2,

        20,

        20,

        32,

        fix2,

        ANCHORS_32,

        score_thresh,

        crop_x0,

        crop_y0,

        crop_size,

        candidates
    );


    // ========================================================
    // 후보가 없으면 바로 종료
    // ========================================================

    if (
        candidates.empty()
    )
    {
        return 0;
    }


    // ========================================================
    // Class-wise NMS
    //
    // 새 모델 class:
    // 0 ~ 9
    // ========================================================

    std::vector<Candidate>
        final_candidates;


    final_candidates.reserve(
        candidates.size()
    );


    for (
        int cls = 0;
        cls < NUM_CLASSES;
        ++cls
    )
    {
        nms_for_class(

            candidates,

            cls,

            nms_iou_thresh,

            final_candidates
        );
    }


    // ========================================================
    // 전체 결과 score 순 정렬
    // ========================================================

    std::sort(

        final_candidates.begin(),

        final_candidates.end(),

        [](
            const Candidate& a,
            const Candidate& b
        )
        {
            return
                a.score
                >
                b.score;
        }
    );


    // ========================================================
    // Python output buffer 복사
    // ========================================================

    const int result_count =

        std::min(

            static_cast<int>(
                final_candidates.size()
            ),

            max_output
        );


    for (
        int i = 0;
        i < result_count;
        ++i
    )
    {
        const Candidate& c =

            final_candidates[i];


        output[i].cls =
            c.cls;


        output[i].score =
            c.score;


        // ====================================================
        // 원본 frame 범위 clamp
        // ====================================================

        output[i].x1 =

            std::max(

                0.0f,

                std::min(
                    639.0f,
                    c.x1
                )
            );


        output[i].y1 =

            std::max(

                0.0f,

                std::min(
                    479.0f,
                    c.y1
                )
            );


        output[i].x2 =

            std::max(

                0.0f,

                std::min(
                    639.0f,
                    c.x2
                )
            );


        output[i].y2 =

            std::max(

                0.0f,

                std::min(
                    479.0f,
                    c.y2
                )
            );
    }


    return result_count;
}
