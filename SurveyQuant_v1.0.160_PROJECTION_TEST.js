#!/usr/bin/env node
'use strict';
const fs = require('fs');

function assert(condition, message) {
  if (!condition) throw new Error('FAIL: ' + message);
}
function extractFunction(source, marker) {
  const start = source.indexOf(marker);
  assert(start >= 0, 'missing function ' + marker);
  const open = source.indexOf('{', start);
  assert(open >= 0, 'missing function body ' + marker);
  let depth = 0, quote = null, escaped = false, lineComment = false, blockComment = false;
  for (let i = open; i < source.length; i++) {
    const c = source[i], n = source[i + 1] || '';
    if (lineComment) { if (c === '\n') lineComment = false; }
    else if (blockComment) { if (c === '*' && n === '/') { blockComment = false; i++; } }
    else if (quote) {
      if (escaped) escaped = false;
      else if (c === '\\') escaped = true;
      else if (c === quote) quote = null;
    } else if (c === '/' && n === '/') { lineComment = true; i++; }
    else if (c === '/' && n === '*') { blockComment = true; i++; }
    else if (c === "'" || c === '"' || c === '`') quote = c;
    else if (c === '{') depth++;
    else if (c === '}') {
      depth--;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error('Unclosed function ' + marker);
}

const file = process.argv[2];
if (!file || !fs.existsSync(file)) throw new Error('Expected patched index.html path');
const html = fs.readFileSync(file, 'utf8');
const required = [
  'function sqScanProjectionDxf(rawBytes){',
  'const out=new Uint8Array(total);let sourcePos=0,outPos=0;',
  'const sourceModel=await parseFile(src,{skipDxfIfNativeModel:true,retainRawDWG:false});',
  'const targetModel=await parseFile(cad,{retainRawDWG:false});',
  'const returnRawDWG=payload.retainRawDWG!==false&&!(skipDxfIfNativeModel&&nativeModel)',
  'if(!skipDxfIfNativeModel||!nativeModel)',
  'function mergeProjectionDxfPreservingReference(rawBytes, additions){'
];
for (const mark of required) assert(html.includes(mark), 'expected V160 patch marker: ' + mark);
assert(!html.includes('sqDxfPairsWithOffsets(originalText)'), 'projection merge still materializes a pair object for every DXF group');
assert(!html.includes('out=sqConcatBytes([out.subarray(0,e.start),insert,out.subarray(e.end)])'), 'repeated whole-file byte copying remains');

const scannerSrc = extractFunction(html, 'function sqScanProjectionDxf(rawBytes){');
const editSrc = extractFunction(html, 'function sqApplyByteEdits(source,edits){');
const getScanner = new Function(scannerSrc + '; return sqScanProjectionDxf;')();
const applyEdits = new Function(editSrc + '; return sqApplyByteEdits;')();

const legacyFixture = [
  '0','SECTION','2','HEADER','9','$ACADVER','1','AC1009','0','ENDSEC',
  '0','SECTION','2','TABLES','0','TABLE','2','LAYER','70','1',
  '0','LAYER','2','0','70','0','62','7','6','CONTINUOUS','0','ENDTAB','0','ENDSEC',
  '0','SECTION','2','ENTITIES','0','LINE','8','0','10','0','20','0','11','1','21','1','0','ENDSEC','0','EOF',''
].join('\n');
const legacyBytes = new TextEncoder().encode(legacyFixture);
const legacy = getScanner(legacyBytes);
assert(legacy.version === 'AC1009', 'legacy DXF version should be detected');
assert(legacy.entitySection && legacy.layerTable && legacy.layerTable.endTab, 'legacy ENTITIES and LAYER boundaries should be detected');
assert(legacy.layerTable.rows.length === 1 && legacy.layerNames.has('0'), 'existing layer rows/names should be detected');
assert(legacy.layerTable.countPair && legacy.layerTable.countPair.value === '1', 'LAYER table count location should be detected');
assert(legacy.entitySection.endSec.start < legacyBytes.length, 'ENTITIES insertion offset should be within source bytes');

const modernFixture = [
  '0','SECTION','2','HEADER','9','$ACADVER','1','AC1015','9','$HANDSEED','5','FF','0','ENDSEC',
  '0','SECTION','2','TABLES',
  '0','TABLE','2','LAYER','5','1','70','1','0','LAYER','5','2','2','0','70','0','62','7','6','CONTINUOUS','0','ENDTAB',
  '0','TABLE','2','BLOCK_RECORD','5','3','70','1','0','BLOCK_RECORD','5','4','2','*Model_Space','0','ENDTAB','0','ENDSEC',
  '0','SECTION','2','ENTITIES','0','LINE','5','5','8','0','10','0','20','0','11','1','21','1','0','ENDSEC','0','EOF',''
].join('\n');
const modernBytes = new TextEncoder().encode(modernFixture);
const modern = getScanner(modernBytes);
assert(modern.version === 'AC1015', 'modern DXF version should be detected');
assert(modern.modelSpaceHandle === '4', 'Model Space block record handle should be detected');
assert(modern.handseedPair && modern.handseedPair.value === 'FF', '$HANDSEED update location should be detected');
assert(modern.maxHandle === 255n, 'maximum handle should include every hexadecimal handle/value used by DXF, including the handseed');

const original = new Uint8Array([10, 20, 30, 40, 50]);
const merged = applyEdits(original, [
  { start: 1, end: 1, insertBytes: new Uint8Array([9, 9]) },
  { start: 3, end: 4, insertBytes: new Uint8Array([8, 8, 8]) }
]);
assert(Array.from(merged).join(',') === '10,9,9,20,30,8,8,8,50', 'single-allocation byte edits should preserve unchanged source bytes');
let rejectedOverlap = false;
try { applyEdits(original, [
  { start: 1, end: 4, insertBytes: new Uint8Array([1]) },
  { start: 2, end: 3, insertBytes: new Uint8Array([2]) }
]); } catch (_) { rejectedOverlap = true; }
assert(rejectedOverlap, 'overlapping byte edits must be rejected instead of corrupting source data');

console.log('PASS V160 projection tests: lightweight legacy/modern DXF metadata scan, Model Space/handseed/handle discovery, exact untouched-byte preservation, single-allocation edit merge, and overlap guard.');
