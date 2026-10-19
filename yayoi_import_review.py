#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成済みの弥生インポートTXTをブラウザで確認・編集する。"""
from __future__ import annotations
import argparse,csv,json,os,threading,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

FIELD_NAMES=["識別フラグ","伝票No","決算","取引日付","借方勘定科目","借方補助科目","借方部門","借方税区分","借方金額","借方税金額","貸方勘定科目","貸方補助科目","貸方部門","貸方税区分","貸方金額","貸方税金額","摘要","番号","期日","タイプ","生成元","仕訳メモ","付箋1","付箋2","調整"]
HTML=r'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>弥生インポート確認</title><style>
body{font-family:sans-serif;margin:0;background:#eee}header{height:44px;box-sizing:border-box;padding:7px 12px;background:#333;color:#fff;display:flex;align-items:center;gap:12px}header button{padding:6px 12px;font-size:14px}.wrap{height:calc(100vh - 44px);overflow:auto;background:#fff}table{border-collapse:collapse;table-layout:fixed;width:max-content;min-width:100%}th,td{border:1px solid #ccc;padding:0;overflow:hidden}th{position:sticky;top:0;background:#eee;z-index:2;padding:6px 8px;white-space:nowrap;font-size:13px;box-sizing:border-box}.thInner{position:relative;width:100%;height:100%}.resizer{position:absolute;right:-8px;top:-6px;width:10px;height:29px;cursor:col-resize;z-index:4}.resizer:hover{background:rgba(0,0,0,.12)}td input{border:0;width:100%;box-sizing:border-box;padding:6px;font-size:14px;background:transparent;text-overflow:clip}tr.dirty{background:#fff4cc}.status{margin-left:auto;color:#ddd}.rowno{padding:0 7px;background:#f5f5f5;text-align:right;position:sticky;left:0;z-index:1;width:48px;box-sizing:border-box}</style></head><body><header><strong id="filename"></strong><button onclick="save()">保存</button><button onclick="downloadFile()">ダウンロード</button><button onclick="reloadRows()">再読込</button><button onclick="exitReview()">終了</button><span>列境界をドラッグで幅変更、クリックで内容に合わせます。</span><span class="status" id="status"></span></header><div class="wrap"><table id="grid"><colgroup id="cols"><col style="width:48px"></colgroup><thead><tr id="head"><th>#</th></tr></thead><tbody id="body"></tbody></table></div><script>
let rows=[],dirty=new Set(),colWidths=[];const MIN_WIDTH=48,MAX_AUTO_WIDTH=800;
function yayoiToIso(v){let m=(v||'').match(/^R\.(\d{1,2})\/(\d{1,2})\/(\d{1,2})$/i);if(m)return `${2018+Number(m[1])}-${String(m[2]).padStart(2,'0')}-${String(m[3]).padStart(2,'0')}`;m=(v||'').match(/^(\d{4})[\/-](\d{1,2})[\/-](\d{1,2})$/);return m?`${m[1]}-${String(m[2]).padStart(2,'0')}-${String(m[3]).padStart(2,'0')}`:''}
function isoToYayoi(v){let m=(v||'').match(/^(\d{4})-(\d{2})-(\d{2})$/);if(!m)return v;let y=Number(m[1]);return y>=2019?`R.${String(y-2018).padStart(2,'0')}/${m[2]}/${m[3]}`:`${m[1]}/${m[2]}/${m[3]}`}
function markDirty(ri,tr){dirty.add(ri);tr.className='dirty';document.getElementById('status').textContent='未保存の変更あり'}
function defaultWidth(ci){if(ci===3)return 145;if([4,10,16,21].includes(ci))return 180;return 100}
function applyWidth(ci,w){w=Math.max(MIN_WIDTH,Math.round(w));colWidths[ci]=w;let c=document.getElementById('cols').children[ci+1];if(c)c.style.width=w+'px'}
function measureText(text,font){let c=measureText.canvas||(measureText.canvas=document.createElement('canvas')),ctx=c.getContext('2d');ctx.font=font;return ctx.measureText(String(text??'')).width}
function autoSize(ci){let th=document.getElementById('head').children[ci+1],font=getComputedStyle(th).font,max=measureText(FIELDS[ci],font)+28;for(let r of rows){let v=r[ci]??'';if(ci===3)v=yayoiToIso(v)||v;max=Math.max(max,measureText(v,'14px sans-serif')+20)}applyWidth(ci,Math.min(MAX_AUTO_WIDTH,max))}
function attachResizer(handle,ci){let startX,startW,moved=false;handle.addEventListener('pointerdown',e=>{e.preventDefault();e.stopPropagation();startX=e.clientX;startW=colWidths[ci];moved=false;handle.setPointerCapture(e.pointerId)});handle.addEventListener('pointermove',e=>{if(startX===undefined)return;let d=e.clientX-startX;if(Math.abs(d)>=2)moved=true;if(moved)applyWidth(ci,startW+d)});handle.addEventListener('pointerup',e=>{if(startX===undefined)return;handle.releasePointerCapture(e.pointerId);startX=undefined;if(!moved)autoSize(ci)});handle.addEventListener('dblclick',e=>{e.preventDefault();e.stopPropagation();autoSize(ci)})}
function render(){let h=document.getElementById('head');h.innerHTML='<th>#</th>';let cg=document.getElementById('cols');cg.innerHTML='<col style="width:48px">';FIELDS.forEach((x,ci)=>{if(!colWidths[ci])colWidths[ci]=defaultWidth(ci);let col=document.createElement('col');col.style.width=colWidths[ci]+'px';cg.appendChild(col);let th=document.createElement('th'),inner=document.createElement('div'),handle=document.createElement('span');inner.className='thInner';inner.append(document.createTextNode(x),handle);handle.className='resizer';handle.title='ドラッグ: 幅変更 / クリック: 内容に合わせる';attachResizer(handle,ci);th.appendChild(inner);h.appendChild(th)});let b=document.getElementById('body');b.textContent='';rows.forEach((r,ri)=>{let tr=document.createElement('tr');if(dirty.has(ri))tr.className='dirty';let no=document.createElement('td');no.className='rowno';no.textContent=ri+1;tr.appendChild(no);for(let ci=0;ci<FIELDS.length;ci++){let td=document.createElement('td'),inp=document.createElement('input');if(ci===3){inp.type='date';inp.value=yayoiToIso(r[ci]??'');inp.onchange=()=>{while(rows[ri].length<FIELDS.length)rows[ri].push('');rows[ri][ci]=isoToYayoi(inp.value);markDirty(ri,tr)}}else{inp.value=r[ci]??'';inp.oninput=()=>{while(rows[ri].length<FIELDS.length)rows[ri].push('');rows[ri][ci]=inp.value;markDirty(ri,tr)}}td.appendChild(inp);tr.appendChild(td)}b.appendChild(tr)})}
async function reloadRows(){if(dirty.size&&!confirm('未保存の変更を破棄して再読込しますか？'))return;let res=await fetch('/api/rows');if(!res.ok){alert(await res.text());return}let x=await res.json();rows=x.rows;dirty.clear();document.getElementById('filename').textContent=x.filename;document.getElementById('status').textContent=`${rows.length} 行`;render()}
async function save(){let res=await fetch('/api/rows',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows})});let t=await res.text();if(!res.ok){alert(t);return false}dirty.clear();document.getElementById('status').textContent=t;render();return true}
async function downloadFile(){if(dirty.size){if(!confirm('未保存の変更があります。保存してからダウンロードしますか？'))return;if(!await save())return}let a=document.createElement('a');a.href='/download?t='+Date.now();a.download=document.getElementById('filename').textContent||'import.txt';document.body.appendChild(a);a.click();a.remove()}
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
  def send_bytes(self,body,ctype="text/plain; charset=utf-8",status=200,headers=None):
   self.send_response(status);self.send_header("Content-Type",ctype);self.send_header("Content-Length",str(len(body)))
   for k,v in (headers or {}).items():self.send_header(k,v)
   self.end_headers();self.wfile.write(body)
  def do_GET(self):
   u=urllib.parse.urlparse(self.path)
   if u.path=="/":return self.send_bytes(HTML.encode(),"text/html; charset=utf-8")
   if u.path=="/api/rows":
    try:return self.send_bytes(json.dumps({"filename":path.name,"rows":read_rows(path)},ensure_ascii=False).encode(),"application/json; charset=utf-8")
    except Exception as e:return self.send_bytes(str(e).encode(),status=500)
   if u.path=="/download":
    try:
     body=path.read_bytes();name=urllib.parse.quote(path.name);return self.send_bytes(body,"text/plain; charset=shift_jis",headers={"Content-Disposition":f"attachment; filename*=UTF-8''{name}","Cache-Control":"no-store"})
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
