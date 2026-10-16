#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pass 2: 中間JSONを画像1枚ずつブラウザで確認・編集する。"""
from __future__ import annotations
import argparse,json,mimetypes,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
DEFAULT_JSON_PATH=Path("data/import_yayoi/receipt_work.json")
ACCOUNT_CANDIDATES=["旅費交通費","接待交際費","雑費"]
SUMMARY_CANDIDATES=["ガソリン代","駐車・駐輪代","マッサージ代","散髪代","修理用、部品、工具代","オファー待ち受け代"]
HTML=r'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>レシート確認</title><style>
body{font-family:sans-serif;margin:0;background:#eee}header{padding:8px 16px;background:#333;color:#fff;display:flex;gap:20px;height:32px;box-sizing:border-box;align-items:center}.main{display:grid;grid-template-columns:300px minmax(420px,1fr) 430px;height:calc(100vh - 32px)}.list{overflow:auto;background:#fafafa;border-right:1px solid #bbb;padding:6px 0}.listRow{display:flex;align-items:center;width:100%;white-space:nowrap}.confirmMark{flex:0 0 26px;border:0;background:transparent;padding:5px 2px 5px 7px;font-family:monospace;font-size:14px;cursor:pointer}.confirmMark:hover{background:#e0e0e0}.listItem{flex:1;border:0;background:transparent;text-align:left;padding:5px 10px 5px 2px;font-size:14px;white-space:nowrap;cursor:pointer;overflow:hidden}.listRow:hover{background:#e9e9e9}.listRow.selected{background:#d8d8d8;font-weight:bold}.listRow.confirmed .listItem{color:#777}.listRow.unused{background:#fff2a8}.listRow.unused .listItem{color:#665500}.listRow.unused.selected{background:#f3df72}.image{display:flex;align-items:flex-start;justify-content:center;overflow:auto;background:#555;padding:12px}.image img{max-width:100%;height:auto;background:white}.form{padding:16px;overflow:auto;background:white}.row{margin:9px 0}.row label{display:block;font-weight:bold;margin-bottom:3px}.row input,.row textarea{box-sizing:border-box;width:100%;font-size:16px;padding:6px}.check{font-size:18px;margin:16px 0}.check input{transform:scale(1.4);margin-right:8px}.warn{padding:8px;background:#fff3cd;white-space:pre-wrap}.buttons{display:flex;gap:8px;position:sticky;bottom:0;background:white;padding:12px 0}.buttons button{font-size:16px;padding:10px 14px}.muted{color:#666;font-size:13px}</style></head><body>
<header><span id="pos"></span><span id="progress"></span><label><input id="onlyUnconfirmed" type="checkbox"> 未確認だけ</label></header><div class="main"><nav class="list" id="receiptList"></nav><div class="image"><img id="receiptImage"></div><div class="form"><div class="warn" id="warning"></div>
<div class="row"><label>画像ファイル</label><div id="filename"></div></div><div class="row"><label>支払日</label><input id="date" type="date"></div><div class="row"><label>時刻</label><input id="time"></div><div class="row"><label>金額</label><input id="amount" type="number"></div><div class="row"><label>店名</label><input id="vendor"></div><div class="row"><label>勘定科目</label><input id="debit_account" list="accountCandidates"><datalist id="accountCandidates"></datalist></div><div class="row"><label>摘要</label><input id="summary" list="summaryCandidates"><datalist id="summaryCandidates"></datalist></div><label class="check"><input id="use" type="checkbox">このレシートを使用する</label><label class="check"><input id="confirmed" type="checkbox">確認済み</label><div class="row"><label>OCR全文</label><textarea id="ocr_text" rows="10" readonly></textarea></div>
<div class="buttons"><button onclick="move(-1)">← 前へ</button><button onclick="resetCurrent()">リセット</button><button onclick="confirmNext()">確認して次へ →</button><button onclick="move(1)">次へ →</button></div><div class="muted">編集内容は自動保存されます。「リセット」で現在の画像をこの画面の起動時の状態へ戻します。</div></div></div>
<script>
let data=[],initialData=[],index=0,saveTimer=null,pendingSave=null;const fields=['date','time','vendor','debit_account','summary'];
function menuName(r){let d=(r.date||'').match(/^\d{4}-(\d{2})-(\d{2})$/),prefix=d?d[1]+d[2]:'----',base=(r.image||'').replace(/^(?:\d{4}_)+/,'');return prefix+'_'+base}function sortedIndexes(){return data.map((r,i)=>i).sort((a,b)=>menuName(data[a]).localeCompare(menuName(data[b]),'ja',{numeric:true})||a-b)}function visibleIndexes(){let only=document.getElementById('onlyUnconfirmed').checked;return sortedIndexes().filter(i=>!only||!data[i].confirmed)}
function setCandidates(id,values){let dl=document.getElementById(id);dl.textContent='';[...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja')).forEach(v=>{let o=document.createElement('option');o.value=v;dl.appendChild(o)})}
async function load(){try{let res=await fetch('/api/receipts');if(!res.ok)throw new Error(await res.text());data=await res.json();initialData=structuredClone(data);if(!data.length)throw new Error('レシートデータがありません');let c=await fetch('/api/candidates');if(c.ok){let x=await c.json();setCandidates('accountCandidates',x.accounts);setCandidates('summaryCandidates',x.summaries)}let all=sortedIndexes(),u=all.find(i=>!data[i].confirmed);index=u!==undefined?u:all[all.length-1];show()}catch(e){document.getElementById('warning').textContent='読み込みエラー: '+e.message}}
function renderList(){let nav=document.getElementById('receiptList');nav.textContent='';for(let i of visibleIndexes()){let r=data[i],row=document.createElement('div'),mark=document.createElement('button'),b=document.createElement('button');row.className='listRow'+(i===index?' selected':'')+(r.confirmed?' confirmed':'')+(r.use===false?' unused':'');mark.type='button';mark.className='confirmMark';mark.textContent=r.confirmed?'[x]':'[ ]';mark.onclick=e=>{e.stopPropagation();toggleConfirmed(i)};b.type='button';b.className='listItem';b.textContent=menuName(r);b.onclick=()=>jump(i);row.append(mark,b);nav.appendChild(row)}requestAnimationFrame(()=>{let s=nav.querySelector('.selected');if(s)s.scrollIntoView({block:'nearest'})})}
function show(){let r=data[index],order=sortedIndexes(),p=order.indexOf(index);document.getElementById('pos').textContent=`${p+1} / ${data.length}`;document.getElementById('progress').textContent=`確認済 ${data.filter(x=>x.confirmed).length} / ${data.length}`;document.getElementById('receiptImage').src='/image?i='+index+'&t='+Date.now();document.getElementById('filename').textContent=r.image;document.getElementById('warning').textContent=r.warning||'警告なし';fields.forEach(f=>document.getElementById(f).value=r[f]??'');document.getElementById('amount').value=r.amount??'';document.getElementById('use').checked=r.use!==false;document.getElementById('confirmed').checked=!!r.confirmed;document.getElementById('ocr_text').value=r.ocr_text||'';renderList()}
function collect(){let r={...data[index]};fields.forEach(f=>r[f]=document.getElementById(f).value);let a=document.getElementById('amount').value;r.amount=a===''?null:Number(a);r.use=document.getElementById('use').checked;r.confirmed=document.getElementById('confirmed').checked;return r}
async function persist(i,r){let res=await fetch('/api/receipt?i='+i,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(r)});if(!res.ok){alert(await res.text());return false}data[i]=r;return true}
function scheduleSave(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>{saveTimer=null;let i=index,r=collect();pendingSave=persist(i,r).then(ok=>{if(ok)renderList();pendingSave=null})},250)}
async function flushSave(){if(saveTimer){clearTimeout(saveTimer);saveTimer=null;let i=index,r=collect();pendingSave=persist(i,r)}if(pendingSave)await pendingSave}
async function resetCurrent(){clearTimeout(saveTimer);saveTimer=null;if(pendingSave)await pendingSave;let i=index,r=structuredClone(initialData[i]);if(await persist(i,r))show()}
async function confirmNext(){await flushSave();let current=index,r={...data[current],confirmed:true};if(await persist(current,r)){document.getElementById('confirmed').checked=true;moveFrom(current,1)}}
async function toggleConfirmed(i){await flushSave();let r={...data[i],confirmed:!data[i].confirmed};if(await persist(i,r)){if(i===index)document.getElementById('confirmed').checked=r.confirmed;show()}}
async function jump(i){await flushSave();if(i!==index){index=i;show()}}async function move(dir){await flushSave();moveFrom(index,dir)}function moveFrom(from,dir){let order=sortedIndexes(),p=order.indexOf(from),n=p+dir;if(n>=0&&n<order.length)index=order[n];show()}
fields.concat(['amount']).forEach(id=>document.getElementById(id).addEventListener('input',scheduleSave));['use','confirmed'].forEach(id=>document.getElementById(id).addEventListener('change',scheduleSave));document.getElementById('onlyUnconfirmed').addEventListener('change',async()=>{await flushSave();let list=visibleIndexes();if(list.length&&!list.includes(index))index=list[0];show()});document.addEventListener('keydown',e=>{if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();confirmNext()}});load();
</script></body></html>'''
def make_handler(json_path:Path):
 def load_work():return json.loads(json_path.read_text(encoding="utf-8"))
 def save_work(work):
  tmp=json_path.with_suffix(json_path.suffix+".tmp");tmp.write_text(json.dumps(work,ensure_ascii=False,indent=2),encoding="utf-8");tmp.replace(json_path)
 def candidates(work):
  rs=work.get("receipts",[]);a=ACCOUNT_CANDIDATES+[str(r.get("debit_account","")) for r in rs];s=SUMMARY_CANDIDATES+[str(r.get("summary","")) for r in rs];return{"accounts":sorted(set(filter(None,a))),"summaries":sorted(set(filter(None,s)))}
 class Handler(BaseHTTPRequestHandler):
  def send_bytes(self,body:bytes,ctype:str,status=200):self.send_response(status);self.send_header("Content-Type",ctype);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
  def do_GET(self):
   u=urllib.parse.urlparse(self.path);q=urllib.parse.parse_qs(u.query)
   if u.path=="/":return self.send_bytes(HTML.encode(),"text/html; charset=utf-8")
   work=load_work()
   if u.path=="/api/receipts":return self.send_bytes(json.dumps(work["receipts"],ensure_ascii=False).encode(),"application/json; charset=utf-8")
   if u.path=="/api/candidates":return self.send_bytes(json.dumps(candidates(work),ensure_ascii=False).encode(),"application/json; charset=utf-8")
   if u.path=="/image":
    try:
     i=int(q.get("i",["0"])[0]);r=work["receipts"][i];p=Path(work["image_dir"])/r["image"];return self.send_bytes(p.read_bytes(),mimetypes.guess_type(p.name)[0] or "application/octet-stream")
    except Exception as e:return self.send_bytes(str(e).encode(),"text/plain; charset=utf-8",404)
   self.send_error(404)
  def do_POST(self):
   u=urllib.parse.urlparse(self.path);q=urllib.parse.parse_qs(u.query)
   if u.path!="/api/receipt":return self.send_error(404)
   try:
    i=int(q["i"][0]);n=int(self.headers.get("Content-Length","0"));r=json.loads(self.rfile.read(n));work=load_work();work["receipts"][i]=r;save_work(work);return self.send_bytes(b"ok","text/plain")
   except Exception as e:return self.send_bytes(str(e).encode(),"text/plain; charset=utf-8",400)
  def log_message(self,fmt,*args):pass
 return Handler
def main():
 p=argparse.ArgumentParser(description="Pass 2: 中間JSONをブラウザで確認・編集");p.add_argument("json_path",nargs="?",default=str(DEFAULT_JSON_PATH));p.add_argument("--host",default="127.0.0.1");p.add_argument("--port",type=int,default=8080);a=p.parse_args();path=Path(a.json_path).resolve()
 if not path.is_file():p.error(f"中間JSONが見つかりません: {path}")
 try:
  work=json.loads(path.read_text(encoding="utf-8"))
  if not isinstance(work.get("receipts"),list):raise ValueError("receipts 配列がありません")
 except (OSError,json.JSONDecodeError,ValueError) as e:p.error(f"中間JSONを読み込めません: {e}")
 server=ThreadingHTTPServer((a.host,a.port),make_handler(path));print(f"中間JSON: {path}");print(f"確認画面: http://{a.host}:{a.port}/");print("終了: Ctrl+C");server.serve_forever()
if __name__=="__main__":main()
