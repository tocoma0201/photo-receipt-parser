#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pass 3: 中間JSONから弥生インポートを生成し、画像名の日付を同期する。"""
from __future__ import annotations
import argparse,csv,datetime,json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import yayoi_receipt_import_old as core
@dataclass
class ExportReceipt:
 record:dict;payment_date:date;amount:int;vendor:str;time_text:str;debit_account:str;summary:str;memo:str
def parse_record(r):
 if r.get("use",True) is False:return None
 try:d=date.fromisoformat(r.get("date",""));amount=int(r["amount"])
 except (ValueError,TypeError,KeyError):return None
 return ExportReceipt(r,d,amount,r.get("vendor",""),r.get("time",""),r.get("debit_account","雑費"),r.get("summary","オファー待ち受け代"),r.get("image",""))
def deduplicate(items):
 merged={}
 for x in items:
  key=(core.vendor_key(x.vendor),x.payment_date.isoformat(),x.time_text,x.amount)
  if key not in merged:merged[key]=x;continue
  base=merged[key];names=[n for n in base.memo.split("\n") if n]
  if x.memo and x.memo not in names:names.append(x.memo)
  base.memo="\n".join(names)
 return sorted(merged.values(),key=lambda x:(x.payment_date,x.time_text,x.vendor,x.amount,x.memo))
def sync_filename(item,image_root):
 r=item.record;rel=Path(r["image"]);old=image_root/rel;new_name=core.build_prefixed_name(item.payment_date,old.name);new=old.with_name(new_name)
 if old!=new:
  if old.exists() and not new.exists():old.rename(new)
  elif old.exists() and new.exists():raise FileExistsError(f"リネーム先が既に存在します: {new}")
  elif not new.exists():raise FileNotFoundError(f"画像が見つかりません: {old}")
 r["image"]=str(rel.with_name(new_name)).replace("\\","/");item.memo=r["image"]
def make_row(seq,x):return ["2000",seq,"",core.to_reiwa_string(x.payment_date),x.debit_account,"","",core.DEFAULT_TAX_IN,x.amount,0,core.DEFAULT_ACCOUNT_CASH,"","",core.DEFAULT_TAX_OUT,x.amount,0,x.summary,"","",0,"",x.memo,"0","0","no"]
def main():
 p=argparse.ArgumentParser(description="Pass 3: JSONから弥生インポート生成・画像名同期");p.add_argument("json_path");p.add_argument("--output-dir",default=None);p.add_argument("--no-deduplicate",action="store_true",help="同一取引候補を1行に統合しない");a=p.parse_args();json_path=Path(a.json_path);work=json.loads(json_path.read_text(encoding="utf-8"));image_root=Path(work["image_dir"]);output_dir=Path(a.output_dir) if a.output_dir else json_path.parent;output_dir.mkdir(parents=True,exist_ok=True);valid=[];invalid_used=[]
 for r in work["receipts"]:
  x=parse_record(r)
  if x is None:
   if r.get("use",True):invalid_used.append(r.get("image","?"))
   continue
  sync_filename(x,image_root);valid.append(x)
 tmp=json_path.with_suffix(json_path.suffix+".tmp");tmp.write_text(json.dumps(work,ensure_ascii=False,indent=2),encoding="utf-8");tmp.replace(json_path);rows=valid if a.no_deduplicate else deduplicate(valid);out=output_dir/datetime.datetime.now().strftime("import_%Y%m%d.txt")
 with out.open("w",encoding="cp932",newline="") as f:
  writer=csv.writer(f,lineterminator="\r\n",quoting=csv.QUOTE_ALL)
  for i,x in enumerate(rows,1):writer.writerow([core.safe_text_for_encoding(str(v),"cp932") if isinstance(v,str) else v for v in make_row(i,x)])
 print(f"インポートファイル: {out}");print(f"使用画像: {len(valid)} / 出力行: {len(rows)}")
 if invalid_used:
  print(f"日付または金額不足で出力できなかった使用対象: {len(invalid_used)}")
  for name in invalid_used:print(f"  {name}")
 return 0
if __name__=="__main__":raise SystemExit(main())
