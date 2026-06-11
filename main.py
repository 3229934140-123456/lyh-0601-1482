import os
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from config import settings
from database import engine, Base, get_db, SessionLocal
import models
import schemas

from routers import projects, tasks, quality, stats, export as export_router


def init_seed_data():
    db = SessionLocal()
    try:
        from models import User, UserRole, Project, ProjectType, ProjectStatus, LabelSpec

        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                username="admin",
                display_name="系统管理员",
                email="admin@example.com",
                role=UserRole.ADMIN,
            )
            db.add(admin)
            db.flush()

        annotator1 = db.query(User).filter(User.username == "annotator01").first()
        if not annotator1:
            annotator1 = User(
                username="annotator01",
                display_name="标注员-张三",
                email="zhangsan@example.com",
                role=UserRole.ANNOTATOR,
            )
            db.add(annotator1)
            db.flush()

        annotator2 = db.query(User).filter(User.username == "annotator02").first()
        if not annotator2:
            annotator2 = User(
                username="annotator02",
                display_name="标注员-李四",
                email="lisi@example.com",
                role=UserRole.ANNOTATOR,
            )
            db.add(annotator2)
            db.flush()

        annotator3 = db.query(User).filter(User.username == "annotator03").first()
        if not annotator3:
            annotator3 = User(
                username="annotator03",
                display_name="标注员-王五",
                email="wangwu@example.com",
                role=UserRole.ANNOTATOR,
            )
            db.add(annotator3)
            db.flush()

        qc1 = db.query(User).filter(User.username == "checker01").first()
        if not qc1:
            qc1 = User(
                username="checker01",
                display_name="质检员-赵六",
                email="zhaoliu@example.com",
                role=UserRole.QUALITY_CHECKER,
            )
            db.add(qc1)
            db.flush()

        db.commit()

        demo_project = db.query(Project).filter(Project.name == "示例-文本情感分类项目").first()
        if not demo_project:
            demo_project = Project(
                name="示例-文本情感分类项目",
                description="这是一个示例文本分类标注项目，用于演示系统功能。标注目标是判断文本的情感倾向：正面、负面、中性。",
                project_type=ProjectType.TEXT,
                status=ProjectStatus.IN_PROGRESS,
                required_annotators=2,
                samples_per_task=10,
                quality_sample_rate=0.2,
                consistency_threshold=0.8,
                lock_timeout_seconds=1800,
                creator_id=admin.id,
            )
            db.add(demo_project)
            db.flush()

            label_specs = [
                LabelSpec(
                    project_id=demo_project.id,
                    name="sentiment",
                    description="文本情感类别",
                    value_type="single_choice",
                    options=[
                        {"value": "positive", "label": "正面", "color": "#52c41a"},
                        {"value": "negative", "label": "负面", "color": "#ff4d4f"},
                        {"value": "neutral", "label": "中性", "color": "#8c8c8c"},
                    ],
                    required=True,
                    sort_order=1,
                ),
                LabelSpec(
                    project_id=demo_project.id,
                    name="confidence",
                    description="标注置信度 (1-5)",
                    value_type="number",
                    required=False,
                    sort_order=2,
                ),
                LabelSpec(
                    project_id=demo_project.id,
                    name="topic_tags",
                    description="主题标签（可多选）",
                    value_type="multi_choice",
                    options=[
                        {"value": "product", "label": "产品"},
                        {"value": "service", "label": "服务"},
                        {"value": "price", "label": "价格"},
                        {"value": "delivery", "label": "物流"},
                        {"value": "other", "label": "其他"},
                    ],
                    required=False,
                    sort_order=3,
                ),
                LabelSpec(
                    project_id=demo_project.id,
                    name="remark",
                    description="备注说明",
                    value_type="text",
                    required=False,
                    sort_order=4,
                ),
            ]
            for spec in label_specs:
                db.add(spec)

            sample_texts = [
                ("这家店的商品质量真的很好，下次还会再来！", "s001"),
                ("物流太慢了，等了整整一周才收到，差评！", "s002"),
                ("价格适中，东西还不错，中规中矩吧。", "s003"),
                ("客服态度非常好，耐心解答了我所有问题。", "s004"),
                ("包装破损了，但商品本身没问题。", "s005"),
                ("性价比超高，比实体店便宜太多了！", "s006"),
                ("产品和描述不符，退货了，不推荐。", "s007"),
                ("发货速度挺快的，隔天就到了，满意。", "s008"),
                ("一般般吧，没什么特别的感觉。", "s009"),
                ("推荐购买，用了一个月感觉很不错！", "s010"),
                ("售后不给力，出了问题找不到人。", "s011"),
                ("外观精美，做工细致，值得入手。", "s012"),
                ("使用说明写得不清楚，折腾半天才弄明白。", "s013"),
                ("整体满意，就是希望能多搞点优惠活动。", "s014"),
                ("完全不符合预期，浪费钱。", "s015"),
            ]

            from models import Sample
            for text, ext_id in sample_texts:
                sample = Sample(
                    project_id=demo_project.id,
                    external_id=ext_id,
                    content=text,
                    sample_metadata={"source": "demo_dataset", "batch": 1},
                )
                db.add(sample)

            image_project = Project(
                name="示例-图片分类标注项目",
                description="这是一个示例图片分类项目。目标是对图片进行场景分类和物体识别。",
                project_type=ProjectType.IMAGE,
                status=ProjectStatus.IN_PROGRESS,
                required_annotators=2,
                samples_per_task=8,
                quality_sample_rate=0.25,
                consistency_threshold=0.8,
                lock_timeout_seconds=1800,
                creator_id=admin.id,
            )
            db.add(image_project)
            db.flush()

            img_labels = [
                LabelSpec(
                    project_id=image_project.id,
                    name="scene_type",
                    description="场景类型",
                    value_type="single_choice",
                    options=[
                        {"value": "indoor", "label": "室内"},
                        {"value": "outdoor", "label": "户外"},
                        {"value": "portrait", "label": "人像"},
                        {"value": "landscape", "label": "风景"},
                        {"value": "product", "label": "产品"},
                    ],
                    required=True,
                    sort_order=1,
                ),
                LabelSpec(
                    project_id=image_project.id,
                    name="image_quality",
                    description="图片质量评分 (1-5)",
                    value_type="number",
                    required=True,
                    sort_order=2,
                ),
            ]
            for spec in img_labels:
                db.add(spec)

            for i in range(1, 13):
                sample = Sample(
                    project_id=image_project.id,
                    external_id=f"img_{i:03d}",
                    content=f"示例图片 {i} 的描述信息",
                    content_url=f"https://example.com/images/sample_{i:03d}.jpg",
                    sample_metadata={"source": "demo_images", "category": "sample"},
                )
                db.add(sample)

            db.commit()
            print("✅ 种子数据初始化完成")

    except Exception as e:
        db.rollback()
        print(f"⚠️  种子数据初始化警告: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 正在启动 AI 数据标注协作服务...")

    Base.metadata.create_all(bind=engine)
    print("✅ 数据库表结构创建完成")

    os.makedirs(settings.EXPORT_DIR, exist_ok=True)

    init_seed_data()

    print(f"📋 服务名称: {settings.APP_NAME}")
    print(f"📦 服务版本: {settings.APP_VERSION}")
    print(f"🔗 API前缀: {settings.API_PREFIX}")
    print(f"🗄️  数据库: {settings.DATABASE_URL}")
    print("✨ 服务启动完成，开始处理请求")
    yield
    print("👋 服务正在关闭...")


app = FastAPI(
    title=settings.APP_NAME,
    description="""
# AI 数据标注协作后端服务

提供完整的数据标注协作管理能力，包括 **项目管理、任务流转、质量复核、人员统计、结果输出** 五大接口组。

## 主要功能

### 项目管理
- 支持文本、图片两种标注项目类型
- 灵活的标签规范定义（单选、多选、文本、数值）
- 样本批量导入与管理

### 任务流转
- 智能任务分配与领取机制
- 任务锁定防止并发冲突
- 多人独立标注 + 一致性自动判断
- 冲突自动检测与待复核任务生成

### 质量复核
- 分层抽样质检（冲突优先抽样）
- 质检结果提交与返工管理
- 冲突人工复核流程
- 完整的返工记录追踪

### 人员统计
- 标注员个人进度与产出统计
- 质量评分与一致性分析
- 项目级整体进度监控
- 活跃用户与任务状态概览

### 结果输出
- 支持 JSON / CSV 格式导出
- 导出任务异步后台执行
- 标注结果汇总与标签分布分析
- 标注员排名与准确率统计
    """,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    contact={
        "name": "AI标注协作平台",
        "url": "https://example.com",
    },
    license_info={
        "name": "MIT License",
    },
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.detail,
            "data": None,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": f"服务器内部错误: {str(exc)}",
            "data": None,
        },
    )


@app.get("/", tags=["系统"])
def root():
    return schemas.ApiResponse(
        message=f"欢迎使用 {settings.APP_NAME} v{settings.APP_VERSION}",
        data={
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "redoc": "/redoc",
            "api_prefix": settings.API_PREFIX,
            "groups": [
                {"name": "项目管理", "prefix": f"{settings.API_PREFIX}/projects"},
                {"name": "任务流转", "prefix": f"{settings.API_PREFIX}/tasks"},
                {"name": "质量复核", "prefix": f"{settings.API_PREFIX}/quality"},
                {"name": "人员统计", "prefix": f"{settings.API_PREFIX}/stats"},
                {"name": "结果输出", "prefix": f"{settings.API_PREFIX}/export"},
            ],
        },
    )


@app.get("/health", tags=["系统"])
def health_check():
    return schemas.ApiResponse(
        message="服务运行正常",
        data={
            "status": "healthy",
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        },
    )


@app.get("/api/v1/seed-info", tags=["系统"])
def get_seed_info():
    return schemas.ApiResponse(
        message="预置的演示账号信息",
        data={
            "note": "以下为系统预置的演示账号，实际部署请删除或修改",
            "accounts": [
                {"username": "admin", "name": "系统管理员", "role": "admin", "id": 1},
                {"username": "annotator01", "name": "标注员-张三", "role": "annotator", "id": 2},
                {"username": "annotator02", "name": "标注员-李四", "role": "annotator", "id": 3},
                {"username": "annotator03", "name": "标注员-王五", "role": "annotator", "id": 4},
                {"username": "checker01", "name": "质检员-赵六", "role": "quality_checker", "id": 5},
            ],
            "demo_projects": [
                {"id": 1, "name": "示例-文本情感分类项目", "type": "text"},
                {"id": 2, "name": "示例-图片分类标注项目", "type": "image"},
            ],
            "suggested_workflow": [
                "1. 调用 POST /api/v1/tasks/claim 领取任务 (annotator_id=2)",
                "2. 调用 POST /api/v1/tasks/{{task_id}}/annotations 创建标注草稿",
                "3. 调用 POST /api/v1/tasks/annotations/{{ann_id}}/submit 提交标注",
                "4. 多个标注员提交后，系统自动进行一致性判断",
                "5. 质检员调用 POST /api/v1/quality/sample 抽样质检",
                "6. 调用 POST /api/v1/quality/checks/{{qc_id}}/submit 提交质检结果",
                "7. 调用 GET /api/v1/export/projects/{{project_id}}/summary 查看结果汇总",
                "8. 调用 POST /api/v1/export/jobs 创建导出任务",
            ],
        },
    )


app.include_router(projects.router, prefix=settings.API_PREFIX)
app.include_router(tasks.router, prefix=settings.API_PREFIX)
app.include_router(quality.router, prefix=settings.API_PREFIX)
app.include_router(stats.router, prefix=settings.API_PREFIX)
app.include_router(export_router.router, prefix=settings.API_PREFIX)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
