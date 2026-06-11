# -*- coding: utf-8 -*-
"""单独验证：冲突复核提交后，同冲突其他 RT 同步完成 + 样本状态更新"""
import json, requests

BASE = "http://localhost:8000/api/v1"
ANN1, ANN2, QC1, P1 = 2, 3, 5, 1

def run(method, url, **kw):
    r = requests.request(method, url, timeout=30, **kw)
    try:
        return r.status_code, r.json()
    except Exception as e:
        return r.status_code, {"raw": r.text[:500]}

step = lambda s: print(f"\n{'='*60}\n  {s}\n{'='*60}")

# ====== 种子里 consistency_threshold 已 0.95 ======
# ====== Claim 任务 ======
step("1. Claim 任务")
_, d = run("POST", f"{BASE}/tasks/claim", json={"project_id":P1,"annotator_id":ANN1,"sample_count":5})
T1 = d['data']['task']['id']; S1 = d['data']['sample_ids']
_, d = run("POST", f"{BASE}/tasks/claim", json={"project_id":P1,"annotator_id":ANN2,"sample_count":5})
T2 = d['data']['task']['id']; S2 = d['data']['sample_ids']
shared = sorted(list(set(S1) & set(S2)))[:1]
print(f"  T1={T1} T2={T2} shared={shared}")
sid = shared[0]

# ====== 标注 1 个样本：ANN1 pos, ANN2 neg（字段完全不同）======
step(f"2. 双标注员标注 S{sid}，答案完全不一致（触发冲突）")
diverse_pos = {"sentiment":"positive","category":"news","urgency":"low","tags":["a","b","c"],"score":0.9}
diverse_neg = {"sentiment":"negative","category":"sports","urgency":"high","tags":["x","y"],"score":0.1}

_, d = run("POST", f"{BASE}/tasks/{T1}/annotations", params={"annotator_id":ANN1},
    json={"sample_id":sid,"task_id":T1,"content":diverse_pos,"time_spent_seconds":5})
aid1 = d['data']['id']
st, d = run("POST", f"{BASE}/tasks/annotations/{aid1}/submit", params={"submitter_id":ANN1},
    json={"content":diverse_pos,"time_spent_seconds":5})
print(f"  ANN1 提交: consistency={d.get('data',{}).get('consistency',{}).get('action','?')}")

_, d = run("POST", f"{BASE}/tasks/{T2}/annotations", params={"annotator_id":ANN2},
    json={"sample_id":sid,"task_id":T2,"content":diverse_neg,"time_spent_seconds":5})
aid2 = d['data']['id']
st, d = run("POST", f"{BASE}/tasks/annotations/{aid2}/submit", params={"submitter_id":ANN2},
    json={"content":diverse_neg,"time_spent_seconds":5})
c = d.get('data',{}).get('consistency', {})
print(f"  ANN2 提交: action={c.get('action')} conflict_created={c.get('conflict_created')} "
      f"review_tasks_created={c.get('review_tasks_created')} is_consistent={c.get('is_consistent')} "
      f"score={c.get('consistency_score')}")

# ====== 查看冲突下的所有 pending RT ======
step("3. 查看该样本的冲突和所有 pending RT")
_, d = run("GET", f"{BASE}/quality/review-tasks", params={"project_id":P1,"page_size":50})
rts = d['data'].get('items', []) if d.get('data') else []
sib_rts = [rt for rt in rts if rt.get('sample_id') == sid]
print(f"  S{sid} 的复核任务共 {len(sib_rts)} 条:")
for rt in sib_rts:
    assignee = rt.get('assignee') or {}
    print(f"    RT{rt['id']} status={rt['status']} assignee={assignee.get('username')}")

if sib_rts:
    rt0 = sib_rts[0]
    step(f"4. 提交 RT{rt0['id']}（质检员 QC1）")
    resolution = {"sentiment":"positive","category":"news","urgency":"medium","tags":["FINAL"],"score":0.7}
    _, d = run("POST", f"{BASE}/quality/review-tasks/{rt0['id']}/submit", json={
        "checker_id": QC1,
        "resolution": resolution,
        "resolution_comment": "采纳 ANN1 正面答案并调整 urgency",
    })
    res = d.get('data', {})
    print(f"  conflict_resolved = {res.get('conflict_resolved')}")
    print(f"  other_review_tasks_synced_completed = {res.get('other_review_tasks_synced_completed')}")
    print(f"  sample.status = {res.get('sample',{}).get('status')}")
    print(f"  sample.final_annotation = {res.get('sample',{}).get('final_annotation')}")
    print(f"  sample.consistency_score = {res.get('sample',{}).get('consistency_score')}")
    print(f"  annotation_count = {res.get('annotation_count')}")
    print(f"  同冲突所有 RT 状态:")
    for rt in res.get('all_conflict_review_tasks', []):
        if rt is None: continue
        cmt = (rt.get('resolution_comment') or '')[:40]
        print(f"    RT{rt['id']} status={rt['status']} comment={cmt}")

    step("5. 二次查询同冲突所有 RT（验证同步完成）")
    _, d = run("GET", f"{BASE}/quality/review-tasks", params={"project_id":P1,"page_size":50})
    rts2 = d['data'].get('items', []) if d.get('data') else []
    sib2 = [rt for rt in rts2 if rt.get('sample_id') == sid]
    all_done = all(rt['status'] == 'completed' for rt in sib2)
    print(f"  S{sid} 的 {len(sib2)} 条复核任务状态:")
    for rt in sib2:
        assignee = rt.get('assignee') or {}
        print(f"    RT{rt['id']} status={rt['status']} assignee={assignee.get('username')}")
    print(f"  >> 全部 completed = {all_done}")

    step("6. 查询样本最终详情")
    _, ds = run("GET", f"{BASE}/projects/{P1}/samples/{sid}")
    s = ds['data'].get('sample', {}) if ds.get('data') else {}
    anns = ds['data'].get('annotations', []) if ds.get('data') else []
    print(f"  sample.status={s.get('status')}")
    print(f"  sample.consistency_score={s.get('consistency_score')}")
    print(f"  sample.final_annotation={s.get('final_annotation')}")
    print(f"  annotations 状态={[a.get('status') for a in anns]}")

    step("7. 查询冲突记录")
    _, dc = run("GET", f"{BASE}/quality/conflicts", params={"project_id":P1,"page_size":20})
    cfs = dc['data'].get('items', []) if dc.get('data') else []
    s_conflicts = [c for c in cfs if c.get('sample_id') == sid]
    for c in s_conflicts:
        note = (c.get('resolution_note') or '')[:40]
        print(f"  conflict {c['id']}: resolved={c.get('resolved')} "
              f"resolver={c.get('resolver_id')} note={note}")
