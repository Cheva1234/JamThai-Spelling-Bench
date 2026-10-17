"""Small OpenAI-compatible HTTP adapter for explicitly configured vLLM servers."""
import json
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials/payload to another destination.


def validate_endpoint(base_url, allow_remote=False):
    p = urlsplit(base_url)
    if p.scheme not in ("http","https") or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("Use an http(s) base URL without credentials, query, or fragment")
    local = p.hostname in ("localhost","127.0.0.1","::1")
    if not local and not allow_remote:
        raise ValueError("Remote endpoint blocked: data rights/provider retention must be cleared first")
    if not local and p.scheme != "https":
        raise ValueError("Remote endpoints require HTTPS")
    return local


def redact(value, secret):
    if isinstance(value,str):
        return value.replace(secret,"[REDACTED]") if secret else value
    if isinstance(value,list):
        return [redact(x,secret) for x in value]
    if isinstance(value,dict):
        return {redact(k,secret):redact(v,secret) for k,v in value.items() if k.lower() not in ("authorization","api_key","api-key","access_token")}
    return value


class Client:
    def __init__(self, base_url, key="", timeout=60, requests_per_second=0):
        self.base = base_url.rstrip("/")
        self.url = self.base+"/chat/completions"
        self.key,self.timeout = key,timeout
        self.interval = 1/requests_per_second if requests_per_second else 0
        self.lock = threading.Lock()
        self.next_time = 0.0
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def models(self):
        """GET /models: the set of served model ids."""
        headers = {"Authorization":"Bearer "+self.key} if self.key else {}
        req = urllib.request.Request(self.base+"/models",headers=headers)
        with self.opener.open(req,timeout=self.timeout) as r:
            obj = json.loads(r.read(1024*1024))
        return {m.get("id") for m in obj.get("data",[]) if isinstance(m,dict)}

    def call(self, payload):
        with self.lock:
            now=time.monotonic()
            delay=max(0,self.next_time-now)
            self.next_time=max(now,self.next_time)+self.interval
        if delay:
            time.sleep(delay)
        headers={"Content-Type":"application/json"}
        if self.key:
            headers["Authorization"]="Bearer "+self.key
        req=urllib.request.Request(self.url,data=json.dumps(payload,ensure_ascii=False).encode(),headers=headers)
        start=time.monotonic()
        result={"raw":None,"failure":None,"retryable":False}
        try:
            with self.opener.open(req,timeout=self.timeout) as r:
                data=r.read(8*1024*1024+1)
                if len(data)>8*1024*1024:
                    raise ValueError("Response exceeds 8 MiB cap")
                obj=json.loads(data)
                result["response"]=redact(obj,self.key)
                choices=obj.get("choices")
                if not isinstance(choices,list) or not choices:
                    raise ValueError("No completion choices")
                choice=choices[0]
                message=choice.get("message",{})
                reasoning=message.get("reasoning_content") or message.get("reasoning")
                result.update(raw=redact(message.get("content"),self.key),
                              server_reasoning=reasoning if isinstance(reasoning,str) else None,
                              finish_reason=choice.get("finish_reason"),usage=obj.get("usage"),
                              resolved_model=obj.get("model"),refusal=bool(message.get("refusal")))
                if result["raw"] is not None and not isinstance(result["raw"],str):
                    raise ValueError("Completion content is not text")
                if result["raw"] is None or result["raw"] == "":
                    result.update(raw=None, failure="refusal" if result["refusal"] else "missing_content")
        except urllib.error.HTTPError as e:
            result.update(failure=f"http_{e.code}",retryable=e.code==429 or 500<=e.code<=599)
            # Bodies can contain secrets or server diagnostics; do not persist them.
        except (TimeoutError, OSError) as e:
            result.update(failure="timeout" if isinstance(e,TimeoutError) or "timed out" in str(e).lower() else "transport_error",retryable=True)
        except (ValueError,TypeError,KeyError,AttributeError):
            result.update(raw=None,failure="invalid_api_response")
        result["latency_seconds"]=time.monotonic()-start
        return redact(result,self.key)
