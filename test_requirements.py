import requests
import json

BASE = "http://127.0.0.1:8000/api/v1"

def pp(name, obj):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    if isinstance(obj, dict):
        if 'data' in obj:
            data = obj['data']
            if isinstance(data, dict) and 'items' in data:
                print(f"  Total: {data.get('total')}, Items: {len(data.get('items', []))}")
                for i, it in enumerate(data['items'][:3]):
                    print(f"  [{i+1}] {json.dumps({k:v for k,v in it.items() if k not in ['annotations','sample','assignee','content']}, ensure_ascii=False, default=str)[:200]}")
            else:
                print(f"  {json.dumps(data, ensure_ascii=False, default=str, indent=2)[:600]}")
        else:
            print(f"  {json.dumps(obj, ensure_ascii=False, default=str, indent=2)[:600]}")
    else:
        print(f"  {str(obj)[:400]}")
    print(f"  Code: {obj.get('code') if isinstance(obj, dict) else 'N/A'} | Msg: {obj.get('message', '')[:120] if isinstance(obj, dict) else ''}")


print("=" * 60)
print("  需求验证测试脚本 - AI 数据标注协作后端")
print("=" * 60)

seed = requests.get(f"{BASE}/seed-info").json()
pp("[0] 种子信息", seed)

users_list = seed.get('data', {}).get('accounts', [])
projects_list = seed.get('data', {}).get('demo_projects', [])

def find_user(role_prefix):
    for u in users_list:
        if u['role'].startswith(role_prefix):
            return {'id': u['id'], 'name': u['name'], 'username': u['username']}
    return None

admin = find_user('admin')
ann1 = find_user('anno') or next((u for u in users_list if u['id']==2), None)
ann2 = next((u for u in users_list if u['id']==3), None) or find_user('anno')
qc1 = find_user('qual') or find_user('checker')

p1_id = projects_list[0]['id']
p2_id = projects_list[1]['id']
print(f"  P1(文本)={p1_id}, P2(图片)={p2_id}")


print("\n" + "=" * 60)
print("【需求3】人员统计 - 验证多维度筛选和新指标")
print("=" * 60)

res = requests.get(f"{BASE}/stats/annotators/progress", params={
    "page": 1, "page_size": 20, "project_id": p1_id
}).json()
pp("[3.1] 标注员进度列表（按项目）", res)

res2 = requests.get(f"{BASE}/stats/annotators/progress", params={
    "page": 1, "page_size": 20, "role": "annotator"
}).json()
pp("[3.2] 标注员进度列表（按角色=annotator）", res2)

res3 = requests.get(f"{BASE}/export/projects/{p1_id}/summary").json()
pp("[3.3] 导出汇总集成人员排名指标", res3)


print("\n" + "=" * 60)
print("【需求2】任务权限收紧 - 验证边界校验")
print("=" * 60)

print("  [2.0] 先给两个标注员分别分配任务")
assign1 = requests.post(f"{BASE}/tasks/assign", json={
    "project_id": p1_id,
    "assignee_id": ann1['id'],
    "assignee_type": "annotator",
    "sample_count": 2,
}).json()
pp("[2.0a] 分配任务给标注员1", assign1)

task1_samples = []
task1_id = None
if assign1.get('data'):
    d = assign1['data']
    if isinstance(d, dict):
        if 'task' in d:
            task1_id = d['task']['id']
        elif 'id' in d:
            task1_id = d['id']
        if 'samples' in d:
            task1_samples = [s['id'] for s in d['samples'][:5]]
        elif 'sample_ids' in d:
            task1_samples = d['sample_ids'][:5]
print(f"  task1_id={task1_id}, task1_samples={task1_samples}")

assign2 = requests.post(f"{BASE}/tasks/assign", json={
    "project_id": p1_id,
    "assignee_id": ann2['id'],
    "assignee_type": "annotator",
    "sample_count": 2,
}).json()
pp("[2.0b] 分配任务给标注员2", assign2)

task2_id = None
task2_samples = []
if assign2.get('data'):
    d = assign2['data']
    if isinstance(d, dict):
        if 'task' in d:
            task2_id = d['task']['id']
        elif 'id' in d:
            task2_id = d['id']
        if 'samples' in d:
            task2_samples = [s['id'] for s in d['samples'][:5]]
        elif 'sample_ids' in d:
            task2_samples = d['sample_ids'][:5]
print(f"  task2_id={task2_id}, task2_samples={task2_samples}")

print("  [2.1] 测试：标注员2尝试用标注员1的任务创建标注 -> 应该失败")
if task1_samples and task1_id:
    bad1 = requests.post(f"{BASE}/tasks/{task1_id}/annotations", params={
        "annotator_id": ann2['id']
    }, json={
        "sample_id": task1_samples[0],
        "task_id": task1_id,
        "content": {"sentiment": "positive"},
        "time_spent_seconds": 10,
    }).json()
    pp("[2.1a] 标注员2→任务1 (预期失败 403)", bad1)

print("  [2.2] 测试：标注员1尝试用项目2的样本 -> 应该失败")
p2_samples = requests.get(f"{BASE}/projects/{p2_id}/samples", params={"limit": 1}).json()
p2_sample_ids = []
if p2_samples.get('data'):
    items = p2_samples['data'].get('items', []) if isinstance(p2_samples['data'], dict) else []
    p2_sample_ids = [s['id'] for s in items]
print(f"  P2 samples: {p2_sample_ids}")

if task1_id and p2_sample_ids:
    bad2 = requests.post(f"{BASE}/tasks/{task1_id}/annotations", params={
        "annotator_id": ann1['id']
    }, json={
        "sample_id": p2_sample_ids[0],
        "task_id": task1_id,
        "content": {"sentiment": "positive"},
        "time_spent_seconds": 10,
    }).json()
    pp("[2.2a] P1任务 + P2样本 (预期失败403)", bad2)


print("\n" + "=" * 60)
print("【需求1】冲突自动生成复核任务")
print("=" * 60)

print("  [1.1] 正确标注：标注员1和标注员2给同一样本提交不同答案 -> 触发冲突+自动生成复核任务")

common_sample = None
if task1_samples and task2_samples:
    common_sample = task1_samples[0] if len(task1_samples) > 0 else None
print(f"  共同样本ID: {common_sample}")

if common_sample and task1_id:
    good1 = requests.post(f"{BASE}/tasks/{task1_id}/annotations", params={
        "annotator_id": ann1['id']
    }, json={
        "sample_id": common_sample,
        "task_id": task1_id,
        "content": {"sentiment": "positive", "score": 0.8},
        "time_spent_seconds": 15,
    }).json()
    pp("[1.1a] 标注员1 草稿标注(positive)", good1)
    a1_id = None
    if good1.get('data') and isinstance(good1['data'], dict):
        a1_id = good1['data'].get('id')
    print(f"  a1_id={a1_id}")

    if a1_id:
        sub1 = requests.post(f"{BASE}/tasks/annotations/{a1_id}/submit", params={
            "submitter_id": ann1['id']
        }, json={
            "content": {"sentiment": "positive", "score": 0.8},
            "time_spent_seconds": 15,
        }).json()
        pp("[1.1b] 标注员1 提交标注", sub1)

if task2_id and common_sample:
    good2 = requests.post(f"{BASE}/tasks/{task2_id}/annotations", params={
        "annotator_id": ann2['id']
    }, json={
        "sample_id": common_sample,
        "task_id": task2_id,
        "content": {"sentiment": "negative", "score": 0.9},
        "time_spent_seconds": 12,
    }).json()
    pp("[1.2a] 标注员2 草稿标注(negative)", good2)
    a2_id = None
    if good2.get('data') and isinstance(good2['data'], dict):
        a2_id = good2['data'].get('id')
    print(f"  a2_id={a2_id}")

    if a2_id:
        sub2 = requests.post(f"{BASE}/tasks/annotations/{a2_id}/submit", params={
            "submitter_id": ann2['id']
        }, json={
            "content": {"sentiment": "negative", "score": 0.9},
            "time_spent_seconds": 12,
        }).json()
        pp("[1.2b] 标注员2 提交标注 -> 预期生成冲突+复核任务", sub2)

print("  [1.3] 查看生成的复核任务列表")
rts = requests.get(f"{BASE}/quality/review-tasks", params={
    "project_id": p1_id, "status": "pending", "limit": 10
}).json()
pp("[1.3] 复核任务列表（含样本详情）", rts)

first_rt_id = None
first_rt_sample = None
if rts.get('data') and isinstance(rts['data'], dict):
    items = rts['data'].get('items', [])
    if items:
        first_rt_id = items[0].get('id')
        first_rt_sample = items[0].get('sample_id')
        print(f"  首条复核任务: id={first_rt_id}, sample_id={first_rt_sample}")
        print(f"  含annotation_count: {items[0].get('annotation_count')}")
        print(f"  含sample_content_preview: {bool(items[0].get('sample_content_preview'))}")

print("  [1.4] 提交复核 -> 期望冲突/样本/统计同步更新")
if first_rt_id:
    rev = requests.post(f"{BASE}/quality/review-tasks/{first_rt_id}/submit", json={
        "checker_id": qc1['id'],
        "resolution": {"sentiment": "positive", "score": 0.85},
        "resolution_comment": "positive正确，标注员1答案采纳"
    }).json()
    pp("[1.4] 复核提交结果", rev)

print("  [1.5] 验证样本最终答案已更新")
if first_rt_sample:
    sp = requests.get(f"{BASE}/projects/{p1_id}/samples/{first_rt_sample}").json()
    pp("[1.5] 样本最终答案检查", sp)

print("\n" + "=" * 60)
print("【需求4】批量质检 + 返工闭环一致性")
print("=" * 60)

sq = requests.post(f"{BASE}/quality/sample", json={
    "project_id": p1_id,
    "checker_id": qc1['id'],
    "sample_count": 3,
    "sample_rate": 0.5,
}).json()
pp("[4.1] 抽样生成质检记录", sq)

qc_ids = []
if sq.get('data'):
    qc_list = sq['data'].get('quality_checks', []) if isinstance(sq['data'], dict) else []
    qc_ids = [q['id'] for q in qc_list if isinstance(q, dict)]
print(f"  生成的质检记录ID: {qc_ids[:5]}")

if len(qc_ids) >= 2:
    batch_ids = qc_ids[:2]
    bp = requests.post(
        f"{BASE}/quality/quality-checks/batch",
        params={
            "checker_id": qc1['id'],
            "action": "approve",
            "common_quality_score": 0.9,
            "common_comment": "批量抽检通过",
        },
        json=batch_ids
    ).json()
    pp("[4.2a] 批量通过质检", bp)

br = None
if len(qc_ids) >= 3:
    rw_id = qc_ids[2]
    br = requests.post(
        f"{BASE}/quality/quality-checks/batch",
        params={
            "checker_id": qc1['id'],
            "action": "rework",
            "rework_reason": "标注质量有疑问，需要返工",
        },
        json=[rw_id]
    ).json()
    pp("[4.2b] 批量返工1条", br)

rework_sample_id = None
created_rework_id = None
if br and br.get('data') and isinstance(br['data'], dict):
    rew_ids = br['data'].get('rework_ids_created', [])
    if rew_ids:
        created_rework_id = rew_ids[0]
        det = br['data'].get('details', [])
        for d in det:
            if d.get('rework_id') == created_rework_id:
                break
print(f"  返工记录ID: {created_rework_id}")

print("  [4.3] 完成返工 -> 期望触发重新一致性判断")
if created_rework_id:
    rwc = requests.post(f"{BASE}/quality/reworks/{created_rework_id}/complete").json()
    pp("[4.3] 返工完成 + 一致性重新检查", rwc)
    if rwc.get('data') and isinstance(rwc['data'], dict):
        print(f"  consistency_checked={rwc['data'].get('consistency_checked')}")
        cr = rwc['data'].get('consistency_result')
        if cr:
            print(f"  一致性结果: processed={cr.get('processed')}, "
                  f"score={cr.get('consistency_score')}, "
                  f"is_consistent={cr.get('is_consistent')}, "
                  f"action={cr.get('action')}")

print("\n" + "=" * 60)
print("  需求验证完成")
print("=" * 60)
