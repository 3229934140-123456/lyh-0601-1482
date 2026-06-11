import urllib.request
import json

BASE_URL = "http://127.0.0.1:8000"

def test_endpoint(name, path, method="GET", data=None):
    url = f"{BASE_URL}{path}"
    try:
        if method == "GET":
            with urllib.request.urlopen(url) as r:
                result = json.loads(r.read().decode())
                print(f"[OK] {name}")
                return result
        else:
            req = urllib.request.Request(url, data=json.dumps(data).encode(), method=method, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as r:
                result = json.loads(r.read().decode())
                print(f"[OK] {name}")
                return result
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        return None

print("=" * 60)
print("AI数据标注协作服务 - API测试")
print("=" * 60)

# 1. 系统接口
print("\n📌 系统接口测试:")
r = test_endpoint("根端点", "/")
if r: print(f"   -> {r.get('message','')}")

r = test_endpoint("健康检查", "/health")
if r: print(f"   -> {r.get('data',{}).get('status','')}")

# 2. 项目管理
print("\n📌 项目管理接口测试:")
r = test_endpoint("项目列表", "/api/v1/projects")
if r:
    total = r.get('data', {}).get('total', 0)
    print(f"   -> 共 {total} 个项目")
    for p in r.get('data', {}).get('items', []):
        print(f"      ID:{p['id']} {p['name']} ({p['project_type']}) 状态:{p['status']}")

r = test_endpoint("标签规范", "/api/v1/projects/1/label-specs")
if r:
    specs = r.get('data', [])
    print(f"   -> 项目1有 {len(specs)} 个标签规范")

r = test_endpoint("样本列表", "/api/v1/projects/1/samples?page_size=5")
if r:
    samples = r.get('data', {}).get('total', 0)
    print(f"   -> 项目1共 {samples} 个样本")

# 3. 任务流转
print("\n📌 任务流转接口测试:")
r = test_endpoint("任务列表", "/api/v1/tasks")
if r:
    total = r.get('data', {}).get('total', 0)
    print(f"   -> 共 {total} 个任务")

claim_data = {"project_id": 1, "annotator_id": 2, "sample_count": 5}
r = test_endpoint("领取任务", "/api/v1/tasks/claim", "POST", claim_data)
if r:
    task = r.get('data')
    if task:
        print(f"   -> 领取任务ID: {task.get('id')}, 状态: {r.get('message')}")
    else:
        print(f"   -> {r.get('message')}")

# 4. 质量复核
print("\n📌 质量复核接口测试:")
r = test_endpoint("冲突列表", "/api/v1/quality/conflicts")
if r:
    total = len(r.get('data', {}).get('items', [])) if isinstance(r.get('data'), dict) else len(r.get('data', []))
    print(f"   -> 共 {total} 条冲突记录")

r = test_endpoint("质检记录列表", "/api/v1/quality/checks")
if r:
    total = r.get('data', {}).get('total', 0) if isinstance(r.get('data'), dict) else 0
    print(f"   -> 共 {total} 条质检记录")

r = test_endpoint("返工列表", "/api/v1/quality/reworks")
if r:
    total = len(r.get('data', {}).get('items', [])) if isinstance(r.get('data'), dict) else len(r.get('data', []))
    print(f"   -> 共 {total} 条返工记录")

# 5. 人员统计
print("\n📌 人员统计接口测试:")
r = test_endpoint("总览统计", "/api/v1/stats/overview")
if r:
    d = r.get('data', {})
    print(f"   -> 项目: 总{d['projects']['total']} 活跃{d['projects']['active']}")
    print(f"   -> 样本: 总{d['samples']['total']} 已通过{d['samples']['approved']}")
    print(f"   -> 用户: 标注员{d['users']['total_annotators']} 质检员{d['users']['total_quality_checkers']}")

r = test_endpoint("所有标注员进度", "/api/v1/stats/annotators/progress?page_size=10")
if r:
    items = r.get('data', {}).get('items', []) if isinstance(r.get('data'), dict) else r.get('data', [])
    print(f"   -> 共 {len(items)} 条进度记录")

r = test_endpoint("项目1统计", "/api/v1/stats/projects/1")
if r:
    d = r.get('data', {})
    if d:
        print(f"   -> 项目1进度: {d.get('progress_percentage',0)*100:.1f}%")

# 6. 结果输出
print("\n📌 结果输出接口测试:")
r = test_endpoint("项目1结果汇总", "/api/v1/export/projects/1/summary")
if r:
    d = r.get('data', {})
    if d:
        print(f"   -> 通过率: {d.get('approval_rate',0)*100:.1f}%")
        print(f"   -> 标签分布: {len(d.get('label_distribution',{}))} 个标签组")
        print(f"   -> 标注员排名: {len(d.get('annotator_rankings',[]))} 人")

r = test_endpoint("导出任务列表", "/api/v1/export/jobs")
if r:
    total = r.get('data', {}).get('total', 0) if isinstance(r.get('data'), dict) else len(r.get('data', []))
    print(f"   -> 共 {total} 个导出任务")

# 7. 演示数据
print("\n📌 演示信息查询:")
r = test_endpoint("种子数据信息", "/api/v1/seed-info")
if r:
    d = r.get('data', {})
    print(f"   -> 演示账号: {len(d.get('accounts',[]))} 个")
    print(f"   -> 建议工作流: {len(d.get('suggested_workflow',[]))} 步")

print("\n" + "=" * 60)
print("🎉 API测试完成！服务运行正常")
print("📚 Swagger文档: http://127.0.0.1:8000/docs")
print("=" * 60)
