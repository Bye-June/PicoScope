"""
test_v1_multichannel.py — 동일 SN에 4채널(TSM/TSS/TSM_R/TSS_R) V1 측정 후
CSV에 컬럼이 순서대로 추가되는지 검증
"""
import socket, time, sys, io, os, csv
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HOST, PORT = '127.0.0.1', 8080
SN         = 'SN-MC-TEST'
CHANNELS   = ['TSM', 'TSS', 'TSM_R', 'TSS_R']

P = F = 0
def ok(m): global P; P+=1; print(f'  [PASS] {m}')
def ng(m): global F; F+=1; print(f'  [FAIL] {m}')
def sec(t): print(f'\n{"="*60}\n  {t}\n{"="*60}')

def send_recv(cmd, timeout=60.0):
    with socket.create_connection((HOST, PORT), timeout=5) as s:
        s.sendall((cmd + '\n').encode('utf-8'))
        s.settimeout(timeout)
        buf = b''
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            buf += chunk
            if b'\n' in buf: break
    return buf.decode('utf-8', errors='replace').strip()

# 오늘 날짜 기준 CSV 경로
today     = datetime.now().strftime('%Y%m%d')
base_dir  = os.path.dirname(os.path.abspath(__file__))
csv_dir   = os.path.join(base_dir, 'results', today, 'csv')
csv_path  = os.path.join(csv_dir, f'{SN}_{today}_V1.csv')

# 이전 테스트 파일 있으면 삭제
if os.path.isfile(csv_path):
    os.remove(csv_path)
    print(f'  [INFO] 기존 파일 삭제: {os.path.basename(csv_path)}')

# SELECT
send_recv('SELECT,34465A', timeout=5)
time.sleep(0.3)

# ── 4채널 순차 측정 ──────────────────────────────────────────────
for idx, ch in enumerate(CHANNELS):
    sec(f'{idx+1}. ANALOG_V1 — {ch}')
    r = send_recv(f'ANALOG_V1,{SN},{ch},5000,2000', timeout=60)
    print(f'  TX: ANALOG_V1,{SN},{ch},5000,2000')
    print(f'  RX: {r}')
    parts = r.split(',')

    if parts[0] != 'ANALOG_V1_RESULT':
        ng(f'{ch}: ANALOG_V1_RESULT 아님 → {r}')
        continue
    ok(f'{ch}: ANALOG_V1_RESULT 수신')

    # CSV 상태 확인
    if not os.path.isfile(csv_path):
        ng(f'{ch}: CSV 파일 없음')
        continue

    with open(csv_path, newline='') as f:
        reader = csv.reader(f)
        header = next(reader)
        rows   = list(reader)

    expected_cols = ['time_us'] + [c + '_mV' for c in CHANNELS[:idx+1]]
    if header == expected_cols:
        ok(f'{ch}: 헤더 정상 → {header}')
    else:
        ng(f'{ch}: 헤더 불일치\n    기대: {expected_cols}\n    실제: {header}')

    if len(rows) == 1000:
        ok(f'{ch}: 1000 rows 확인')
    else:
        ng(f'{ch}: rows={len(rows)} (기대 1000)')

    # 첫 행 time_us 확인
    try:
        t0 = float(rows[0][0])
        t1 = float(rows[1][0])
        ok(f'{ch}: time_us[0]={t0:.1f}  time_us[1]={t1:.1f}')
    except Exception as e:
        ng(f'{ch}: time_us 파싱 실패 — {e}')

    # 이번 채널 값 확인
    col_idx = header.index(ch + '_mV')
    try:
        v0 = float(rows[0][col_idx])
        ok(f'{ch}: [{ch}_mV][0] = {v0:.3f} mV')
    except Exception as e:
        ng(f'{ch}: 값 파싱 실패 — {e}')

    time.sleep(0.2)

# ── 최종 CSV 구조 검증 ──────────────────────────────────────────
sec('최종 CSV 전체 구조')
if os.path.isfile(csv_path):
    with open(csv_path, newline='') as f:
        reader = csv.reader(f)
        header = next(reader)
        rows   = list(reader)
    size_kb = os.path.getsize(csv_path) / 1024
    print(f'  파일: {os.path.basename(csv_path)}  ({size_kb:.1f} KB)')
    print(f'  헤더: {header}')
    print(f'  행 수: {len(rows)}')
    print(f'  첫 행: {rows[0]}')
    print(f'  끝 행: {rows[-1]}')

    if header == ['time_us', 'TSM_mV', 'TSS_mV', 'TSM_R_mV', 'TSS_R_mV']:
        ok('5컬럼 최종 헤더 정상')
    else:
        ng(f'최종 헤더 불일치: {header}')

    if len(rows) == 1000:
        ok('최종 1000 rows 확인')
    else:
        ng(f'최종 rows={len(rows)}')
else:
    ng('최종 CSV 파일 없음')

# ── 결과 ────────────────────────────────────────────────────────
sec('최종 결과')
tot = P + F
print(f'  PASS : {P} / {tot}')
print(f'  FAIL : {F} / {tot}')
if F == 0:
    print('\n  ★ 4채널 멀티컬럼 CSV 저장 모두 정상')
else:
    print(f'\n  ✘ {F}개 실패')
