#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pass 2: 中間JSONを画像1枚ずつブラウザで確認・編集する。"""
from __future__ import annotations
import argparse,json,mimetypes,os,subprocess,sys,threading,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
DEFAULT_JSON_PATH=Path("data/import_yayoi/receipt_work.json")
ACCOUNT_CANDIDATES=["旅費交通費","接待交際費","雑費"]
SUMMARY_CANDIDATES=["ガソリン代","駐車・駐輪代","マッサージ代","散髪代","修理用、部品、工具代","オファー待ち受け代"]
HTML=r'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>レシート確認</title><style>
body{font-family:sans-serif;margin:0;background:#eee}header{padding:8px 16px;background:#333;color:#fff;display:flex;gap:20px;height:32px;box-sizing:border-box;align-items:center}.searchBox{width:220px;box-sizing:border-box;padding:3px 6px;font-size:14px}.main{display:grid;grid-template-columns:300px minmax(420px,1fr) 430px;height:calc(100vh - 32px)}.list{overflow:auto;background:#fafafa;border-right:1px solid #bbb;padding:6px 0}.listRow{display:flex;align-items:center;width:100%;white-space:nowrap}.confirmMark{flex:0 0 26px;border:0;background:transparent;padding:5px 2px 5px 7px;font-family:monospace;font-size:14px;cursor:pointer}.memoMark{flex:0 0 20px;text-align:center;font-size:14px}.listItem{flex:1;border:0;background:transparent;text-align:left;padding:5px 10px 5px 2px;font-size:14px;white-space:nowrap;cursor:pointer;overflow:hidden}.listRow:hover{background:#e9e9e9}.listRow.selected{background:#d8d8d8;font-weight:bold}.listRow.confirmed .listItem{color:#777}.listRow.unused{background:#fff2a8}.listRow.unused .listItem{color:#665500}.listRow.unused.selected{background:#f3df72}.image{display:flex;align-items:flex-start;justify-content:center;overflow:auto;background:#555;padding:12px}.image img{max-width:100%;height:auto;background:white}.form{padding:16px;overflow:auto;background:white}.row{margin:9px 0}.row label{display:block;font-weight:bold;margin-bottom:3px}.row input,.row textarea{box-sizing:border-box;width:100%;font-size:16px;padding:6px}.check{font-size:18px;margin:16px 0}.check input{transform:scale(1.4);margin-right:8px}.warn{padding:8px;background:#fff3cd;white-space:pre-wrap}.buttons{display:flex;gap:8px;position:sticky;bottom:0;background:white;padding:12px 0}.buttons button,.finalButtons button{font-size:16px;padding:10px 14px}.muted{color:#666;font-size:13px}.finalButtons{display:flex;gap:8px;margin-top:12px}</style></head><body>
<header><span id="pos"></span><span id="progress"></span><label><input id="onlyUnconfirmed" type="checkbox"> 未確認だけ</label><input id="searchText" class="searchBox" type="search" placeholder="JSON内を検索"></header><div class="main"><nav class="list" id="receiptList"></nav><div class="image"><img id="receiptImage"></div><div class="form"><div class="warn" id="warning"></div>
<div class="row"><label>画像ファイル</label><div id="filename"></div></div><div class="row"><label>支払日</label><input id="date" type="date"></div><div class="row"><label>時刻</label><input id="time"></div><div class="row"><label>金額</label><input id="amount" type="number"></div><div class="row"><label>店名</label><input id="vendor" list="vendorCandidates"><datalist id="vendorCandidates"></datalist></div><div class="row"><label>勘定科目</label><input id="debit_account" list="accountCandidates"><datalist id="accountCandidates"></datalist></div><div class="row"><label>摘要</label><input id="summary" list="summaryCandidates"><datalist id="summaryCandidates"></datalist></div><div class="row"><label>メモ</label><input id="memo" list="memoCandidates"><datalist id="memoCandidates"></datalist></div><label class="check"><input id="use" type="checkbox">このレシートを使用する</label><label class="check"><input id="confirmed" type="checkbox">確認済み</label><div class="row"><label>OCR全文</label><textarea id="ocr_text" rows="10" readonly></textarea></div>
<div class="buttons"><button onclick="move(-1)">← 前へ</button><button onclick="resetCurrent()">リセット</button><button onclick="goBack()">戻る</button><button onclick="confirmCurrent()">確認</button><button onclick="move(1)">次へ →</button></div><div class="muted">編集内容は自動保存されます。「リセット」で現在の画像をこの画面の起動時の状態へ戻します。</div><div class="finalButtons"><button onclick="generateImport()">importファイル出力</button><button onclick="exitReview()">終了</button></div></div></div>
<script>
let data=[],initialData=[],index=0,saveTimer=null,pendingSave=null,history=[];const fields=['date','time','vendor','debit_account','summary','memo'];
function menuName(r){let d=(r.date||'').match(/^\d{4}-(\d{2})-(\d{2})$/),prefix=d?d[1]+d[2]:'----',base=(r.image||'').replace(/^(?:\d{4}_)+/,'');return prefix+'_'+base}function sortedIndexes(){return data.map((r,i)=>i).sort((a,b)=>menuName(data[a]).localeCompare(menuName(data[b]),'ja',{numeric:true})||a-b)}function visibleIndexes(){let only=document.getElementById('onlyUnconfirmed').checked,q=document.getElementById('searchText').value.trim().toLocaleLowerCase('ja');return sortedIndexes().filter(i=>(!only||!data[i].confirmed)&&(!q||JSON.stringify(data[i]).toLocaleLowerCase('ja').includes(q)))}
function setCandidates(id,values){let dl=document.getElementById(id);dl.textContent='';[...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja')).forEach(v=>{let o=document.createElement('option');o.value=v;dl.appendChild(o)})}
async function saveState(){let res=await fetch('/api/review-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index,history})});if(!res.ok)throw new Error(await res.text())}
async function load(){try{let res=await fetch('/api/receipts');if(!res.ok)throw new Error(await res.text());data=await res.json();initialData=structuredClone(data);if(!data.length)throw new Error('レシートデータがありません');let c=await fetch('/api/candidates');if(c.ok){let x=await c.json();setCandidates('vendorCandidates',x.vendors);setCandidates('accountCandidates',x.accounts);setCandidates('summaryCandidates',x.summaries);setCandidates('memoCandidates',x.memos)}let stateRes=await fetch('/api/review-state'),state=stateRes.ok?await stateRes.json():{},savedHistory=Array.isArray(state.history)?state.history.filter(i=>Number.isInteger(i)&&i>=0&&i<data.length):[];if(savedHistory.length&&Number.isInteger(state.index)&&state.index>=0&&state.index<data.length){history=savedHistory;index=state.index}else{history=[];let all=sortedIndexes(),u=all.find(i=>!data[i].confirmed&&data[i].use!==false);index=u!==undefined?u:all[all.length-1]}show()}catch(e){document.getElementById('warning').textContent='読み込みエラー: '+e.message}}
function renderList(){let nav=document.getElementById('receiptList');nav.textContent='';for(let i of visibleIndexes()){let r=data[i],row=document.createElement('div'),mark=document.createElement('button'),memo=document.createElement('span'),b=document.createElement('button');row.className='listRow'+(i===index?' selected':'')+(r.confirmed?' confirmed':'')+(r.use===false?' unused':'');mark.type='button';mark.className='confirmMark';mark.textContent=r.confirmed?'[x]':'[ ]';mark.onclick=e=>{e.stopPropagation();toggleConfirmed(i)};memo.className='memoMark';memo.textContent=(r.memo||'').trim()?'📝':'';memo.title=(r.memo||'').trim()?r.memo:'';b.type='button';b.className='listItem';b.textContent=menuName(r);b.onclick=()=>jump(i);row.append(mark,memo,b);nav.appendChild(row)}requestAnimationFrame(()=>{let s=nav.querySelector('.selected');if(s)s.scrollIntoView({block:'nearest'})})}
function show(){let r=data[index],order=sortedIndexes(),p=order.indexOf(index);document.getElementById('pos').textContent=`${p+1} / ${data.length}`;document.getElementById('progress').textContent=`確認済 ${data.filter(x=>x.confirmed).length} / ${data.length}`;document.getElementById('receiptImage').src='/image?i='+index+'&t='+Date.now();document.getElementById('filename').textContent=r.image;document.getElementById('warning').textContent=r.warning||'警告なし';fields.forEach(f=>document.getElementById(f).value=r[f]??'');document.getElementById('amount').value=r.amount??'';document.getElementById('use').checked=r.use!==false;document.getElementById('confirmed').checked=!!r.confirmed;document.getElementById('ocr_text').value=r.ocr_text||'';renderList()}
function collect(){let r={...data[index]};fields.forEach(f=>r[f]=document.getElementById(f).value);let a=document.getElementById('amount').value;r.amount=a===''?null:Number(a);r.use=document.getElementById('use').checked;r.confirmed=document.getElementById('confirmed').checked;return r}
async function persist(i,r){let res=await fetch('/api/receipt?i='+i,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(r)});if(!res.ok){alert(await res.text());return false}data[i]=r;return true}
function scheduleSave(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>{saveTimer=null;let i=index,r=collect();pendingSave=persist(i,r).then(ok=>{if(ok)renderList();pendingSave=null})},250)}
async function flushSave(){if(saveTimer){clearTimeout(saveTimer);saveTimer=null;let i=index,r=collect();pendingSave=persist(i,r)}if(pendingSave)await pendingSave}
async function resetCurrent(){clearTimeout(saveTimer);saveTimer=null;if(pendingSave)await pendingSave;let i=index,r=structuredClone(initialData[i]);if(await persist(i,r))show()}
async function switchTo(i,remember=true){if(i===index)return;if(remember)history.push(index);index=i;show();await saveState()}
async function goBack(){await flushSave();if(history.length){let i=history.pop();index=i;show();await saveState()}}
async function confirmCurrent(){await flushSave();let current=index,r={...data[current],confirmed:true};if(await persist(current,r)){document.getElementById('confirmed').checked=true;let next=sortedIndexes().find(i=>!data[i].confirmed&&data[i].use!==false);if(next!==undefined)await switchTo(next,true);else{show();await saveState()}}}
async function toggleConfirmed(i){await flushSave();let r={...data[i],confirmed:!data[i].confirmed};if(await persist(i,r)){if(i===index)document.getElementById('confirmed').checked=r.confirmed;show()}}
async function jump(i){await flushSave();if(i!==index)await switchTo(i,true)}async function move(dir){await flushSave();let order=sortedIndexes(),p=order.indexOf(index),n=p+dir;if(n>=0&&n<order.length)await switchTo(order[n],true)}
async function generateImport(){await flushSave();let res=await fetch('/api/generate',{method:'POST'}),text=await res.text();alert(text);if(res.ok){let r=await fetch('/api/receipts');if(r.ok){data=await r.json();show();await saveState()}}}
async function exitReview(){await flushSave();await saveState();let res=await fetch('/api/shutdown',{method:'POST'});if(!res.ok){alert(await res.text());return}window.open('','_self');window.close();setTimeout(()=>{document.body.innerHTML='<div style="padding:30px;font-family:sans-serif">レシート確認を終了しました。このタブはブラウザの制限により自動で閉じられませんでした。</div>'},300)}
fields.concat(['amount']).forEach(id=>document.getElementById(id).addEventListener('input',scheduleSave));['use','confirmed'].forEach(id=>document.getElementById(id).addEventListener('change',scheduleSave));document.getElementById('onlyUnconfirmed').addEventListener('change',async()=>{await flushSave();let list=visibleIndexes();if(list.length&&!list.includes(index))await switchTo(list[0],true);else show()});document.getElementById('searchText').addEventListener('input',()=>renderList());document.addEventListener('keydown',e=>{if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();confirmCurrent()}});load();
</script></body></html>'''
def make_handler(json_path:Path):
 def load_work():return json.loads(json_path.read_text(encoding="utf-8"))
 def save_work(work):
  tmp=json_path.with_suffix(json_path.suffix+".tmp");tmp.write_text(json.dumps(work,ensure_ascii=False,indent=2),encoding="utf-8");tmp.replace(json_path)
 def candidates(work):
  rs=work.get("receipts",[]);v=[str(r.get("vendor","")) for r in rs];a=ACCOUNT_CANDIDATES+[str(r.get("debit_account","")) for r in rs];s=SUMMARY_CANDIDATES+[str(r.get("summary","")) for r in rs];m=[str(r.get("memo","")) for r in rs];return{"vendors":sorted(set(filter(None,v))),"accounts":sorted(set(filter(None,a))),"summaries":sorted(set(filter(None,s))),"memos":sorted(set(filter(None,m)))}
 class Handler(BaseHTTPRequestHandler):
  def send_bytes(self,body:bytes,ctype:str,status=200):self.send_response(status);self.send_header("Content-Type",ctype);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
  def do_GET(self):
   u=urllib.parse.urlparse(self.path);q=urllib.parse.parse_qs(u.query)
   if u.path=="/":return self.send_bytes(HTML.encode(),"text/html; charset=utf-8")
   work=load_work()
   if u.path=="/api/receipts":return self.send_bytes(json.dumps(work["receipts"],ensure_ascii=False).encode(),"application/json; charset=utf-8")
   if u.path=="/api/candidates":return self.send_bytes(json.dumps(candidates(work),ensure_ascii=False).encode(),"application/json; charset=utf-8")
   if u.path=="/api/review-state":return self.send_bytes(json.dumps(work.get("review_state",{}),ensure_ascii=False).encode(),"application/json; charset=utf-8")
   if u.path=="/image":
    try:
     i=int(q.get("i",["0"])[0]);r=work["receipts"][i];p=Path(work["image_dir"])/r["image"];return self.send_bytes(p.read_bytes(),mimetypes.guess_type(p.name)[0] or "application/octet-stream")
    except Exception as e:return self.send_bytes(str(e).encode(),"text/plain; charset=utf-8",404)
   self.send_error(404)
  def do_POST(self):
   u=urllib.parse.urlparse(self.path);q=urllib.parse.parse_qs(u.query)
   try:
    if u.path=="/api/receipt":
     i=int(q["i"][0]);n=int(self.headers.get("Content-Length","0"));r=json.loads(self.rfile.read(n));work=load_work();work["receipts"][i]=r;save_work(work);return self.send_bytes(b"ok","text/plain")
    if u.path=="/api/review-state":
     n=int(self.headers.get("Content-Length","0"));state=json.loads(self.rfile.read(n));work=load_work();work["review_state"]={"index":state.get("index"),"history":state.get("history",[])};save_work(work);return self.send_bytes(b"ok","text/plain")
    if u.path=="/api/generate":
     script=Path(__file__).with_name("yayoi_receipt_generate.py");result=subprocess.run([sys.executable,str(script),str(json_path)],capture_output=True,text=True,encoding="utf-8");text=(result.stdout+result.stderr).strip() or ("完了" if result.returncode==0 else "失敗");return self.send_bytes(text.encode(),"text/plain; charset=utf-8",200 if result.returncode==0 else 500)
    if u.path=="/api/shutdown":
     self.send_bytes("終了します".encode(),"text/plain; charset=utf-8");threading.Thread(target=self.server.shutdown,daemon=True).start();return
    self.send_error(404)
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
 server=ThreadingHTTPServer((a.host,a.port),make_handler(path));web_host=os.environ.get("WEB_HOST");url=f"https://{a.port}-{web_host}/" if web_host else f"http://{'127.0.0.1' if a.host in ('0.0.0.0','::') else a.host}:{a.port}/";print(f"中間JSON: {path}");print(f"確認画面: {url}");print("Cloud Shellでは上記URLを開くか、[ウェブでプレビュー]からポートを選択してください。" if web_host else "確認画面をブラウザで開いてください。");print("終了: Ctrl+C");server.serve_forever()
if __name__=="__main__":main()
