"""
seat_state_machine.py — [배포 본체 · 5-b] 유령좌석 상태머신

★ 이 파일은 최종 배포에 그대로 들어간다.
  입력이 웹캠이든 하드웨어(DPU) 파이프라인이든, 이 클래스는 손대지 않는다.
  앞단은 오직 (person_present, bag_present, now) 세 값만 넘겨주면 된다.

상태:
    UNKNOWN / OCCUPIED / GHOST / EMPTY

상태머신 처리 순서:
    1) YOLO 순간 관측 생성
    2) HYSTERESIS_FRAMES 동안 동일 관측 확인
    3) 확정 관측 생성
    4) 일반 상태 변경 후보 발생
    5) STATE_CHANGE_SECONDS 동안 후보 상태 유지
    6) 최종 상태 변경

GHOST 상태:
    - 사람 없음 + 가방 있음(BAG_ONLY)이 GHOST_SECONDS 동안 유지되면
      추가 상태 변경 타이머 없이 즉시 GHOST로 변경한다.

시간:
    - ghost_seconds:
        BAG_ONLY 확정 후 GHOST로 변경되기까지의 시간

    - state_change_seconds:
        OCCUPIED, EMPTY 등 일반 상태 변경의 안정화 시간
        단, GHOST로 진입할 때는 적용하지 않는다.

실환경 기본값:
    - GHOST_SECONDS = 900초
    - HYSTERESIS_FRAMES = 100프레임
    - STATE_CHANGE_SECONDS = 5초

now:
    - 실시간 웹캠:
        time.time()

    - 녹화영상 재현:
        frame_count / fps

    두 값 모두 초 단위의 동일한 시간 기준만 유지하면 동작한다.
"""


# ============================================================
# 실환경 기본값
# ============================================================

GHOST_SECONDS_REAL = 900.0
HYSTERESIS_FRAMES_REAL = 100
STATE_CHANGE_SECONDS_REAL = 5.0


class SeatStateMachine:
    """
    입력:
        매 프레임
        (person_present, bag_present, now)

    출력:
        확정 상태 문자열
        "UNKNOWN" / "OCCUPIED" / "GHOST" / "EMPTY"
    """

    def __init__(
        self,
        ghost_seconds=GHOST_SECONDS_REAL,
        hysteresis_frames=HYSTERESIS_FRAMES_REAL,
        state_change_seconds=STATE_CHANGE_SECONDS_REAL
    ):
        # ----------------------------------------------------
        # 설정 파라미터
        # ----------------------------------------------------

        self.ghost_seconds = ghost_seconds
        self.hysteresis_frames = hysteresis_frames
        self.state_change_seconds = state_change_seconds

        # ----------------------------------------------------
        # 현재 최종 확정 상태
        # ----------------------------------------------------

        self.state = "UNKNOWN"

        # ----------------------------------------------------
        # 히스테리시스 관련 변수
        # ----------------------------------------------------

        # 직전 순간 관측:
        # "OCCUPIED" / "BAG_ONLY" / "EMPTY"
        self._raw_obs = None

        # 같은 순간 관측이 연속으로 들어온 프레임 수
        self._obs_count = 0

        # 히스테리시스를 통과한 확정 관측
        self._confirmed_obs = None

        # ----------------------------------------------------
        # GHOST 판정 타이머
        # ----------------------------------------------------

        # BAG_ONLY가 확정된 최초 시각
        self._ghost_start = None

        # ----------------------------------------------------
        # 일반 상태 변경 타이머
        # ----------------------------------------------------

        # 현재 변경하려는 후보 상태
        self._target_state = None

        # 후보 상태가 처음 발생한 시각
        self._state_change_start = None

    # ========================================================
    # 사람·가방 Boolean을 순간 관측으로 변환
    # ========================================================

    @staticmethod
    def _raw_observation(person, bag):
        """
        person, bag 입력을 순간 관측 문자열로 변환한다.

        person=True:
            가방 검출 여부와 상관없이 OCCUPIED

        person=False, bag=True:
            BAG_ONLY

        person=False, bag=False:
            EMPTY
        """

        if person:
            return "OCCUPIED"

        if bag:
            return "BAG_ONLY"

        return "EMPTY"

    # ========================================================
    # 일반 상태 변경 타이머
    # ========================================================

    def _change_state_with_timer(self, new_state, now):
        """
        일반 상태를 즉시 변경하지 않고,
        new_state가 state_change_seconds 동안 유지된 경우 변경한다.

        GHOST 진입에는 이 함수를 사용하지 않는다.
        """

        # ----------------------------------------------------
        # 요청 상태가 이미 현재 상태와 같은 경우
        # ----------------------------------------------------

        if new_state == self.state:
            # 이전에 남아 있던 상태 변경 후보를 취소한다.
            self._target_state = None
            self._state_change_start = None

            return

        # ----------------------------------------------------
        # 새로운 상태 변경 후보가 발생한 경우
        # ----------------------------------------------------

        if self._target_state != new_state:
            self._target_state = new_state
            self._state_change_start = now

            # 후보가 처음 발생한 프레임에서는
            # 타이머만 시작하고 상태를 변경하지 않는다.
            return

        # ----------------------------------------------------
        # 같은 후보 상태가 계속 유지된 시간 확인
        # ----------------------------------------------------

        elapsed = now - self._state_change_start

        if elapsed >= self.state_change_seconds:
            self.state = new_state

            # 상태 변경이 끝났으므로 후보와 타이머를 초기화한다.
            self._target_state = None
            self._state_change_start = None

    # ========================================================
    # 상태 갱신
    # ========================================================

    def update(
        self,
        person_present: bool,
        bag_present: bool,
        now: float
    ) -> str:
        """
        매 프레임 호출하여 좌석 상태를 갱신한다.
        """

        # 현재 프레임의 순간 관측 생성
        obs = self._raw_observation(
            person_present,
            bag_present
        )

        # ====================================================
        # 1. 히스테리시스
        # ====================================================

        # 현재 관측이 직전 관측과 같으면 연속 횟수 증가
        if obs == self._raw_obs:
            self._obs_count += 1

        # 관측이 바뀌면 새로운 관측을 1프레임부터 다시 계산
        else:
            self._raw_obs = obs
            self._obs_count = 1

        # 같은 관측이 기준 프레임 이상 유지되면 확정 관측으로 승격
        if self._obs_count >= self.hysteresis_frames:
            self._confirmed_obs = obs

        # 아직 한 번도 확정된 관측이 없으면 현재 상태 유지
        if self._confirmed_obs is None:
            return self.state

        # ====================================================
        # 2. 확정 관측에 따른 상태 처리
        # ====================================================

        # ----------------------------------------------------
        # 사람 있음
        # ----------------------------------------------------

        if self._confirmed_obs == "OCCUPIED":
            self._change_state_with_timer(
                "OCCUPIED",
                now
            )

            # 사람이 확인되었으므로 GHOST 타이머 취소
            self._ghost_start = None

        # ----------------------------------------------------
        # 사람과 가방 모두 없음
        # ----------------------------------------------------

        elif self._confirmed_obs == "EMPTY":
            self._change_state_with_timer(
                "EMPTY",
                now
            )

            # 가방이 없으므로 GHOST 타이머 취소
            self._ghost_start = None

        # ----------------------------------------------------
        # 사람 없음 + 가방 있음
        # ----------------------------------------------------

        elif self._confirmed_obs == "BAG_ONLY":
            # BAG_ONLY가 확정되었으므로 이전에 진행되던
            # OCCUPIED 또는 EMPTY 전환 후보는 취소한다.
            self._target_state = None
            self._state_change_start = None

            # 이미 GHOST 상태라면 그대로 유지한다.
            if self.state == "GHOST":
                return self.state

            # GHOST 타이머가 시작되지 않았다면 현재 시각 저장
            if self._ghost_start is None:
                self._ghost_start = now

                # 프로그램 시작 시 UNKNOWN이었더라도
                # 가방이 있는 좌석은 현재 사용할 수 없으므로
                # GHOST 판정 전까지 OCCUPIED로 취급한다.
                if self.state == "UNKNOWN":
                    self.state = "OCCUPIED"

            # BAG_ONLY 확정 후 경과 시간
            elapsed = now - self._ghost_start

            # ghost_seconds에 도달하면 추가 5초 없이 즉시 GHOST 확정
            if elapsed >= self.ghost_seconds:
                self.state = "GHOST"

                # 일반 상태 변경 후보도 확실하게 초기화
                self._target_state = None
                self._state_change_start = None

        return self.state

    # ========================================================
    # UI용 통합 상태 전환 정보
    # ========================================================

    def transition_info(self, now):
        """
        현재 진행 중인 상태 전환 정보를 반환한다.

        일반 상태 전환 예:
            {
                "current_state": "OCCUPIED",
                "next_state": "EMPTY",
                "remaining": 3.2
            }

        GHOST 전환 예:
            {
                "current_state": "OCCUPIED",
                "next_state": "GHOST",
                "remaining": 527.8
            }

        진행 중인 상태 전환이 없으면 None을 반환한다.
        """

        # ----------------------------------------------------
        # 1. 일반 상태 변경 타이머 진행 중
        # ----------------------------------------------------

        if (
            self._target_state is not None
            and self._state_change_start is not None
        ):
            elapsed = now - self._state_change_start

            remaining = max(
                0.0,
                self.state_change_seconds - elapsed
            )

            return {
                "current_state": self.state,
                "next_state": self._target_state,
                "remaining": remaining
            }

        # ----------------------------------------------------
        # 2. BAG_ONLY에서 GHOST로 전환 대기 중
        # ----------------------------------------------------

        if (
            self._confirmed_obs == "BAG_ONLY"
            and self._ghost_start is not None
            and self.state != "GHOST"
        ):
            elapsed = now - self._ghost_start

            remaining = max(
                0.0,
                self.ghost_seconds - elapsed
            )

            return {
                "current_state": self.state,
                "next_state": "GHOST",
                "remaining": remaining
            }

        # 진행 중인 상태 전환 없음
        return None
