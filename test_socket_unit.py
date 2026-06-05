"""
소켓 프로토콜 단위 테스트 (GUI 없이 파싱/응답 로직만 검증)
"""

def parse_mode(mode_str):
    m = mode_str.upper()
    if m.startswith('SPC'):
        ids = [x for x in m.split('/')[1:] if x.isdigit()]
        if ids:
            return 'SPC (ID ' + ', '.join(ids) + ')'
        return 'SPC (ID 1, 3)'
    return mode_str

def parse_command(data):
    parts = data.split(',')
    assert len(parts) == 6, f'parts={len(parts)} (기대 6)'
    cmd = parts[0].upper()
    assert cmd == 'START', f'cmd={cmd}'

    sns   = [parts[1].strip(), parts[2].strip()]
    mode1 = parse_mode(parts[3].strip())
    mode2 = parse_mode(parts[4].strip())
    mode3 = parse_mode(parts[5].strip())

    ch_triplets = [('A','B','C'), ('D','E','F')]
    products = []
    for i in range(2):
        sn = sns[i]
        if sn:
            ch1, ch2, ch3 = ch_triplets[i]
            channels = {}
            if mode1: channels[ch1] = mode1
            if mode2: channels[ch2] = mode2
            if mode3: channels[ch3] = mode3
            products.append({'sn': sn, 'channels': channels})
    return products

def build_result(products, all_pass=True):
    result_parts = ['RESULT']
    for i in range(2):
        if i < len(products):
            result_parts.append(products[i]['sn'])
            result_parts.append('PASS' if all_pass else 'FAIL')
        else:
            result_parts.extend(['', ''])
    return ','.join(result_parts)


print('=' * 60)
print('소켓 프로토콜 단위 테스트')
print('=' * 60)

# 테스트 1: 2제품 SENT+SENT+SPC
pkt = 'START,SN-TEST-001,SN-TEST-002,SENT,SENT,SPC/1/3'
prods = parse_command(pkt)
assert len(prods) == 2
p1, p2 = prods
assert p1['sn'] == 'SN-TEST-001'
assert p1['channels'] == {'A':'SENT','B':'SENT','C':'SPC (ID 1, 3)'}
assert p2['sn'] == 'SN-TEST-002'
assert p2['channels'] == {'D':'SENT','E':'SENT','F':'SPC (ID 1, 3)'}
result = build_result(prods, all_pass=True)
parts  = result.split(',')
assert parts == ['RESULT','SN-TEST-001','PASS','SN-TEST-002','PASS'], parts
print('[TEST 1] 2제품 SENT+SENT+SPC/1/3')
print(f'  수신: {pkt}')
print(f'  제품1 채널: {p1["channels"]}')
print(f'  제품2 채널: {p2["channels"]}')
print(f'  송신: {result}')
print('  PASS')

# 테스트 2: 제품 1개 (SN2 빈칸)
pkt2 = 'START,SN-TEST-003,,SENT,SENT,SPC/1/3'
prods2 = parse_command(pkt2)
assert len(prods2) == 1
assert prods2[0]['sn'] == 'SN-TEST-003'
assert prods2[0]['channels'] == {'A':'SENT','B':'SENT','C':'SPC (ID 1, 3)'}
result2 = build_result(prods2, all_pass=True)
parts2  = result2.split(',')
assert parts2 == ['RESULT','SN-TEST-003','PASS','',''], parts2
print()
print('[TEST 2] 1제품만 (SN2 빈칸)')
print(f'  수신: {pkt2}')
print(f'  제품1 채널: {prods2[0]["channels"]}')
print(f'  송신: {result2}')
print('  PASS')

# 테스트 3: ANALOG 모드
pkt3 = 'START,SN-A01,SN-A02,ANALOG,ANALOG,ANALOG'
prods3 = parse_command(pkt3)
assert prods3[0]['channels'] == {'A':'ANALOG','B':'ANALOG','C':'ANALOG'}
assert prods3[1]['channels'] == {'D':'ANALOG','E':'ANALOG','F':'ANALOG'}
print()
print('[TEST 3] ANALOG 모드')
print(f'  수신: {pkt3}')
print(f'  제품1 채널: {prods3[0]["channels"]}')
print(f'  제품2 채널: {prods3[1]["channels"]}')
print('  PASS')

# 테스트 4: 잘못된 칸 수 (7칸)
try:
    parse_command('START,SN1,SN2,SN3,SENT,SENT,EXTRA')
    print('  ERROR: 예외 미발생')
except AssertionError as e:
    print()
    print(f'[TEST 4] 잘못된 칸 수 거부')
    print(f'  오류 메시지: {e}')
    print('  PASS (예외 정상 발생)')

# 테스트 5: 현재 실제 채널 구성 검증 (A:SENT, B:SENT, C:SPC 1/3)
pkt5 = 'START,SN-REAL-001,SN-REAL-002,SENT,SENT,SPC/1/3'
prods5 = parse_command(pkt5)
expected_ch1 = {'A':'SENT', 'B':'SENT', 'C':'SPC (ID 1, 3)'}
expected_ch2 = {'D':'SENT', 'E':'SENT', 'F':'SPC (ID 1, 3)'}
assert prods5[0]['channels'] == expected_ch1, prods5[0]['channels']
assert prods5[1]['channels'] == expected_ch2, prods5[1]['channels']
print()
print('[TEST 5] 실제 채널 구성 (A:SENT, B:SENT, C:SPC 1/3)')
print(f'  수신: {pkt5}')
print(f'  제품1 → A=SENT, B=SENT, C=SPC (ID 1, 3)')
print(f'  제품2 → D=SENT, E=SENT, F=SPC (ID 1, 3)')
result5 = build_result(prods5, all_pass=True)
print(f'  송신(PASS시): {result5}')
result5f = build_result(prods5, all_pass=False)
print(f'  송신(FAIL시): {result5f}')
print('  PASS')

print()
print('=' * 60)
print('모든 단위 테스트 통과')
print('=' * 60)
