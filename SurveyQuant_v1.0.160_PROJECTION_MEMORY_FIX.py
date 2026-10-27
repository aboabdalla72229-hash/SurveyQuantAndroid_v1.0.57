#!/usr/bin/env python3
"""Reduce projection-time memory peaks in SurveyQuant's shared CAD runtime."""
from __future__ import annotations
import argparse
from pathlib import Path

SCANNER = r'''// Lightweight DXF metadata scanner. It walks code/value lines once and keeps only
// section/table markers, existing layer names, and the handles needed for safe edits.
function sqScanProjectionDxf(rawBytes){
 if(!(rawBytes instanceof Uint8Array)||!rawBytes.length)throw new Error('لا تتوفر بايتات DXF الأصلية للحفاظ على تفاصيل اللوحة.');
 const decoded=new TextDecoder('windows-1252').decode(rawBytes);
 const originalText=decoded.startsWith('ï»¿')?'   '+decoded.slice(3):decoded;
 const result={eol:originalText.includes('\r\n')?'\r\n':'\n',version:'AC1009',entitySection:null,layerTable:null,layerNames:new Set(),maxHandle:0n,modelSpaceHandle:null,handseedPair:null};
 let pos=0,previous=null,activeSection='',activeTable='',layerRow=null,blockRow=null;
 const lineAt=start=>{if(start>=originalText.length)return null;const nl=originalText.indexOf('\n',start),lineEnd=nl<0?originalText.length:nl;let valueEnd=lineEnd;if(valueEnd>start&&originalText[valueEnd-1]==='\r')valueEnd--;return{text:originalText.slice(start,valueEnd),start,valueEnd,end:nl<0?originalText.length:nl+1};};
 while(pos<originalText.length){
  const codeLine=lineAt(pos);if(!codeLine)break;const valueLine=lineAt(codeLine.end);if(!valueLine)break;
  const pair={code:codeLine.text.trim(),value:valueLine.text.trim(),start:codeLine.start,valueStart:valueLine.start,valueEnd:valueLine.valueEnd,end:valueLine.end};
  if(previous&&previous.code==='9'&&previous.value.toUpperCase()==='$ACADVER')result.version=pair.value||'AC1009';
  if(previous&&previous.code==='9'&&previous.value.toUpperCase()==='$HANDSEED'&&pair.code==='5')result.handseedPair=pair;
  if((pair.code==='5'||pair.code==='105')&&/^[0-9A-F]+$/i.test(pair.value)){try{const h=BigInt('0x'+pair.value);if(h>result.maxHandle)result.maxHandle=h;}catch(_){}}
  if(previous&&previous.code==='0'&&previous.value.toUpperCase()==='SECTION'&&pair.code==='2'){
   activeSection=pair.value.toUpperCase();
  }
  if(pair.code==='0'&&pair.value.toUpperCase()==='ENDSEC'&&activeSection){
   if(activeSection==='ENTITIES')result.entitySection={endSec:pair};
   activeSection='';
  }
  if(previous&&previous.code==='0'&&previous.value.toUpperCase()==='TABLE'&&pair.code==='2'){
   activeTable=pair.value.toUpperCase();layerRow=null;blockRow=null;
   if(activeTable==='LAYER')result.layerTable={tableStart:previous.start,endTab:null,rows:[],countPair:null,tableHandlePair:null};
  }
  if(activeTable==='LAYER'&&result.layerTable){
   if(pair.code==='0'){
    if(layerRow){layerRow.end=pair.start;result.layerTable.rows.push(layerRow);if(layerRow.name)result.layerNames.add(layerRow.name.toUpperCase());layerRow=null;}
    if(pair.value.toUpperCase()==='LAYER')layerRow={start:pair.start,end:pair.end,name:''};
    else if(pair.value.toUpperCase()==='ENDTAB'){result.layerTable.endTab=pair;activeTable='';}
   }else if(layerRow){if(pair.code==='2'&&!layerRow.name)layerRow.name=pair.value;}
   else{
    if(pair.code==='70'&&!result.layerTable.countPair)result.layerTable.countPair=pair;
    if(pair.code==='5'&&!result.layerTable.tableHandlePair)result.layerTable.tableHandlePair=pair;
   }
  }else if(activeTable==='BLOCK_RECORD'){
   if(pair.code==='0'){
    if(blockRow&&blockRow.name&&blockRow.handle&&blockRow.name.replace(/[\s_-]/g,'').toUpperCase()==='*MODELSPACE')result.modelSpaceHandle=blockRow.handle.toUpperCase();
    blockRow=null;
    if(pair.value.toUpperCase()==='BLOCK_RECORD')blockRow={name:'',handle:''};
    else if(pair.value.toUpperCase()==='ENDTAB')activeTable='';
   }else if(blockRow){if(pair.code==='2'&&!blockRow.name)blockRow.name=pair.value;if(pair.code==='5'&&!blockRow.handle)blockRow.handle=pair.value;}
  }
  previous=pair;pos=pair.end;
 }
 if(activeTable==='LAYER'&&layerRow){layerRow.end=originalText.length;result.layerTable.rows.push(layerRow);if(layerRow.name)result.layerNames.add(layerRow.name.toUpperCase());}
 if(activeTable==='BLOCK_RECORD'&&blockRow&&blockRow.name&&blockRow.handle&&blockRow.name.replace(/[\s_-]/g,'').toUpperCase()==='*MODELSPACE')result.modelSpaceHandle=blockRow.handle.toUpperCase();
 if(!result.entitySection)throw new Error('لم يتم العثور على قسم ENTITIES صالح في لوحة DXF المرجعية.');
 if(!result.layerTable||!result.layerTable.endTab)throw new Error('لوحة DXF المرجعية لا تحتوي على جدول LAYER صالح؛ أوقفت التصدير لتجنب إعادة رسم اللوحة وتغيير خصائصها.');
 return result;
}
'''

BYTE_EDITS = r'''function sqApplyByteEdits(source,edits){
 // Allocate the final byte array once. Repeated full-buffer slice/concat cycles made
 // large drawings consume several times their size during projection.
 const ordered=edits.slice().sort((a,b)=>a.start-b.start||a.end-b.end);
 let total=source.length,cursor=0;
 for(const e of ordered){
  if(!Number.isInteger(e.start)||!Number.isInteger(e.end)||e.start<cursor||e.end<e.start||e.end>source.length)throw new Error('Projection byte edits overlap or exceed the reference DXF.');
  const insert=e.insertBytes||new Uint8Array(0);total+=insert.length-(e.end-e.start);cursor=e.end;
 }
 const out=new Uint8Array(total);let sourcePos=0,outPos=0;
 for(const e of ordered){const untouched=e.start-sourcePos;out.set(source.subarray(sourcePos,e.start),outPos);outPos+=untouched;const insert=e.insertBytes||new Uint8Array(0);out.set(insert,outPos);outPos+=insert.length;sourcePos=e.end;}
 out.set(source.subarray(sourcePos),outPos);outPos+=source.length-sourcePos;
 if(outPos!==out.length)throw new Error('Projection byte merge produced an inconsistent output length.');
 return out;
}'''

NEW_MERGE = r'''// Keep the reference DXF byte-for-byte intact except for adding required layer rows
// and appending new entities. The streaming scanner avoids one JS object per DXF pair.
function mergeProjectionDxfPreservingReference(rawBytes, additions){
 const scan=sqScanProjectionDxf(rawBytes),entitySection=scan.entitySection,layerTable=scan.layerTable;
 const versionNo=parseInt(String(scan.version).replace(/^AC/i,''),10)||1009,modern=versionNo>=1012;
 const layerFirstEntity=new Map();
 for(const e of additions||[]){const n=asciiLayerName(e.layer);if(n&&n!=='0'&&!layerFirstEntity.has(n))layerFirstEntity.set(n,e);}
 const missing=[...layerFirstEntity.keys()].filter(n=>!scan.layerNames.has(n.toUpperCase()));
 let layerRows='',entityRecords='',handseedValue=null;
 if(modern){
  const layerBuild=sqBuildModernLayerRows(layerFirstEntity,missing,scan,layerTable);layerRows=layerBuild.text;
  const entityBuild=sqBuildModernEntityRecords(additions,scan,layerBuild.maxHandle);entityRecords=entityBuild.text;handseedValue=entityBuild.nextHandseed;
 }else{
  const eol=scan.eol;
  for(const name of missing){const e=layerFirstEntity.get(name),c=Number.isFinite(Number(e?.color))?Number(e.color):7;layerRows+=`0${eol}LAYER${eol}2${eol}${name}${eol}70${eol}0${eol}62${eol}${c}${eol}6${eol}CONTINUOUS${eol}`;}
  entityRecords=(additions||[]).map(entityToR12).filter(Boolean).join('');
 }
 entityRecords=entityRecords.replace(/\n/g,scan.eol);
 const edits=[];
 if(layerRows){edits.push({start:layerTable.endTab.start,end:layerTable.endTab.start,insertBytes:sqEncodeAscii(layerRows)});if(layerTable.countPair){const count=layerTable.rows.length+missing.length;edits.push({start:layerTable.countPair.valueStart,end:layerTable.countPair.valueEnd,insertBytes:sqEncodeAscii(String(count))});}}
 if(entityRecords)edits.push({start:entitySection.endSec.start,end:entitySection.endSec.start,insertBytes:sqEncodeAscii(entityRecords)});
 if(handseedValue&&entityRecords&&scan.handseedPair)edits.push({start:scan.handseedPair.valueStart,end:scan.handseedPair.valueEnd,insertBytes:sqEncodeAscii(handseedValue)});
 return sqApplyByteEdits(rawBytes,edits);
}'''

REPLACEMENTS = [
    ("function sqBuildModernLayerRows(layerFirstEntity,missing,pairs,layerTable){\n if(!missing.length)return{text:'',maxHandle:sqMaxDxfHandle(pairs)};",
     "function sqBuildModernLayerRows(layerFirstEntity,missing,scan,layerTable){\n if(!missing.length)return{text:'',maxHandle:scan.maxHandle};"),
    (" let maxHandle=sqMaxDxfHandle(pairs),text='';", " let maxHandle=scan.maxHandle,text='';"),
    ("function sqBuildModernEntityRecords(entities,pairs,startHandle){\n let maxHandle=typeof startHandle==='bigint'?startHandle:sqMaxDxfHandle(pairs);\n const owner=sqFindModelSpaceHandle(pairs);",
     "function sqBuildModernEntityRecords(entities,scan,startHandle){\n let maxHandle=typeof startHandle==='bigint'?startHandle:scan.maxHandle;\n const owner=scan.modelSpaceHandle;"),
]


def replace_once(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    if n != 1:
        raise ValueError(f"{label}: expected exactly one match, found {n}")
    return src.replace(old, new, 1)


def extract_function(src: str, marker: str) -> tuple[int, int]:
    start = src.find(marker)
    if start < 0:
        raise ValueError(f"Missing marker: {marker}")
    brace = src.find("{", start)
    if brace < 0:
        raise ValueError(f"No function body for {marker}")
    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    i = brace
    while i < len(src):
        c = src[i]
        nxt = src[i + 1] if i + 1 < len(src) else ""
        if line_comment:
            if c == "\n": line_comment = False
        elif block_comment:
            if c == "*" and nxt == "/": block_comment = False; i += 1
        elif quote:
            if escaped: escaped = False
            elif c == "\\": escaped = True
            elif c == quote: quote = None
        elif c == "/" and nxt == "/": line_comment = True; i += 1
        elif c == "/" and nxt == "*": block_comment = True; i += 1
        elif c in ("'", '"', "`"): quote = c
        elif c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0: return start, i + 1
        i += 1
    raise ValueError(f"Unclosed JavaScript function: {marker}")


def patch_html(src: str) -> str:
    if "function sqScanProjectionDxf(rawBytes){" in src or "Lightweight DXF metadata scanner" in src:
        raise ValueError("V160 projection memory patch already appears to be installed; refusing duplicate insertion.")
    for old, new in REPLACEMENTS:
        src = replace_once(src, old, new, old[:72])
    src = replace_once(src, "function sqApplyByteEdits(source,edits){let out=source.slice();edits.sort((a,b)=>b.start-a.start);for(const e of edits){const insert=e.insertBytes||new Uint8Array(0);out=sqConcatBytes([out.subarray(0,e.start),insert,out.subarray(e.end)]);}return out;}", BYTE_EDITS, "single-allocation byte editor")
    m_start, m_end = extract_function(src, "function mergeProjectionDxfPreservingReference(rawBytes, additions){")
    src = src[:m_start] + SCANNER + "\n" + NEW_MERGE + src[m_end:]
    # Drop source-DWG conversion and binary retention only in the first projection input.
    src = replace_once(src,
        "async function sqParseDwgInWorker(file,timeoutMs=90000){",
        "async function sqParseDwgInWorker(file,timeoutMs=90000,options={}){",
        "worker parser options")
    src = replace_once(src,
        "wasmBase:sqDwgWasmRuntimePath()},[buffer]);",
        "wasmBase:sqDwgWasmRuntimePath(),skipDxfIfNativeModel:!!options.skipDxfIfNativeModel,retainRawDWG:options.retainRawDWG!==false},[buffer]);",
        "worker payload flags")
    src = replace_once(src,
        "model.source='DWG';model.convertedFromDWG=!!rawDXFBytes;model.sourceName=file.name;model.rawDWGBytes=new Uint8Array(result.sourceBuffer);model.rawDXFBytes=rawDXFBytes;",
        "model.source='DWG';model.convertedFromDWG=!!rawDXFBytes;model.sourceName=file.name;model.rawDWGBytes=result.sourceBuffer?new Uint8Array(result.sourceBuffer):null;model.rawDXFBytes=rawDXFBytes;",
        "worker source buffer retention")
    src = replace_once(src,
        "async function parseFile(file){\n const ext=file.name.toLowerCase().split('.').pop();",
        "async function parseFile(file,options={}){\n const ext=file.name.toLowerCase().split('.').pop();",
        "shared parseFile options")
    src = replace_once(src,
        "const workerModel=await sqParseDwgInWorker(file);",
        "const workerModel=await sqParseDwgInWorker(file,90000,options);",
        "worker parse options call")
    src = replace_once(src,
        "     nativeModel.nativeDwgDatabase=db;",
        "     // The parsed entity model is sufficient; do not retain the second full DWG database tree.\n     nativeModel.nativeDwgDatabase=null;",
        "release duplicate native database")
    src = replace_once(src,
        "   // Keep a temporary DWG-to-DXF record stream for project tools that consume DXF bytes.\n   // Native database data remains the preferred source for supported CAD geometry and axes.\n   try{",
        "   // A source board in the projection operation needs parsed CAD entities, not a spare\n   // DWG-to-DXF copy. The reference board still uses the full conversion stream below.\n   if(options.skipDxfIfNativeModel&&nativeModel&&nativeModel.entities?.length){nativeModel.source='DWG';nativeModel.convertedFromDWG=false;nativeModel.sourceName=file.name;nativeModel.rawDWGBytes=null;nativeModel.rawDXFBytes=null;nativeModel.dwgReadMode='main-thread-native';return nativeModel;}\n   try{",
        "main-thread source conversion skip")
    src = replace_once(src,
        "nativeModel.rawDWGBytes=sourceBytes.slice();nativeModel.rawDXFBytes=null;",
        "nativeModel.rawDWGBytes=options.retainRawDWG===false?null:sourceBytes.slice();nativeModel.rawDXFBytes=null;",
        "fallback raw DWG retention")
    src = replace_once(src,
        "model.rawDWGBytes=sourceBytes.slice();model.rawDXFBytes=dxfBytes.slice();",
        "model.rawDWGBytes=options.retainRawDWG===false?null:sourceBytes.slice();model.rawDXFBytes=dxfBytes;",
        "fallback binary retention and DXF copy")
    src = replace_once(src,
        "const sourceModel=await parseFile(src);",
        "const sourceModel=await parseFile(src,{skipDxfIfNativeModel:true,retainRawDWG:false});",
        "projection source lightweight parse")
    src = replace_once(src,
        "const targetModel=await parseFile(cad);",
        "const targetModel=await parseFile(cad,{retainRawDWG:false});",
        "projection target raw DWG release")
    # Patch the worker's own native/fallback conversion and transfer policy.
    src = replace_once(src,
        "' const sourceBytes=new Uint8Array(payload.buffer);let lib=null,nativeModel=null,nativeReadError=null,dxfBytes=null,conversionError=null;',",
        "' const sourceBytes=new Uint8Array(payload.buffer);let lib=null,nativeModel=null,nativeReadError=null,dxfBytes=null,conversionError=null;const skipDxfIfNativeModel=!!payload.skipDxfIfNativeModel;',",
        "worker conditional conversion flag")
    src = replace_once(src,
        "' try{if(typeof lib.dwg_write_dxf!==\"function\")throw new Error(\"محرك LibreDWG لا يحتوي على محول DXF.\");dxfBytes=sqValidateDwgConversion(lib.dwg_write_dxf(sourceBytes.buffer));}catch(e){conversionError=String(e&&e.message||e);}',",
        "' if(!skipDxfIfNativeModel||!nativeModel){try{if(typeof lib.dwg_write_dxf!==\"function\")throw new Error(\"محرك LibreDWG لا يحتوي على محول DXF.\");dxfBytes=sqValidateDwgConversion(lib.dwg_write_dxf(sourceBytes.buffer));}catch(e){conversionError=String(e&&e.message||e);}}',",
        "worker conditional DXF conversion")
    src = replace_once(src,
        "' const result={nativeModel: nativeModel,sourceBuffer:sourceBytes.buffer,dxfBuffer:dxfBytes?dxfBytes.buffer:null,nativeReadError:nativeReadError?String(nativeReadError):\"\",conversionError:conversionError?String(conversionError):\"\"};',",
        "' const returnRawDWG=payload.retainRawDWG!==false&&!(skipDxfIfNativeModel&&nativeModel);const result={nativeModel: nativeModel,sourceBuffer:returnRawDWG?sourceBytes.buffer:null,dxfBuffer:dxfBytes?dxfBytes.buffer:null,nativeReadError:nativeReadError?String(nativeReadError):\"\",conversionError:conversionError?String(conversionError):\"\"};',",
        "worker optional source buffer")
    src = replace_once(src,
        "' const transfers=[sourceBytes.buffer];if(dxfBytes&&dxfBytes.buffer!==sourceBytes.buffer)transfers.push(dxfBytes.buffer);',",
        "' const transfers=[];if(returnRawDWG)transfers.push(sourceBytes.buffer);if(dxfBytes&&dxfBytes.buffer!==sourceBytes.buffer)transfers.push(dxfBytes.buffer);',",
        "worker transfer list")
    validate_html(src, patched=True)
    return src


def validate_html(src: str, patched: bool = False) -> None:
    required = {
        "streaming DXF scanner": "function sqScanProjectionDxf(rawBytes){",
        "one-allocation byte output": "const out=new Uint8Array(total);let sourcePos=0,outPos=0;",
        "scanner-backed projection merge": "const scan=sqScanProjectionDxf(rawBytes),entitySection=scan.entitySection",
        "source DWG parse may skip unused DXF conversion": "skipDxfIfNativeModel:!!options.skipDxfIfNativeModel",
        "worker does not return unused DWG bytes": "const returnRawDWG=payload.retainRawDWG!==false&&!(skipDxfIfNativeModel&&nativeModel)",
        "reference board releases redundant DWG buffer": "const targetModel=await parseFile(cad,{retainRawDWG:false});",
        "source board avoids unnecessary conversion": "const sourceModel=await parseFile(src,{skipDxfIfNativeModel:true,retainRawDWG:false});",
        "all CAD projects keep shared parser": "window.parseFile = parseFile;",
        "raw reference DXF bytes retained": "model.rawDXFBytes=rawDXFBytes;",
    }
    for label, marker in required.items():
        if marker not in src:
            raise ValueError(f"Validation failed: {label} marker missing")
    if "sqDxfPairsWithOffsets(originalText)" in src:
        raise ValueError("Projection merge still materializes an array for every DXF code/value pair")
    if "const insert=e.insertBytes||new Uint8Array(0);out=sqConcatBytes([out.subarray(0,e.start),insert,out.subarray(e.end)])" in src:
        raise ValueError("Repeated full-file byte concatenation is still present")
    if patched and src.count("function sqScanProjectionDxf(rawBytes){") != 1:
        raise ValueError("Streaming scanner must be inserted exactly once")
    if not patched:
        raise ValueError("Source validation called in the wrong mode")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--html", required=True, type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--check-only", action="store_true")
    a = p.parse_args()
    src = a.html.read_text(encoding="utf-8")
    if a.check_only:
        validate_html(src, patched=True)
        print("PASS: streaming DXF scanner, one-allocation output merge, and projection-only DWG buffer release verified")
        return
    out = patch_html(src)
    dest = a.output or a.html
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(out, encoding="utf-8")
    print(f"PASS: applied V160 projection memory patch; wrote {dest} ({len(out)} characters)")

if __name__ == "__main__":
    main()
