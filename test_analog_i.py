"""ANALOG_I 단독 재시도"""
import socket, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def send_recv(cmd, timeout=30):
    with socket.create_connection(('127.0.0.1', 8080), timeout=5) as s:
        s.sendall((cmd + '\n').encode('utf-8'))
        s.settimeout(timeout)
        buf = b''
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            buf += chunk
            if b'\n' in buf: break
    return buf.decode('utf-8', errors='replace').strip()

# DMM 화면 선택 후 단독 측정
send_recv('SELECT,34465A', timeout=5)
time.sleep(0.3)

print('ANALOG_I 단독 테스트...')
try:
    t0 = time.perf_counter()
    r = send_recv('ANALOG_I,SN-TEST,VCC_M,0,100', timeout=30)
    ms = (time.perf_counter() - t0) * 1000
    print(f'  응답: {r}')
    print(f'  소요: {ms:.0f}ms')
except Exception as e:
    print(f'  실패: {e}')
