#!/usr/bin/env python3
"""Make SurveyQuant's shared DWG parser worker-backed and avoid redundant DXF parsing."""
from __future__ import annotations
import argparse
from pathlib import Path

WORKER_INSERT = r'''let sqDwgWorker = null;
let sqDwgWorkerBlobUrl = null;
let sqDwgWorkerInitPromise = null;
let sqDwgWorkerRequestId = 0;
const sqDwgWorkerPending = new Map();

function sqBuildDwgWorkerSource(){
 const helpers=[p3,addCadEntity,textNumber,entityTextValue,sqPolylineIsClosed,vec,sqDwgRows,sqDwgType,sqDwgLayerName,sqDwgBlockRecords,sqDwgModelSpaceEntities,parseDWGDatabase,sqValidateDwgConversion].map(fn=>fn.toString()).join('\n');
 const workerBody = [
 'let sqEnginePromise=null,sqEngineFatal=false,sqQueue=Promise.resolve();',
 'async function sqLoadEngine(payload){',
 ' if(!sqEnginePromise){try{importScripts(payload.wasmScriptUrl,payload.engineScriptUrl);const mod=self.SurveyQuantLibreDwg;const LibreDwg=mod&&(mod.LibreDwg||mod.default&&mod.default.LibreDwg);if(!LibreDwg||typeof LibreDwg.create!=="function")throw new Error("واجهة محرك LibreDWG غير موجودة داخل العامل.");sqEnginePromise=LibreDwg.create(payload.wasmBase);}catch(e){sqEngineFatal=true;throw e;}}',
 ' try{return await sqEnginePromise;}catch(e){sqEngineFatal=true;throw e;}',
 '}',
 'async function sqProcess(payload){',
 ' const sourceBytes=new Uint8Array(payload.buffer);let lib=null,nativeModel=null,nativeReadError=null,dxfBytes=null,conversionError=null;',
 ' const signature=new TextDecoder("latin1").decode(sourceBytes.subarray(0,6));',
 ' if(sourceBytes.length<16)throw new Error("ملف DWG قصير أو تالف.");',
 ' if(!/^(?:AC1004|AC1006|AC1009|AC1012|AC1014|AC1015|AC1018|AC1021|AC1024|AC1027|AC1032)$/.test(signature))throw new Error("ترويسة DWG غير معروفة أو إصدار غير مدعوم: "+signature);',
 ' lib=await sqLoadEngine(payload);',
 ' if(typeof lib.dwg_read_data==="function"&&typeof lib.convert==="function"){let dataPtr=0;try{const mod=self.SurveyQuantLibreDwg;const fileTypes=mod.Dwg_File_Type||(mod.default&&mod.default.Dwg_File_Type)||{};dataPtr=lib.dwg_read_data(sourceBytes.buffer,fileTypes.DWG??0);if(!dataPtr)throw new Error("لم يُرجع القارئ الأصلي قاعدة DWG صالحة.");const db=lib.convert(dataPtr);if(!db||!db.tables)throw new Error("قاعدة DWG لا تحتوي على جداول CAD.");const m=parseDWGDatabase(db);if(!m||!Array.isArray(m.entities)||!m.entities.length)throw new Error("قراءة DWG الأصلية لم تُرجع عناصر CAD قابلة للاستخدام.");nativeModel={source:"DWG",entities:m.entities,layers:Array.from(m.layers.entries()),points:m.points,segments:m.segments,polylines:m.polylines,elevTexts:m.elevTexts};}catch(e){nativeReadError=String(e&&e.message||e);nativeModel=null;}finally{if(dataPtr&&typeof lib.dwg_free==="function"){try{lib.dwg_free(dataPtr);}catch(_){}}}}else nativeReadError="إصدار محرك LibreDWG لا يدعم قراءة قاعدة DWG الأصلية.";',
 ' try{if(typeof lib.dwg_write_dxf!=="function")throw new Error("محرك LibreDWG لا يحتوي على محول DXF.");dxfBytes=sqValidateDwgConversion(lib.dwg_write_dxf(sourceBytes.buffer));}catch(e){conversionError=String(e&&e.message||e);}',
 ' if(!nativeModel&&!dxfBytes)throw new Error("تعذرت قراءة DWG وتحويله. القارئ: "+(nativeReadError||"غير متاح")+"؛ المحول: "+(conversionError||"غير متاح"));',
 ' const result={nativeModel: nativeModel,sourceBuffer:sourceBytes.buffer,dxfBuffer:dxfBytes?dxfBytes.buffer:null,nativeReadError:nativeReadError?String(nativeReadError):"",conversionError:conversionError?String(conversionError):""};',
 ' const transfers=[sourceBytes.buffer];if(dxfBytes&&dxfBytes.buffer!==sourceBytes.buffer)transfers.push(dxfBytes.buffer);',
 ' self.postMessage({requestId:payload.requestId,ok:true,result:result},transfers);',
 '}',
 'self.onmessage=function(event){const payload=event.data||{};sqQueue=sqQueue.then(async function(){try{await sqProcess(payload);}catch(e){self.postMessage({requestId:payload.requestId,ok:false,fatal:sqEngineFatal,error:String(e&&e.message||e||"DWG worker failed")});}});};'
 ].join('\n');
 return helpers+'\n'+workerBody;
}
function sqTerminateDwgWorker(worker, timeoutId, timeoutError){
 if(worker&&sqDwgWorker===worker)sqDwgWorker=null;
 try{if(worker)worker.terminate();}catch(_){}
 if(sqDwgWorkerBlobUrl){try{URL.revokeObjectURL(sqDwgWorkerBlobUrl);}catch(_){}sqDwgWorkerBlobUrl=null;}
 sqDwgWorkerPending.forEach((pending,id)=>{clearTimeout(pending.timer);sqDwgWorkerPending.delete(id);if(id===timeoutId&&timeoutError)pending.reject(timeoutError);else pending.resolve(null);});
}
function sqEnsureDwgWorker(){
 if(sqDwgWorker)return Promise.resolve(sqDwgWorker);
 if(sqDwgWorkerInitPromise)return sqDwgWorkerInitPromise;
 sqDwgWorkerInitPromise=Promise.resolve().then(()=>{
  if(typeof Worker!=='function'||typeof Blob!=='function'||!URL.createObjectURL)return null;
  let blobUrl=null,worker=null;
  try{blobUrl=URL.createObjectURL(new Blob([sqBuildDwgWorkerSource()],{type:'text/javascript'}));worker=new Worker(blobUrl);}catch(_){if(blobUrl)URL.revokeObjectURL(blobUrl);return null;}
  sqDwgWorkerBlobUrl=blobUrl;sqDwgWorker=worker;
  worker.onmessage=function(event){const msg=event.data||{},pending=sqDwgWorkerPending.get(msg.requestId);if(!pending)return;if(msg.fatal){sqTerminateDwgWorker(worker);return;}clearTimeout(pending.timer);sqDwgWorkerPending.delete(msg.requestId);if(msg.ok)pending.resolve(msg.result);else pending.reject(new Error(String(msg.error||'تعذرت قراءة ملف DWG داخل عامل القراءة.')));};
  worker.onerror=function(){sqTerminateDwgWorker(worker);};
  worker.onmessageerror=function(){sqTerminateDwgWorker(worker);};
  return worker;
 }).finally(()=>{sqDwgWorkerInitPromise=null;});
 return sqDwgWorkerInitPromise;
}
async function sqParseDwgInWorker(file,timeoutMs=90000){
 const worker=await sqEnsureDwgWorker();if(!worker)return null;
 const buffer=await file.arrayBuffer();
 const requestId=++sqDwgWorkerRequestId;
 const result=await new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>sqTerminateDwgWorker(worker,requestId,new Error('تجاوزت قراءة '+file.name+' مهلة '+Math.round(timeoutMs/1000)+' ثانية. أُوقف عامل DWG حتى لا يظل التطبيق عالقًا.')),timeoutMs);
  sqDwgWorkerPending.set(requestId,{resolve:resolve,reject:reject,timer:timer});
  try{worker.postMessage({requestId:requestId,buffer:buffer,wasmScriptUrl:new URL(SQ_WRITER_WASM_URL,document.baseURI).href,engineScriptUrl:new URL(SQ_WRITER_ENGINE_URL,document.baseURI).href,wasmBase:sqDwgWasmRuntimePath()},[buffer]);}
  catch(_){clearTimeout(timer);sqDwgWorkerPending.delete(requestId);resolve(null);}
 });
 if(!result)return null;
 const rawDXFBytes=result.dxfBuffer?new Uint8Array(result.dxfBuffer):null;let model=null;
 if(result.nativeModel)model={...result.nativeModel,layers:new Map(result.nativeModel.layers||[])};
 // Most DWGs already yield native entities. Parse the converted DXF only if the native reader returned none.
 if(!model&&rawDXFBytes){let lastErr=null;for(const encoding of ['utf-8','windows-1252']){try{const candidate=parseDXF(new TextDecoder(encoding,{fatal:false}).decode(rawDXFBytes));if(candidate&&(candidate.entities?.length||candidate.points?.length||candidate.segments?.length||candidate.polylines?.length)){model=candidate;break;}lastErr=new Error('تم تحويل DWG إلى DXF لكن لم يعثر قارئ اللوحة على كيانات قابلة للقراءة.');}catch(e){lastErr=e;}}if(!model)throw lastErr||new Error('تعذر تحليل DXF المحول من DWG.');}
 if(!model)throw new Error('لم ينتج محرك DWG عناصر CAD قابلة للاستخدام.');
 model.source='DWG';model.convertedFromDWG=!!rawDXFBytes;model.sourceName=file.name;model.rawDWGBytes=new Uint8Array(result.sourceBuffer);model.rawDXFBytes=rawDXFBytes;
 if(result.nativeReadError)model.nativeDwgReadWarning=String(result.nativeReadError);if(result.conversionError)model.dwgConversionError=String(result.conversionError);
 model.dwgReadMode='worker';return model;
}
'''

OLD_WORKER_INSERT = "async function parseFile(file){\n const ext=file.name.toLowerCase().split('.').pop();\n if(ext==='dwg'){\n  const sourceBytes=new Uint8Array(await file.arrayBuffer());"
NEW_WORKER_INSERT = "async function parseFile(file){\n const ext=file.name.toLowerCase().split('.').pop();\n if(ext==='dwg'){\n  const workerModel=await sqParseDwgInWorker(file);\n  if(workerModel)return workerModel;\n  const sourceBytes=new Uint8Array(await file.arrayBuffer());"

OLD_DXF_FALLBACK = """   let dxfModel=null,lastErr=null;
   for(const encoding of ['utf-8','windows-1252']){
    try{const candidate=parseDXF(new TextDecoder(encoding,{fatal:false}).decode(dxfBytes));if(candidate&&(candidate.entities?.length||candidate.points?.length||candidate.segments?.length||candidate.polylines?.length)){dxfModel=candidate;break;}lastErr=new Error('تم تحويل DWG إلى DXF لكن لم يعثر قارئ اللوحة على كيانات قابلة للقراءة.');}
    catch(e){lastErr=e;}
   }
   // Prefer native database geometry for axis labels and precise source coordinates;
   // if that database does not expose usable model-space geometry, use DXF parsing.
   const model=nativeModel&&((nativeModel.entities?.length||0)>0)?nativeModel:dxfModel;
"""
NEW_DXF_FALLBACK = """   // Avoid parsing the converted DXF again when the native reader already returned CAD entities.
   let model=nativeModel&&((nativeModel.entities?.length||0)>0)?nativeModel:null;
   let lastErr=null;
   if(!model){
    for(const encoding of ['utf-8','windows-1252']){
     try{const candidate=parseDXF(new TextDecoder(encoding,{fatal:false}).decode(dxfBytes));if(candidate&&(candidate.entities?.length||candidate.points?.length||candidate.segments?.length||candidate.polylines?.length)){model=candidate;break;}lastErr=new Error('تم تحويل DWG إلى DXF لكن لم يعثر قارئ اللوحة على كيانات قابلة للقراءة.');}
     catch(e){lastErr=e;}
    }
   }
"""


def replace_once(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    if n != 1:
        raise ValueError(f"{label}: expected exactly one match, found {n}")
    return src.replace(old, new, 1)


def patch_html(src: str) -> str:
    if "function sqBuildDwgWorkerSource()" in src or "sqParseDwgInWorker(file" in src:
        raise ValueError("The fast DWG reader already appears to be installed; refusing duplicate insertion.")
    out = replace_once(src, OLD_WORKER_INSERT, NEW_WORKER_INSERT, "shared DWG parser worker hook")
    out = replace_once(out, "async function parseFile(file){", WORKER_INSERT + "\nasync function parseFile(file){", "worker reader insertion")
    out = replace_once(out, OLD_DXF_FALLBACK, NEW_DXF_FALLBACK, "skip redundant DXF parse")
    validate_html(out, patched=True)
    return out


def validate_html(src: str, patched: bool = False) -> None:
    checks = {
        "shared parser exposes worker-backed DWG path": "const workerModel=await sqParseDwgInWorker(file);",
        "worker source is generated from known CAD helpers": "function sqBuildDwgWorkerSource(){",
        "persistent worker caches engine": "let sqEnginePromise=null,sqEngineFatal=false,sqQueue=Promise.resolve();",
        "worker can be terminated on timeout": "sqTerminateDwgWorker(worker,requestId,new Error(",
        "native model preserves layers": "layers:Array.from(m.layers.entries())",
        "native entities avoid redundant DXF parsing": "Avoid parsing the converted DXF again when the native reader already returned CAD entities.",
        "source DWG bytes retained": "model.rawDWGBytes=new Uint8Array(result.sourceBuffer)",
        "converted DXF bytes retained": "model.rawDXFBytes=rawDXFBytes",
        "all CAD projects still use shared parseFile": "window.parseFile = parseFile;",
    }
    for label, marker in checks.items():
        if marker not in src:
            raise ValueError(f"Validation failed: {label} missing")
    if "let dxfModel=null,lastErr=null;\n   for(const encoding of ['utf-8','windows-1252'])" in src:
        raise ValueError("Redundant converted-DXF parsing still runs before native-model selection")
    if patched and src.count("function sqBuildDwgWorkerSource(){") != 1:
        raise ValueError("The shared DWG worker must be inserted exactly once")
    if not patched:
        raise ValueError("Source validation called in the wrong mode")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--html", required=True, type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--check-only", action="store_true")
    args = p.parse_args()
    source = args.html.read_text(encoding="utf-8")
    if args.check_only:
        validate_html(source, patched=True)
        print("PASS: shared worker-backed DWG reader, reusable WASM worker, layer-preserving model, and redundant DXF parse elimination verified")
        return
    result = patch_html(source)
    target = args.output or args.html
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result, encoding="utf-8")
    print(f"PASS: patched shared DWG reader for all CAD-capable projects; wrote {target} ({len(result)} characters)")

if __name__ == "__main__":
    main()
