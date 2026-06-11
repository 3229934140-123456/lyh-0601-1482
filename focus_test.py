import requests, json
BASE = "http://127.0.0.1:8000/api/v1"
ANN1, ANN2, QC1 = 2, 3, 5
P1 = 1

def run(name, method, url, **kw):
    print(f"\n{'='*70}\n  {name}\n{'='*70}")
    r = requests.request(method, url, timeout=10, **kw)
    try:
        d = r.json()
    except Exception as e:
        print(f"  HTTP={r.status_code}, raw={r.text[:200]}")
        return None
    code = d.get('code', r.status_code)
    msg = d.get('message', '')[:120]
    print(f"  HTTP={r.status_code} | code={code} | {msg}")
    return d

# ========= 分配任务 =========
d1 = run("分配 T1 (ANN1)", "POST", f"{BASE}/tasks/assign",
    json={"project_id":P1,"assignee_id":ANN1,"assignee_type":"annotator","sample_count":2})
T1 = d1['data']['task']['id']; S1 = d1['data']['sample_ids'][0]
print(f"  T1={T1}, shared={S1}")

d2 = run("分配 T2 (ANN2，也包含 S1)", "POST", f"{BASE}/tasks/assign",
    json={"project_id":P1,"assignee_id":ANN2,"assignee_type":"annotator","sample_count":2})
T2 = d2['data']['task']['id']
print(f"  T2={T2}, samples={d2['data']['sample_ids']}")

# 如果 T2 没有包含 S1，那就强制给 ANN2 分配包含 S1 的任务，用 T1 的样本列表再分配一次
SHARED = S1
if S1 not in d2['data']['sample_ids']:
    # 尝试用 claim 再分配，希望能拿到 S1
    for i in range(2):
        dd = run(f"重试分配 ANN2 任务 {i+1}", "POST", f"{BASE}/tasks/assign",
            json={"project_id":P1,"assignee_id":ANN2,"assignee_type":"annotator","sample_count":2})
        if S1 in dd['data'].get('sample_ids', []):
            T2 = dd['data']['task']['id']
            print(f"  找到了！新 T2={T2}, samples={dd['data']['sample_ids']}")
            break

# ========= ANN1 标注 S1 (positive) =========
d = run("ANN1 创建 S1 草稿 (positive)", "POST",
    f"{BASE}/tasks/{T1}/annotations", params={"annotator_id":ANN1},
    json={"sample_id":SHARED,"task_id":T1,"content":{"sentiment":"positive","urgency":"low","tags":["news"]},"time_spent_seconds":9})
A1 = d['data']['id'] if d.get('data') else None

d = run("ANN1 提交 S1", "POST", f"{BASE}/tasks/annotations/{A1}/submit",
    params={"submitter_id":ANN1},
    json={"content":{"sentiment":"positive","urgency":"low","tags":["news"]},"time_spent_seconds":9})
c = d['data'].get('consistency', {})
print(f"  -> consistency: {json.dumps(c, ensure_ascii=False)}")

# ========= ANN2 标注 S1 (negative 完全不同，加上全部字段不同) =========
d = run("ANN2 创建 S1 草稿 (完全不同！)", "POST",
    f"{BASE}/tasks/{T2}/annotations", params={"annotator_id":ANN2},
    json={"sample_id":SHARED,"task_id":T2,"content":{"sentiment":"negative","urgency":"high","tags":["breaking","warning","alert"]},"time_spent_seconds":11})
A2 = d['data']['id'] if d.get('data') else None

d = run("【需求1核心】ANN2 提交 S1 -> 答案不一致 触发冲突复核", "POST", f"{BASE}/tasks/annotations/{A2}/submit",
    params={"submitter_id":ANN2},
    json={"content":{"sentiment":"negative","urgency":"high","tags":["breaking","warning","alert"]},"time_spent_seconds":11})
c = d['data'].get('consistency', {}) if d.get('data') else {}
print(f"  -> consistency: {json.dumps(c, ensure_ascii=False, default=str)}")

# ========= 查看复核任务 =========
d = run("复核任务列表（应该>=1）", "GET", f"{BASE}/quality/review-tasks",
    params={"project_id":P1,"limit":3})
items = d['data']['items'] if d.get('data') else []
print(f"  count={len(items)}")
for it in items[:2]:
    print(f"    id={it['id']} sid={it['sample_id']} ann_cnt={it.get('annotation_count')} "
          f"qc={it.get('assignee',{}).get('id') if it.get('assignee') else 'N/A'}")
RT_ID = items[0]['id'] if items else None
CHECK_SID = items[0]['sample_id'] if items else None

# ========= 提交复核 =========
if RT_ID:
    d = run("提交复核：采纳 ANN1 答案", "POST", f"{BASE}/quality/review-tasks/{RT_ID}/submit",
        json={"checker_id":QC1,"resolution":{"sentiment":"positive","urgency":"low","tags":["news"]},
              "resolution_comment":"采纳ANN1 POSITIVE答案"})
    if d.get('data'):
        print(f"  conflict_resolved={d['data'].get('conflict_resolved')}")

    # 检查样本最终答案
    if CHECK_SID:
        d = run("【验证】样本最终答案检查", "GET", f"{BASE}/projects/{P1}/samples/{CHECK_SID}")
        sd = d['data'] if d.get('data') else {}
        smp = sd.get('sample', {}) if isinstance(sd, dict) else {}
        print(f"  status={smp.get('status')}, consistency_score={smp.get('consistency_score')}")
        print(f"  final_annotation={smp.get('final_annotation')}")
        print(f"  ann_count={sd.get('annotation_count')}")

# ========= 需求3：人员统计验证 =========
d = run("【需求3a】标注员进度列表 (带角色和时间筛选)", "GET", f"{BASE}/stats/annotators/progress",
    params={"role":"annotator","page_size":10})
if d.get('data'):
    items = d['data'].get('items', [])
    for it in items[:3]:
        print(f"  {it.get('annotator_username')} role={it.get('annotator_role')} completed={it.get('completed_count')} approved={it.get('approved')} pass_rate={it.get('pass_rate')} avg_s={it.get('avg_time_per_sample_seconds')}")

d = run("【需求3b】结果汇总导出（含新指标）", "GET", f"{BASE}/export/projects/{P1}/summary")
if d.get('data'):
    ranks = d['data'].get('annotator_rankings', [])
    for r in ranks[:3]:
        print(f"  rank: {r.get('username')} role={r.get('annotator_role')} pass={r.get('pass_rate')} reworks={r.get('rework_count')} avg_s={r.get('avg_time_per_sample_seconds')}")

# ========= 需求4：批量质检 =========
d = run("抽样质检", "POST", f"{BASE}/quality/sample",
    json={"project_id":P1,"checker_id":QC1,"sample_count":5,"sample_rate":0.3})
qcs = d['data']['quality_checks'] if d.get('data') else []
qc_ids = [q['id'] for q in qcs]
print(f"  sampled: {qc_ids}")

if len(qc_ids) >= 3:
    ids = qc_ids[:2]
    d = run("【需求4a】批量通过 2 条", "POST", f"{BASE}/quality/quality-checks/batch",
        params={"checker_id":QC1,"action":"approve","common_quality_score":0.9},
        json=ids)
    print(f"  result: processed={d['data'].get('processed') if d.get('data') else 'ERR'}")

    rw_id = qc_ids[2]
    d = run("【需求4b】批量返工 1 条", "POST", f"{BASE}/quality/quality-checks/batch",
        params={"checker_id":QC1,"action":"rework","rework_reason":"批量质检要求返工"},
        json=[rw_id])
    if d.get('data'):
        rew_ids = d['data'].get('rework_ids_created', [])
        print(f"  reworks: {rew_ids}")
        if rew_ids:
            d = run("【需求4c】完成返工 -> 重新一致性判断", "POST",
                f"{BASE}/quality/reworks/{rew_ids[0]}/complete")
            if d.get('data'):
                print(f"  consistency_checked={d['data'].get('consistency_checked')}")
                cr = d['data'].get('consistency_result', {})
                if cr:
                    print(f"    processed={cr.get('processed')}, "
                          f"action={cr.get('action')}, "
                          f"score={cr.get('consistency_score')}")

# ========= 需求2：权限边界验证 =========
print(f"\n{'='*70}\n  【需求2】权限边界最后验证\n{'='*70}")
d = run("ANN2 用 ANN1 的 T1 标注 -> 预期 403", "POST",
    f"{BASE}/tasks/{T1}/annotations", params={"annotator_id":ANN2},
    json={"sample_id":SHARED,"task_id":T1,"content":{"x":1},"time_spent_seconds":1})
if d.get('code') == 403:
    print(f"  [OK] 正确！403 权限拒绝：{d.get('message')}")
else:
    print(f"  [WARN] 结果：{d.get('code')} {d.get('message')}")

# 项目2样本
d = run("查询 P2 样本1个", "GET", f"{BASE}/projects/2/samples", params={"limit":1})
p2sid = None
if d.get('data'):
    it = d['data'].get('items', []) if isinstance(d['data'], dict) else []
    if it: p2sid = it[0]['id']
if p2sid:
    d = run("P1的T1 + P2的样本 -> 预期 403", "POST",
        f"{BASE}/tasks/{T1}/annotations", params={"annotator_id":ANN1},
        json={"sample_id":p2sid,"task_id":T1,"content":{"x":1},"time_spent_seconds":1})
    if d.get('code') == 403:
        print(f"  [OK] 正确！403 权限拒绝：{d.get('message')}")
    else:
        print(f"  [WARN] 结果：{d.get('code')} {d.get('message')}")
