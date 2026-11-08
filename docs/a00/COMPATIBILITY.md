# A00 合成兼容性核验脚本

以下为实际执行的离线辅助脚本，保留在证据中供审查；不是新增生产模块。执行命令：`python -B ../a00-evidence/verify_compatibility.py`，工作目录为实际仓库检出 `work/p1-2a-audit`。脚本放在其相邻 `work/a00-evidence` 中；复现时按本机目录调整 repo/out 路径。脚本读取固定 Git 对象，在临时目录建合成 SQLite/Artifact 数据，结束后清理，不访问现有数据库。最终输出见 compatibility.json 与 REGRESSION.md。

```python
import ast, hashlib, json, sqlite3, subprocess, sys, tempfile
from contextlib import closing
from pathlib import Path
repo=Path(__file__).resolve().parent.parent/'p1-2a-audit'
out=Path(__file__).resolve().parent
subprocess.run(['git','diff','--exit-code'],cwd=repo,check=True)
def git(*args):return subprocess.check_output(['git',*args],cwd=repo)
p0='ed4850dc17601a9e8177c12c95d1281e072cccd4';p11='778bad7c6db0f4412ce3c55bca0c24b78ad66905';design='00e9436a73d33e01b1a288334b7c08a48661e42e'
def tree(ref):
 rows={}
 for e in git('ls-tree','-r','-z',ref).split(b'\0'):
  if e:
   meta,p=e.split(b'\t');rows[p.decode()]=meta.decode()
 return rows
old=tree(p11);base=tree(design);merged=tree('HEAD')
assert all(merged.get(p)==v for p,v in old.items())
changed_base=[p for p,v in base.items() if merged.get(p)!=v];assert changed_base==['README.md'],changed_base
for ref,name in [(design,'tree-before.txt'),('HEAD','tree-after-integration.txt')]: (out/name).write_bytes(git('ls-tree','-r',ref))
(out/'tree-diff.txt').write_bytes(git('diff','--stat',design,'HEAD')+git('diff','--name-status',design,'HEAD'))
lines=[]
for args in [('rev-parse','HEAD'),('log','-1','--format=%H %P'),('merge-base',p0,p11),('merge-base',design,p11),('merge-base','HEAD',p11),('merge-base','HEAD',design),('status','--porcelain')]:
 lines.append('$ git '+' '.join(args)+'\n'+git(*args).decode())
for a,b in [(p0,p11),(p11,'HEAD'),(design,'HEAD')]:
 p=subprocess.run(['git','merge-base','--is-ancestor',a,b],cwd=repo);assert p.returncode==0;lines.append(f'git merge-base --is-ancestor {a} {b}: exit 0')
(out/'ancestry.txt').write_text('\n'.join(lines),encoding='utf-8')
# Use the fixed P0 model and hash functions directly from committed blobs.
ns={};exec(compile(git('show',p0+':backend/app/models.py'),'<fixed-P0-models>','exec'),ns)
tree0=ast.parse(git('show',p0+':backend/app/store.py'))
funcs=[n for n in tree0.body if isinstance(n,ast.FunctionDef) and n.name in {'canonical','digest'}]
ns.update(hashlib=hashlib,json=json);exec(compile(ast.Module(body=funcs,type_ignores=[]),'<fixed-P0-hash>','exec'),ns)
sys.path.insert(0,str(repo/'backend'))
from app.models import Event
from app.store import Store,canonical,digest
from app.artifacts import ArtifactStore
from app.main import create_app
from fastapi.testclient import TestClient
cid='11111111-1111-4111-8111-111111111111'
c=ns['Challenge'](challenge_id=cid,name='Synthetic A00 compatibility',category='Crypto',created_at='2026-11-07T00:00:00.000000+00:00')
e=ns['Event'](event_id='22222222-2222-4222-8222-222222222222',challenge_id=cid,sequence=1,occurred_at='2026-11-07T00:00:00.000000+00:00',actor='user',event_type='note',payload={'text':'synthetic \u4e2d\u6587','nested':{'z':1,'a':'\\\n'}},previous_event_hash='0'*64)
e.event_hash=ns['digest'](e)
body=e.model_dump_json();can=ns['canonical'](e.model_dump(exclude={'event_hash'})).encode()
with tempfile.TemporaryDirectory(prefix='a00-synthetic-',dir=out) as td:
 root=Path(td);dbpath=root/'workbench.sqlite3'
 with sqlite3.connect(dbpath) as db:
  db.executescript('CREATE TABLE schema_migrations (version TEXT PRIMARY KEY);'+git('show',p0+':backend/app/migrations/001_initial.sql').decode())
  db.execute('INSERT INTO schema_migrations VALUES (?)',('001_initial.sql',));db.execute('INSERT INTO challenges VALUES (?,?)',(cid,c.model_dump_json()));db.execute('INSERT INTO events VALUES (?,?,?,?)',(e.event_id,cid,1,body));db.execute('INSERT INTO event_heads VALUES (?,?,?)',(cid,1,e.event_hash))
 db.close()
 s=Store(dbpath);loaded=s.events(cid)[0];assert digest(loaded)==e.event_hash;assert canonical(loaded.model_dump(exclude={'event_hash'})).encode()==can
 with s.connect() as db:
  assert db.execute('SELECT body FROM events').fetchone()[0].encode()==body.encode()
  assert db.execute('SELECT sequence,event_hash FROM event_heads').fetchone()==(1,e.event_hash)
  versions=[r[0] for r in db.execute('SELECT version FROM schema_migrations ORDER BY version')];assert versions==['001_initial.sql','002_artifacts.sql']
 assert s.verify(cid)['valid']
 with TestClient(create_app(root)) as client:
  health=client.get('/api/health').json();assert health['execution_enabled'] is False and health['model_network_enabled'] is False
  payload=b'synthetic A00 evidence\x00\xff\n';url=f'/api/challenges/{cid}/artifacts'
  r=client.post(url,files={'file':('synthetic.bin',payload,'application/octet-stream')});assert r.status_code==201,r.text;a=r.json()
  r=client.post(url,files={'file':('renamed.bin',payload,'application/octet-stream')});assert r.status_code==200 and r.json()==a
  download=client.get(url+'/'+a['artifact_id']+'/content');assert download.content==payload,(download.status_code,download.text)
 with s.connect() as db:
  snapshot=(db.execute('SELECT * FROM events ORDER BY sequence').fetchall(),db.execute('SELECT * FROM event_heads').fetchall(),db.execute('SELECT * FROM artifacts').fetchall())
 s=Store(dbpath)
 with TestClient(create_app(root)) as client:
  r=client.post(url,files={'file':('restart.bin',payload,'application/octet-stream')});assert r.status_code==200 and r.json()==a
 with s.connect() as db:
  assert snapshot==(db.execute('SELECT * FROM events ORDER BY sequence').fetchall(),db.execute('SELECT * FROM event_heads').fetchall(),db.execute('SELECT * FROM artifacts').fetchall())
  assert db.execute('SELECT body FROM events WHERE sequence=1').fetchone()[0]==body
 events=s.events(cid);assert len(events)==2 and events[1].event_id==a['source_event_id'] and a['artifact_id'] in events[1].artifact_ids;assert s.verify(cid)['valid']
 result={'source_p11_files_identical':len(old),'design_files_preserved_except_readme':len(base)-1,'readme_equals_p11':merged['README.md']==old['README.md'],'historical_event_hash':e.event_hash,'historical_event_body_sha256':hashlib.sha256(body.encode()).hexdigest(),'canonical_bytes_equal':True,'old_body_bytes_preserved':True,'event_heads_preserved':True,'migrations':versions,'artifact_source_link_preserved':True,'same_challenge_dedup_no_extra_event':True,'restart_all_event_artifact_rows_unchanged':True,'download_sha256':hashlib.sha256(payload).hexdigest(),'safety_health':health,'scope':'Synthetic compatibility only; no real models/tools/keys/attachments'}
# Create evidence using the literal fixed-P1-1 Store source, then reopen it
# through the integrated app and compare every persisted row and blob.
import io
fixed={'__package__':'app','__file__':str(repo/'backend/app/store.py')}
exec(compile(git('show',p11+':backend/app/store.py'),'<fixed-P1-1-Store>','exec'),fixed)
with tempfile.TemporaryDirectory(prefix='a00-p11-synthetic-',dir=out) as td:
 root=Path(td);dbpath=root/'workbench.sqlite3';previous=fixed['Store'](dbpath)
 from app.models import Challenge
 previous.create(Challenge(challenge_id=cid,name='Synthetic fixed P1-1',category='Misc'))
 data=b'synthetic fixed P1-1 historical artifact\x00'
 blobs=ArtifactStore(root/'artifacts');info=blobs.ingest(io.BytesIO(data),filename='p11.bin')
 artifact,event=previous.add_artifact(cid,sha256=info.sha256,size=info.size,media_type=info.media_type,original_filename=info.original_filename)
 def snap():
  with closing(sqlite3.connect(dbpath)) as db:return {t:db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in ['challenges','events','event_heads','artifacts','schema_migrations']}
 before=snap()
 with TestClient(create_app(root)) as client:
  url=f'/api/challenges/{cid}/artifacts';r=client.post(url,files={'file':('duplicate.bin',data,'application/octet-stream')});assert r.status_code==200 and r.json()==artifact.model_dump()
  assert client.get(url+'/'+artifact.artifact_id+'/content').content==data
 assert snap()==before
 assert Store(dbpath).verify(cid)['valid']
 result['fixed_p11_database_all_rows_preserved']=True
 result['fixed_p11_source_event_id_preserved']=Store(dbpath).artifact(cid,artifact.artifact_id).source_event_id==event.event_id
(out/'compatibility.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
```
