import pypdf
import re

reader = pypdf.PdfReader('HAR3970-2301_자계강건화TAS.pdf')
text = ''.join(page.extract_text() for page in reader.pages)
matches = re.finditer(r'.{0,300}trigger.{0,300}', text, re.IGNORECASE)

with open('spc_info.txt', 'w', encoding='utf-8') as f:
    for m in matches:
        f.write(m.group(0).replace('\n', ' ') + '\n---\n')

matches2 = re.finditer(r'.{0,300}interval.{0,300}', text, re.IGNORECASE)
with open('spc_info.txt', 'a', encoding='utf-8') as f:
    for m in matches2:
        f.write(m.group(0).replace('\n', ' ') + '\n---\n')
