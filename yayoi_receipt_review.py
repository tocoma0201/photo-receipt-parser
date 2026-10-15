#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pass 2: 中間JSONを画像1枚ずつブラウザで確認・編集する。"""
from __future__ import annotations

import argparse
import json
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML = r'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>レシート確認</title>
<style>body{font-family:sans-serif;margin:0;background:#eee}header{padding:8px 16px;background:#333;color:#fff;display:flex;gap:20px}.main{display:grid;grid-template-columns:minmax(420px,1fr) 430px;height:calc(100vh - 48px)}.image{display:flex;align-items:flex-start;justify-content:center;overflow:auto;background:#555;padding:12px}.image img{max-width:100%;height:auto;background:white}.form{padding:16px;overflow:auto;background:white}.row{margin:9px 0}.row label{display:block;font-weight:bold;margin-bottom:3px}.row input,.row select,.row textarea{box-sizing:border-box;width:100%;font-size:16px;padding:6px}.check{font-size:18px;margin:16px 0}.check input{transform:scale(1.4);margin-right:8px}.warn{padding:8px;background:#fff3cd;white-space:pre-wrap}.buttons{display:flex;gap:8px;position:sticky;bottom:0;background:white;padding:12px 0}.buttons button{font-size:16px;padding:10px 14px}.muted{color:#666;font-size:13px}</style></head><body>
<header><span id="pos"></span><span id="progress"></span><label><input id="onlyUnconfirmed" type="checkbox" checked> 未確認だけ</label></header>
<div class="main"><div class="image"><img id="receiptImage"></div><div class="form">
<div class="warn" id="warning"></div>
<div class="row"><label>画像ファイル</label><div id="filename"></div></div>
<div class="row"><label>支払日</label><input id="date" type="date"></div>
<div class="row"><label>時刻</label><input id="time"></div>
<div class="row"><label>金額</label><input id="amount" type="number"></div>
<div class="row"><label>店名</label><input id="vendor"></div>
<div class="row"><label>勘定科目</label><input id="debit_account"></div>
<div class="row"><label>摘要</label><input id="summary"></div>
<label class="check"><input id="use" type="checkbox">このレシートを使用する</label>
<label class="check"><input id="confirmed" type="checkbox">確認済み</label>
<div class="row"><label>OCR全文</label><textarea id="ocr_text" rows="10" readonly></textarea></div>
<div class="buttons"><button onclick="move(-1)">← 前へ</button><button onclick="save(false)">保存</button><button onclick="save(true)">確認して次へ →</button></div>
<div class="muted">確認済みは作業進捗だけに使用され、インポート生成条件にはなりません。</div>
</div></div>
<script>
let data=[], index=0; const fields=['date','time','vendor','debit_account','summary'];
async function load(){data=await (await fetch('/api/receipts')).json(); let u=data.findIndex(x=>!x.confirmed); index=u>=0?u:0; show()}
function visibleIndexes(){let only=document.getElementById('onlyUnconfirmed').checked; return data.map((r,i)=>[r,i]).filter(([r])=>!only||!r.confirmed).map(([,i])=>i)}
function show(){if(!data.length)return; let r=data[index]; document.getElementById('pos').textContent=`${index+1} / ${data.length}`; document.getElementById('progress').textContent=`確認済 ${data.filter(x=>x.confirmed).length} / ${data.length}`; document.getElementById('receiptImage').src='/image?i='+index+'&t='+Date.now(); document.getElementById('filename').textContent=r.image; document.getElementById('warning').textContent=r.warning||'警告なし'; fields.forEach(f=>document.getElementById(f).value=r[f]??''); document.getElementById('amount').value=r.amount??''; document.getElementById('use').checked=r.use!==false; document.getElementById('confirmed').checked=!!r.confirmed; document.getElementById('ocr_text').value=r.ocr_text||''}
function collect(confirm){let r={...data[index]}; fields.forEach(f=>r[f]=document.getElementById(f).value); let a=document.getElementById('amount').value;r.amount=a===''?null:Number(a);r.use=document.getElementById('use').checked;r.confirmed=confirm?true:document.getElementById('confirmed').checked;return r}
async function save(next){let r=collect(next);let res=await fetch('/api/receipt?i='+index,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(r)});if(!res.ok){alert(await res.text());return}data[index]=r;if(next)move(1);else show()}
function move(dir){let list=visibleIndexes();let p=list.indexOf(index);if(p<0){let candidate=list.find(i=>dir>0?i>index:i<index);if(candidate!==undefined)index=candidate}else{let n=p+dir;if(n>=0&&n<list.length)index=list[n]}show()}
document.getElementById('onlyUnconfirmed').addEventListener('change',()=>{let list=visibleIndexes();if(list.length&&!list.includes(index))index=list[0];show()});
document.addEventListener('keydown',e=>{if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();save(true)}});load();
</script></body></html>'''


def make_handler(json_path: Path):
    def load_work():
        return json.loads(json_path.read_text(encoding="utf-8"))
    def save_work(work):
        tmp = json_path.with_suffix(json_path.suffix + ".tmp")
        tmp.write_text(json.dumps(work, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(json_path)

    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self, body: bytes, ctype: str, status=200):
            self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            u=urllib.parse.urlparse(self.path); q=urllib.parse.parse_qs(u.query)
            if u.path=="/": return self.send_bytes(HTML.encode(), "text/html; charset=utf-8")
            work=load_work()
            if u.path=="/api/receipts": return self.send_bytes(json.dumps(work["receipts"],ensure_ascii=False).encode(), "application/json; charset=utf-8")
            if u.path=="/image":
                try:
                    i=int(q.get("i",["0"])[0]); r=work["receipts"][i]; p=Path(work["image_dir"])/r["image"]
                    body=p.read_bytes(); return self.send_bytes(body, mimetypes.guess_type(p.name)[0] or "application/octet-stream")
                except Exception as e: return self.send_bytes(str(e).encode(), "text/plain; charset=utf-8",404)
            self.send_error(404)
        def do_POST(self):
            u=urllib.parse.urlparse(self.path); q=urllib.parse.parse_qs(u.query)
            if u.path!="/api/receipt": return self.send_error(404)
            try:
                i=int(q["i"][0]); n=int(self.headers.get("Content-Length","0")); r=json.loads(self.rfile.read(n)); work=load_work(); work["receipts"][i]=r; save_work(work); return self.send_bytes(b"ok","text/plain")
            except Exception as e: return self.send_bytes(str(e).encode(),"text/plain; charset=utf-8",400)
        def log_message(self, fmt, *args): pass
    return Handler


def main():
    p=argparse.ArgumentParser(description="Pass 2: 中間JSONをブラウザで確認・編集")
    p.add_argument("json_path"); p.add_argument("--host",default="127.0.0.1"); p.add_argument("--port",type=int,default=8080); a=p.parse_args()
    path=Path(a.json_path).resolve(); server=ThreadingHTTPServer((a.host,a.port),make_handler(path)); print(f"確認画面: http://{a.host}:{a.port}/"); print("終了: Ctrl+C"); server.serve_forever()

if __name__=="__main__": main()
