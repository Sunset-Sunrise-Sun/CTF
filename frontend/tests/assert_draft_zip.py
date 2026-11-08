"""Independent stdlib byte/hash verification of real HTTP download fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

p = argparse.ArgumentParser()
p.add_argument('zip')
p.add_argument('generated')
p.add_argument('--human')
p.add_argument('--version', type=int)
p.add_argument('--corrupt', action='store_true')
p.add_argument('--complete', action='store_true')
args = p.parse_args()
with zipfile.ZipFile(args.zip) as z:
    assert z.testzip() is None
    names = z.namelist()
    assert len(names) == len(set(names))
    sums = [line.split(None, 1) for line in z.read('SHA256SUMS').decode().splitlines()]
    assert {n for _, n in sums} == set(names) - {'SHA256SUMS'}
    assert len(sums) == len(names) - 1
    verified = []
    for expected, name in sums:
        actual = hashlib.sha256(z.read(name)).hexdigest()
        assert actual == expected, name
        verified.append({'path': name, 'expected': expected, 'actual': actual})
    generated = Path(args.generated).read_bytes()
    assert z.read('writeup_generated.md') == generated
    manifest = json.loads(z.read('manifest.json'))
    w = manifest['writeup']
    final = z.read('writeup.md')
    assert w['final_sha256'] == hashlib.sha256(final).hexdigest()
    assert w['final_size'] == len(final)
    assert w['generated']['sha256'] == hashlib.sha256(generated).hexdigest()
    assert w['generated']['size'] == len(generated)
    disclosure = z.read('ai_disclosure.md').decode()
    if args.human:
        human = Path(args.human).read_bytes()
        assert final == human
        assert w['final_source'] == 'human'
        assert w['human']['version'] == args.version
        assert w['human']['size'] == len(human)
        assert w['human']['sha256'] == hashlib.sha256(human).hexdigest()
        assert '人工稿 v' + str(args.version) in disclosure
    else:
        assert w['final_source'] == 'generated'
        prefix = ('> 注意：已保存的人工稿完整性校验失败，本文件为服务器生成的初稿。\n\n' if args.corrupt else '> 注意：尚未保存人工稿，本文件为服务器生成的初稿。\n\n').encode()
        assert final == prefix + generated
        assert '服务器初稿' in disclosure
    if args.corrupt:
        assert w['integrity_error']
        assert manifest['completeness'] == 'incomplete'
        assert 'INCOMPLETE.txt' in names
        assert not any(b'C5_TAMPERED' in z.read(n) for n in names)
    if args.complete:
        assert manifest['completeness'] == 'complete'
        assert manifest['missing_requirements'] == []
        assert 'INCOMPLETE.txt' not in names
    else:
        assert manifest['completeness'] == 'incomplete'
        assert 'INCOMPLETE.txt' in names
    result = {'zip': args.zip, 'status': 'PASS', 'final_source': w['final_source'], 'human_version': w['human']['version'] if args.human else None, 'human_metadata': w['human'], 'final_sha256': w['final_sha256'], 'generated_sha256': w['generated']['sha256'], 'files': len(names), 'checksums': verified, 'completeness': manifest['completeness']}
Path(args.zip + '.verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(f"ZIP PASS: {w['final_source']}, {len(sums)}/{len(sums)} SHA256SUMS, final/generated exact bytes, {manifest['completeness']}")
