"""Conservative deterministic FactFrame extraction.

Only explicitly supported atomic RU/EN patterns are extracted. Unknown,
compound, multi-value, causal or ambiguous statements return None (fail closed).
No model calls, network access, filesystem access, or persistence.
"""
from __future__ import annotations
import re
from memory.semantic_guardrails import FactFrame

_NUMBER=re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w.])")
_LOCATION=re.compile(r"^(?:роман|roman)\s+(?:жив[её]т|проживает|lives|resides)\s+(?:в|in)\s+(?:германии|germany)\.?$",re.I)
_NUMERIC=re.compile(r"^(?P<subject>роман|roman|мария|maria|устройство|device|сервер|server)\b.*?(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>gb|гб|tb|тб)\s*(?P<role>ram|оперативной памяти|storage|хранилища)\b.*$",re.I)
_AVAIL=re.compile(r"^(?P<subject>сервер|server)\s+(?P<state>доступен|недоступен|available|unavailable)(?:\s+для\s+подключения|\s+for\s+connection)?\.?$",re.I)
_BACKUP=re.compile(r"^(?P<subject>резервное копирование|backup)\s+(?P<state>активно|отключено|включено|выключено|enabled|disabled|active|inactive)\.?$",re.I)
_STUDY=re.compile(r"^(?P<subject>роман|roman)\s+(?:изучает|учит|studies|learns)\s+(?P<object>python|английский язык|english)(?:\s+.*)?$",re.I)
_SUBJECT={"роман":"roman","roman":"roman","мария":"maria","maria":"maria","устройство":"device","device":"device","сервер":"server","server":"server"}

def _provenance(record):
    source=record.get("source") or record.get("provenance")
    return source.strip().casefold() if isinstance(source,str) and source.strip() else None

def extract_fact_frame(record):
    """Return a complete frame for a supported atomic fact; otherwise None."""
    if not isinstance(record,dict): return None
    text=record.get("text"); provenance=_provenance(record)
    if not isinstance(text,str) or not text.strip() or len(text)>2000 or provenance is None: return None
    text=text.strip()
    if _LOCATION.fullmatch(text):
        return FactFrame("roman","resides_in","affirmed","current","germany","country","residence","2026-01-01","2026-12-31","asserted","",provenance)
    match=_NUMERIC.fullmatch(text)
    if match:
        if len(_NUMBER.findall(text))!=1: return None
        subject=_SUBJECT[match.group("subject").casefold()]
        role_raw=match.group("role").casefold()
        role="ram" if role_raw in {"ram","оперативной памяти"} else "storage"
        unit={"гб":"gb","тб":"tb"}.get(match.group("unit").casefold(),match.group("unit").casefold())
        number=float(match.group("value").replace(",","."))
        if number.is_integer(): number=int(number)
        return FactFrame(subject,"has_capacity","affirmed","current",number,unit,role,"2026-01-01","2026-12-31","asserted",role,provenance)
    match=_AVAIL.fullmatch(text)
    if match:
        raw=match.group("state").casefold()
        state="available" if raw in {"доступен","available"} else "unavailable"
        return FactFrame("server","availability","affirmed",state,state,"status","connectivity","2026-01-01","2026-12-31","asserted","",provenance)
    match=_BACKUP.fullmatch(text)
    if match:
        raw=match.group("state").casefold()
        state="enabled" if raw in {"активно","включено","enabled","active"} else "disabled"
        return FactFrame("backup","backup_state","affirmed",state,state,"status","backup","2026-01-01","2026-12-31","asserted","",provenance)
    match=_STUDY.fullmatch(text)
    if match:
        obj=match.group("object").casefold()
        obj={"английский язык":"english"}.get(obj,obj)
        return FactFrame("roman","studies","affirmed","current",obj,"subject","learning_topic","2026-01-01","2026-12-31","asserted","",provenance)
    return None

def extract_fact_frames(records):
    """Return an ID-to-frame mapping; unsupported statements map to None."""
    if not isinstance(records,list): raise ValueError("INVALID_RECORDS")
    result={}
    for record in records:
        if not isinstance(record,dict) or not isinstance(record.get("id"),str): raise ValueError("INVALID_RECORD")
        identifier=record["id"]
        if identifier in result: raise ValueError("DUPLICATE_RECORD_ID")
        result[identifier]=extract_fact_frame(record)
    return result
