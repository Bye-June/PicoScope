# CE TOS (3MAP00490A) — TOS Output 검사 구현 문서

> 작성일: 2026-06-04
> 작성 목적: PicoScope 기반 TOS Output 검사 로직 구현 근거 및 세부 내용 기록
> 참조 문서: CE TOS_PCB Assy_3MAP00490A_Rev C_220110.pdf, TLE4997A8D_CE TOS.pdf

---

## 1. 검사 대상 개요

| 항목 | 내용 |
|---|---|
| PCB 모델 | 3MAP00490A (CE TOS - Torque Output Sensor PCB) |
| 주요 IC | TLE4997A8D (Infineon, Dual-Die Linear Hall Sensor) x2 (U1, U2) |
| 검사 도구 | PicoScope 6804E (8채널) |
| 해당 Test Item | Test Item 1: TOS Output (Test Item 2 Variation은 별도 참고) |

---

## 2. IC 동작 원리 요약 (TLE4997A8D)

### 2.1 Dual-Die 구조

```
U1:
  OUT_T (Top Die)    -> TSM   : 자기장에 비례하는 정방향 출력
  OUT_B (Bottom Die) -> TSS   : 자기장에 반비례하는 역방향 출력

U2:
  OUT_T -> TSM_R
  OUT_B -> TSS_R
```

### 2.2 PCB 검사 조건 (자기장 없음)

자기장 B = 0mT 일 때:
```
TSM = TSS = TSM_R = TSS_R = VDD/2 = 2.5V  (zero-field output)
```

- PCB 단품 검사 환경에서는 Hall 소자에 자기장이 인가되지 않음
- 따라서 모든 출력은 이론상 정확히 VDD의 50% = 2.5V

### 2.3 Ratiometric 출력 특성

```
V_OUT = VDD x 0.5  (B=0 기준)

즉, VOUT/VDD = 0.5 = 50% 고정
```

- 전원 전압(VDD)이 변해도 출력 비율은 유지됨
- 이를 Ratiometric 출력이라 함

---

## 3. PCB 회로 구조

### 3.1 신호 경로

```
VCC_M(5V) --> VDD_T, VDD_B (U1 전원)
VCC_R(5V) --> VDD_T, VDD_B (U2 전원)

U1 OUT_T --> BLM3(470옴 페라이트) --> C1(100nF) --> CON1.TSM
U1 OUT_B --> BLM4(470옴 페라이트) --> C3(100nF) --> CON1.TSS
U2 OUT_T --> BLM5(470옴 페라이트) --> C5(100nF) --> CON1.TSM_R
U2 OUT_B --> BLM6(470옴 페라이트) --> C7(100nF) --> CON1.TSS_R
```

BLM(페라이트 비드) + C(100nF): EMI 필터 (고주파 노이즈 억제)

### 3.2 CON1 핀 배치

| 핀 번호 | 신호명 | 용도 |
|---|---|---|
| 1 | TSS | U1 Bottom Die 출력 |
| 2 | TSM | U1 Top Die 출력 |
| 3 | GND_M | U1 GND |
| 4 | VCC_M | U1 전원 (+5V) |
| 5 | VCC_R | U2 전원 (+5V) |
| 6 | GND_R | U2 GND |
| 7 | TSM_R | U2 Top Die 출력 |
| 8 | TSS_R | U2 Bottom Die 출력 |

---

## 4. Test Item 분류

### Test Item 1 - TOS Output [PicoScope로 구현]

| 항목 | 내용 |
|---|---|
| 전원 조건 | Power A(VCC_M/GND_M), Power B(VCC_R/GND_R)에 5V 인가. NOTE 16 참조. |
| NOTE 16 해석 | 5V 인가 후 50ms 동안 50us 간격으로 1000회 샘플 취득 후 평균값 산출 |
| 측정 대상 | TSM, TSS, TSM_R, TSS_R |
| 판정 기준 | 2.5V +/- 0.1V 이내 |
| 도구 | PicoScope 6804E |

### Test Item 2 - TOS Output Variation [PicoScope 구현 불가]

| 항목 | 내용 |
|---|---|
| 전원 조건 | Power A, Power B에 5V 인가 |
| 추가 조건 | ECU Interface Circuit 연결 필수 (외부 치구) |
| ECU Interface Circuit | 10k옴 직렬저항 + 100nF 캐패시터 (PCB에 없음, 외부 연결) |
| 측정 대상 | TSM, TSS, TSM_R, TSS_R |
| 판정 기준 | TSM < 7mV, TSS < 7mV, TSM-TSS < 7mV 외 |
| 도구 | 정밀 멀티미터 (스코프 DC 정확도 +/-150mV >> 허용오차 7mV) |

> 주의: Test Item 2는 PicoScope 6804E로 자동화 불가.
> 외부 ECU Interface Circuit 치구 + 정밀 멀티미터로 별도 수작업 검사 필요.

### Test Item 3 - TOS Consumption Current

| 항목 | 내용 |
|---|---|
| 전원 조건 | Power A, Power B에 5V 인가 |
| 판정 기준 | VCC_M: Max 20mA, VCC_R: Max 20mA |
| 도구 | 전류계 (PicoScope 미사용) |

---

## 5. TOS Output 측정 방식 설계 (Test Item 1)

### 5.1 Ratiometric 측정을 사용하는 이유

문제: PicoScope 6804E는 8-bit ADC 고정
```
+/-5V 레인지에서 DC 정확도 = +/-3% x 5V = +/-150mV
판정 기준: +/-100mV
-> 절대값 직접 측정 불가 (오차가 허용오차보다 큼)
```

해결: Ratiometric 측정
```
VCC_M(U1 전원)과 TSM을 동일 레인지에서 동시 측정

오차 e가 두 채널에 동일하게 적용되면:
  VCC_M 측정값 = 5.0V x (1+e)
  TSM   측정값 = 2.5V x (1+e)
  비율 = TSM / VCC_M = 0.5  -> 오차 완전 소거!

판정: 비율 = 50% +/- 2% (= 2.5V +/- 0.1V / 5.0V)
```

### 5.2 1000회 측정의 의미

NOTE 16: "50us(Frequency), 1,000times @PCB Ass'y"

해석:
- 5V 안정 인가 상태에서 50us 간격으로 1000회 샘플 취득
- 총 측정 시간: 50us x 1000 = 50ms
- 목적: IC 내부 노이즈(rms 3mV)를 평균화 -> 통계적으로 안정된 측정값

노이즈 감소 효과:
```
1회 측정 노이즈:   +/-3mV (IC 내부 노이즈 rms)
1000회 평균 후:    +/-3mV / sqrt(1000) = +/-0.09mV
-> 노이즈 31배 감소
```

### 5.3 PicoScope 채널 배치

```
Ch A: VCC_M  (U1 기준전압, 5V)   <- Ratiometric 기준
Ch B: TSM    (U1 Top Die 출력)
Ch C: TSS    (U1 Bottom Die 출력)
Ch D: VCC_R  (U2 기준전압, 5V)   <- Ratiometric 기준
Ch E: TSM_R  (U2 Top Die 출력)
Ch F: TSS_R  (U2 Bottom Die 출력)
Ch G: 예비   (소비전류 측정 등 활용 가능)
Ch H: 예비
```

> 참고: PicoScope 6804E는 8채널이므로 VCC 기준채널 2개 + 신호채널 4개 동시 측정 가능

### 5.4 캡처 파라미터

| 파라미터 | 현재 (SENT용) | TOS용 |
|---|---|---|
| 캡처 시간 | 약 3ms | 50ms |
| 샘플 수 | 30,000 | 약 500,000 (10MS/s x 50ms) |
| Timebase | 20 (9.77 MS/s) | 동일 또는 조정 |
| 전압 레인지 | +/-5V | +/-5V (6채널 모두 동일) |
| 다운샘플링 | RAW | 1000점 균등 추출 또는 전체 평균 |

> 주의: 500,000 샘플은 현재 버퍼(num_samples=30,000)를 초과함.
> ps6000aMemorySegments() API 확인 또는 Streaming 모드 검토 필요. 7.1항 참조.

---

## 6. 판정 로직

```python
# Ratiometric 판정 로직 예시

def analyze_tos_output(data):
    """
    data: {
        'A': np.array([...]),  # VCC_M 샘플
        'B': np.array([...]),  # TSM 샘플
        'C': np.array([...]),  # TSS 샘플
        'D': np.array([...]),  # VCC_R 샘플
        'E': np.array([...]),  # TSM_R 샘플
        'F': np.array([...]),  # TSS_R 샘플
    }
    """
    # 전체 평균 (1000회 측정 평균화)
    vcc_m = np.mean(data['A'])
    vcc_r = np.mean(data['D'])
    tsm   = np.mean(data['B'])
    tss   = np.mean(data['C'])
    tsm_r = np.mean(data['E'])
    tss_r = np.mean(data['F'])

    # Ratiometric 비율 계산
    ratio_tsm   = tsm   / vcc_m  # 목표: 0.50
    ratio_tss   = tss   / vcc_m  # 목표: 0.50
    ratio_tsm_r = tsm_r / vcc_r  # 목표: 0.50
    ratio_tss_r = tss_r / vcc_r  # 목표: 0.50

    # 판정: 50% +/- 2% (= 2.5V +/- 0.1V / 5.0V)
    RATIO_MIN = 0.48
    RATIO_MAX = 0.52

    results = {
        'TSM':   RATIO_MIN <= ratio_tsm   <= RATIO_MAX,
        'TSS':   RATIO_MIN <= ratio_tss   <= RATIO_MAX,
        'TSM_R': RATIO_MIN <= ratio_tsm_r <= RATIO_MAX,
        'TSS_R': RATIO_MIN <= ratio_tss_r <= RATIO_MAX,
    }

    pass_fail = all(results.values())

    # 절대 전압 추정값도 함께 리포트 (측정된 VCC를 기준으로 환산)
    abs_voltages = {
        'TSM_V':   tsm,    # 추정 절대 전압 (V)
        'TSS_V':   tss,
        'TSM_R_V': tsm_r,
        'TSS_R_V': tss_r,
        'VCC_M_V': vcc_m,
        'VCC_R_V': vcc_r,
    }

    return pass_fail, results, abs_voltages
```

---

## 7. 구현 전 확인 필요 사항 (미결 항목)

> 아래 항목은 구현 착수 전 반드시 확인 또는 결정이 필요한 사항입니다.
> 확인 완료 시 확인 일자 및 결과를 기록하세요.

---

### [A] 하드웨어 / 측정 환경

#### 7.1 PicoScope 메모리 버퍼 한계 확인 [주의]

- 현재 코드: num_samples = 30,000 (SENT용)
- TOS 검사 필요: 50ms @ 10MS/s = 약 500,000 샘플
- 6804E의 8-bit 모드 최대 버퍼 크기 확인 필요
- 확인 방법: Pico 공식 스펙시트 또는 ps6000aGetMaxSegments() 호출
- 대안 A: Streaming 모드로 50ms 연속 수신 (버퍼 제한 없음, 단 처리 복잡)
- 대안 B: 샘플링 속도를 1MS/s로 낮춤 -> 50,000 샘플로 캡처
  - 1MS/s에서도 1000샘플/50ms 평균 조건 충족 가능
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

#### 7.2 6채널 동시 캡처 시 실제 샘플링 속도 확인 [주의]

- PicoScope 6804E는 채널 수 증가 시 최대 샘플링 속도 저하 가능
- 현재 SENT 검사: 4채널 @ 10MS/s
- TOS 검사: 6채널 동시 사용 -> 실제 최대 샘플링 속도 확인 필요
- 최소 요구: 20kS/s (1000샘플 / 50ms) -> 매우 낮아 문제없을 것으로 예상
- 실제 하드웨어로 ps6000aGetTimebase() 호출하여 6채널 시 timebase 한계 확인
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

#### 7.3 VCC_M / VCC_R 프로브 연결 위치 확인 [주의]

- Ratiometric 측정을 위해 VCC_M, VCC_R을 스코프로 측정해야 함
- 도면 기준: VCC_M -> BLM1(470옴) -> TP1, VCC_R -> BLM0(470옴) -> TP2
- 질문: 스코프 프로브를 TP1/TP2에 연결하는가, CON1 핀 4/5에 연결하는가?
  - TP1/TP2: IC 직전의 VDD 전압 (BLM 통과 후) -> IC 실제 전원을 더 정확히 반영
  - CON1 핀 4/5: 커넥터 입력 전압 -> BLM 전압 강하 미포함
  - BLM 470옴의 DC 저항은 수 옴 수준으로 일반적으로 무시 가능
- 권장: IC 가까운 TP1, TP2를 신호 테스트 포인트와 함께 사용
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

#### 7.4 실제 PCB에서 IC 파워온 안정화 시간 실측 [주의]

- 데이터시트: Power-on time max 1ms
- 실제 PCB: VDD 바이패스 캐패시터(C2=47nF, C6=47nF)가 있어 실제 시정수 다를 수 있음
- 측정 방법: 5V 인가 순간부터 TSM 출력이 2.5V로 안정되는 시간을 스코프로 실측
- 권장 대기 시간: 10ms (데이터시트 1ms의 10배 여유)
- 이 대기 시간 이후 50ms 캡처 시작
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

#### 7.5 VCC_M과 VCC_R이 동일 전원 레일인지 확인 [주의]

- 도면 상 VCC_M(U1 전원), VCC_R(U2 전원)은 별개 네트
- 외부 전원공급기에서 같은 채널로 공급하는가, 다른 채널로 공급하는가?
- 같은 레일이면: VCC_M만 측정하고 VCC_R에도 동일 값 사용 가능 -> 채널 1개 절약
- 다른 레일이면: VCC_M, VCC_R 각각 별도 채널 필요
- 현재 이 문서는 별도 채널(Ch A, Ch D) 가정으로 설계됨
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

#### 7.6 스코프 프로브 접지 공유 문제 확인 [주의]

- PicoScope 6804E: 모든 채널의 GND(BNC 외부 도체)가 공통 접지로 연결됨
- PCB의 GND_M과 GND_R이 분리되어 있다면 프로브 접지 연결 시 단락 위험
- 도면 확인: GND_M과 GND_R이 PCB 상에서 연결되어 있는지 반드시 확인
- 연결 안 된 경우: 차동 프로브 사용 또는 GND_M-GND_R 외부 브리지 연결 필요
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

#### 7.7 CON1 커넥터 타입 및 치구 소켓 확인 [주의]

- 검사 시 CON1에 프로브를 연결해야 함
- CON1의 물리적 커넥터 타입 확인 필요 (8핀, 피치 간격, 잠금 방식)
- 기존 SENT 모델 소켓 치구와 별도의 TOS 전용 소켓 치구 필요 여부 결정
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

---

### [B] NOTE 16 해석 관련

#### 7.8 NOTE 16 정확한 의미 LG Innotek 확인 필요 [주의]

- 도면 NOTE 16: "Torque output inspection : 50us(Frequency), 1,000times @PCB Ass'y"
- 현재 해석 (이 문서 기준): 5V 연속 인가 후 50us 간격 x 1000회 = 50ms 평균
- 대안 해석 A: 50us 주기로 전원을 ON/OFF하며 1000회 측정 (전원 사이클링)
  - 문제: IC 파워온 1ms >> 50us ON 시간 -> IC 안정화 불가, 해석 불일치
- 대안 해석 B: LG Innotek 전용 검사 장비의 동작 방식을 기술한 것
  - 이 경우 우리 시스템으로 동등 조건 구현 불가, 별도 협의 필요
- 권장 행동: LG Innotek 담당자에게 NOTE 16 적용 방식 직접 문의
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

#### 7.9 판정 기준 절대값 vs Ratiometric 적용 여부 확인 [주의]

- 도면 Test List: "2.5V +/- 0.1V" (절대값 기준)
- 이 문서에서는 Ratiometric 방식인 "50% +/- 2%"로 변환하여 사용
- 전제 조건: VCC_M = VCC_R = 5.00V 일 때만 비율 +/-2% = +/-100mV 성립
- 예: VCC가 4.8V이면 -> 2.4V +/- 0.096V (비율 기준은 통과, 절대값은 다를 수 있음)
- LG Innotek의 의도가 절대값 판정인지 비율 판정인지 확인 필요
- 권장: Ratiometric으로 판정하되, 실측 VCC 기반 절대 전압도 함께 리포트
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

---

### [C] 소프트웨어 구현 관련

#### 7.10 SENT 검사와 TOS 검사 공존 방식 결정 [주의]

- 현재 시스템: 8PCA00020A(SENT) 모델 중심으로 설계됨
- CE TOS(3MAP00490A) 추가 시 동일 소프트웨어에서 처리 방식 결정 필요
  - 방안 A: 제품 모델 선택 시 검사 모드 전환 (채널 설정, 분석 로직 분리)
  - 방안 B: CE TOS 전용 별도 실행 파일/모드
- 현재 test_sequence.py 구조가 SENT 전용 Analyzer 클래스 중심
- TOS 전용 분석기 클래스(TosAnalyzer 또는 AnalogAnalyzer) 추가 설계 필요
- [ ] 결정 완료: ____년 __월 __일 / 결정 내용: ________________________

#### 7.11 capture_block() 파라미터 확장 방식 결정 [주의]

- 현재: num_samples = 30,000 하드코딩
- TOS 검사: 다른 샘플 수, 다른 timebase 필요
- 변경 방안:
  ```python
  # 현재
  def capture_block(self, channels, trigger_awg=False, awg_ids=None)

  # 제안
  def capture_block(self, channels, num_samples=None, timebase=None,
                    trigger_awg=False, awg_ids=None)
  ```
- 기존 SENT 호출부에 영향 없도록 기본값 유지 필요
- [ ] 결정 완료: ____년 __월 __일 / 결정 내용: ________________________

#### 7.12 CSV 저장 포맷 결정 (TOS 검사 결과) [주의]

- 기존 SENT 검사: raw 파형 전체를 CSV로 저장
- TOS 검사: 파형 전체 저장 vs 통계값(평균, 비율)만 저장
  - 파형 전체: 500,000샘플 x 6채널 -> 약 12MB (용량 매우 큼)
  - 통계값만: 판정에 필요한 mean, ratio, PASS/FAIL만 저장 (권장)
- 권장 CSV 컬럼 구성:
  ```
  timestamp, VCC_M_mean_V, VCC_R_mean_V,
  TSM_mean_V, TSS_mean_V, TSM_R_mean_V, TSS_R_mean_V,
  ratio_TSM, ratio_TSS, ratio_TSM_R, ratio_TSS_R,
  TSM_pass, TSS_pass, TSM_R_pass, TSS_R_pass, overall_pass
  ```
- [ ] 결정 완료: ____년 __월 __일 / 결정 내용: ________________________

#### 7.13 UI 표시 항목 및 배치 결정 [주의]

- CE TOS 선택 시 UI에 표시할 항목 결정 필요:
  - 실시간 파형 표시 여부 (DC 신호이므로 파형보다 수치가 더 유용)
  - 각 채널별 평균 전압 수치 표시
  - PASS/FAIL 표시 방식 (Test Item별 개별 + 종합)
- Test Item 2, 3 (수작업 검사)의 UI 처리: 결과 입력란 제공 vs 생략
- [ ] 결정 완료: ____년 __월 __일 / 결정 내용: ________________________

---

### [D] Test Item 2 (Variation) 관련

#### 7.14 ECU Interface Circuit 외부 치구 사양 확정 [주의]

- PCB 도면 및 IC 데이터시트 Application Circuit 기준 예상 사양:
  - 직렬 저항: 10k옴 (CON1 각 신호 핀 -> 측정 포인트)
  - 병렬 캐패시터: 100nF (측정 포인트 -> GND)
  - 4채널 각각 적용 (TSM, TSS, TSM_R, TSS_R)
- 위 사양이 실제 LG Innotek 검사 사양과 일치하는지 확인 필요
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

#### 7.15 Test Item 2 판정 기준 7mV의 정확한 의미 확인 [주의]

- 도면: "TSM < 7mV, TSS_R < 7mV, TSM-TSS < 7mV" 등
- 해석 1: 절대값이 7mV 미만 -> 출력이 거의 0V에 가까워야 함 (오프셋 검사)
- 해석 2: 노이즈/리플이 7mV 미만 -> AC 성분 크기 검사
- 해석 3: TSM과 TSS의 편차가 7mV 미만 -> 두 출력의 매칭도 검사
- 도면 판독만으로는 의미가 명확하지 않으므로 LG Innotek 담당자 확인 필요
- [ ] 확인 완료: ____년 __월 __일 / 결과: ____________________________

---

## 8. 구현하지 않기로 한 사항

| 항목 | 이유 |
|---|---|
| Test Item 2 Variation PicoScope 자동화 | DC 정확도 부족 (+/-150mV >> 허용오차 7mV). ECU 치구 필요 |
| 절대값 직접 판정 | DC 정확도 부족. Ratiometric 방식으로 대체 |
| NOTE 16 파워 사이클링 (50us ON/OFF) | IC 안정화 시간(1ms) > 50us. 바이패스 캐패시터 충방전 문제. 5V 연속 인가로 해석 |
| Test Item 3 소비전류 자동 측정 | 별도 전류계 필요. 현재 자동화 계획 없음 |

---

## 9. 참고: IC 데이터시트 핵심 스펙

| 파라미터 | 값 |
|---|---|
| VDD 동작 범위 | 4.5V ~ 5.5V (표준), 4V ~ 7V (확장) |
| Zero-field 출력 (B=0) | VDD / 2 = 2.5V (typ) |
| 출력 노이즈 | max 3mV rms |
| 파워온 시간 | max 1ms |
| DAC 출력 대역폭 | 3.2kHz |
| 신호 지연 | max 250us @ 100Hz |
| 부하 저항 | 10k옴 이상 (pull-down to GND) |
| 부하 캐패시턴스 | max 210nF |

---

## 10. 관련 파일

| 파일 | 설명 |
|---|---|
| src/hw_picoscope.py | PicoScope 하드웨어 추상화 클래스 |
| src/test_sequence.py | 테스트 시퀀스 오케스트레이션 |
| src/main.py | UI 및 메인 루프 |
| CE TOS_PCB Assy_3MAP00490A_Rev C_220110.pdf | PCB 도면 및 Test List |
| TLE4997A8D_CE TOS.pdf | IC 데이터시트 |
| picoscope-6000-series-a-api-programmers-guide.pdf | PicoScope API 레퍼런스 |

---

## 11. 확인 항목 요약 체크리스트

| 번호 | 항목 | 분류 | 담당 | 완료 |
|---|---|---|---|---|
| 7.1 | PicoScope 500K 샘플 버퍼 가능 여부 | 하드웨어 | 개발팀 | [ ] |
| 7.2 | 6채널 동시 캡처 시 샘플링 속도 저하 여부 | 하드웨어 | 개발팀 | [ ] |
| 7.3 | VCC 프로브 연결 위치 (TP1/TP2 vs CON1 핀) | 하드웨어 | 개발팀 | [ ] |
| 7.4 | 실제 IC 파워온 안정화 시간 실측 | 하드웨어 | 개발팀 | [ ] |
| 7.5 | VCC_M / VCC_R 동일 레일 여부 | 하드웨어 | 개발팀 | [ ] |
| 7.6 | GND_M / GND_R 공통 여부 (접지 단락 위험) | 하드웨어 | 개발팀 | [ ] |
| 7.7 | CON1 커넥터 타입 및 치구 설계 | 하드웨어 | 치구팀 | [ ] |
| 7.8 | NOTE 16 정확한 의미 | 고객사 확인 | LG Innotek | [ ] |
| 7.9 | 판정 기준 절대값 vs Ratiometric 여부 | 고객사 확인 | LG Innotek | [ ] |
| 7.10 | SENT/TOS 공존 소프트웨어 구조 결정 | 소프트웨어 | 개발팀 | [ ] |
| 7.11 | capture_block() 파라미터 확장 방식 | 소프트웨어 | 개발팀 | [ ] |
| 7.12 | CSV 저장 포맷 (통계값 vs 전체 파형) | 소프트웨어 | 개발팀 | [ ] |
| 7.13 | UI 표시 항목 및 배치 | 소프트웨어 | 개발팀 | [ ] |
| 7.14 | ECU Interface Circuit 치구 사양 확정 | 고객사 확인 | LG Innotek | [ ] |
| 7.15 | Test Item 2 7mV 판정 기준의 의미 | 고객사 확인 | LG Innotek | [ ] |

---

*문서 끝 — 구현 착수 전 위 체크리스트의 미결 사항을 모두 확인한 후 진행할 것*
*최종 수정일: 2026-06-04*
