#!/usr/bin/env python3
"""Strict, repeatable repair for the V156 SurveyQuant CAD runtime.

Fixes two confirmed copy/paste defects and one avoidable full-size DWG buffer copy in the packaged index.html:
1. surfacePointsFromModel referenced parser-scope variables that do not exist there.
2. sqBuildModernEntityRecords contained a parser branch instead of emitting XLINE/RAY DXF records.

The patch intentionally avoids rebuilding drawings or modifying original DXF records.
"""
from __future__ import annotations
import argparse
from pathlib import Path


def replace_in_function(src: str, start_marker: str, end_marker: str,
                        old: str, new: str, label: str) -> str:
    start = src.find(start_marker)
    if start < 0:
        raise ValueError(f"{label}: function start marker not found")
    end = src.find(end_marker, start + len(start_marker))
    if end < 0:
        raise ValueError(f"{label}: function end marker not found")
    body = src[start:end]
    count = body.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected exactly one defective fragment in target function, found {count}")
    body = body.replace(old, new, 1)
    return src[:start] + body + src[end:]


PARSE_COPY_BAD = "  const fileContent=sourceBytes.buffer.slice(sourceBytes.byteOffset,sourceBytes.byteOffset+sourceBytes.byteLength);\n"
PARSE_COPY_GOOD = "  const fileContent=sourceBytes.buffer; // sourceBytes owns this complete ArrayBuffer; avoid a redundant DWG-sized copy.\n"

SURFACE_BAD = """  else if((type==='XLINE'||type==='RAY')&&(e.basePoint||e.startPoint||e.position)&&(e.directionVector||e.unitVector||e.direction)){const base=p3((e.basePoint||e.startPoint||e.position).x,(e.basePoint||e.startPoint||e.position).y,(e.basePoint||e.startPoint||e.position).z);const dir=e.directionVector||e.unitVector||e.direction;addCadEntity(m,type,layer,{basePoint:base,directionVector:p3(dir.x,dir.y,dir.z)});}
"""
SURFACE_GOOD = """  else if(e.type==='XLINE'||e.type==='RAY'){/* Infinite construction geometry has no finite terrain Z samples. */}
"""

WRITER_BAD = """  else if((type==='XLINE'||type==='RAY')&&(e.basePoint||e.startPoint||e.position)&&(e.directionVector||e.unitVector||e.direction)){const base=p3((e.basePoint||e.startPoint||e.position).x,(e.basePoint||e.startPoint||e.position).y,(e.basePoint||e.startPoint||e.position).z);const dir=e.directionVector||e.unitVector||e.direction;addCadEntity(m,type,layer,{basePoint:base,directionVector:p3(dir.x,dir.y,dir.z)});}
"""
WRITER_GOOD = """  else if((e.type==='XLINE'||e.type==='RAY')&&(e.basePoint||e.startPoint||e.position)&&(e.directionVector||e.unitVector||e.direction)){const base=e.basePoint||e.startPoint||e.position,dir=e.directionVector||e.unitVector||e.direction; if([base.x,base.y,dir.x,dir.y].every(v=>Number.isFinite(Number(v))))emit(e.type,e.type==='RAY'?'AcDbRay':'AcDbXline',L,color,xyz(base,10)+xyz(dir,11));}
"""


def patch_html(src: str) -> str:
    out = replace_in_function(
        src, "async function parseFile(file){", "function layerUI(model,targetId){",
        PARSE_COPY_BAD, PARSE_COPY_GOOD, "DWG input memory copy"
    )
    out = replace_in_function(
        out, "function surfacePointsFromModel(m){", "function triArea2(",
        SURFACE_BAD, SURFACE_GOOD, "surface point extraction"
    )
    out = replace_in_function(
        out, "function sqBuildModernEntityRecords(entities,pairs,startHandle){", "function sqApplyByteEdits(",
        WRITER_BAD, WRITER_GOOD, "modern DXF XLINE/RAY writer"
    )
    validate_html(out, patched=True)
    if out == src:
        raise ValueError("No changes applied: the source appears already patched")
    return out


def validate_html(src: str, patched: bool = False) -> None:
    parse_start = src.find("async function parseFile(file){")
    parse_end = src.find("function layerUI(model,targetId){", parse_start + 1)
    surf_start = src.find("function surfacePointsFromModel(m){")
    surf_end = src.find("function triArea2(", surf_start + 1)
    wr_start = src.find("function sqBuildModernEntityRecords(entities,pairs,startHandle){")
    wr_end = src.find("function sqApplyByteEdits(", wr_start + 1)
    if min(parse_start, parse_end, surf_start, surf_end, wr_start, wr_end) < 0:
        raise ValueError("Required CAD functions could not be located")
    parse_body = src[parse_start:parse_end]
    surf = src[surf_start:surf_end]
    writer = src[wr_start:wr_end]
    if patched:
        if PARSE_COPY_BAD.strip() in parse_body:
            raise ValueError("The redundant full-size DWG input copy remains")
        if "const fileContent=sourceBytes.buffer;" not in parse_body:
            raise ValueError("The zero-copy DWG input buffer path is missing")
        if SURFACE_BAD.strip() in surf:
            raise ValueError("The surface-point runtime bug remains")
        if WRITER_BAD.strip() in writer:
            raise ValueError("The modern DXF XLINE/RAY writer bug remains")
        if "Infinite construction geometry has no finite terrain Z samples." not in surf:
            raise ValueError("Surface-point guard is missing")
        if "'AcDbRay':'AcDbXline'" not in writer or "xyz(dir,11)" not in writer:
            raise ValueError("Modern XLINE/RAY record generation is missing")
    else:
        if PARSE_COPY_BAD.strip() not in parse_body:
            raise ValueError("Expected DWG input copy defect signature is not present")
        if SURFACE_BAD.strip() not in surf or WRITER_BAD.strip() not in writer:
            raise ValueError("Expected V156 defect signatures are not present; refusing an unverified patch")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--html", required=True, type=Path, help="Path to the packaged app index.html")
    p.add_argument("--output", type=Path, help="Write patched HTML here instead of changing input")
    p.add_argument("--check-only", action="store_true", help="Verify that the three fixes are already present")
    args = p.parse_args()
    src = args.html.read_text(encoding="utf-8")
    if args.check_only:
        validate_html(src, patched=True)
        print("PASS: DWG buffer reuse, surface extraction, and modern DXF XLINE/RAY writer fixes verified")
        return
    result = patch_html(src)
    target = args.output or args.html
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result, encoding="utf-8")
    print(f"PASS: applied three targeted CAD runtime fixes; wrote {target} ({len(result)} characters)")

if __name__ == "__main__":
    main()
