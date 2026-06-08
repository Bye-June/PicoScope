"""
test_socket.py -- tcp_protocol_spec.txt 기반 소켓 명령 통합 테스트
앱이 실행 중인 상태에서 실행해야 합니다 (포트 8080)
"""
import socket, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HOST, PORT = '127.0.0.1', 8080
TIMEOUT = 30.0

P = F = 0
def ok(m): global P; P+=1; print(f'  [PASS] {m}')
def ng(m): global F; F+=1; print(f'  [FAIL] {m}')
def sec(t): print(f'\n{"="*60}\n  {t}\n{"="*60}')

def send_recv(cmd: str, timeout=TIMEOUT) -> str:
    with socket.create_connection((HOST, PORT), timeout=5) as s:
        s.sendall((cmd + '\n').encode('utf-8'))
        s.settimeout(timeout)
        buf = b''
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b'\n' in buf:
                break
    return buf.decode('utf-8', errors='replace').strip()

# ── SELECT 명령 ─────────────────────────────────────────────────
sec('1. SELECT 명령')
try:
    r = send_recv('SELECT,34465A', timeout=5)
    print(f'  응답: {r}')
    if r == 'SELECT_ACK,34465A':
        ok('SELECT,34465A → SELECT_ACK,34465A')
    else:
        ng(f'SELECT 응답 불일치: {r}')
except Exception as e:
    ng(f'SELECT 실패: {e}')

time.sleep(0.5)

try:
    r = send_recv('SELECT,PICOSCOPE', timeout=5)
    print(f'  응답: {r}')
    if r == 'SELECT_ACK,PICOSCOPE':
        ok('SELECT,PICOSCOPE → SELECT_ACK,PICOSCOPE')
    else:
        ng(f'SELECT PICOSCOPE 응답 불일치: {r}')
except Exception as e:
    ng(f'SELECT PICOSCOPE 실패: {e}')

time.sleep(0.5)
send_recv('SELECT,34465A', timeout=5)  # DMM 화면으로 복귀

# ── ANALOG_V2 (단발 전압 측정) ───────────────────────────────────
sec('2. ANALOG_V2 -- 단발 전압 측정 (TSM, 0~10000mV)')
try:
    r = send_recv('ANALOG_V2,SN-TEST,TSM,0,10000', timeout=15)
    print(f'  응답: {r}')
    parts = r.split(',')
    if parts[0] == 'ANALOG_V2_RESULT' and parts[1] == 'SN-TEST' and parts[2] == 'TSM':
        val_mv = float(parts[4])
        ok(f'ANALOG_V2 응답 구조 정상 | 측정값: {val_mv:.3f} mV')
        if parts[3] == 'PASS':
            ok(f'판정 PASS (0~10000mV 범위 내)')
        else:
            ng(f'판정 FAIL — 측정값 {val_mv:.3f}mV 가 범위 벗어남')
    else:
        ng(f'ANALOG_V2 응답 형식 불일치: {r}')
except Exception as e:
    ng(f'ANALOG_V2 실패: {e}')

# ── ANALOG_I (단발 전류 측정) ────────────────────────────────────
sec('3. ANALOG_I -- 단발 전류 측정 (VCC_M, 0~100mA)')
try:
    r = send_recv('ANALOG_I,SN-TEST,VCC_M,0,100', timeout=15)
    print(f'  응답: {r}')
    parts = r.split(',')
    if parts[0] == 'ANALOG_I_RESULT' and parts[1] == 'SN-TEST' and parts[2] == 'VCC_M':
        val_ma = float(parts[4])
        ok(f'ANALOG_I 응답 구조 정상 | 측정값: {val_ma:.3f} mA')
        if parts[3] == 'PASS':
            ok(f'판정 PASS (0~100mA 범위 내)')
        else:
            ng(f'판정 FAIL — 측정값 {val_ma:.3f}mA 가 범위 벗어남')
    else:
        ng(f'ANALOG_I 응답 형식 불일치: {r}')
except Exception as e:
    ng(f'ANALOG_I 실패: {e}')

# ── ANALOG_V1 (1000회 × 50µs 전압 측정) ─────────────────────────
sec('4. ANALOG_V1 -- 1000회 x 50us 측정 (TSM, 2500+-5000mV)')
try:
    t0 = time.perf_counter()
    r = send_recv('ANALOG_V1,SN-TEST,TSM,2500,5000', timeout=30)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f'  응답: {r}')
    print(f'  소요: {elapsed:.0f}ms')
    parts = r.split(',')
    if parts[0] == 'ANALOG_V1_RESULT' and parts[1] == 'SN-TEST' and parts[2] == 'TSM':
        min_mv = float(parts[4])
        max_mv = float(parts[5])
        ok(f'ANALOG_V1 응답 구조 정상 | MIN={min_mv:.3f}mV  MAX={max_mv:.3f}mV')
        if parts[3] == 'PASS':
            ok(f'판정 PASS')
        else:
            ng(f'판정 FAIL — 범위 이탈 (±5000mV 이므로 측정값 이상)')
    else:
        ng(f'ANALOG_V1 응답 형식 불일치: {r}')
except Exception as e:
    ng(f'ANALOG_V1 실패: {e}')

# ── 에러 케이스 ──────────────────────────────────────────────────
sec('5. 에러 케이스 -- 잘못된 명령')
try:
    r = send_recv('ANALOG_V1,SN-TEST,TSM,2500', timeout=5)
    print(f'  응답: {r}')
    if 'ERROR' in r:
        ok(f'필드 부족 에러 정상 처리')
    else:
        ng(f'에러 미처리: {r}')
except Exception as e:
    ng(f'에러 케이스 실패: {e}')

# ── 결과 ─────────────────────────────────────────────────────────
sec('최종 결과')
tot = P + F
print(f'  PASS : {P} / {tot}')
print(f'  FAIL : {F} / {tot}')
if F == 0:
    print('\n  ★ 모든 소켓 명령 정상 동작 확인')
else:
    print(f'\n  ✘ {F}개 실패')
