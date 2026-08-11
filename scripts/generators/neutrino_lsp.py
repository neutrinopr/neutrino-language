#!/usr/bin/env python3
"""Compiler-backed LSP surface for `.neu` (M5  T2, ).

ONE editor substrate that VS Code and the console share. It **delegates to the
compiler** and MAPS its output — it never re-parses `.neu` or re-derives validation:

- **diagnostics** come from `neutrino_lang.py diagnostics` (which runs
  `neutrino-translate` and maps its coded parser diagnostics + ranges); this server
  only converts them to LSP `Diagnostic`s (1-based → 0-based, severity, stable `code`).
- **semantic tokens** come from `neutrino_lang.py symbols` (which runs
  `neutrino-emit --kind=symbols`); the COMPILER decides each token's identity and role
  (input / compute output / ledger effect / procedure) and its line — this server only
  locates the compiler-named identifier on that line to assign the highlight span.

Scope (T2): diagnostics + semantic tokens only. Hover / go-to-def / completion / rename
are deliberately out of scope. Fail-closed: a missing compiler binary, a compiler
failure, or malformed diagnostics/symbol JSON surface an explicit LSP error, never a
silent empty result.

Entry points:
  neutrino_lsp.py                       # stdio LSP server (VS Code / console client)
  neutrino_lsp.py --diagnostics FILE    # batch: print the mapped LSP diagnostics as JSON
  neutrino_lsp.py --semantic-tokens FILE# batch: print the mapped semantic tokens + legend
The batch modes use the SAME mapping the server does (a scriptable + testable surface).

Binaries: --translate / --emit, else $NEUTRINO_TRANSLATE / $NEUTRINO_EMIT (passed through
to neutrino_lang.py).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LANG = os.path.join(HERE, "neutrino_lang.py")

# LSP semantic-token legend. The roles come from the compiler's symbol `kind`s; these are
# the standard LSP token types they map onto (a theme colors them). `input` -> parameter and
# `compute` -> variable is the input-vs-compute distinction  requires.
TOKEN_TYPES = ["parameter", "variable", "event", "function"]
KIND_TO_TOKEN = {
    "input": "parameter",
    "compute": "variable",
    "debit": "event",
    "credit": "event",
    "procedure": "function",
}
SEVERITY_TO_LSP = {"error": 1, "warning": 2, "warn": 2, "information": 3, "info": 3, "hint": 4}


class CompilerError(Exception):
    """A fail-closed compiler/tooling failure (missing binary, non-JSON, malformed output)."""


def _run_lang(subcmd, path, translate=None, emit=None):
    """Invoke neutrino_lang.py <subcmd> <path>, returning parsed JSON. Fail-closed."""
    cmd = [sys.executable, LANG, subcmd, path]
    env = dict(os.environ)
    if translate:
        env["NEUTRINO_TRANSLATE"] = translate
    if emit:
        env["NEUTRINO_EMIT"] = emit
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    except OSError as e:
        raise CompilerError(f"could not launch neutrino_lang.py: {e}")
    if not p.stdout.strip():
        raise CompilerError(f"neutrino_lang.py {subcmd} produced no output (stderr: {p.stderr.strip()[:200]})")
    try:
        data = json.loads(p.stdout)
    except ValueError as e:
        raise CompilerError(f"neutrino_lang.py {subcmd} emitted non-JSON: {e}")
    if isinstance(data, dict) and data.get("error"):
        raise CompilerError(str(data["error"]))
    return data


def _flatten(symbols):
    for s in symbols:
        yield s
        yield from _flatten(s.get("children", []))


def diagnostics_for(path, translate=None, emit=None):
    """Map the compiler's coded diagnostics to LSP Diagnostics (0-based ranges)."""
    data = _run_lang("diagnostics", path, translate, emit)
    if "diagnostics" not in data:
        raise CompilerError("diagnostics output has no 'diagnostics' array")
    out = []
    for d in data["diagnostics"]:
        rng = d.get("range") or {"start": {"line": 1, "column": 1}, "end": {"line": 1, "column": 1}}
        out.append({
            "range": {
                "start": {"line": rng["start"]["line"] - 1, "character": rng["start"]["column"] - 1},
                "end": {"line": rng["end"]["line"] - 1, "character": rng["end"]["column"] - 1},
            },
            "severity": SEVERITY_TO_LSP.get(d.get("severity", "error"), 1),
            "code": d.get("code", ""),
            "source": "neutrino",
            "message": d.get("message", ""),
        })
    return out


def semantic_tokens_for(path, text=None, translate=None, emit=None):
    """Map the compiler's symbols to LSP semantic tokens (delta-encoded). The role + line
    are the compiler's; the span is the compiler-named identifier located on that line."""
    data = _run_lang("symbols", path, translate, emit)
    # Fail closed on the symbols envelope's own failure signal: neutrino_lang.py reports an emit
    # failure/malformed output as ok:false + a symbols.* error-diagnostic (valid JSON, empty
    # symbols), NOT a top-level "error" — so without this the tokens path would silently return
    # []. (The diagnostics path deliberately does the opposite: it MAPS ok:false's diagnostics to
    # squiggles; token highlighting has no such surface, so a compiler failure must be an error.)
    if data.get("ok") is False:
        msgs = "; ".join(d.get("message", "") for d in data.get("diagnostics", []))
        raise CompilerError(f"symbols failed: {msgs or 'compiler reported ok:false'}")
    if "symbols" not in data:
        raise CompilerError("symbols output has no 'symbols' array")
    if text is None:
        with open(path) as f:
            text = f.read()
    lines = text.splitlines()
    toks = []  # (line0, char0, length, tokenTypeIndex)
    for s in _flatten(data["symbols"]):
        tok_type = KIND_TO_TOKEN.get(s.get("kind"))
        name = s.get("name")
        if tok_type is None or not name:
            continue
        line1 = (s.get("range") or {}).get("start", {}).get("line")
        if not line1 or line1 - 1 >= len(lines):
            continue
        m = re.search(r"\b" + re.escape(name) + r"\b", lines[line1 - 1])
        if not m:
            continue
        toks.append((line1 - 1, m.start(), len(name), TOKEN_TYPES.index(tok_type)))
    toks.sort(key=lambda t: (t[0], t[1]))
    data_arr = []
    prev_line = prev_char = 0
    for line0, char0, length, ttype in toks:
        d_line = line0 - prev_line
        d_char = char0 - (prev_char if d_line == 0 else 0)
        data_arr.extend([d_line, d_char, length, ttype, 0])
        prev_line, prev_char = line0, char0
    return {"legend": {"tokenTypes": TOKEN_TYPES, "tokenModifiers": []}, "data": data_arr}


# ---------------------------------------------------------------------------
# stdio LSP server (JSON-RPC over Content-Length framing)
# ---------------------------------------------------------------------------

class Server:
    def __init__(self, translate=None, emit=None):
        self.translate = translate
        self.emit = emit
        self.docs = {}  # uri -> text
        self.shutdown = False

    # --- framing ---
    def _read(self):
        headers = {}
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            line = line.decode("ascii").strip()
            if line == "":
                break
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        n = int(headers.get("content-length", 0))
        return json.loads(sys.stdin.buffer.read(n).decode("utf-8"))

    def _write(self, msg):
        body = json.dumps(msg).encode("utf-8")
        sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()

    def _respond(self, mid, result=None, error=None):
        m = {"jsonrpc": "2.0", "id": mid}
        if error is not None:
            m["error"] = error
        else:
            m["result"] = result
        self._write(m)

    def _notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _show_error(self, text):
        self._notify("window/showMessage", {"type": 1, "message": text})  # 1 = Error

    # --- helpers ---
    def _tmp(self, uri, text):
        # the compiler reads files; write the in-memory doc to a temp .neu.
        fd, tmp = tempfile.mkstemp(suffix=".neu")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        return tmp

    def _publish(self, uri, text):
        tmp = self._tmp(uri, text)
        try:
            diags = diagnostics_for(tmp, self.translate, self.emit)
            self._notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": diags})
        except CompilerError as e:
            self._show_error(f"neutrino diagnostics failed: {e}")
        finally:
            os.unlink(tmp)

    # --- dispatch ---
    def handle(self, msg):
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}
        if method == "initialize":
            self._respond(mid, {
                "capabilities": {
                    "textDocumentSync": {"openClose": True, "change": 1},  # 1 = Full
                    "semanticTokensProvider": {
                        "legend": {"tokenTypes": TOKEN_TYPES, "tokenModifiers": []},
                        "full": True,
                    },
                },
                "serverInfo": {"name": "neutrino-lsp", "version": "0.1.0"},
            })
        elif method == "initialized":
            pass
        elif method == "textDocument/didOpen":
            td = params["textDocument"]
            self.docs[td["uri"]] = td["text"]
            self._publish(td["uri"], td["text"])
        elif method == "textDocument/didChange":
            uri = params["textDocument"]["uri"]
            changes = params.get("contentChanges", [])
            if changes:
                self.docs[uri] = changes[-1]["text"]  # full sync
                self._publish(uri, self.docs[uri])
        elif method == "textDocument/didClose":
            self.docs.pop(params["textDocument"]["uri"], None)
        elif method == "textDocument/semanticTokens/full":
            uri = params["textDocument"]["uri"]
            text = self.docs.get(uri)
            if text is None:
                self._respond(mid, {"data": []})
                return
            tmp = self._tmp(uri, text)
            try:
                st = semantic_tokens_for(tmp, text=text, translate=self.translate, emit=self.emit)
                self._respond(mid, {"data": st["data"]})
            except CompilerError as e:
                self._respond(mid, error={"code": -32001, "message": f"neutrino semantic tokens failed: {e}"})
            finally:
                os.unlink(tmp)
        elif method == "shutdown":
            self.shutdown = True
            self._respond(mid, None)
        elif method == "exit":
            sys.exit(0 if self.shutdown else 1)
        elif mid is not None:
            self._respond(mid, error={"code": -32601, "message": f"method not found: {method}"})

    def serve(self):
        while True:
            msg = self._read()
            if msg is None:
                break
            try:
                self.handle(msg)
            except Exception as e:  # never crash the server on a bad message; surface it
                if msg.get("id") is not None:
                    self._respond(msg["id"], error={"code": -32603, "message": str(e)})
                else:
                    self._show_error(f"neutrino-lsp internal error: {e}")


def main():
    ap = argparse.ArgumentParser(description="Compiler-backed LSP surface for .neu ()")
    ap.add_argument("--diagnostics", metavar="FILE", help="batch: print mapped LSP diagnostics JSON")
    ap.add_argument("--semantic-tokens", metavar="FILE", help="batch: print mapped semantic tokens JSON")
    ap.add_argument("--translate", help="neutrino-translate binary (else $NEUTRINO_TRANSLATE)")
    ap.add_argument("--emit", help="neutrino-emit binary (else $NEUTRINO_EMIT)")
    args = ap.parse_args()
    try:
        if args.diagnostics:
            json.dump(diagnostics_for(args.diagnostics, args.translate, args.emit), sys.stdout, indent=2)
            sys.stdout.write("\n")
        elif args.semantic_tokens:
            json.dump(semantic_tokens_for(args.semantic_tokens, translate=args.translate, emit=args.emit),
                      sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            Server(args.translate, args.emit).serve()
    except CompilerError as e:
        print(f"neutrino-lsp: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
