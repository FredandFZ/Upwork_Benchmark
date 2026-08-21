#!/usr/bin/env python3
import json, sys
from collections import defaultdict

def load_jsonl(path):
    rows=[]
    with open(path,encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def prf(pred, gold):
    pset=set(pred or [])
    gset=set(gold or [])
    if not pset and not gset:
        return 1.0,1.0,1.0
    precision=len(pset & gset)/len(pset) if pset else 0.0
    recall=len(pset & gset)/len(gset) if gset else 1.0
    f1=2*precision*recall/(precision+recall) if precision+recall else 0.0
    return precision,recall,f1

def dict_field_accuracy(pred, gold):
    # Gold current_state is a flat dict in pilot v0.1.
    if not isinstance(pred,dict) or not isinstance(gold,dict):
        return 0.0
    if not gold:
        return 1.0
    return sum(1 for k,v in gold.items() if pred.get(k)==v)/len(gold)

def score_one(pred, item):
    rq=item["rq"]
    g=item["gold"]
    if rq=="RQ1":
        p,r,f=prf(pred.get("selected_message_ids"),g["relevant_message_ids"])
        _,cr,cf=prf(pred.get("critical_message_ids"),g["critical_message_ids"])
        score=0.6*f+0.4*cr
        return {"score":score,"precision":p,"recall":r,"f1":f,"critical_recall":cr}
    if rq=="RQ2":
        scope=float(pred.get("scope_label")==g["scope_label"])
        applies=float(pred.get("applies_to_current_task")==g["applies_to_current_task"])
        _,er,ef=prf(pred.get("evidence_message_ids"),g["evidence_message_ids"])
        score=0.45*scope+0.35*applies+0.20*ef
        return {"score":score,"scope_acc":scope,"application_acc":applies,"evidence_f1":ef}
    if rq=="RQ3":
        state=dict_field_accuracy(pred.get("current_state"),g["current_state"])
        _,_,af=prf(pred.get("active_evidence_message_ids"),g["active_evidence_message_ids"])
        _,_,sf=prf(pred.get("superseded_message_ids"),g["superseded_message_ids"])
        score=0.6*state+0.2*af+0.2*sf
        return {"score":score,"state_field_acc":state,"active_evidence_f1":af,"superseded_f1":sf}
    if rq=="RQ4":
        action=float(pred.get("action")==g["action"])
        _,_,ef=prf(pred.get("evidence_message_ids"),g["evidence_message_ids"])
        score=0.8*action+0.2*ef
        return {"score":score,"action_acc":action,"evidence_f1":ef}
    if rq=="RQ5":
        status=float(pred.get("requirement_status")==g["requirement_status"])
        stage=float(pred.get("failure_stage")==g["failure_stage"])
        level=float(pred.get("evidence_level")==g["evidence_level"])
        _,_,ef=prf(pred.get("evidence_message_ids"),g["evidence_message_ids"])
        score=0.4*status+0.3*stage+0.1*level+0.2*ef
        return {"score":score,"status_acc":status,"failure_stage_acc":stage,"evidence_level_acc":level,"evidence_f1":ef}
    raise ValueError(rq)

def main(gold_path,pred_path):
    gold_rows=load_jsonl(gold_path)
    preds={x["instance_id"]:x for x in load_jsonl(pred_path)}
    details=[]
    per_rq=defaultdict(list)
    for item in gold_rows:
        iid=item["instance_id"]
        pred=preds.get(iid,{})
        s=score_one(pred,item)
        details.append({"instance_id":iid,"rq":item["rq"],**s})
        per_rq[item["rq"]].append(s["score"])
    summary={rq:sum(xs)/len(xs) for rq,xs in sorted(per_rq.items())}
    macro=sum(summary.values())/len(summary) if summary else 0.0
    print(json.dumps({"macro_score":macro,"per_rq":summary,"details":details},ensure_ascii=False,indent=2))

if __name__=="__main__":
    if len(sys.argv)!=3:
        print("Usage: python evaluator.py gold.jsonl predictions.jsonl")
        raise SystemExit(2)
    main(sys.argv[1],sys.argv[2])
