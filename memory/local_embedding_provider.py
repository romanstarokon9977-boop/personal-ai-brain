"""Loopback-only OpenAI-compatible llama.cpp embeddings client."""
from __future__ import annotations
import json, math, urllib.error, urllib.request
from urllib.parse import urlparse

class LocalEmbeddingError(RuntimeError):
    """Local embedding endpoint unavailable or returned invalid data."""

class LocalEmbeddingProvider:
    def __init__(self, base_url="http://127.0.0.1:8090", model="multilingual-e5-small", timeout=30.0, dimension=384):
        parsed=urlparse(base_url)
        if parsed.scheme!="http" or parsed.hostname not in {"127.0.0.1","localhost","::1"}:
            raise ValueError("LOOPBACK_URL_REQUIRED")
        if not isinstance(model,str) or not model.strip(): raise ValueError("INVALID_MODEL")
        if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or timeout<=0: raise ValueError("INVALID_TIMEOUT")
        if isinstance(dimension,bool) or not isinstance(dimension,int) or dimension<1: raise ValueError("INVALID_DIMENSION")
        self.endpoint=base_url.rstrip("/")+"/v1/embeddings"
        self.model=model; self.timeout=float(timeout); self.dimension=dimension

    def __call__(self,texts):
        if not isinstance(texts,list) or not texts or any(not isinstance(x,str) or not x.strip() or len(x)>8000 for x in texts):
            raise LocalEmbeddingError("INVALID_INPUT_TEXTS")
        payload=json.dumps({"model":self.model,"input":["query: "+x for x in texts]},ensure_ascii=False).encode("utf-8")
        request=urllib.request.Request(self.endpoint,data=payload,headers={"Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(request,timeout=self.timeout) as response:
                if response.status!=200: raise LocalEmbeddingError("LOCAL_EMBEDDING_HTTP_ERROR")
                body=json.loads(response.read().decode("utf-8"))
        except LocalEmbeddingError: raise
        except (urllib.error.URLError,TimeoutError,OSError,ValueError) as exc:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_UNAVAILABLE_OR_INVALID") from exc
        data=body.get("data") if isinstance(body,dict) else None
        if not isinstance(data,list) or len(data)!=len(texts): raise LocalEmbeddingError("EMBEDDING_COUNT_MISMATCH")
        ordered=[None]*len(texts)
        for item in data:
            if not isinstance(item,dict): raise LocalEmbeddingError("INVALID_EMBEDDING_ITEM")
            index=item.get("index"); vector=item.get("embedding")
            if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(texts): raise LocalEmbeddingError("INVALID_EMBEDDING_INDEX")
            if ordered[index] is not None: raise LocalEmbeddingError("DUPLICATE_EMBEDDING_INDEX")
            if not isinstance(vector,list) or len(vector)!=self.dimension: raise LocalEmbeddingError("EMBEDDING_DIMENSION_MISMATCH")
            values=[]
            for value in vector:
                if isinstance(value,bool) or not isinstance(value,(int,float)): raise LocalEmbeddingError("NON_NUMERIC_EMBEDDING_VALUE")
                number=float(value)
                if not math.isfinite(number): raise LocalEmbeddingError("NON_FINITE_EMBEDDING_VALUE")
                values.append(number)
            if not any(values): raise LocalEmbeddingError("ZERO_NORM_EMBEDDING")
            ordered[index]=values
        if any(x is None for x in ordered): raise LocalEmbeddingError("MISSING_EMBEDDING_INDEX")
        return ordered
