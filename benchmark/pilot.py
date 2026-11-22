"""Family-aware real-PR input registration, immutable prediction sealing and labels.

Candidate strata are sampling metadata, never adjudicated truth. Headline use is
blocked until exposure and labels are audited separately from prediction inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from benchmark.frozen import seal_predictions
from benchmark.pr_truth import PRTruth, merge_safety
from core.domain.review_contracts import DomainRecord
from core.review.artifacts import write_json_atomic
from core.review.jobs import digest


class PilotCase(DomainRecord):
    case_id: str = Field(pattern=r"^[a-z0-9-]{1,100}$")
    pr_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+/pull/[0-9]+$")
    original_url: str
    base_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    head_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    comparison_base_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    patch_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    family_id: str
    stratum: Literal["source_issue_candidate", "unreviewed_control"]
    previously_exposed: bool = False


def related_families(candidates: list[PilotCase]) -> list[list[PilotCase]]:
    """Connect URL aliases and equivalent patches, including transitive links."""
    parents: dict[str, str] = {}

    def root(key: str) -> str:
        parents.setdefault(key, key)
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    def url_key(url: str) -> str:
        return "url:" + url.rstrip("/").casefold()

    for case in candidates:
        leader = root(url_key(case.pr_url))
        for key in (url_key(case.original_url), "patch:" + case.family_id):
            parents[root(key)] = leader
    groups: dict[str, list[PilotCase]] = {}
    for case in candidates:
        groups.setdefault(root(url_key(case.pr_url)), []).append(case)
    return list(groups.values())


def register(candidates: list[PilotCase], destination: Path, *, seed="pilot-v1") -> dict:
    selected = []
    for family in related_families(candidates):
        representative = min(family, key=lambda case: digest([seed, case.pr_url]))
        selected.append(representative.model_copy(update={
            "previously_exposed": any(case.previously_exposed for case in family)
        }))
    selected.sort(key=lambda case: digest([seed, case.pr_url]))
    issue = [c for c in selected if c.stratum=="source_issue_candidate"]
    control = [c for c in selected if c.stratum=="unreviewed_control"]
    if len(issue)<40 or len(control)<20:
        raise ValueError(f"pilot needs 40 unique source-issue candidates and 20 unreviewed controls; have {len(issue)}/{len(control)}")
    issue,control=issue[:40],control[:20]
    # Exposed cases go to development first; never silently place one in held-out.
    issue.sort(key=lambda c: not c.previously_exposed)
    control.sort(key=lambda c: not c.previously_exposed)
    if sum(c.previously_exposed for c in issue)>14 or sum(c.previously_exposed for c in control)>6:
        raise ValueError("exposure exceeds development allocation; revise the candidate pool explicitly")
    splits={"development":issue[:14]+control[:6],"validation":issue[14:20]+control[6:10],"test":issue[20:]+control[10:]}
    destination.mkdir(parents=True,exist_ok=False)
    inputs=[]
    for split,cases in splits.items():
        for case in cases:
            if split!="development" and case.previously_exposed:
                raise ValueError("exposed family cannot enter held-out/validation inputs")
            inputs.append(case.model_dump(mode="json")|{"split":split})
        write_json_atomic(destination/(split+".json"),{"name":"real-pilot-v1-"+split,"split":split,
            "used_for_system_design":split=="development","eligible_for_headline_metrics":False,
            "prs":[c.pr_url for c in cases],"exposure_audit_required":True})
    write_json_atomic(destination/"inputs.json", inputs)
    manifest={"name":"real-pilot-v1","candidate_count":60,"family_count":60,
        "split_counts":{key:len(value) for key,value in splits.items()},"strata":{"source_issue_candidate":40,"unreviewed_control":20},
        "inputs_sha256":hashlib.sha256((destination/"inputs.json").read_bytes()).hexdigest(),
        "eligible_for_headline_metrics":False,"adjudication":"pending","exposure_audit":"pending",
        "sampling":"Purposive public candidate pool; proposed strata are not defective/clean labels."}
    write_json_atomic(destination/"manifest.json",manifest)
    write_json_atomic(destination/"annotations.pending.json",{c.pr_url:{"status":"pending","truth":None,"issue_labels":[],
        "exposure_audit":"pending","base_sha":c.base_sha,"head_sha":c.head_sha} for c in issue+control})
    return manifest


def load_inputs(root: Path) -> tuple[dict,list[dict]]:
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    content=(root/"inputs.json").read_bytes()
    if hashlib.sha256(content).hexdigest()!=manifest["inputs_sha256"]:
        raise ValueError("pilot input integrity mismatch")
    cases=json.loads(content)
    if len(cases)!=manifest["candidate_count"] or len({c["family_id"] for c in cases})!=len(cases):
        raise ValueError("pilot count or family identity mismatch")
    for case in cases:
        PilotCase.model_validate({key:value for key,value in case.items() if key!="split"})
        path=root/"patches"/(case["case_id"]+".diff")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=case["patch_sha256"]:
            raise ValueError("frozen pilot patch integrity mismatch")
    return manifest,cases


def seal(root: Path, predictions: list[dict], output: Path, *, split="test"):
    manifest,cases=load_inputs(root)
    selected={c["pr_url"]:c for c in cases if c["split"]==split}
    urls=[p.get("pr_url") for p in predictions]
    if len(urls)!=len(set(urls)) or set(urls)!=set(selected):
        raise ValueError("every selected case needs exactly one prediction, including failed/no-verdict attempts")
    profiles=set()
    for pred in predictions:
        case=selected[pred["pr_url"]]; result=pred.get("result",pred)
        from core.runtime.models import ReviewResult
        ReviewResult.from_dict(result)
        target=result["target"]
        if (result.get("health",{}).get("status")=="failed" and result.get("decision") is None
                and not result.get("product_findings") and pred.get("attempted_target")):
            target=pred["attempted_target"]
        matches=(all(target.get(k)==case[k] for k in ("base_sha","head_sha")) and
                 (target.get("comparison_base_sha") or target.get("base_sha"))==case["comparison_base_sha"])
        if not matches:
            raise ValueError("prediction target differs from frozen pilot")
        provenance=result.get("provenance") or {}
        if not provenance.get("reviewer_commit") or provenance.get("dirty") is not False:
            raise ValueError("pilot predictions require a frozen clean reviewer")
        profile = {k: provenance.get(k) for k in ("reviewer_commit","provider","model","prompt_version",
                   "analysis_mode","finding_verifier_mode","finding_source_rules","discovery_protocol","requirement_strategy","pilot_profile")}
        profile["limits"] = {key: value for key, value in (provenance.get("budget") or {}).items()
                             if key.startswith("max_")}
        profiles.add(digest(profile))
    if len(profiles)!=1:
        raise ValueError("pilot predictions mix reviewer/model profiles")
    seal_predictions(output,predictions)
    write_json_atomic(output.with_suffix(".seal.json"),{"inputs_sha256":manifest["inputs_sha256"],"split":split,
        "predictions_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),"profile_fingerprint":next(iter(profiles))})


def score(root: Path, predictions_path: Path, annotations_path: Path) -> dict:
    manifest,cases=load_inputs(root)
    seal_record=json.loads(predictions_path.with_suffix(".seal.json").read_text())
    if (seal_record["inputs_sha256"]!=manifest["inputs_sha256"] or
            seal_record["predictions_sha256"]!=hashlib.sha256(predictions_path.read_bytes()).hexdigest()):
        raise ValueError("sealed pilot predictions changed")
    predictions=json.loads(predictions_path.read_text());annotations=json.loads(annotations_path.read_text())
    evaluations,flattened=[],[]
    exposure_complete=True
    for pred in predictions:
        raw=pred.get("result",pred);annotation=annotations.get(pred["pr_url"],{})
        label="unlabeled"
        if annotation.get("status")=="adjudicated":
            truth=PRTruth.model_validate(annotation["truth"])
            intended=pred.get("attempted_target") if raw.get("health",{}).get("status")=="failed" else None
            truth.check_target(raw|{"target":intended or raw["target"]})
            label=truth.label
        exposure_complete &= annotation.get("exposure_audit")=="passed"
        evaluations.append({"pr_url":pred["pr_url"],"pr_truth":label})
        flattened.append(raw|{"pr_url":pred["pr_url"]})
    safety=merge_safety(evaluations,flattened)
    labels_complete=not any(safety["labels"][key] for key in ("unlabeled","uncertain"))
    return {"merge_safety":safety,"labels_complete":labels_complete,"exposure_audited":exposure_complete,
        "eligible_for_headline_metrics":False,
        "scope":"Safety accounting only. Issue matching, label independence, representative sampling and release qualification are separate requirements.",
        "annotations_sha256":hashlib.sha256(annotations_path.read_bytes()).hexdigest()}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path);parser.add_argument("--predictions",type=Path,required=True)
    parser.add_argument("--annotations",type=Path);parser.add_argument("--seal",action="store_true")
    parser.add_argument("--output",type=Path,help="New immutable prediction file when sealing")
    parser.add_argument("--split",default="test",choices=["development","validation","test"])
    args=parser.parse_args()
    if args.seal:
        if args.output is None: parser.error("--output is required when sealing; source predictions are never overwritten")
        seal(args.root,json.loads(args.predictions.read_text()),args.output,split=args.split)
    else:
        if args.annotations is None: parser.error("--annotations is required for scoring")
        print(json.dumps(score(args.root,args.predictions,args.annotations),indent=2))
