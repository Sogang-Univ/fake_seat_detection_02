#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>


// ============================================================
// Python으로 돌려줄 Detection 구조체
// ============================================================

extern "C" {

struct DetectionC {
    int cls;

    float score;

    float x1;
    float y1;
    float x2;
    float y2;
};

}


// ============================================================
// YOLOv5 설정
// ============================================================

static constexpr int NUM_ANCHORS = 3;
static constexpr int NUM_CLASSES = 80;
static constexpr int NO = 85;


// ------------------------------------------------------------
// 우리가 현재 사용하는 COCO class
//
// 0  = person
// 24 = backpack
// 26 = handbag
// 28 = suitcase
//
// 나중에 클래스 추가 가능
// ------------------------------------------------------------

static constexpr int NUM_TARGET_CLASSES = 4;

static constexpr int TARGET_COCO[NUM_TARGET_CLASSES] = {
    0,
    24,
    26,
    28
};


// ------------------------------------------------------------
// 우리 프로젝트 class
//
// 0 = person
// 1 = bag
// ------------------------------------------------------------

static constexpr int TARGET_OURS[NUM_TARGET_CLASSES] = {
    0,
    1,
    1,
    1
};


// ============================================================
// Candidate
// ============================================================

struct Candidate {

    int coco_cls;
    int our_cls;

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
) {

    return 1.0f /
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
) {

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


    if (union_area <= 0.0f) {
        return 0.0f;
    }


    return inter / union_area;
}


// ============================================================
// Anchor 정보
// ============================================================

static const float ANCHORS_8[3][2] = {
    {10.0f, 13.0f},
    {16.0f, 30.0f},
    {33.0f, 23.0f}
};


static const float ANCHORS_16[3][2] = {
    {30.0f, 61.0f},
    {62.0f, 45.0f},
    {59.0f, 119.0f}
};


static const float ANCHORS_32[3][2] = {
    {116.0f, 90.0f},
    {156.0f, 198.0f},
    {373.0f, 326.0f}
};


// ============================================================
// 하나의 DPU head decode
//
// 입력:
// raw = NHWC int8
//       (1,H,W,255)
//
// 여기서 바로 필요한 값만 읽는다.
// 전체 float array를 만들지 않는다.
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
) {

    // --------------------------------------------------------
    // DPU dequant scale
    //
    // output float =
    // int8 * 2^(-fix_point)
    // --------------------------------------------------------

    const float dequant_scale =
        std::ldexp(
            1.0f,
            -fix_point
        );


    // --------------------------------------------------------
    // Model 640 coordinate
    // ->
    // original crop coordinate
    // --------------------------------------------------------

    const float coord_scale =
        static_cast<float>(
            crop_size
        )
        /
        640.0f;


    for (int y = 0; y < H; ++y) {

        for (int x = 0; x < W; ++x) {

            // NHWC pixel base
            const int pixel_base =
                (
                    y * W + x
                )
                * 255;


            for (int a = 0; a < NUM_ANCHORS; ++a) {

                const int base =
                    pixel_base
                    +
                    a * NO;


                // ====================================================
                // Objectness 먼저 계산
                // ====================================================

                const float tconf =
                    static_cast<float>(
                        raw[
                            base + 4
                        ]
                    )
                    *
                    dequant_scale;


                const float objectness =
                    sigmoid_f(
                        tconf
                    );


                // ====================================================
                // 필요한 클래스 중 threshold 통과 가능성이 있는지
                // 먼저 확인
                // ====================================================

                bool has_candidate = false;

                float class_scores[
                    NUM_TARGET_CLASSES
                ];


                for (
                    int tc = 0;
                    tc < NUM_TARGET_CLASSES;
                    ++tc
                ) {

                    const int coco_cls =
                        TARGET_COCO[tc];


                    const float tcls =
                        static_cast<float>(
                            raw[
                                base
                                +
                                5
                                +
                                coco_cls
                            ]
                        )
                        *
                        dequant_scale;


                    const float cls_prob =
                        sigmoid_f(
                            tcls
                        );


                    const float score =
                        objectness
                        *
                        cls_prob;


                    class_scores[tc] =
                        score;


                    if (
                        score
                        >=
                        score_thresh
                    ) {

                        has_candidate = true;
                    }
                }


                // ----------------------------------------------------
                // 모든 필요한 클래스가 threshold 미만이면
                // box 계산 자체를 하지 않고 즉시 skip
                // ----------------------------------------------------

                if (!has_candidate) {

                    continue;
                }


                // ====================================================
                // Box decode
                // ====================================================

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
                    sigmoid_f(
                        tx
                    );


                const float sy =
                    sigmoid_f(
                        ty
                    );


                const float sw =
                    sigmoid_f(
                        tw
                    );


                const float sh =
                    sigmoid_f(
                        th
                    );


                // YOLOv5 공식

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


                const float bw_factor =
                    sw * 2.0f;


                const float bh_factor =
                    sh * 2.0f;


                const float bw =
                    bw_factor
                    *
                    bw_factor
                    *
                    anchors[a][0];


                const float bh =
                    bh_factor
                    *
                    bh_factor
                    *
                    anchors[a][1];


                // ====================================================
                // Model input coordinate
                // ====================================================

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


                // ====================================================
                // 원본 640x480 좌표로 복원
                // ====================================================

                x1 =
                    x1 * coord_scale
                    +
                    static_cast<float>(
                        crop_x0
                    );


                x2 =
                    x2 * coord_scale
                    +
                    static_cast<float>(
                        crop_x0
                    );


                y1 =
                    y1 * coord_scale
                    +
                    static_cast<float>(
                        crop_y0
                    );


                y2 =
                    y2 * coord_scale
                    +
                    static_cast<float>(
                        crop_y0
                    );


                // ====================================================
                // Threshold 통과한 class만 candidate 생성
                // ====================================================

                for (
                    int tc = 0;
                    tc < NUM_TARGET_CLASSES;
                    ++tc
                ) {

                    if (
                        class_scores[tc]
                        <
                        score_thresh
                    ) {

                        continue;
                    }


                    Candidate c;

                    c.coco_cls =
                        TARGET_COCO[tc];

                    c.our_cls =
                        TARGET_OURS[tc];

                    c.score =
                        class_scores[tc];

                    c.x1 = x1;
                    c.y1 = y1;
                    c.x2 = x2;
                    c.y2 = y2;


                    candidates.push_back(
                        c
                    );
                }
            }
        }
    }
}


// ============================================================
// Class별 NMS
//
// 기존 Python 코드와 동일하게
// COCO class별로 NMS 후
// 프로젝트 class로 매핑한다.
//
// 즉 backpack/handbag/suitcase는 각각 NMS한다.
// ============================================================

static void nms_for_class(
    const std::vector<Candidate>& input,

    int coco_cls,

    float iou_thresh,

    std::vector<Candidate>& output
) {

    std::vector<Candidate> cls_candidates;


    for (
        const Candidate& c
        :
        input
    ) {

        if (
            c.coco_cls
            ==
            coco_cls
        ) {

            cls_candidates.push_back(
                c
            );
        }
    }


    if (
        cls_candidates.empty()
    ) {

        return;
    }


    std::sort(
        cls_candidates.begin(),
        cls_candidates.end(),

        [](
            const Candidate& a,
            const Candidate& b
        ) {

            return a.score > b.score;
        }
    );


    std::vector<bool> removed(
        cls_candidates.size(),
        false
    );


    for (
        size_t i = 0;
        i < cls_candidates.size();
        ++i
    ) {

        if (
            removed[i]
        ) {

            continue;
        }


        output.push_back(
            cls_candidates[i]
        );


        for (
            size_t j = i + 1;
            j < cls_candidates.size();
            ++j
        ) {

            if (
                removed[j]
            ) {

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
            ) {

                removed[j] =
                    true;
            }
        }
    }
}


// ============================================================
// Python에서 호출하는 함수
//
// head0 = 80x80x255
// head1 = 40x40x255
// head2 = 20x20x255
//
// 반환:
// Detection 개수
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
) {

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
    ) {

        return -1;
    }


    std::vector<Candidate> candidates;


    // 일반적으로 threshold가 높기 때문에
    // 실제 후보는 많지 않음
    candidates.reserve(
        256
    );


    // ========================================================
    // P3
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
    // NMS
    // ========================================================

    std::vector<Candidate> final_candidates;


    final_candidates.reserve(
        candidates.size()
    );


    for (
        int tc = 0;
        tc < NUM_TARGET_CLASSES;
        ++tc
    ) {

        nms_for_class(
            candidates,

            TARGET_COCO[tc],

            nms_iou_thresh,

            final_candidates
        );
    }


    // ========================================================
    // Python output buffer로 복사
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
    ) {

        output[i].cls =
            final_candidates[i].our_cls;


        output[i].score =
            final_candidates[i].score;


        output[i].x1 =
            final_candidates[i].x1;

        output[i].y1 =
            final_candidates[i].y1;

        output[i].x2 =
            final_candidates[i].x2;

        output[i].y2 =
            final_candidates[i].y2;
    }


    return result_count;
}
