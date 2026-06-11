# -*- coding: utf-8 -*-
"""测试需求4：批量质检 + 返工闭环 + 返工后重新一致性判断"""
import json, requests, time, random

BASE = "http://localhost:8000/api/v1"
ANN1, ANN2, QC1, P1 = 2, 3, 5, 1  # 基于种子数据硬编码

def run(name, method, url, **kw):
    print(f"\n{'='*70}\n  {name}\n{'='*70}")
    r = requests.request(method, url, timeout=30, **kw)
    try:
        d = r.json()
    except Exception as e:
        d = {"raw": r.text[:500]}
    code = d.get('code') if isinstance(d, dict) else 'N/A'
    msg = (d.get('message','') if isinstance(d, dict) else '')[:80]
    print(f"  HTTP={r.status_code} | code={code} | {msg}")
    return d

# ========= 1. 分配 T1(ANN1), T2(ANN2)，使用 claim 接口，然后找共同样本交集 =========
T1 = T2 = None
shared_ids = []

# ANN1 claim 10个样本的任务
d = run("1a. ANN1 Claim 任务(10)", "POST", f"{BASE}/tasks/claim",
    json={"project_id":P1,"annotator_id":ANN1,"sample_count":10})
if d.get('data'):
    T1 = d['data']['task']['id']
    shared_ids = d['data'].get('sample_ids', [])
    print(f"  T1={T1}, samples={shared_ids}")

# ANN2 claim 10个样本的任务
d = run("1b. ANN2 Claim 任务(10)", "POST", f"{BASE}/tasks/claim",
    json={"project_id":P1,"annotator_id":ANN2,"sample_count":10})
T2_samples = []
if d.get('data'):
    T2 = d['data']['task']['id']
    T2_samples = d['data'].get('sample_ids', [])
    print(f"  T2={T2}, samples={T2_samples}")

# 找交集（共享的样本）
if shared_ids and T2_samples:
    shared_ids = list(set(shared_ids) & set(T2_samples))
    print(f"  共享样本数（2人都有的）: {len(shared_ids)} = {shared_ids}")
    # 只取前5个
    shared_ids = shared_ids[:5]

if not (T1 and T2 and len(shared_ids) >= 2):
    print("FATAL: 任务分配失败或共享样本不足")
    exit(1)

# ========= 2. ANN1 提交 5 个样本的标注 =========
print("\n" + "#"*70)
print("  2. ANN1 标注 5 个样本（全部提交 positive）")
print("#"*70)
ann1_ids = []
for i, sid in enumerate(shared_ids):
    # 草稿
    d = run(f"ANN1 草稿 S{sid}", "POST",
        f"{BASE}/tasks/{T1}/annotations", params={"annotator_id":ANN1},
        json={"sample_id":sid,"task_id":T1,
              "content":{"sentiment":"positive","urgency":"low","tags":["news"]},
              "time_spent_seconds":10+i})
    aid = d['data']['id'] if d.get('data') else None
    if aid:
        # 提交
        d = run(f"ANN1 提交 S{sid}", "POST",
            f"{BASE}/tasks/annotations/{aid}/submit", params={"submitter_id":ANN1},
            json={"content":{"sentiment":"positive","urgency":"low","tags":["news"]},
                  "time_spent_seconds":10+i})
        ann1_ids.append(aid)

# ========= 3. ANN2 提交 5 个样本的标注（和 ANN1 完全一致，这样会自动通过） =========
print("\n" + "#"*70)
print("  3. ANN2 标注 5 个样本（和 ANN1 完全一致 -> auto approved）")
print("#"*70)
ann2_ids = []
for i, sid in enumerate(shared_ids):
    d = run(f"ANN2 草稿 S{sid}", "POST",
        f"{BASE}/tasks/{T2}/annotations", params={"annotator_id":ANN2},
        json={"sample_id":sid,"task_id":T2,
              "content":{"sentiment":"positive","urgency":"low","tags":["news"]},
              "time_spent_seconds":11+i})
    aid = d['data']['id'] if d.get('data') else None
    if aid:
        d = run(f"ANN2 提交 S{sid} -> 自动批准", "POST",
            f"{BASE}/tasks/annotations/{aid}/submit", params={"submitter_id":ANN2},
            json={"content":{"sentiment":"positive","urgency":"low","tags":["news"]},
                  "time_spent_seconds":11+i})
        c = d['data'].get('consistency', {}) if d.get('data') else {}
        print(f"    S{sid} action={c.get('action')} is_consistent={c.get('is_consistent')}")
        ann2_ids.append(aid)

# ========= 4. 抽样质检（抽满所有5个样本） =========
print("\n" + "#"*70)
print("  4. 抽样质检（sample_rate=1.0，抽满全部）")
print("#"*70)
d = run("抽样", "POST", f"{BASE}/quality/sample",
    json={"project_id":P1,"checker_id":QC1,"sample_count":10,"sample_rate":1.0})
qcs = d['data']['quality_checks'] if d.get('data') else []
qc_ids = [q['id'] for q in qcs]
print(f"  抽中 QC 记录数：{len(qc_ids)}")

# ========= 5. 批量通过前 2 条 =========
batch_approve_ids = qc_ids[:2] if len(qc_ids) >= 2 else []
batch_reject_id = qc_ids[2:3] if len(qc_ids) >= 3 else []
batch_rework_ids = qc_ids[3:5] if len(qc_ids) >= 5 else []
print(f"  分组: approve={batch_approve_ids} reject={batch_reject_id} rework={batch_rework_ids}")

if batch_approve_ids:
    d = run("【需求4a】批量通过 APPROVE", "POST",
        f"{BASE}/quality/quality-checks/batch",
        params={"checker_id":QC1,"action":"approve","common_quality_score":0.9,
                "common_comment":"批量通过，内容正确"},
        json=batch_approve_ids)
    if d.get('data'):
        print(f"  processed={d['data'].get('processed')} failed={d['data'].get('failed')}")

# ========= 6. 批量驳回 1 条 =========
if batch_reject_id:
    d = run("【需求4b】批量驳回 REJECT", "POST",
        f"{BASE}/quality/quality-checks/batch",
        params={"checker_id":QC1,"action":"reject","common_quality_score":0.4,
                "common_comment":"批量驳回，内容错误"},
        json=batch_reject_id)
    if d.get('data'):
        print(f"  processed={d['data'].get('processed')} failed={d['data'].get('failed')}")

# ========= 7. 批量返工 2 条 =========
rework_ids_created = []
if batch_rework_ids:
    d = run("【需求4c】批量要求返工 REWORK", "POST",
        f"{BASE}/quality/quality-checks/batch",
        params={"checker_id":QC1,"action":"rework",
                "rework_reason":"批量质检要求返工，请重新审核"},
        json=batch_rework_ids)
    if d.get('data'):
        print(f"  processed={d['data'].get('processed')} failed={d['data'].get('failed')}")
        rework_ids_created = d['data'].get('rework_ids_created', [])
        print(f"  生成返工任务ID: {rework_ids_created}")

# ========= 8. 处理返工：ANN1 为每个返工样本重新提交标注 =========
if rework_ids_created:
    print("\n" + "#"*70)
    print("  8. 处理返工 + 完成返工触发重新一致性判断")
    print("#"*70)

    # 先查询返工对应的 sample_id 列表
    rework_sample_map = {}
    for rwid in rework_ids_created:
        d = run(f"查询返工 {rwid}", "GET", f"{BASE}/quality/reworks/{rwid}")
        if d.get('data'):
            rw = d['data']
            sid = rw.get('sample_id')
            rework_sample_map[rwid] = sid
            print(f"  返工 {rwid} -> S{sid} 原标注员={rw.get('original_annotator_id')}")

    # 为每个返工样本创建新版本标注（用 ANN1 作为返工标注员）
    for rwid, sid in rework_sample_map.items():
        d = run(f"ANN1 返工新标注 S{sid}", "POST",
            f"{BASE}/tasks/{T1}/annotations", params={"annotator_id":ANN1},
            json={"sample_id":sid,"task_id":T1,
                  "content":{"sentiment":"positive","urgency":"medium","tags":["news","updated"]},
                  "time_spent_seconds":20})
        new_aid = d['data']['id'] if d.get('data') else None
        if new_aid:
            d = run(f"提交返工 S{sid} 新标注AID={new_aid}", "POST",
                f"{BASE}/tasks/annotations/{new_aid}/submit",
                params={"submitter_id":ANN1},
                json={"content":{"sentiment":"positive","urgency":"medium","tags":["news","updated"]},
                      "time_spent_seconds":20})
            # 【需求4核心】完成返工 -> 触发重新一致性判断
            d = run(f"【需求4核心】完成返工 {rwid} -> 重新一致性判断", "POST",
                f"{BASE}/quality/reworks/{rwid}/complete",
                json={"new_annotation_id":new_aid})
            if d.get('data'):
                c = d['data'].get('consistency_result', {})
                print(f"  结果: consistency_checked={d['data'].get('consistency_checked')}")
                if c:
                    print(f"    is_consistent={c.get('is_consistent')} action={c.get('action')} score={c.get('consistency_score')}")

# ========= 9. 最终状态检查 =========
print("\n" + "#"*70)
print("  9. 最终状态检查")
print("#"*70)
for sid in shared_ids:
    d = run(f"S{sid} 状态", "GET", f"{BASE}/projects/{P1}/samples/{sid}")
    if d.get('data'):
        s = d['data'].get('sample', {})
        print(f"  S{sid}: status={s.get('status')} final_ann={s.get('final_annotation')}")
