'use strict';
const fs = require('node:fs');
const htmlPath = process.argv[2];
if (!htmlPath) throw new Error('Usage: node SurveyQuant_v1.0.161_PROJECTION_RAW_TARGET_TEST.js <index.html>');
const html = fs.readFileSync(htmlPath, 'utf8');
function assert(condition, message) { if (!condition) throw new Error('FAIL V161: ' + message); }
const required = [
  ['V161 raw-reference marker', 'sqV161RawReferenceOnly'],
  ['reference DWG conversion-only flag is sent', 'conversionOnly:!!options.conversionOnly'],
  ['reference DWG worker skips native database parsing', '!conversionOnly&&typeof lib.dwg_read_data==="function"'],
  ['worker returns validated DXF bytes without parsing all entities', "dwgReadMode:'worker-conversion-only'"],
  ['main-thread fallback returns raw-only DXF', "dwgReadMode:'main-thread-conversion-only'"],
  ['DXF reference skips full model parse', "if(options.rawOnly)return {source:'DXF'"],
  ['projection source uses reduced side arrays', 'projectionSource:!!options.projectionSource'],
  ['projection target uses raw-only mode', 'rawOnly:true,conversionOnly:true'],
  ['reference DXF still goes through byte-preserving merge', 'mergeProjectionDxfPreservingReference(targetModel.rawDXFBytes,additions)'],
  ['target entities are not redundantly cloned', 'const additions=[],entities=[];let addedPoints=0,addedCad=0;'],
  ['main-thread native database reference is released', 'nativeModel.db=null;nativeModel.nativeDwgDatabase=null;'],
  ['source still contributes actual CAD entities', 'for(const e of sourceModel.entities){additions.push(e);addedCad++;}'],
  ['X/Easting and Y/Northing reporting remains', 'X = Easting (E) وY = Northing (N)'],
];
for (const [label, needle] of required) assert(html.includes(needle), label);
assert(!html.includes('const additions=[],entities=[...(targetModel.entities||[])];'), 'full reference entity array clone remains');
assert(!html.includes("const targetModel=await parseFile(cad,{retainRawDWG:false});"), 'old full-reference parse call remains');
assert(html.includes('function sqScanProjectionDxf(rawBytes){'), 'V160 streaming scanner has disappeared');
assert(html.includes('const out=new Uint8Array(total);let sourcePos=0,outPos=0;'), 'V160 single-allocation byte output has disappeared');
console.log('PASS V161 projection regression checks: raw-only reference, conversion-only DWG, lightweight source overlays, original reference-byte merge, and no duplicate target model allocation.');
