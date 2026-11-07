// Offline independent Node reference; no Python helpers or production imports.
import fs from 'node:fs';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const SAFE=9007199254740991, INDEX=2147483647;
const DC=Buffer.from('CTF/model-stream/content/v1'), DB=Buffer.from('CTF/model-stream/batch/v1');
const CK='fingerprint_version key_id audit_dataset_id challenge_id request_id batch_id first_sequence last_sequence chunk_count'.split(' ');
const EK='provider_id model_id content_bytes_delta tool_delta_count first_received_at last_received_at'.split(' ');
class Rejected extends Error { constructor(code,limit,structure){super(code);this.code=code;this.limit=limit;this.structure=structure;} }
function no(code,limit,structure){throw new Rejected(code,limit,structure);}
// Separate iterative preflight, independent of the recursive value parser.
// Reserve each member at its opening quote, before descending into its value.
function guardStructure(source){
  const stack=[]; // Never more than 8 scanner frames, not input containers.
  let inString=false,escaped=false,keyString=false;
  for(const ch of source){
    if(inString){
      if(escaped)escaped=false;
      else if(ch==='\\')escaped=true;
      else if(ch==='"'){inString=false;if(keyString)stack.at(-1).keyExpected=false;}
      continue;
    }
    if(ch==='"'){
      keyString=!!(stack.length&&stack.at(-1).kind==='{'&&stack.at(-1).keyExpected);
      if(keyString){
        if(stack.at(-1).members===16)no('limit_exceeded','projection_structure','object_keys');
        stack.at(-1).members++;
      }
      inString=true;
    }else if(ch==='{'||ch==='['){
      if(stack.length===8)no('limit_exceeded','projection_structure','container_depth');
      stack.push({kind:ch,members:0,keyExpected:ch==='{'});
    }else if(ch==='}'||ch===']'){
      if(!stack.length||stack.at(-1).kind!==(ch==='}'?'{':'['))no('invalid_json');
      stack.pop();
    }else if(ch===','&&stack.length&&stack.at(-1).kind==='{')stack.at(-1).keyExpected=true;
  }
}
function str(v,cap=262144,nonempty=false){
  if(typeof v!=='string')no('fingerprint_schema_error');
  for(const c of v){const n=c.codePointAt(0);if(n>=0xd800&&n<=0xdfff)no('invalid_json');}
  const n=Buffer.byteLength(v,'utf8');
  if(n>cap)no('limit_exceeded','string_utf8_bytes');
  if(nonempty&&!v.length)no('fingerprint_schema_error');
  return n;
}
function integer(v,min=0,max=SAFE){
  if(typeof v!=='number'||!Number.isInteger(v))no('integer_type');
  if(v<min||v>max)no('range_error');
}
// Token-aware parser: JSON.parse on an entire object would lose duplicate keys
// and the distinction between the lexical integers 1 and the floats 1.0/1e0.
function parse(raw){
  if(raw.length>=3&&raw.subarray(0,3).equals(Buffer.from([239,187,191])))no('invalid_json');
  let source;
  try{source=new TextDecoder('utf-8',{fatal:true}).decode(raw);}catch{no('invalid_json');}
  guardStructure(source);
  let i=0;
  const ws=()=>{while(i<source.length&&/[\x20\t\n\r]/.test(source[i]))i++;};
  function string(){
    if(source[i]!=='"')no('invalid_json');
    const start=i++;
    while(i<source.length){
      const c=source[i++];
      if(c==='"'){
        let v;try{v=JSON.parse(source.slice(start,i));}catch{no('invalid_json');}
        str(v);return v;
      }
      if(c==='\\'){i++;continue;}
      if(c.charCodeAt(0)<32)no('invalid_json');
    }
    no('invalid_json');
  }
  function value(){
    ws();const ch=source[i];
    if(ch==='"')return string();
    if(ch==='{'){
      i++;ws();const out=Object.create(null);
      if(source[i]==='}'){i++;return out;}
      while(true){
        ws();const key=string();str(key,32);ws();
        if(source[i++]!==':')no('invalid_json');
        if(Object.hasOwn(out,key))no('duplicate_key');
        out[key]=value();ws();
        const end=source[i++];if(end==='}')return out;if(end!==',')no('invalid_json');
      }
    }
    if(ch==='['){
      i++;ws();const out=[];if(source[i]===']'){i++;return out;}
      while(true){out.push(value());ws();const end=source[i++];if(end===']')return out;if(end!==',')no('invalid_json');}
    }
    for(const [token,v] of [['null',null],['true',true],['false',false]]){
      if(source.startsWith(token,i)){i+=token.length;return v;}
    }
    const match=source.slice(i).match(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/);
    if(!match)no('invalid_json');
    const token=match[0];i+=token.length;
    if(token==='-0')no('noncanonical_integer');
    if(/[.eE]/.test(token))no('integer_type');
    if(token.replace('-','').length>16)no('range_error');
    const n=BigInt(token);if(n>BigInt(SAFE)||n<-BigInt(SAFE))no('range_error');
    return Number(n);
  }
  const result=value();ws();if(i!==source.length)no('invalid_json');return result;
}
function scalarOrder(a,b){
  const aa=[...a].map(c=>c.codePointAt(0)),bb=[...b].map(c=>c.codePointAt(0));
  for(let i=0;i<Math.min(aa.length,bb.length);i++)if(aa[i]!==bb[i])return aa[i]-bb[i];
  return aa.length-bb.length;
}
function quoted(s){
  str(s);let out='"';
  const escapes=new Map([[34,'\\"'],[92,'\\\\'],[8,'\\b'],[9,'\\t'],[10,'\\n'],[12,'\\f'],[13,'\\r']]);
  for(const c of s){const cp=c.codePointAt(0);out+=escapes.get(cp)??(cp<32?'\\u'+cp.toString(16).padStart(4,'0'):c);}
  return out+'"';
}
function serialize(v){
  if(v===null)return 'null';
  if(typeof v==='string')return quoted(v);
  if(typeof v==='number'){integer(v);return v.toString(10);}
  if(Array.isArray(v))return '['+v.map(serialize).join(',')+']';
  if(typeof v==='object')return '{'+Object.keys(v).sort(scalarOrder).map(k=>{str(k,32);return quoted(k)+':'+serialize(v[k]);}).join(',')+'}';
  no('fingerprint_schema_error');
}
const canonical=v=>Buffer.from(serialize(v),'utf8');
// Test reports are not protocol objects: case names must not be interpreted as
// stream-content-v1 property names, and report encoding never enters the MAC.
function stableReport(v){
  if(Array.isArray(v))return v.map(stableReport);
  if(v!==null&&typeof v==='object')return Object.fromEntries(Object.keys(v).sort(scalarOrder).map(k=>[k,stableReport(v[k])]));
  return v;
}
function keys(v,required,optional=[]){
  if(!v||typeof v!=='object'||Array.isArray(v)||required.some(k=>!Object.hasOwn(v,k))||Object.keys(v).some(k=>![...required,...optional].includes(k)))no('fingerprint_schema_error');
}
function timestamp(v){
  str(v);
  if(!/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00:00$/.test(v))no('timestamp_format');
  const y=Number(v.slice(0,4)),m=Number(v.slice(5,7)),d=Number(v.slice(8,10));
  const leap=y%4===0&&(y%100!==0||y%400===0);
  const days=[31,leap?29:28,31,30,31,30,31,31,30,31,30,31];
  if(y<1||m<1||m>12||d<1||d>days[m-1]||Number(v.slice(11,13))>23||Number(v.slice(14,16))>59||Number(v.slice(17,19))>59)no('timestamp_format');
}
function field(name,v){
  name=name.split('.').at(-1);
  if(['first_sequence','last_sequence','chunk_count','chunk_sequence'].includes(name))integer(v,1);
  else if(['choice_index','index'].includes(name))integer(v,0,INDEX);
  else if(['content_bytes_delta','tool_delta_count'].includes(name))integer(v);
  else if(['first_received_at','last_received_at'].includes(name))timestamp(v);
  else if(['audit_dataset_id','challenge_id','request_id','batch_id'].includes(name)){
    str(v,36);if(!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(v))no('fingerprint_schema_error');
  }else if(name==='fingerprint_version'){if(v!=='stream-content-v1')no('fingerprint_schema_error');}
  else if(name==='content_fingerprint'){str(v,64);if(!/^[0-9a-f]{64}$/.test(v))no('fingerprint_schema_error');}
  else if(['key_id','provider_id'].includes(name))str(v,128,true);
  else if(name==='model_id')str(v,256,true);
  else if(['id','name'].includes(name))str(v,256);
  else if(['arguments','content'].includes(name)){if(v!==null||name!=='content')str(v);}
  else if(name==='type'){if(v!=='function')no('fingerprint_schema_error');}
  else no('fingerprint_schema_error');
}
function frame(label,data){
  const prefix=Buffer.alloc(8);prefix.writeBigUInt64BE(BigInt(data.length));
  return {label,length:data.length,prefix_hex:prefix.toString('hex'),framed_hex:Buffer.concat([prefix,data]).toString('hex')};
}
const mac=(key,b)=>crypto.createHmac('sha256',key).update(b).digest('hex');
function full(x,key){
  keys(x,['C','records','M_extra'],['supplied_M']);const c=x.C,records=x.records,e=x.M_extra;
  keys(c,CK);keys(e,EK);for(const [k,v] of Object.entries({...c,...e}))field(k,v);
  if(c.last_sequence<c.first_sequence||c.chunk_count!==c.last_sequence-c.first_sequence+1)no('context_mismatch');
  if(!Array.isArray(records)||records.length!==c.chunk_count)no('context_mismatch');
  if(records.length>256)no('limit_exceeded','projected_batch_bytes');
  let contentBytes=0,deltas=0;
  for(const [i,r] of records.entries()){
    keys(r,['chunk_sequence','choices']);field('chunk_sequence',r.chunk_sequence);if(r.chunk_sequence!==c.first_sequence+i)no('context_mismatch');
    if(!Array.isArray(r.choices)||!r.choices.length)no('fingerprint_schema_error');
    if(r.choices.length>1)no('limit_exceeded','choices_per_frame');
    for(const choice of r.choices){
      keys(choice,['choice_index'],['content','tool_deltas']);field('choice_index',choice.choice_index);
      if(Object.hasOwn(choice,'content')){field('content',choice.content);if(choice.content!==null)contentBytes+=Buffer.byteLength(choice.content);}
      const tools=choice.tool_deltas??[];
      if(Object.hasOwn(choice,'tool_deltas')&&!Array.isArray(choice.tool_deltas))no('fingerprint_schema_error');
      if(tools.length>16)no('limit_exceeded','tool_deltas_per_frame');
      deltas+=tools.length;
      for(const t of tools){
        keys(t,['index'],['id','type','function']);for(const [k,v] of Object.entries(t))if(k!=='function')field(k,v);
        if(Object.hasOwn(t,'function')){keys(t.function,[],['name','arguments']);for(const [k,v] of Object.entries(t.function)){field(k,v);contentBytes+=Buffer.byteLength(v);}}
      }
    }
  }
  if(deltas>4096)no('limit_exceeded','tool_deltas_per_request');
  if(contentBytes!==e.content_bytes_delta||deltas!==e.tool_delta_count)no('context_mismatch');
  if(Object.hasOwn(x,'supplied_M')){
    keys(x.supplied_M,[...CK,...EK,'content_fingerprint']);for(const [k,v] of Object.entries(x.supplied_M))field(k,v);
    if(Object.entries({...c,...e}).some(([k,v])=>x.supplied_M[k]!==v))no('context_mismatch');
  }
  const jc=canonical(c),rs=records.map(canonical);
  if(rs.some(r=>r.length>1048576))no('limit_exceeded','projected_record_bytes');
  const placeholder={...c,...e,content_fingerprint:'0'.repeat(64)};
  const projected=8+DC.length+8+jc.length+rs.reduce((n,r)=>n+8+r.length,0)+8+DB.length+8+canonical(placeholder).length;
  if(projected>2097152)no('limit_exceeded','projected_batch_bytes');
  const cf=[frame('domain_content',DC),frame('J(C)',jc),...rs.map((r,i)=>frame('R_'+(c.first_sequence+i),r))];
  const cm=Buffer.concat(cf.map(f=>Buffer.from(f.framed_hex,'hex'))),fingerprint=mac(key,cm);
  const m={...c,...e,content_fingerprint:fingerprint},jm=canonical(m);
  const bf=[frame('domain_batch',DB),frame('J(M)',jm)],bm=Buffer.concat(bf.map(f=>Buffer.from(f.framed_hex,'hex')));
  return {status:'ok',J_C_hex:jc.toString('hex'),R_hex:rs.map(r=>r.toString('hex')),J_M_hex:jm.toString('hex'),M:m,
    content_frames:cf,batch_frames:bf,content_message_hex:cm.toString('hex'),batch_message_hex:bm.toString('hex'),
    content_fingerprint:fingerprint,batch_digest:mac(key,bm),projected_batch_bytes:projected};
}
function evaluate(c,key){
  try{
    const x=parse(Buffer.from(c.input_utf8_hex,'hex'));
    if(c.mode==='full')return full(x,key);
    if(c.mode==='field'){keys(x,['field','value']);field(x.field,x.value);return {status:'ok',canonical_hex:canonical(x.value).toString('hex')};}
    if(c.mode==='canonical')return {status:'ok',canonical_hex:canonical(x).toString('hex')};
    throw new Error('Unknown fixture mode');
  }catch(e){if(!(e instanceof Rejected))throw e;return {status:'error',code:e.code,...(e.limit?{limit_code:e.limit}:{}),...(e.structure?{structure_limit:e.structure}:{})};}
}
const argv=process.argv.slice(2),get=k=>argv[argv.indexOf(k)+1];
if(!argv.includes('--fixture'))throw new Error('--fixture required');
const fixturePath=path.resolve(get('--fixture')),f=JSON.parse(fs.readFileSync(fixturePath,'utf8'));
const calculate=argv.includes('--calculate-only');
if(f.kind!==(calculate?'unfrozen-inputs':'golden'))throw new Error('Never regenerate expected from golden fixture');
const key=Buffer.from(f.synthetic_key_hex,'hex');if(key.length!==32)throw new Error('Synthetic key must be 32 bytes');
const cases=f.cases.filter(c=>!argv.includes('--case')||c.id===get('--case'));if(!cases.length)throw new Error('No cases');
const actual=Object.fromEntries(cases.map(c=>[c.id,evaluate(c,key)]));
if(!calculate)for(const c of cases)if(serialize(actual[c.id])!==serialize(c.expected))throw new Error('Mismatch '+c.id);
const encoded=JSON.stringify(stableReport(actual));
if(argv.includes('--report')&&path.resolve(get('--report'))===fixturePath)throw new Error('Report must not overwrite fixture');
if(argv.includes('--report'))fs.writeFileSync(get('--report'),encoded+'\n','utf8');
if(argv.includes('--machine'))process.stdout.write(encoded+'\n');
else if(!calculate&&!argv.includes('--case')){
  for(const id of ['V1','V2','V3']){
    const command=[fileURLToPath(import.meta.url),'--fixture',fixturePath,'--case',id,'--machine'];
    const runs=[0,1].map(()=>spawnSync(process.execPath,command,{encoding:'utf8'}));
    if(runs.some(r=>r.status!==0)||runs[0].stdout!==runs[1].stdout||serialize(JSON.parse(runs[0].stdout)[id])!==serialize(actual[id]))throw new Error('Fresh process mismatch '+id);
  }
  console.log(`Node.js: ${cases.length} frozen cases PASS; 6 fresh-process V1/V2/V3 checks PASS`);
}else console.log(`Node.js: calculated ${cases.length} actual results (NOT a test run)`);
