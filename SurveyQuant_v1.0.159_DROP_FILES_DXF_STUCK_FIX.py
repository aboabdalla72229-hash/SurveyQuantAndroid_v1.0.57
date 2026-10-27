#!/usr/bin/env python3
"""Patch the SurveyQuant v1.0.158 drop-files flow so DXF export stays visible and DWG reads cannot leave a permanent spinner."""
from __future__ import annotations
import argparse
from pathlib import Path

OLD_RESULTS = '<div class="results-box" id="dropFilesResults"><div id="dropFilesSummary" class="info-list"></div><button class="btn-orange" onclick="downloadDroppedDXF()">📐 استخراج DXF المدمج</button></div>'
NEW_RESULTS = '<div class="results-box" id="dropFilesResults" style="display:block"><div id="dropFilesSummary" class="info-list"></div><button id="downloadDroppedDXFButton" class="btn-orange" type="button" onclick="downloadDroppedDXF()" disabled style="opacity:.55;cursor:not-allowed">📐 استخراج لوحة DXF الناتجة (بعد نجاح الإسقاط)</button></div>'

NEW_PROJECTION_FUNCTION = r'''async function sqParseProjectionFileWithTimeout(file,label,timeoutMs=90000){
 let timer=null;
 const readPromise=Promise.resolve().then(()=>parseFile(file));
 const timeoutPromise=new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('تجاوزت قراءة '+label+' مهلة 90 ثانية. أوقف البرنامج الانتظار حتى لا يظل عالقًا؛ أعد المحاولة، وإذا تكرر الخطأ مع DWG فالمحرك لم يُنهِ القراءة.')),timeoutMs);});
 try{return await Promise.race([readPromise,timeoutPromise]);}finally{if(timer!==null)clearTimeout(timer);}
}
async function dropFilesMerge(){
 const progress=document.getElementById('dropFilesProgress');
 const results=document.getElementById('dropFilesResults');
 const summary=document.getElementById('dropFilesSummary');
 const exportButton=document.getElementById('downloadDroppedDXFButton');
 const setProgress=(message)=>{if(progress){progress.style.display='block';progress.textContent=message;}};
 const setExportReady=(ready)=>{if(exportButton){exportButton.disabled=!ready;exportButton.style.opacity=ready?'1':'.55';exportButton.style.cursor=ready?'pointer':'not-allowed';exportButton.textContent=ready?'📐 استخراج لوحة DXF الناتجة':'📐 استخراج لوحة DXF الناتجة (بعد نجاح الإسقاط)';}};
 const src=document.getElementById('dropSurveyFiles').files[0],cad=document.getElementById('dropCadFile').files[0];
 droppedDXF='';setExportReady(false);if(results)results.style.display='block';if(summary)summary.textContent='';
 if(!src||!cad){setProgress('⚠️ اختر الملف الأول واللوحة المرجعية قبل بدء الإسقاط.');return alert('اختر الملف المراد إسقاطه في الخانة الأولى واللوحة المرجعية في الخانة الثانية.');}
 try{
  setProgress('⏳ جاري قراءة الملف الأول: '+src.name);
  await new Promise(r=>setTimeout(r,30));
  const sourceModel=await sqParseProjectionFileWithTimeout(src,'الملف الأول');
  if(!sourceModel||!Array.isArray(sourceModel.entities))throw new Error('لم يُرجع الملف الأول عناصر قابلة للإسقاط.');
  setProgress('✅ تمت قراءة الملف الأول. ⏳ جاري قراءة اللوحة المرجعية: '+cad.name);
  await new Promise(r=>setTimeout(r,30));
  const targetModel=await sqParseProjectionFileWithTimeout(cad,'اللوحة المرجعية');
  if(!targetModel||!['DXF','DWG'].includes(String(targetModel.source).toUpperCase()))throw new Error('الخانة الثانية يجب أن تكون لوحة DXF أو DWG.');
  if(!Array.isArray(targetModel.entities)||!targetModel.entities.length)throw new Error('تم فتح الملف المرجعي لكن لم تُقرأ منه عناصر CAD قابلة للاستخدام.');
  const additions=[],entities=[...(targetModel.entities||[])];let addedPoints=0,addedCad=0;
  if(Array.isArray(sourceModel.points)&&sourceModel.points.length){const ps=getPointStyleSettings();for(const p of sourceModel.points){addPointDetailEntities(additions,{e:Number(p.e),n:Number(p.n),z:Number(p.z||0),id:p.id||('P'+(addedPoints+1))},ps);addedPoints++;}}
  if(sourceModel.entities?.length){if(!sourceModel.points?.length||sourceModel.source==='DXF'||sourceModel.source==='DWG'){for(const e of sourceModel.entities){additions.push(e);addedCad++;}}}
  entities.push(...additions);
  if(!entities.length)throw new Error('لم يتم العثور على عناصر قابلة للإسقاط.');
  setProgress('⏳ تمت قراءة اللوحة المرجعية. جاري إعداد ملف DXF مع الحفاظ على العناصر الأصلية...');
  await new Promise(r=>setTimeout(r,20));
  if(targetModel.rawDXFBytes instanceof Uint8Array){
    droppedDXF=mergeProjectionDxfPreservingReference(targetModel.rawDXFBytes,additions);
    const checkText=new TextDecoder('windows-1252').decode(droppedDXF);
    const validationIssue=inspectPreservedReferenceDXF(checkText);if(validationIssue)throw new Error(validationIssue+' تم إيقاف التصدير لحماية تفاصيل اللوحة المرجعية.');
  }else{
    droppedDXF=buildR12FromEntities(entities,{preserveEntityColors:true});
    if(!validateGeneratedDXF(droppedDXF))throw new Error('تعذر إنشاء DXF صالح من اللوحة المرجعية.');
  }
  if(!(droppedDXF instanceof Uint8Array)&&!(typeof droppedDXF==='string'&&droppedDXF.length))throw new Error('لم ينتج عن الإسقاط ملف DXF قابل للتنزيل.');
  if(summary)summary.innerHTML='تم إسقاط <b>'+escapeHtml(src.name)+'</b> على <b>'+escapeHtml(cad.name)+'</b>.<br>عناصر اللوحة المرجعية: <b>'+(targetModel.entities?.length||0)+'</b> | عناصر الملف الأول: <b>'+addedCad+'</b> | نقاط مضافة بالتفاصيل: <b>'+addedPoints+'</b>.<br><span class="muted">'+(String(targetModel.source).toUpperCase()==='DXF'?'تم الحفاظ على بايتات وعناصر وخصائص اللوحة المرجعية الأصلية كما هي؛ أُضيفت العناصر الجديدة فقط دون إعادة رسم عناصر المرجع.':'تم استخدام DXF الناتج من تحويل DWG كأساس للإضافة؛ قد توجد قيود تحويل على بعض الكيانات الخاصة. لا يمكن أن تكون نتيجة DXF نسخة ثنائية مطابقة لملف DWG.')+'<br>الإحداثيات ثابتة: X = Easting (E) وY = Northing (N)، دون تبديل.</span>';
  if(results)results.style.display='block';setExportReady(true);setProgress('✅ اكتمل الإسقاط وتم تجهيز ملف DXF. اضغط زر «استخراج لوحة DXF الناتجة» للحفظ.');
 }catch(e){
  droppedDXF='';setExportReady(false);const message=String(e?.message||e||'خطأ غير معروف');
  if(summary)summary.innerHTML='<b>تعذر تجهيز لوحة DXF.</b><br>'+escapeHtml(message);
  if(results)results.style.display='block';setProgress('❌ فشل الإسقاط: '+message);
  console.error('dropFilesMerge',e);alert('تعذر إسقاط الملف على اللوحة: '+message);
 }
}
'''

OLD_RESET = "card.querySelectorAll('.results-box,.cad-panel:not(.project-output-settings),.info-list[id$=\"Summary\"],.info-list[id$=\"Status\"]').forEach(e=>{if(e.id!=='quantResults')e.style.display='none';});"
NEW_RESET = "card.querySelectorAll('.results-box,.cad-panel:not(.project-output-settings),.info-list[id$=\"Summary\"],.info-list[id$=\"Status\"]').forEach(e=>{if(e.id!=='quantResults'&&e.id!=='dropFilesResults')e.style.display='none';});if(card.id==='dropFilesCard'){const db=document.getElementById('downloadDroppedDXFButton'),rs=document.getElementById('dropFilesResults'),sm=document.getElementById('dropFilesSummary'),pr=document.getElementById('dropFilesProgress');if(rs)rs.style.display='block';if(sm)sm.textContent='';if(pr){pr.style.display='none';pr.textContent='⏳ جاري قراءة اللوحتين ومعالجة الإسقاط...';}if(db){db.disabled=true;db.style.opacity='.55';db.style.cursor='not-allowed';db.textContent='📐 استخراج لوحة DXF الناتجة (بعد نجاح الإسقاط)';}}"


def replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise ValueError(f'{label}: expected exactly one match, found {count}')
    return src.replace(old, new, 1)


def patch_html(src: str) -> str:
    for marker in ('async function dropFilesMerge(){', '\nfunction downloadDroppedDXF(){', 'function resetProjectInputs(card){', OLD_RESULTS):
        if marker not in src: raise ValueError(f'Missing required V158 marker: {marker[:70]}')
    if 'downloadDroppedDXFButton' in src or 'sqParseProjectionFileWithTimeout' in src:
        raise ValueError('The drop-files repair already appears to be installed; refusing a duplicate patch.')
    out = replace_once(src, OLD_RESULTS, NEW_RESULTS, 'always-visible DXF export button')
    start = out.index('async function dropFilesMerge(){')
    end = out.index('\nfunction downloadDroppedDXF(){', start)
    out = out[:start] + NEW_PROJECTION_FUNCTION.rstrip() + out[end:]
    out = replace_once(out, OLD_RESET, NEW_RESET, 'drop-files project reset')
    validate_html(out, patched=True)
    return out


def validate_html(src: str, patched: bool = False) -> None:
    if patched:
        checks = {
            'always visible results box': 'id="dropFilesResults" style="display:block"',
            'disabled until successful export': 'id="downloadDroppedDXFButton" class="btn-orange" type="button"',
            'bounded DWG/DXF parsing': 'async function sqParseProjectionFileWithTimeout(file,label,timeoutMs=90000)',
            'timeout used for first input': "sqParseProjectionFileWithTimeout(src,'الملف الأول')",
            'timeout used for reference board': "sqParseProjectionFileWithTimeout(cad,'اللوحة المرجعية')",
            'visible failure status': "setProgress('❌ فشل الإسقاط: '+message)",
            'export enabled after DXF validation': 'setExportReady(true);setProgress(\'✅ اكتمل الإسقاط',
            'project reset preserves export control': "e.id!=='quantResults'&&e.id!=='dropFilesResults'",
        }
        for label, marker in checks.items():
            if marker not in src: raise ValueError(f'Validation failed: {label} missing')
        if 'finally{if(progress)progress.style.display=\'none\';}' in src:
            raise ValueError('Old behavior that hides a permanently stuck progress state remains')
    else:
        if OLD_RESULTS not in src: raise ValueError('Expected V158 hidden result button is not present')
        if 'async function dropFilesMerge(){' not in src: raise ValueError('Projection function missing')
        if 'function resetProjectInputs(card){' not in src: raise ValueError('Project reset function missing')


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--html', required=True, type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--check-only', action='store_true')
    a = p.parse_args()
    src = a.html.read_text(encoding='utf-8')
    if a.check_only:
        validate_html(src, patched=True)
        print('PASS: always-visible DXF export control, finite reader timeout, visible error/success state, and reset behavior validated')
        return
    result = patch_html(src)
    target = a.output or a.html
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result, encoding='utf-8')
    print(f'PASS: repaired drop-files DXF export and stuck-reading feedback; wrote {target} ({len(result)} characters)')

if __name__ == '__main__':
    main()
