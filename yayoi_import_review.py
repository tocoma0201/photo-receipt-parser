#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成済みの弥生インポートTXTをブラウザで確認・編集する。"""
from __future__ import annotations
import argparse,csv,json,os,threading,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

FIELD_NAMES=["識別フラグ","伝票No","決算","取引日付","借方勘定科目","借方補助科目","借方部門","借方税区分","借方金額","借方税金額","貸方勘定科目","貸方補助科目","貸方部門","貸方税区分","貸方金額","貸方税金額","摘要","番号","期日","タイプ","生成元","仕訳メモ","付箋1","付箋2","調整"]
HTML=r'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>弥生インポート確認</title><style>
body{font-family:sans-serif;margin:0;background:#eee}header{height:44px;box-sizing:border-box;padding:7px 12px;background:#333;color:#fff;display:flex;align-items:center;gap:12px}header button{padding:6px 12px;font-size:14px}.wrap{height:calc(100vh - 44px);overflow:auto;background:#fff}table{border-collapse:collapse;min-width:2200px;width:100%}th,td{border:1px solid #ccc;padding:0}th{position:sticky;top:0;background:#eee;z-index:2;padding:6px 8px;white-space:nowrap;font-size:13px}td input{border:0;width:100%;min-width:90px;box-sizing:border-box;padding:6px;font-size:14px;background:transparent}td:nth-child(4) input{min-width:110px}td:nth-child(5) input,td:nth-child(11) input,td:nth-child(17) input,td:nth-child(22) input{min-width:180px}tr.dirty{background:#fff4cc}.status{margin-left:auto;color:#ddd}.rowno{padding:0 7px;background:#f5f5f5;text-align:right;position:sticky;left:0;z-index:1}</style></head><body><header><strong id="filename"></strong><button onclick="save()">保存</button><button onclick="reloadRows()">再読込</button><button onclick="exitReview()">終了</button><span>セルを直接編集できます。変更行は黄色表示されます。</span><span class="status" id="status"></span></header><div class="wrap"><table><thead><tr id="head"><th>#</th></tr></thead><tbody id="body"></tbody></table></div><script>
let rows=[],dirty=new Set();
function yayoiToIso(v){let m=(v||'').match(/^R\.(\d{1,2})\/(\d{1,2})\/(\d{1,2})$/i);if(m)return `${2018+Number(m[1])}-${String(m[2]).padStart(2,'0')}-${String(m[3]).padStart(2,'0')}`;m=(v||'').match(/^(\d{4})[\/-](\d{1,2})[\/-](\d{1,2})$/);return m?`${m[1]}-${String(m[2]).padStart(2,'0')}-${String(m[3]).padStart(2,'0')}`:''}
function isoToYayoi(v){let m=(v||'').match(/^(\d{4})-(\d{2})-(\d{2})$/);if(!m)return v;let y=Number(m[1]);return y>=2019?`R.${String(y-2018).padStart(2,'0')}/${m[2]}/${m[3]}`:`${m[1]}/${m[2]}/${m[3]}`}
function markDirty(ri,tr){dirty.add(ri);tr.className='dirty';document.getElementById('status').textContent='未保存の変更あり'}
function render(){let h=document.getElementById('head');h.innerHTML='<th>#</th>';FIELDS.forEach(x=>{let th=document.createElement('th');th.textContent=x;h.appendChild(th)});let b=document.getElementById('body');b.textContent='';rows.forEach((r,ri)=>{let tr=document.createElement('tr');if(dirty.has(ri))tr.className='dirty';let no=document.createElement('td');no.className='rowno';no.textContent=ri+1;tr.appendChild(no);for(let ci=0;ci<FIELDS.length;ci++){let td=document.createElement('td'),inp=document.createElement('input');if(ci===3){inp.type='date';inp.value=yayoiToIso(r[ci]??'');inp.onchange=()=>{while(rows[ri].length<FIELDS.length)rows[ri].push('');rows[ri][ci]=isoToYayoi(inp.value);markDirty(ri,tr)}}else{inp.value=r[ci]??'';inp.oninput=()=>{while(rows[ri].length<FIELDS.length)rows[ri].push('');rows[ri][ci]=inp.value;markDirty(ri,tr)}}td.appendChild(inp);tr.appendChild(td)}b.appendChild(tr)})}
async function reloadRows(){if(dirty.size&&!confirm('未保存の変更を破棄して再読込しますか？'))return;let res=await fetch('/api/rows');if(!res.ok){alert(await res.text());return}let x=await res.json();rows=x.rows;dirty.clear();document.getElementById('filename').textContent=x.filename;document.getElementById('status').textContent=`${rows.length} 行`;render()}
async function save(){let res=await fetch('/api/rows',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows})});let t=await res.text();if(!res.ok){alert(t);return}dirty.clear();document.getElementById('status').textContent=t;render()}
async function exitReview(){if(dirty.size&&!confirm('未保存の変更があります。保存せず終了しますか？'))return;let res=await fetch('/api/shutdown',{method:'POST'});if(!res.ok){alert(await res.text());return}window.open('','_self');window.close();setTimeout(()=>document.body.innerHTML='<div style="padding:30px;font-family:sans-serif">確認ツールを終了しました。このタブは閉じてください。</div>',300)}
const FIELDS='''+json.dumps(FIELD_NAMES,ensure_ascii=False)+r''';reloadRows();</script></body></html>'''

def read_rows(path:Path):
 with path.open("r",encoding="cp932",newline="") as f:return list(csv.reader(f))
def write_rows(path:Path,rows):
 tmp=path.with_suffix(path.suffix+".tmp")
 with tmp.open("w",encoding="cp932",newline="") as f:
  w=csv.writer(f,lineterminator="\r\n",quoting=csv.QUOTE_ALL)
  for row in rows:w.writerow(row)
 tmp.replace(path)
def make_handler(path:Path):
 class Handler(BaseHTTPRequestHandler):
  def send_bytes(self,body,ctype="text/plain; charset=utf-8",status=200):self.send_response(status);self.send_header("Content-Type",ctype);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
  def do_GET(self):
   if urllib.parse.urlparse(self.path).path=="/":return self.send_bytes(HTML.encode(),"text/html; charset=utf-8")
   if urllib.parse.urlparse(self.path).path=="/api/rows":
    try:return self.send_bytes(json.dumps({"filename":path.name,"rows":read_rows(path)},ensure_ascii=False).encode(),"application/json; charset=utf-8")
    except Exception as e:return self.send_bytes(str(e).encode(),status=500)
   self.send_error(404)
  def do_POST(self):
   u=urllib.parse.urlparse(self.path)
   try:
    if u.path=="/api/rows":
     n=int(self.headers.get("Content-Length","0"));x=json.loads(self.rfile.read(n));rows=x.get("rows")
     if not isinstance(rows,list):raise ValueError("rows が不正です")
     for i,row in enumerate(rows,1):
      if not isinstance(row,list):raise ValueError(f"{i}行目が不正です")
      if len(row)!=len(FIELD_NAMES):raise ValueError(f"{i}行目の列数が {len(row)} です（期待値 {len(FIELD_NAMES)}）")
     write_rows(path,rows);return self.send_bytes(f"保存しました: {len(rows)} 行".encode())
    if u.path=="/api/shutdown":
     self.send_bytes("終了します".encode());threading.Thread(target=self.server.shutdown,daemon=True).start();return
    self.send_error(404)
   except Exception as e:return self.send_bytes(str(e).encode(),status=400)
  def log_message(self,fmt,*args):pass
 return Handler
def main():
 p=argparse.ArgumentParser(description="弥生インポートTXTをWebで確認・編集");p.add_argument("txt_path");p.add_argument("--host",default="127.0.0.1");p.add_argument("--port",type=int,default=8081);a=p.parse_args();path=Path(a.txt_path).resolve()
 if not path.is_file():p.error(f"インポートファイルが見つかりません: {path}")
 try:read_rows(path)
 except Exception as e:p.error(f"インポートファイルを読み込めません: {e}")
 server=ThreadingHTTPServer((a.host,a.port),make_handler(path));web_host=os.environ.get("WEB_HOST");url=f"https://{a.port}-{web_host}/" if web_host else f"http://{'127.0.0.1' if a.host in ('0.0.0.0','::') else a.host}:{a.port}/";print(f"インポートファイル: {path}");print(f"確認画面: {url}");print("終了: Ctrl+C");server.serve_forever()
if __name__=="__main__":main()
