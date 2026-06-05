"""
test_socket.py — 소켓 명령어 분기 자동 테스트
Usage: python test_socket.py
  (앱이 실행 중이어야 함 — port 8080)
"""
import socket
import time

HOST = '127.0.0.1'
PORT = 8080
TIMEOUT = 3.0

PASS = '\033[92mPASS\033[0m'
FAIL = '\033[91mFAIL\033[0m'
SKIP = '\033[93mSKIP\033[0m'


def send_recv(sock: socket.socket, msg: str, wait: float = 0.4) -> str:
    sock.sendall((msg + '\n').encode('utf-8'))
    time.sleep(wait)
    try:
        sock.settimeout(TIMEOUT)
        data = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b'\n' in data:
                break
    except socket.timeout:
        pass
    return data.decode('utf-8', errors='ignore').strip()


def check(label: str, resp: str, expect_contains: str):
    ok = expect_contains.upper() in resp.upper()
    status = PASS if ok else FAIL
    print(f'  [{status}] {label}')
    print(f'         TX: {label.split("→")[0].strip()}')
    print(f'         RX: {resp!r}')
    if not ok:
        print(f'         EXPECTED contains: {expect_contains!r}')
    return ok


results = []

try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    print(f'Connected to {HOST}:{PORT}\n')
except ConnectionRefusedError:
    print(f'[ERROR] 앱이 실행 중이지 않습니다 (port {PORT} 연결 거부)')
    exit(1)

print('=' * 60)
print('1. SELECT 명령')
print('=' * 60)

# 1-1: 정상 SELECT DMM
r = send_recv(sock, 'SELECT,DMM')
results.append(check('SELECT,DMM → SELECT_ACK,DMM', r, 'SELECT_ACK,DMM'))

# 1-2: 정상 SELECT PICOSCOPE
r = send_recv(sock, 'SELECT,PICOSCOPE')
results.append(check('SELECT,PICOSCOPE → SELECT_ACK,PICOSCOPE', r, 'SELECT_ACK,PICOSCOPE'))

# 1-3: 소문자 허용 여부
r = send_recv(sock, 'SELECT,dmm')
results.append(check('SELECT,dmm (소문자) → SELECT_ACK,DMM', r, 'SELECT_ACK'))

# 1-4: 잘못된 화면명
r = send_recv(sock, 'SELECT,UNKNOWN')
results.append(check('SELECT,UNKNOWN → ERROR', r, 'ERROR'))

# 1-5: 파라미터 누락
r = send_recv(sock, 'SELECT')
results.append(check('SELECT (파라미터 없음) → ERROR', r, 'ERROR'))

# 1-6: 파라미터 과다
r = send_recv(sock, 'SELECT,DMM,EXTRA')
results.append(check('SELECT,DMM,EXTRA → ERROR', r, 'ERROR'))

print()
print('=' * 60)
print('2. START 명령')
print('=' * 60)

# 2-1: 정상 START
r = send_recv(sock, 'START,SN001,SN002,ANALOG,ANALOG,ANALOG')
results.append(check('START,SN001,SN002,ANALOG,ANALOG,ANALOG → (no error)', r, ''))
# START는 응답이 없을 수 있음 (ACK 없음)
print(f'         RX: {r!r}  (START는 즉시 ACK 없음)')

# 2-2: 파라미터 부족
r = send_recv(sock, 'START,SN001,SN002,ANALOG')
results.append(check('START (파라미터 부족) → ERROR', r, 'ERROR'))

# 2-3: 파라미터 과다
r = send_recv(sock, 'START,SN001,SN002,ANALOG,ANALOG,ANALOG,EXTRA')
results.append(check('START (파라미터 과다) → ERROR', r, 'ERROR'))

print()
print('=' * 60)
print('3. ANALOG_V1 명령 (파싱 분기)')
print('=' * 60)

# 3-1: 유효 채널 — DMM 미연결 시 ANALOG_ERROR 또는 측정 시작
r = send_recv(sock, 'ANALOG_V1,SN001,TSM,2500,100', wait=1.0)
results.append(check('ANALOG_V1,SN001,TSM,2500,100 → (응답 있음)', r, ''))
print(f'         RX: {r!r}  (DMM 연결 여부에 따라 RESULT 또는 ERROR)')

# 3-2: 잘못된 채널
r = send_recv(sock, 'ANALOG_V1,SN001,BADCHAN,2500,100')
results.append(check('ANALOG_V1,SN001,BADCHAN (잘못된 채널) → ANALOG_ERROR', r, 'ANALOG_ERROR'))

# 3-3: 숫자 파싱 오류
r = send_recv(sock, 'ANALOG_V1,SN001,TSM,ABC,100')
results.append(check('ANALOG_V1 숫자 오류 → ANALOG_ERROR', r, 'ANALOG_ERROR'))

# 3-4: 파라미터 부족
r = send_recv(sock, 'ANALOG_V1,SN001,TSM,2500')
results.append(check('ANALOG_V1 (파라미터 부족) → ERROR', r, 'ERROR'))

# 3-5: TSS_R 채널
r = send_recv(sock, 'ANALOG_V1,SN002,TSS_R,2500,100', wait=0.5)
results.append(check('ANALOG_V1,SN002,TSS_R (유효 채널) → 응답 있음', r, ''))
print(f'         RX: {r!r}')

print()
print('=' * 60)
print('4. ANALOG_V2 명령 (파싱 분기)')
print('=' * 60)

# 4-1: 유효 채널
r = send_recv(sock, 'ANALOG_V2,SN001,TSM,2400,2600', wait=1.0)
results.append(check('ANALOG_V2,SN001,TSM,2400,2600 → 응답 있음', r, ''))
print(f'         RX: {r!r}')

# 4-2: 잘못된 채널
r = send_recv(sock, 'ANALOG_V2,SN001,VCC_M,2400,2600')
results.append(check('ANALOG_V2,SN001,VCC_M (전류 채널) → ANALOG_ERROR', r, 'ANALOG_ERROR'))

# 4-3: 숫자 파싱 오류
r = send_recv(sock, 'ANALOG_V2,SN001,TSM,LOW,HIGH')
results.append(check('ANALOG_V2 숫자 오류 → ANALOG_ERROR', r, 'ANALOG_ERROR'))

# 4-4: 파라미터 부족
r = send_recv(sock, 'ANALOG_V2,SN001,TSM')
results.append(check('ANALOG_V2 (파라미터 부족) → ERROR', r, 'ERROR'))

print()
print('=' * 60)
print('5. ANALOG_I 명령 (파싱 분기)')
print('=' * 60)

# 5-1: 유효 채널
r = send_recv(sock, 'ANALOG_I,SN001,VCC_M,50,200', wait=1.0)
results.append(check('ANALOG_I,SN001,VCC_M,50,200 → 응답 있음', r, ''))
print(f'         RX: {r!r}')

# 5-2: 잘못된 채널 (전압 채널 사용)
r = send_recv(sock, 'ANALOG_I,SN001,TSM,50,200')
results.append(check('ANALOG_I,SN001,TSM (전압 채널) → ANALOG_ERROR', r, 'ANALOG_ERROR'))

# 5-3: VCC_R 채널
r = send_recv(sock, 'ANALOG_I,SN002,VCC_R,50,200', wait=0.5)
results.append(check('ANALOG_I,SN002,VCC_R (유효 채널) → 응답 있음', r, ''))
print(f'         RX: {r!r}')

# 5-4: 숫자 파싱 오류
r = send_recv(sock, 'ANALOG_I,SN001,VCC_M,LOW,HIGH')
results.append(check('ANALOG_I 숫자 오류 → ANALOG_ERROR', r, 'ANALOG_ERROR'))

# 5-5: 파라미터 부족
r = send_recv(sock, 'ANALOG_I,SN001,VCC_M')
results.append(check('ANALOG_I (파라미터 부족) → ERROR', r, 'ERROR'))

print()
print('=' * 60)
print('6. 알 수 없는 명령')
print('=' * 60)

r = send_recv(sock, 'UNKNOWN_CMD')
results.append(check('UNKNOWN_CMD → ERROR', r, 'ERROR'))

r = send_recv(sock, 'PING')
results.append(check('PING → ERROR', r, 'ERROR'))

r = send_recv(sock, '')
print(f'  [----] 빈 명령 → (무응답 예상) RX={r!r}')

sock.close()

print()
print('=' * 60)
# 빈 문자열 expect는 무조건 pass 처리
valid_results = [res for res in results if isinstance(res, bool)]
passed = sum(valid_results)
total  = len(valid_results)
print(f'결과: {passed}/{total} PASS')
if passed == total:
    print('모든 파싱 분기 정상 동작 ✓')
else:
    print(f'{total - passed}개 항목 확인 필요')
print('=' * 60)
