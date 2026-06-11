import requests, json, time
BASE = "http://127.0.0.1:8000/api/v1"

def t(name, resp):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    d = resp.json()
    code = d.get('code')
    msg = d.get('message')[:120]
    print(f"  HTTP={resp.status_code} | code={code} | msg={msg}")
    data = d.get('data')
    if isinstance(data, dict):
        keys = list(data.keys())
        print(f"  data keys: {keys[:12]}")
        if 'task' in data:
            print(f"    task.id={data['task'].get('id')}, samples={[s.get('id') for s in data.get('samples',[])]}")
        if 'items' in data:
            print(f"    total={data.get('total')}, items_count={len(data['items'])}")
            for i, it in enumerate(data['items'][:2]):
                short = {k:v for k,v in it.items() if k not in ['sample','annotations','assignee','content','sample_metadata','final_annotation','label_specs']}
                print(f"    [{i+1}] {json.dumps(short, ensure_ascii=False, default=str)[:220]}")
        if 'annotation' in data and isinstance(data['annotation'], dict):
            a = data['annotation']
            print(f"    annotation.id={a.get('id')}, status={a.get('status')}")
        if 'consistency' in data and isinstance(data['consistency'], dict):
            c = data['consistency']
            print(f"    consistency: is_consistent={c.get('is_consistent')}, score={c.get('consistency_score')}, action={c.get('action')}")
            print(f"    conflict_created={c.get('conflict_created')}, review_tasks_created={c.get('review_tasks_created')}")
            if c.get('assigned_quality_checkers'):
                print(f"    assigned QC: {c.get('assigned_quality_checkers')}")
        if isinstance(data, dict) and 'processed' in data:
            short = {k:v for k,v in data.items() if k not in ['details']}
            print(f"    summary: {json.dumps(short, ensure_ascii=False, default=str)[:300]}")
    else:
        print(f"  data (truncated): {json.dumps(data, ensure_ascii=False, default=str)[:300]}")
    return d

print("="*70)
print("  端到端测试：4个需求完整流程验证")
print("="*70)

# 基础数据
P1 = 1
P2 = 2
ADMIN, ANN1, ANN2, ANN3, QC1 = 1,2,3,4,5

# ============ 需求3：人员统计（先验证一下）
d1 = requests.get(f"{BASE}/stats/annotators/progress", params={"project_id": P1, "role": "annotator"})
t("[需求3.1] 标注员进度列表(项目+角色筛选)", d1)

d2 = requests.get(f"{BASE}/export/projects/{P1}/summary")
t("[需求3.2] 导出汇总排名字段检查", d2)

# ============ 需求2：任务权限收紧 + 分配任务
print("\n" + "="*70)
print("  分配任务给 ANN1 和 ANN2")
print("="*70)

r = requests.post(f"{BASE}/tasks/assign", json={"project_id":1,"assignee_id":ANN1,"assignee_type":"annotator","sample_count":2})
d = t("[分配 ANN1 任务1", r)
T1_ID = d['data']['task']['id']
S1 = d['data']['sample_ids'][0] if d.get('data') and d['data'].get('sample_ids') else None
print(f"  T1_ID={T1_ID}, shared sample S1={S1}")

r = requests.post(f"{BASE}/tasks/assign", json={"project_id":1,"assignee_id":ANN2,"assignee_type":"annotator","sample_count":2})
d = t("[分配 ANN2 任务2]", r)
T2_ID = d['data']['task']['id']
# 我们要让 ANN2 也拿到同样 S1，为了一致性测试；如果不是，后续覆盖测试需求2的权限检查就用 ANN1 的 S1
S2_list = d['data']['sample_ids'] if d.get('data') else []
print(f"  T2_ID={T2_ID}, S2_list={S2_list}")

# 测试需求2：ANN2尝试用T1_ID和S1 -> 失败
if T1_ID and S1:
    r = requests.post(f"{BASE}/tasks/{T1_ID}/annotations", params={"annotator_id": ANN2}, json={
        "sample_id": S1, "task_id": T1_ID,
        "content": {"x":1}, "time_spent_seconds": 5
    })
    t("[需求2.1] ANN2用ANN1任务 -> 预期失败(403)", r)

# 测试需求2：ANN1用T1_ID + P2样本 -> 失败
p2_samples_r = requests.get(f"{BASE}/projects/{P2}/samples", params={"limit":1})
p2_d = p2_samples_r.json()
p2_sid = None
if p2_d.get('data'):
    items = p2_d['data'].get('items', []) if isinstance(p2_d['data'], dict) else []
    if items: p2_sid = items[0]['id']
print(f"  P2 sample id for permission test: {p2_sid}")

if T1_ID and p2_sid:
    r = requests.post(f"{BASE}/tasks/{T1_ID}/annotations", params={"annotator_id": ANN1}, json={
        "sample_id": p2_sid, "task_id": T1_ID,
        "content": {"x":1}, "time_spent_seconds":5
    })
    t("[需求2.2] P1任务+P2样本 -> 预期失败(403)", r)

# ============ 需求1：多人标注不一致 -> 自动生成复核任务
print("\n" + "="*70)
print("  需求1：ANN1和ANN2给S1提交不同答案")
print("="*70)

# ANN1标注S1 (POSITIVE)
if T1_ID and S1:
    r = requests.post(f"{BASE}/tasks/{T1_ID}/annotations", params={"annotator_id": ANN1}, json={
        "sample_id": S1, "task_id": T1_ID,
        "content": {"sentiment":"positive","score":0.8}, "time_spent_seconds": 10
    })
    d = t("[ANN1] 草稿标注 S1 (POSITIVE)", r)
    A1_ID = d['data']['id'] if d.get('data') else None
    print(f"  A1_ID={A1_ID}")
    if A1_ID:
        r = requests.post(f"{BASE}/tasks/annotations/{A1_ID}/submit", params={"submitter_id":ANN1},
            json={"content": {"sentiment":"positive","score":0.8}, "time_spent_seconds":10})
        t("[ANN1] 提交 S1 标注", r)

# 先给 ANN2 手动分配 S1 样本
print("\n  --- 为了一致性测试：给 ANN2 分配包含 S1 的任务")
r = requests.post(f"{BASE}/tasks/assign", json={"project_id":1,"assignee_id":ANN2,"assignee_type":"annotator","sample_count":1})
d = t("[再分配] ANN2 新任务", r)
NEW_T2 = None
SHARED = None
if d.get('data'):
    NEW_T2 = d['data']['task']['id']
    sids = d['data']['sample_ids']
    # 检查 S1 是否在里面，不在的话就不测试冲突，跳过
    if S1 in sids:
        SHARED = S1
    elif sids:
        SHARED = sids[0]
        S1 = SHARED  # 覆盖为新的共享
        print(f"  New shared sample: {SHARED}")

# 如果 ANN2 也有 S1 就走完整测试需求1
if NEW_T2 and SHARED:
    # ANN2标注 S1 (NEGATIVE)
    r = requests.post(f"{BASE}/tasks/{NEW_T2}/annotations", params={"annotator_id":ANN2}, json={
        "sample_id": SHARED, "task_id": NEW_T2,
        "content": {"sentiment":"negative","score":0.9}, "time_spent_seconds": 12
    })
    d = t("[ANN2] 草稿标注 S1 (NEGATIVE)", r)
    A2_ID = d['data']['id'] if d.get('data') else None
    if A2_ID:
        r = requests.post(f"{BASE}/tasks/annotations/{A2_ID}/submit", params={"submitter_id":ANN2},
            json={"content": {"sentiment":"negative","score":0.9}, "time_spent_seconds":12})
        d = t("[需求1核心] ANN2提交 -> 触发冲突+复核任务", r)

# 查看复核任务
print(f"\n  --- 查看复核任务列表")
r = requests.get(f"{BASE}/quality/review-tasks", params={"project_id": P1, "limit": 5})
d = t("[需求1.3] 复核任务(含样本)", r)
RT_ID = None
RT_SAMPLE = None
if d.get('data'):
    items = d['data'].get('items', []) if isinstance(d['data'], dict) else []
    if items:
        it = items[0]
        RT_ID = it.get('id')
        RT_SAMPLE = it.get('sample_id')
        print(f"  sample_details check: annotation_count={it.get('annotation_count')}, has_preview={bool(it.get('sample_content_preview'))}")

# 提交复核 -> 冲突解决+样本更新
if RT_ID:
    r = requests.post(f"{BASE}/quality/review-tasks/{RT_ID}/submit", json={
        "checker_id": QC1,
        "resolution": {"sentiment":"positive","score":0.85},
        "resolution_comment": "POS正确，采纳ANN1"
    })
    d = t("[需求1.4] 提交复核 -> 期望级联更新", d=r)

# 验证样本最终答案
if RT_SAMPLE:
    r = requests.get(f"{BASE}/projects/{P1}/samples/{RT_SAMPLE}")
    d = t("[需求1.5] 检查样本最终答案", r)
    if d.get('data') and isinstance(d['data'], dict):
        print(f"  sample.status={d['data'].get('status')}")
        print(f"  final_annotation={d['data'].get('final_annotation')}")
        print(f"  consistency_score={d['data'].get('consistency_score')}")

# ============ 需求4：批量质检 + 返工闭环
print("\n" + "="*70)
print("  需求4：批量质检/返工/一致性重新判断")
print("="*70)

# 抽样生成质检
r = requests.post(f"{BASE}/quality/sample", json={
    "project_id": P1, "checker_id": QC1,
    "sample_count": 4, "sample_rate": 0.2})
d = t("[需求4.1] 抽样质检", r)
QC_IDS = []
if d.get('data') and isinstance(d['data'], dict):
    qcs = d['data'].get('quality_checks', [])
    QC_IDS = [q['id'] for q in qcs if isinstance(q, dict)]
print(f"  QC_IDS={QC_IDS[:6]}")

# 批量通过
if len(QC_IDS) >= 2:
    ids = QC_IDS[:2]
    r = requests.post(f"{BASE}/quality/quality-checks/batch",
        params={"checker_id":QC1,"action":"approve","common_quality_score":0.95,"common_comment":"批量通过"},
        json=ids)
    d = t("[需求4.2a] 批量通过 2 条", r)

# 批量返工1条
REWORK_ID = None
if len(QC_IDS) >= 3:
    ids = QC_IDS[2:3]
    r = requests.post(f"{BASE}/quality/quality-checks/batch",
        params={"checker_id":QC1,"action":"rework","rework_reason":"需要返工修正"},
        json=ids)
    d = t("[需求4.2b] 批量返工 1 条", r)
    if d.get('data') and isinstance(d['data'], dict):
        reworks = d['data'].get('rework_ids_created', [])
        if reworks: REWORK_ID = reworks[0]
print(f"  REWORK_ID = {REWORK_ID}")

# 完成返工 -> 触发一致性判断
if REWORK_ID:
    r = requests.post(f"{BASE}/quality/reworks/{REWORK_ID}/complete")
    d = t("[需求4.3] 完成返工 -> 一致性重新判断", r)
    if d.get('data') and isinstance(d['data'], dict):
        print(f"  consistency_checked = {d['data'].get('consistency_checked')}")
        cr = d['data'].get('consistency_result') or {}
        print(f"  consistency: processed={cr.get('processed')}, score={cr.get('consistency_score')}, action={cr.get('action')}")

print("\n" + "="*70)
print("  全部测试完成")
print("="*70)
