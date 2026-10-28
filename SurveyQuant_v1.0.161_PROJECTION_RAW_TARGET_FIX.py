#!/usr/bin/env python3
"""Reduce DWG projection time and memory by reading reference drawings as raw output only."""
from __future__ import annotations
import argparse
from pathlib import Path


def replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected exactly one match, found {count}")
    return src.replace(old, new, 1)


def patch(src: str) -> str:
    if "sqV161RawReferenceOnly" in src:
        raise ValueError("V161 patch is already present; refusing duplicate insertion")

    # Tell the DWG worker to skip building a full native database when only a
    # reference drawing's export bytes are needed.
    src = replace_once(src,
        "' const sourceBytes=new Uint8Array(payload.buffer);let lib=null,nativeModel=null,nativeReadError=null,dxfBytes=null,conversionError=null;const skipDxfIfNativeModel=!!payload.skipDxfIfNativeModel;',",
        "' const sourceBytes=new Uint8Array(payload.buffer);let lib=null,nativeModel=null,nativeReadError=null,dxfBytes=null,conversionError=null;const skipDxfIfNativeModel=!!payload.skipDxfIfNativeModel,conversionOnly=!!payload.conversionOnly;',",
        "worker conversion-only flag")
    src = replace_once(src,
        "' if(typeof lib.dwg_read_data===\"function\"&&typeof lib.convert===\"function\"){let dataPtr=0;try{",
        "' if(!conversionOnly&&typeof lib.dwg_read_data===\"function\"&&typeof lib.convert===\"function\"){let dataPtr=0;try{",
        "worker skip native database")
    src = replace_once(src,
        "}else nativeReadError=\"إصدار محرك LibreDWG لا يدعم قراءة قاعدة DWG الأصلية.\";",
        "}else if(!conversionOnly)nativeReadError=\"إصدار محرك LibreDWG لا يدعم قراءة قاعدة DWG الأصلية.\";",
        "worker conditional native warning")

    # Add operation flags to the worker message and use conversion-only mode for
    # the reference board. Source boards still require native entities.
    src = replace_once(src,
        "skipDxfIfNativeModel:!!options.skipDxfIfNativeModel,retainRawDWG:options.retainRawDWG!==false},[buffer]);",
        "skipDxfIfNativeModel:!!options.skipDxfIfNativeModel,retainRawDWG:options.retainRawDWG!==false,conversionOnly:!!options.conversionOnly,projectionSource:!!options.projectionSource},[buffer]);",
        "worker options payload")

    # A reference DWG can return immediately after validated DWG->DXF conversion.
    src = replace_once(src,
        "if(!result)return null;\n const rawDXFBytes=result.dxfBuffer?new Uint8Array(result.dxfBuffer):null;let model=null;",
        "if(!result)return null;\n const rawDXFBytes=result.dxfBuffer?new Uint8Array(result.dxfBuffer):null;\n if(options.rawOnly&&rawDXFBytes)return {source:'DWG',convertedFromDWG:true,sourceName:file.name,entities:[],layers:new Map(),points:[],segments:[],polylines:[],rawDWGBytes:null,rawDXFBytes,dwgReadMode:'worker-conversion-only'};\n let model=null;",
        "worker raw-only early return")

    # For the main-thread fallback, avoid keeping the entire native database object.
    src = replace_once(src,
        "if(typeof lib.dwg_read_data==='function'&&typeof lib.convert==='function'){",
        "if(!options.conversionOnly&&typeof lib.dwg_read_data==='function'&&typeof lib.convert==='function'){",
        "main-thread conversion-only skip")
    src = replace_once(src,
        "} else nativeReadError=new Error('إصدار محرك DWG لا يوفّر قراءة قاعدة DWG الأصلية.');",
        "} else if(!options.conversionOnly)nativeReadError=new Error('إصدار محرك DWG لا يوفّر قراءة قاعدة DWG الأصلية.');",
        "main-thread conditional native warning")
    src = replace_once(src,
        "nativeModel=parseDWGDatabase(db);\n     // The parsed entity model is sufficient; do not retain the second full DWG database tree.\n     nativeModel.nativeDwgDatabase=null;",
        "nativeModel=parseDWGDatabase(db,{projectionSource:!!options.projectionSource});\n     // Do not keep the raw database tree through the parsed model on the fallback path.\n     nativeModel.db=null;nativeModel.nativeDwgDatabase=null;",
        "main-thread database release")
    src = replace_once(src,
        "   }catch(e){conversionError=e;}\n\n   if(!dxfBytes){",
        "   }catch(e){conversionError=e;}\n\n   if(options.rawOnly&&dxfBytes){return {source:'DWG',convertedFromDWG:true,sourceName:file.name,entities:[],layers:new Map(),points:[],segments:[],polylines:[],rawDWGBytes:null,rawDXFBytes:dxfBytes,dwgReadMode:'main-thread-conversion-only'};}\n   if(!dxfBytes){",
        "main-thread raw-only early return")

    # DXF reference inputs should also bypass full entity parsing and raw-byte copying.
    src = replace_once(src,
        " if(ext==='dxf'){let lastErr=null;for(const enc of ['utf-8','windows-1252']){",
        " if(ext==='dxf'){if(options.rawOnly)return {source:'DXF',sourceName:file.name,entities:[],layers:new Map(),points:[],segments:[],polylines:[],rawDWGBytes:null,rawDXFBytes:bytes};let lastErr=null;for(const enc of ['utf-8','windows-1252']){",
        "DXF raw-only fast path")

    # Lightweight source-side parsing: keep all source CAD entities and point rows,
    # but do not allocate extra segment/polyline/elevation-text arrays unused by overlay.
    src = replace_once(src,
        "function parseDWGDatabase(db){\n const m={source:'DWG',entities:[],layers:new Map(),points:[],segments:[],polylines:[],elevTexts:[],db};",
        "function parseDWGDatabase(db,options={}){\n const projectionSource=!!options.projectionSource;\n const m={source:'DWG',entities:[],layers:new Map(),points:[],segments:[],polylines:[],elevTexts:[],db};",
        "projection-aware DWG database parser")
    src = replace_once(src,
        "if(a&&b){m.segments.push({a,b,layer});addCadEntity(m,'LINE',layer,{a,b});}",
        "if(a&&b){if(!projectionSource)m.segments.push({a,b,layer});addCadEntity(m,'LINE',layer,{a,b});}",
        "projection line-array reduction")
    src = replace_once(src,
        "m.polylines.push({vertices:vs,closed,layer});addCadEntity(m,type,layer,{vertices:vs,closed});for(let i=0;i<vs.length-1;i++)m.segments.push({a:vs[i],b:vs[i+1],layer});if(closed)m.segments.push({a:vs.at(-1),b:vs[0],layer});",
        "if(!projectionSource){m.polylines.push({vertices:vs,closed,layer});for(let i=0;i<vs.length-1;i++)m.segments.push({a:vs[i],b:vs[i+1],layer});if(closed)m.segments.push({a:vs.at(-1),b:vs[0],layer});}addCadEntity(m,type,layer,{vertices:vs,closed});",
        "projection polyline-array reduction")
    old_elev = "if(z!==null)m.elevTexts.push({x:q.x,y:q.y,z,text:String(raw),layer,type:type,height:Number(e.textHeight||e.height||0),rotation:Number(e.rotation||0)});"
    if src.count(old_elev) != 2:
        raise ValueError(f"projection elevation-text reduction: expected exactly 2 matches, found {src.count(old_elev)}")
    src = src.replace(old_elev, "if(!projectionSource&&z!==null)m.elevTexts.push({x:q.x,y:q.y,z,text:String(raw),layer,type:type,height:Number(e.textHeight||e.height||0),rotation:Number(e.rotation||0)});")
    src = replace_once(src,
        "const m=parseDWGDatabase(db);if(!m||!Array.isArray(m.entities)||!m.entities.length)",
        "const m=parseDWGDatabase(db,{projectionSource:!!payload.projectionSource});if(!m||!Array.isArray(m.entities)||!m.entities.length)",
        "worker projection parser mode")

    # Request the light model for source files, and a raw-preserving stream for the reference.
    src = replace_once(src,
        "const sourceModel=await parseFile(src,{skipDxfIfNativeModel:true,retainRawDWG:false});",
        "const sourceModel=await parseFile(src,{skipDxfIfNativeModel:true,retainRawDWG:false,projectionSource:true});",
        "source projection parsing mode")
    src = replace_once(src,
        "const targetModel=await parseFile(cad,{retainRawDWG:false});",
        "const targetModel=await parseFile(cad,{retainRawDWG:false,rawOnly:true,conversionOnly:true});",
        "reference raw-only parsing mode")
    src = replace_once(src,
        "const additions=[],entities=[...(targetModel.entities||[])];let addedPoints=0,addedCad=0;",
        "const additions=[],entities=[];let addedPoints=0,addedCad=0;",
        "avoid target entity clone")
    src = replace_once(src,
        "  if(!entities.length)throw new Error('لم يتم العثور على عناصر قابلة للإسقاط.');",
        "  if(!targetModel.rawDXFBytes&&!entities.length)throw new Error('لم يتم العثور على عناصر قابلة للإسقاط في اللوحة المرجعية.');\n  if(!additions.length)throw new Error('لم يتم العثور على عناصر قابلة للإسقاط في الملف الأول.');",
        "projection source and target validation")
    src = replace_once(src,
        "عناصر اللوحة المرجعية: <b>${targetModel.entities?.length||0}</b> | عناصر الملف الأول:",
        "اللوحة المرجعية: <b>تم الحفاظ على بياناتها الأصلية دون إعادة تحليل كل كياناتها</b> | عناصر الملف الأول:",
        "projection summary text")

    # Keep an explicit marker so checks and future reruns can prove this patch is active.
    src = src.replace("/* V1.0.103: native DXF-to-DXF overlay.", "/* sqV161RawReferenceOnly: reference boards use a raw-preserving, conversion-only path. */\n/* V1.0.103: native DXF-to-DXF overlay.", 1)
    validate(src)
    return src


def validate(src: str) -> None:
    required = {
        "V161 patch marker": "sqV161RawReferenceOnly",
        "worker conversion-only mode": "conversionOnly=!!payload.conversionOnly",
        "worker raw-only early return": "dwgReadMode:'worker-conversion-only'",
        "main-thread raw-only early return": "dwgReadMode:'main-thread-conversion-only'",
        "DXF raw-only fast path": "if(options.rawOnly)return {source:'DXF'",
        "source lightweight parse": "projectionSource:!!options.projectionSource",
        "target raw-only parse": "rawOnly:true,conversionOnly:true",
        "reference byte-preserving merge remains active": "mergeProjectionDxfPreservingReference(targetModel.rawDXFBytes,additions)",
        "no reference entity full clone": "const additions=[],entities=[];let addedPoints=0,addedCad=0;",
        "fallback DB tree released": "nativeModel.db=null;nativeModel.nativeDwgDatabase=null;",
    }
    for label, marker in required.items():
        if marker not in src:
            raise ValueError(f"Validation failed: {label} marker is missing")
    if "const additions=[],entities=[...(targetModel.entities||[])];" in src:
        raise ValueError("Reference entity array is still cloned")
    if "function parseDWGDatabase(db){" in src:
        raise ValueError("Projection-aware parseDWGDatabase signature is missing")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--html", required=True, type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--check-only", action="store_true")
    args = p.parse_args()
    src = args.html.read_text(encoding="utf-8")
    if args.check_only:
        validate(src)
        print("PASS V161: raw-only reference, conversion-only DWG, reduced source-side geometry buffers, and preserved-byte merge are present")
        return
    out = patch(src)
    dest = args.output or args.html
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(out, encoding="utf-8")
    print(f"PASS V161: patched {dest} ({len(out)} characters)")

if __name__ == "__main__":
    main()
