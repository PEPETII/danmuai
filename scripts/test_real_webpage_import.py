"""真实网页导入测试：用 gamersky.com 网页验证完整链路。

用法：python scripts/test_real_webpage_import.py

需要：AI 配置已设好（api_endpoint / api_key / model_id）。
"""
import os
import sys
import time

# 确保项目根在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config_store.storage import ConfigStore
from app.knowledge.database import KnowledgeDatabase
from app.knowledge.import_service import ImportOrchestrator
from app.knowledge.repository import KnowledgeRepository

TEST_URL = "https://www.gamersky.com/handbook/202202/1461277.shtml"


def main():
    # 1. 打开真实 knowledge DB
    db_dir = os.path.join(os.environ.get("APPDATA", ""), "DanmuAI")
    db_path = os.path.join(db_dir, "knowledge.db")
    print(f"[1] DB: {db_path}")
    db = KnowledgeDatabase._open_at(db_path)

    # 2. Repository + Orchestrator
    repo = KnowledgeRepository(db)
    orch = ImportOrchestrator(db, repo)

    # 3. 创建/复用知识包
    packages = repo.list_packages()
    pkg = None
    for p in packages:
        if p["name"] == "test_gamersky":
            pkg = p
            break
    if pkg is None:
        pkg = repo.create_package(name="test_gamersky", description="gamersky real import test")
        print(f"[2] Created package: {pkg['public_id']}")
    else:
        print(f"[2] Using existing package: {pkg['public_id']}")

    package_id_row = db.conn.execute(
        "SELECT id FROM knowledge_packages WHERE public_id=?", (pkg["public_id"],)
    ).fetchone()
    package_id = int(package_id_row[0])

    # 4. 创建 source
    source = repo.create_source(
        package_id=package_id,
        source_type="webpage",
        display_name="gamersky handbook",
    )
    source_id = source["id"]
    print(f"[3] Created source: id={source_id}")

    # 5. 加载 AI config（ConfigStore 是 dict-like，直接传实例）
    config_store = ConfigStore()
    config = config_store  # ConfigStore itself is the config dict-like object
    print(f"[4] AI config: endpoint={config_store.get('api_endpoint', '')[:50]} model={config_store.get('model_id', '')}")

    # 6. 提交导入
    print(f"[5] Submitting import: {TEST_URL}")
    job_id = orch.submit_import(
        config=config,
        package_id=package_id,
        source_id=source_id,
        source_type="webpage",
        payload={"source_url": TEST_URL},
        document_kind="game",
        content_kind="auto",
    )
    print(f"[6] Job submitted: {job_id}")

    # 7. 轮询等待完成
    print("[7] Waiting for job to finish...")
    deadline = time.time() + 300  # 5 min timeout
    last_status = None
    while time.time() < deadline:
        job = repo.get_job(job_id)
        if job is None:
            time.sleep(1)
            continue
        status = job["status"]
        if status != last_status:
            print(f"    status={status} stage={job['stage']} "
                  f"processed={job['processed_chunks']}/{job['total_chunks']} "
                  f"items={job['generated_items']} "
                  f"failed_chunks={job['failed_chunks']}")
            last_status = status
        if status in ("completed", "completed_with_errors", "failed", "cancelled"):
            break
        time.sleep(2)

    # 8. 打印最终结果
    job = repo.get_job(job_id)
    print("\n" + "=" * 60)
    print("FINAL RESULT")
    print("=" * 60)
    print(f"  status:          {job['status']}")
    print(f"  stage:           {job['stage']}")
    print(f"  total_chunks:    {job['total_chunks']}")
    print(f"  processed:       {job['processed_chunks']}")
    print(f"  failed_chunks:   {job['failed_chunks']}")
    print(f"  generated_items: {job['generated_items']}")
    print(f"  dedup_items:     {job['deduplicated_items']}")
    print(f"  input_tokens:    {job['input_tokens']}")
    print(f"  output_tokens:   {job['output_tokens']}")
    print(f"  error_message:   {job['error_message'][:200] if job['error_message'] else '(none)'}")

    # 9. 列出入库条目
    items_result = repo.list_items(package_id=package_id)
    print(f"\n  ITEMS IN DB: {items_result['total']}")
    for i, item in enumerate(items_result["items"][:10]):
        print(f"    [{i+1}] kind={item['kind']} title={item['title'][:40]} "
              f"content={item['content'][:60]}")

    # 10. 列出 chunks 诊断
    chunks = repo.list_chunks(source_id)
    print(f"\n  CHUNKS: {len(chunks)}")
    for c in chunks:
        err = c.get("error_message", "") or ""
        print(f"    chunk {c['sequence_no']}: status={c['status']} "
              f"err={err[:100] if err else '(none)'}")

    orch.close()
    db.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
