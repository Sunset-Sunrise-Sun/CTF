<script setup lang="ts">
import { ref, onMounted } from 'vue';
type Category = 'Misc'|'Crypto'|'Pwn'|'Web'|'Reverse';
interface Challenge { challenge_id:string; name:string; category:Category; solve_status:string; writeup_status:string }
interface Event { event_id:string; sequence:number; occurred_at:string; actor:string; event_type:string; payload:Record<string,unknown>; artifact_ids:string[]; event_refs:string[]; event_hash:string }
const categories:Category[]=['Misc','Crypto','Pwn','Web','Reverse'];
const challenges=ref<Challenge[]>([]), events=ref<Event[]>([]), selected=ref<Challenge>(), name=ref(''), category=ref<Category>('Misc'), note=ref(''), retrospective=ref(false), error=ref(''), integrity=ref('');
async function api<T>(path:string, body?:unknown):Promise<T> {
 const response=await fetch('/api'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(!response.ok) throw new Error('请求失败：'+response.status);
 return response.json();
}
async function guarded(action:()=>Promise<void>) { error.value='';try{await action()}catch(e){error.value=String(e)} }
async function load(){challenges.value=await api<Challenge[]>('/challenges')}
async function select(c:Challenge){selected.value=c;integrity.value='';events.value=await api<Event[]>('/challenges/'+c.challenge_id+'/events')}
async function create(){await guarded(async()=>{const c=await api<Challenge>('/challenges',{name:name.value,category:category.value});name.value='';await load();await select(c)})}
async function addNote(){await guarded(async()=>{if(!selected.value)return;await api('/challenges/'+selected.value.challenge_id+'/notes',{text:note.value,retrospective:retrospective.value});note.value='';await select(selected.value)})}
async function verify(){await guarded(async()=>{if(selected.value)integrity.value=JSON.stringify(await api('/challenges/'+selected.value.challenge_id+'/integrity'))})}
onMounted(()=>guarded(load));
</script>
<template>
 <main><h1>CTF Agent Workbench</h1><p>本地证据工作台 · P0</p><p>模型通信与工具执行尚未在界面启用。Writeup 尚未生成。</p>
 <p v-if="error" role="alert">{{error}}</p>
 <form @submit.prevent="create"><label>题目名称 <input v-model="name" required maxlength="200"></label> <label>分类 <select v-model="category"><option v-for="c in categories" :key="c">{{c}}</option></select></label> <button>创建题目</button></form>
 <nav aria-label="题目"><button v-for="c in challenges" :key="c.challenge_id" @click="guarded(()=>select(c))">{{c.category}} · {{c.name}}</button></nav>
 <section v-if="selected"><h2>{{selected.name}}</h2><p>解题：{{selected.solve_status}} · Writeup：{{selected.writeup_status}}</p>
 <form @submit.prevent="addNote"><label>用户笔记 <textarea v-model="note" required maxlength="10000" /></label><label><input type="checkbox" v-model="retrospective">回溯笔记（记录当前录入时间）</label><button>追加笔记</button></form>
 <button @click="verify">校验事件链</button><output>{{integrity}}</output>
 <h3>事件时间线</h3><p v-if="!events.length">尚无记录。未记录的操作不能作为已执行证据。</p>
 <ol><li v-for="e in events" :key="e.event_id"><strong>#{{e.sequence}} {{e.event_type}} · {{e.actor}}</strong><p>{{e.occurred_at}} · {{e.event_id}}</p><pre>{{e.payload}}</pre><p>证据 ID：{{e.artifact_ids.join(', ')||'无'}} · 关联事件：{{e.event_refs.join(', ')||'无'}}</p><code>{{e.event_hash}}</code></li></ol></section>
 </main>
</template>
<style>body{font-family:system-ui;background:#101724;color:#e2e8f0;margin:0}main{max-width:960px;margin:40px auto;padding:24px}button,input,select,textarea{font:inherit;padding:8px;margin:6px;border-radius:5px}button{cursor:pointer}nav{margin:24px 0}li{padding:16px;border-bottom:1px solid #43516a}pre,code{white-space:pre-wrap;overflow-wrap:anywhere}textarea{display:block;width:90%}output{display:block}p[role=alert]{color:#fca5a5}</style>
