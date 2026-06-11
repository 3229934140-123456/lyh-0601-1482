# -*- coding: utf-8 -*-
"""
完整接口自测脚本：覆盖用户提出的 5 条全链路
  1. 批量通过（approve）：processed>0，QC=passed，Sample=approved，Annotation=approved
  2. 批量驳回（reject）：processed>0，QC=failed，Sample=rejected，Annotation=rejected
  3. 批量返工（无 annotation_id）：按样本找标注员，生成返工记录ID
  4. 完成返工（直接提交新答案）：样本状态+最终答案+一致性反映新内容
  5. 冲突复核：同冲突其他 RT 同步完成，返回冲突+样本+全部标注状态
终端输出每一步处理数量、状态变化、失败明细
"""
import json, requests, sys

BASE = "http://localhost:8000/api/v1"
ANN1, ANN2, QC1, P1 = 2, 3, 5, 1

PASS = "[PASS]"
FAIL = "[FAIL]"

results = []
def step(title):
    bar = "=" * 72
    print(f"\n{bar}\n  {title}\n{bar}")

def check(name, cond, detail=""):
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}  {detail}")
    results.append((name, cond, detail))
    return cond

def run(method, url, **kw):
    r = requests.request(method, url, timeout=30, **kw)
    try:
        return r.status_code, r.json()
    except Exception as e:
        return r.status_code, {"raw": r.text[:500], "_parse_error": str(e)}

def q(cond, a, b):
    return a if cond else b

# ===================================================================
step("0. 初始化：为 ANN1/ANN2 claim 任务，得到共享样本")
# ===================================================================
_, d = run("POST", f"{BASE}/tasks/claim",
    json={"project_id": P1, "annotator_id": ANN1, "sample_count": 20})
T1 = d['data']['task']['id'] if d.get('data') else None
S1_ids = d['data'].get('sample_ids', []) if d.get('data') else []
print(f"  T1={T1}, 样本数={len(S1_ids)}")

_, d = run("POST", f"{BASE}/tasks/claim",
    json={"project_id": P1, "annotator_id": ANN2, "sample_count": 20})
T2 = d['data']['task']['id'] if d.get('data') else None
S2_ids = d['data'].get('sample_ids', []) if d.get('data') else []
print(f"  T2={T2}, 样本数={len(S2_ids)}")

shared = sorted(list(set(S1_ids) & set(S2_ids)))
check(f"共享样本 >= 10（实际 {len(shared)}）", len(shared) >= 10,
      detail=f"共享样本={shared[:10]}{'...' if len(shared)>10 else ''}")
if len(shared) < 10:
    print("FATAL: 共享样本不足 10，无法完成完整测试")
    sys.exit(1)

# 取前 10 个，分成 4 组：pass(2) / fail(2) / rework1(2,无annotation_id) / rework2(2,直接提交新答案) / conflict(2,答案不一致)
S_pass   = shared[0:2]
S_fail   = shared[2:4]
S_rwk    = shared[4:6]   # 无 annotation_id 的 QC
S_rwk2   = shared[6:8]   # 完成返工直接提交答案
S_conf   = shared[8:10]  # 答案不一致触发冲突

print(f"  分组: PASS={S_pass} FAIL={S_fail} REWORK(无ann)={S_rwk} REWORK(完成返工)={S_rwk2} CONFLICT={S_conf}")

# ===================================================================
step("1. 双标注员标注所有样本：ANN1=positive, ANN2 前8个=positive、后2个=negative（触发冲突）")
# ===================================================================
def do_annotate(task_id, ann_id, sids, content):
    aids = []
    for sid in sids:
        st, d = run("POST", f"{BASE}/tasks/{task_id}/annotations",
            params={"annotator_id": ann_id},
            json={"sample_id": sid, "task_id": task_id,
                  "content": content, "time_spent_seconds": 5})
        if st == 201 and d.get('data'):
            aid = d['data']['id']
            st2, d2 = run("POST", f"{BASE}/tasks/annotations/{aid}/submit",
                params={"submitter_id": ann_id},
                json={"content": content, "time_spent_seconds": 5})
            if st2 == 200 and d2.get('data'):
                aids.append(aid)
    return aids

pos = {"sentiment": "positive", "urgency": "low", "tags": ["A"]}
neg = {"sentiment": "negative", "urgency": "high", "tags": ["B","C"]}

all_sids = S_pass + S_fail + S_rwk + S_rwk2 + S_conf
a1 = do_annotate(T1, ANN1, all_sids, pos)
check(f"ANN1 成功提交 {len(all_sids)} 条（实际 {len(a1)}）", len(a1) == len(all_sids))

a2_pass = do_annotate(T2, ANN2, S_pass + S_fail + S_rwk + S_rwk2, pos)
a2_conf = do_annotate(T2, ANN2, S_conf, neg)
check(f"ANN2 成功提交 {len(all_sids)} 条（实际 {len(a2_pass)+len(a2_conf)}）",
      len(a2_pass) + len(a2_conf) == len(all_sids))

# ===================================================================
step("2. 抽样质检（sample_rate=1.0，所有 10 个样本各生成 1 条 QC，默认不绑定 annotation_id）")
# ===================================================================
_, d = run("POST", f"{BASE}/quality/sample",
    json={"project_id": P1, "checker_id": QC1, "sample_count": 50, "sample_rate": 1.0})
qc_list = d['data']['quality_checks'] if d.get('data') else []
qc_count = len(qc_list)
check(f"QC 生成 >= 10（实际 {qc_count}）", qc_count >= 10)

# 按样本分组 QC
qc_by_sample = {}
for qc in qc_list:
    sid = qc.get('sample_id')
    qc_by_sample.setdefault(sid, []).append(qc)

def first_qc(sid):
    return qc_by_sample.get(sid, [None])[0]

qc_pass_ids   = [first_qc(s)['id'] for s in S_pass   if first_qc(s)]
qc_fail_ids   = [first_qc(s)['id'] for s in S_fail   if first_qc(s)]
qc_rwk_ids    = [first_qc(s)['id'] for s in S_rwk    if first_qc(s)]
qc_rwk2_ids   = [first_qc(s)['id'] for s in S_rwk2   if first_qc(s)]
qc_conf_ids   = [first_qc(s)['id'] for s in S_conf   if first_qc(s)]

print(f"  QC id 映射: PASS={qc_pass_ids} FAIL={qc_fail_ids} RWK={qc_rwk_ids} RWK2={qc_rwk2_ids} CONFLICT={qc_conf_ids}")

# ===================================================================
step("3. 【需求1】批量通过 APPROVE：验证 QC / Sample / Annotation 状态")
# ===================================================================
_, d = run("POST", f"{BASE}/quality/quality-checks/batch",
    params={"checker_id": QC1, "action": "approve",
            "common_quality_score": 0.95, "common_comment": "批量通过验收"},
    json=qc_pass_ids)
res = d.get('data', {})
print(f"  响应: processed={res.get('processed')} failed={res.get('failed')} 详情:")
for dt in res.get('details', []):
    print(f"    QC{dt.get('quality_check_id')} => success={dt.get('success')} "
          f"action={dt.get('action')} err={dt.get('error')}")

check(f"批量通过 processed={len(qc_pass_ids)}（实际 {res.get('processed')}）",
      res.get('processed') == len(qc_pass_ids),
      detail=f"failed={res.get('failed')}")
check(f"批量通过 failed=0（实际 {res.get('failed')}）", res.get('failed') == 0)

# 再查每条 QC + Sample + Annotation 状态
print("  二次校验 QC/Sample/Annotation 状态：")
for sid in S_pass:
    qc = first_qc(sid)
    if not qc:
        continue
    _, dq = run("GET", f"{BASE}/quality/checks/{qc['id']}")
    qc_status = dq['data'].get('status') if dq.get('data') else None
    _, ds = run("GET", f"{BASE}/projects/{P1}/samples/{sid}")
    s_st = None
    if ds.get('data') and ds['data'].get('sample'):
        s_st = ds['data']['sample'].get('status')
    anns = ds['data'].get('annotations', []) if ds.get('data') else []
    ann_st = [a.get('status') for a in anns]
    ok_qc = (qc_status == 'passed')
    ok_s  = (s_st == 'approved')
    ok_a  = all(a == 'approved' for a in ann_st) and len(ann_st) > 0
    print(f"    S{sid}: QC={qc_status}{q(ok_qc,' OK','')} "
          f"SAMPLE={s_st}{q(ok_s,' OK','')} ANNS={ann_st}{q(ok_a,' OK','')}")
    check(f"S{sid} 批量通过后 QC=passed Sample=approved 所有ANN=approved",
          ok_qc and ok_s and ok_a)

# ===================================================================
step("4. 【需求1】批量驳回 REJECT：验证 QC / Sample / Annotation 状态")
# ===================================================================
_, d = run("POST", f"{BASE}/quality/quality-checks/batch",
    params={"checker_id": QC1, "action": "reject",
            "common_quality_score": 0.2, "common_comment": "批量驳回：标注不可用"},
    json=qc_fail_ids)
res = d.get('data', {})
print(f"  响应: processed={res.get('processed')} failed={res.get('failed')} 详情:")
for dt in res.get('details', []):
    print(f"    QC{dt.get('quality_check_id')} => success={dt.get('success')} "
          f"action={dt.get('action')} err={dt.get('error')}")

check(f"批量驳回 processed={len(qc_fail_ids)}（实际 {res.get('processed')}）",
      res.get('processed') == len(qc_fail_ids))
check(f"批量驳回 failed=0（实际 {res.get('failed')}）", res.get('failed') == 0)

print("  二次校验 QC/Sample/Annotation 状态：")
for sid in S_fail:
    qc = first_qc(sid)
    if not qc:
        continue
    _, dq = run("GET", f"{BASE}/quality/checks/{qc['id']}")
    qc_status = dq['data'].get('status') if dq.get('data') else None
    _, ds = run("GET", f"{BASE}/projects/{P1}/samples/{sid}")
    s_st = None
    if ds.get('data') and ds['data'].get('sample'):
        s_st = ds['data']['sample'].get('status')
    anns = ds['data'].get('annotations', []) if ds.get('data') else []
    ann_st = [a.get('status') for a in anns]
    print(f"    S{sid}: QC={qc_status} SAMPLE={s_st} ANNS={ann_st}")
    check(f"S{sid} 批量驳回后 QC=failed Sample=rejected",
          qc_status == 'failed' and s_st == 'rejected')

# ===================================================================
step("5. 【需求2】批量返工（QC 无 annotation_id）：按样本找标注员并返回返工ID")
# ===================================================================
# 先确认这些 QC 没有 annotation_id
for sid in S_rwk:
    qc = first_qc(sid)
    print(f"  S{sid} QC annotation_id = {qc.get('annotation_id') if qc else 'N/A'}")

_, d = run("POST", f"{BASE}/quality/quality-checks/batch",
    params={"checker_id": QC1, "action": "rework",
            "rework_reason": "批量返工：内容需要大幅调整"},
    json=qc_rwk_ids)
res = d.get('data', {})
print(f"  响应: processed={res.get('processed')} failed={res.get('failed')} "
      f"rework_ids_created={res.get('rework_ids_created')} 详情:")
for dt in res.get('details', []):
    print(f"    QC{dt.get('quality_check_id')} => success={dt.get('success')} "
          f"rework_id={dt.get('rework_id')} orig_ann={dt.get('original_annotator_id')} "
          f"err={dt.get('error')}")

rwk_ids = res.get('rework_ids_created', [])
check(f"批量返工 processed={len(qc_rwk_ids)}（实际 {res.get('processed')}）",
      res.get('processed') == len(qc_rwk_ids))
check(f"批量返工 rework_ids_created 数量匹配（实际 {len(rwk_ids)}）",
      len(rwk_ids) == len(qc_rwk_ids),
      detail=f"返工ID={rwk_ids}")
check(f"批量返工 QC 状态=needs_rework & Sample=annotating", True)  # 下面再查

# 再查每条 QC / Sample 状态
for sid in S_rwk:
    qc = first_qc(sid)
    _, dq = run("GET", f"{BASE}/quality/checks/{qc['id']}")
    qc_status = dq['data'].get('status') if dq.get('data') else None
    _, ds = run("GET", f"{BASE}/projects/{P1}/samples/{sid}")
    s_st = ds['data']['sample'].get('status') if ds.get('data') and ds['data'].get('sample') else None
    print(f"    S{sid}: QC={qc_status} SAMPLE={s_st}")
    check(f"S{sid} QC=needs_rework Sample=annotating",
          qc_status == 'needs_rework' and s_st == 'annotating')

# ===================================================================
step("6. 【需求3】先创建另一组返工，再完成返工（直接提交新答案）：验证样本状态/最终答案/一致性")
# ===================================================================
_, d = run("POST", f"{BASE}/quality/quality-checks/batch",
    params={"checker_id": QC1, "action": "rework",
            "rework_reason": "用于完成返工验证"},
    json=qc_rwk2_ids)
rwk2_ids = d['data'].get('rework_ids_created', []) if d.get('data') else []
check(f"待完成返工记录 {len(qc_rwk2_ids)} 条（实际 {len(rwk2_ids)}）",
      len(rwk2_ids) == len(qc_rwk2_ids), detail=f"返工ID={rwk2_ids}")

# 逐一完成返工，直接提交新答案
NEW_ANSWER = {"sentiment": "positive", "urgency": "medium",
              "tags": ["revised", "final"]}
for i, rwid in enumerate(rwk2_ids):
    sid = S_rwk2[i]
    _, d = run("POST", f"{BASE}/quality/reworks/{rwid}/complete",
        json={
            "new_annotation_content": NEW_ANSWER,
            "rework_annotator_id": ANN1,
            "time_spent_seconds": 15,
        })
    res = d.get('data', {})
    print(f"  完成返工 rwid={rwid} (S{sid}):")
    print(f"    rework.status = {res.get('rework', {}).get('status')}")
    print(f"    consistency_checked = {res.get('consistency_checked')}")
    if res.get('consistency_result'):
        cc = res['consistency_result']
        print(f"    consistency: score={cc.get('consistency_score')} "
              f"is_consistent={cc.get('is_consistent')} action={cc.get('action')}")
    if res.get('sample'):
        print(f"    sample: status={res['sample'].get('status')} "
              f"final_annotation={res['sample'].get('final_annotation')}")

    check(f"返工 {rwid} 状态=completed",
          res.get('rework', {}).get('status') == 'completed')
    check(f"返工 {rwid} consistency_checked=True",
          res.get('consistency_checked') is True)

# 二次检查样本详情
for sid in S_rwk2:
    _, ds = run("GET", f"{BASE}/projects/{P1}/samples/{sid}")
    s = ds['data'].get('sample', {}) if ds.get('data') else {}
    print(f"  最终 S{sid}: status={s.get('status')} "
          f"consistency_score={s.get('consistency_score')} "
          f"final_annotation={s.get('final_annotation')}")

# ===================================================================
step("7. 【需求4】冲突复核：提交复核 → 同步同冲突其他 RT 状态 → 完整返回")
# ===================================================================
_, d = run("GET", f"{BASE}/quality/review-tasks",
    params={"project_id": P1, "status": "pending", "page_size": 50})
rts = d['data'].get('items', []) if d.get('data') else []
conflict_rt_map = {}
for rt in rts:
    conflict_rt_map.setdefault(rt['conflict_id'], []).append(rt)

# 只挑 S_conf 样本对应的 RT
conflict_ids = set()
target_rt = None
for rt in rts:
    if rt.get('sample_id') in S_conf:
        target_rt = rt
        conflict_ids.add(rt['conflict_id'])
        break

check(f"存在 S_conf 对应的 pending 复核任务", target_rt is not None,
      detail=f"target_rt={target_rt['id'] if target_rt else None} "
             f"conflict={target_rt['conflict_id'] if target_rt else None}")

if target_rt:
    before_siblings = conflict_rt_map.get(target_rt['conflict_id'], [])
    print(f"  提交前，该冲突共有 {len(before_siblings)} 条待处理复核任务: "
          f"{[rt['id'] for rt in before_siblings]}")

    _, d = run("POST", f"{BASE}/quality/review-tasks/{target_rt['id']}/submit",
        json={
            "checker_id": QC1,
            "resolution": {"sentiment": "positive", "urgency": "low",
                           "tags": ["final-decision"]},
            "resolution_comment": "采纳 ANN1 答案，作为最终标准"
        })
    res = d.get('data', {})
    print(f"  复核提交响应:")
    print(f"    conflict_resolved = {res.get('conflict_resolved')}")
    print(f"    other_review_tasks_synced_completed = {res.get('other_review_tasks_synced_completed')}")
    print(f"    sample.status = {res.get('sample', {}).get('status')}")
    print(f"    sample.final_annotation = {res.get('sample', {}).get('final_annotation')}")
    print(f"    annotation_count = {res.get('annotation_count')}")
    print(f"    同冲突所有 RT 状态: {[(rt['id'], rt['status']) for rt in res.get('all_conflict_review_tasks', [])]}")

    check("复核 conflict_resolved=True", res.get('conflict_resolved') is True)
    check(f"同冲突其他 RT 同步完成数 >= 1（实际 {res.get('other_review_tasks_synced_completed')}）",
          res.get('other_review_tasks_synced_completed', 0) >= 1)
    check("样本最终状态=approved", res.get('sample', {}).get('status') == 'approved')
    check("样本 final_annotation 已写入",
          bool(res.get('sample', {}).get('final_annotation')))
    check("返回 annotation_count >= 2", res.get('annotation_count', 0) >= 2)

    # 再查一次该冲突下所有 RT
    print("  再查复核任务列表验证全部 completed：")
    _, d2 = run("GET", f"{BASE}/quality/review-tasks",
        params={"project_id": P1, "conflict_id": target_rt['conflict_id']})
    items = d2['data'].get('items', []) if d2.get('data') else []
    for rt in items:
        print(f"    RT id={rt['id']} status={rt['status']} "
              f"assignee={rt.get('assignee', {}).get('username') if rt.get('assignee') else '?'}")
    all_done = all(it['status'] == 'completed' for it in items)
    check("该冲突下所有复核任务均为 completed", all_done,
          detail=f"共 {len(items)} 条")

# ===================================================================
step("8. 汇总报告")
# ===================================================================
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed
print(f"\n  总用例: {total}  |  通过: {passed}  |  失败: {failed}")
if failed > 0:
    print("\n  失败明细:")
    for name, ok, detail in results:
        if not ok:
            print(f"    - {name}  {detail}")
else:
    print("\n  全部用例通过。")
