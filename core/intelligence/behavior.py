"""Bounded pure-expression contrast facts. Never eval/import/execute repository code.

Unsupported syntax abstains. Sampled differences do not establish a defect or
input validity; the reviewer must still justify the expected contract.
"""
from __future__ import annotations

import ast
import hashlib
import json
from itertools import product

from core.input.snapshot import InputError


class Unsupported(ValueError):
    pass


def _value(node, values, depth=0):
    if depth>12:
        raise Unsupported("expression depth")
    visit=lambda item: _value(item,values,depth+1)
    if isinstance(node,ast.Constant) and type(node.value) in {str,int,bool,type(None)}:
        if isinstance(node.value,str) and len(node.value)>256 or isinstance(node.value,int) and abs(node.value)>1_000_000:
            raise Unsupported("literal limit")
        return node.value
    if isinstance(node,ast.Name) and node.id in values:
        return values[node.id]
    if isinstance(node,(ast.List,ast.Tuple)) and len(node.elts)<=16:
        elements = [visit(item) for item in node.elts]
        return tuple(elements) if isinstance(node, ast.Tuple) else elements
    if isinstance(node,ast.Call) and not node.keywords:
        if isinstance(node.func,ast.Name) and node.func.id=="len" and len(node.args)==1:
            value=visit(node.args[0])
            if type(value) in {str,bytes,list,tuple}: return len(value)
            raise TypeError("unsupported len input")
        if (isinstance(node.func,ast.Attribute) and node.func.attr=="encode" and len(node.args)<=1
                and (not node.args or isinstance(node.args[0],ast.Constant) and node.args[0].value in {"utf-8","utf8","UTF-8"})):
            value=visit(node.func.value)
            if type(value) is str: return value.encode("utf-8")
        raise Unsupported("call outside pure whitelist")
    if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub)):
        left,right=visit(node.left),visit(node.right)
        if type(left) is not int or type(right) is not int: raise Unsupported("integer operation required")
        return left+right if isinstance(node.op,ast.Add) else left-right
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.Not,ast.USub)):
        value=visit(node.operand)
        if isinstance(node.op,ast.Not): return not value
        if type(value) is not int: raise Unsupported("unary operand")
        return -value
    if isinstance(node,ast.Compare) and len(node.ops)==len(node.comparators)==1:
        left,right=visit(node.left),visit(node.comparators[0]);op=node.ops[0]
        if isinstance(op,ast.LtE): return left<=right
        if isinstance(op,ast.Lt): return left<right
        if isinstance(op,ast.GtE): return left>=right
        if isinstance(op,ast.Gt): return left>right
        if isinstance(op,ast.Eq): return left==right
        if isinstance(op,ast.NotEq): return left!=right
        if isinstance(op,(ast.Is,ast.IsNot)) and (right is None or type(right) is bool):
            return left is right if isinstance(op,ast.Is) else left is not right
    if isinstance(node,ast.Subscript) and isinstance(node.slice,ast.Slice):
        value=visit(node.value)
        if type(value) not in {list,tuple,str,bytes}: raise TypeError("sequence required")
        bounds=[visit(part) if part is not None else None for part in (node.slice.lower,node.slice.upper,node.slice.step)]
        if any(part is not None and type(part) not in {int, bool} for part in bounds): raise TypeError("integer bounds required")
        return value[slice(*bounds)]
    raise Unsupported("unsupported expression")


def _functions(text):
    if len(text)>64000:
        raise Unsupported("file limit")
    tree=ast.parse(text)
    if sum(1 for _ in ast.walk(tree))>5000:
        raise Unsupported("syntax node limit")
    if any(not isinstance(n,ast.FunctionDef) and not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)) for n in tree.body):
        raise Unsupported("module bindings or effects require broader semantics")
    functions={}
    for node in tree.body:
        if not isinstance(node,ast.FunctionDef): continue
        if node.name=="len" or node.name in functions:
            raise Unsupported("shadowed builtin or duplicate definition")
        body=node.body[1:] if ast.get_docstring(node) is not None else node.body
        arguments=node.args
        if (node.decorator_list or arguments.defaults or arguments.kw_defaults or arguments.vararg or arguments.kwarg
                or arguments.posonlyargs or arguments.kwonlyargs or not 1<=len(arguments.args)<=3
                or len(body)!=1 or not isinstance(body[0],ast.Return)):
            continue
        if any(annotation is not None and not (isinstance(annotation,ast.Name) and annotation.id in {"int","str","list","bytes","bool"})
               for annotation in [node.returns,*[arg.annotation for arg in arguments.args]]):
            continue
        if any(arg.arg=="len" for arg in arguments.args): continue
        expression=body[0].value
        # Syntax whitelist applies to every branch, including branches not sampled.
        allowed=(ast.Return,ast.Constant,ast.Name,ast.Load,ast.Call,ast.Attribute,ast.BinOp,ast.Add,ast.Sub,
                 ast.UnaryOp,ast.Not,ast.USub,ast.Compare,ast.LtE,ast.Lt,ast.GtE,ast.Gt,ast.Eq,ast.NotEq,
                 ast.Is,ast.IsNot,ast.Subscript,ast.Slice,ast.List,ast.Tuple)
        if expression is None or any(not isinstance(n,allowed) for n in ast.walk(expression)):
            continue
        functions[node.name]=(node,expression,tuple(arg.arg for arg in arguments.args),body[0])
    return functions


def _domains(parameters, expressions):
    strings,numbers,sequences=set(),set(),set()
    for expression in expressions:
        for node in ast.walk(expression):
            if isinstance(node,ast.Attribute) and node.attr=="encode" and isinstance(node.value,ast.Name): strings.add(node.value.id)
            if isinstance(node,ast.Subscript) and isinstance(node.slice,ast.Slice):
                if isinstance(node.value,ast.Name): sequences.add(node.value.id)
                numbers.update(n.id for n in ast.walk(node.slice) if isinstance(n,ast.Name))
            if isinstance(node, ast.Compare) and isinstance(node.ops[0], (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                numbers.update(n.id for n in (node.left, *node.comparators) if isinstance(n, ast.Name))
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
                numbers.update(n.id for n in (node.left, node.right) if isinstance(n, ast.Name))
    return [["","a","é","🙂"] if p in strings else [[],["a"],["a","b","c","d"]] if p in sequences
            else [0,1,2,3] if p in numbers else [None,False,0,1,"","a","é",[],["a","b"]] for p in parameters]


def compare_pure(before: str, after: str, *, max_samples=100, max_facts=4) -> list[dict]:
    try:
        old,new=_functions(before),_functions(after)
    except (SyntaxError,Unsupported,RecursionError):
        return []
    facts=[]
    for name in sorted(old.keys() & new.keys())[:8]:
        left,right=old[name],new[name]
        if left[2]!=right[2] or ast.dump(left[1])==ast.dump(right[1]): continue
        for sample,values in enumerate(product(*_domains(left[2],(left[1],right[1])))):
            if sample>=max_samples or len(facts)>=max_facts: break
            bindings=dict(zip(left[2],values))
            try:
                outputs=[]
                for expression in (left[1],right[1]):
                    try:
                        value = repr(_value(expression, bindings))
                        if len(value) > 200:
                            raise Unsupported("result exceeds the evidence budget")
                        outputs.append({"kind":"return_value","value":value})
                    except (TypeError,ValueError,IndexError,ZeroDivisionError) as error:
                        if isinstance(error,Unsupported): raise
                        outputs.append({"kind":"raises","value":type(error).__name__})
                if outputs[0]!=outputs[1]:
                    facts.append({"symbol":name,"inputs":bindings,"base":outputs[0],"head":outputs[1],
                                  "base_line":left[3].lineno,"head_line":right[3].lineno,
                                  "base_operation":"\n".join(before.splitlines()[left[3].lineno-1:left[3].end_lineno]),
                                  "head_operation":"\n".join(after.splitlines()[right[3].lineno-1:right[3].end_lineno])})
            except Unsupported:
                continue
    return facts


def build_behavior_context(provider,snapshot,paths) -> list[dict]:
    results=[]
    for path in sorted(set(paths))[:12]:
        if not path.endswith(".py"): continue
        try:
            base=provider.read(snapshot,path,"base");head=provider.read(snapshot,path,"head")
            facts=compare_pure(base.content.decode("utf-8"),head.content.decode("utf-8"),max_facts=2)
            if facts:
                for fact in facts:
                    fact["id"]="BX-"+hashlib.sha256(json.dumps(fact,sort_keys=True).encode()).hexdigest()[:16]
                results.append({"path":path,"snapshot_id":snapshot.id,"source":"bounded_python_ast",
                                "base_sha256":base.content_sha256,"head_sha256":head.content_sha256,"examples":facts,
                                "limitations":["Sampled pure-expression differences, not executed tests, input-validity proof or defect verdict."]})
        except (InputError,UnicodeError,RecursionError):
            continue
    return results[:4]
