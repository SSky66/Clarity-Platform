"""
文件上传模块测试
覆盖: upload-dataset, upload-model
"""

import pytest
from fastapi.testclient import TestClient
from io import BytesIO

from models import UserRole, TaskStatus


class TestUploadDataset:
    """POST /api/tasks/{id}/upload-dataset"""

    def test_upload_dataset_success(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """制造商正常上传数据集"""
        task = create_task(status=TaskStatus.UPLOADING, manufacturer_id=manufacturer.id)
        file_content = b"mock dataset content"
        resp = client.post(
            f"/api/tasks/{task.id}/upload-dataset",
            headers=mfr_headers,
            files={"file": ("test_dataset.zip", BytesIO(file_content), "application/zip")}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "dataset"
        assert data["ipfs_hash"].startswith("ipfs://mock/")
        assert data["filename"] == "test_dataset.zip"

    def test_upload_dataset_by_supplier(self, client: TestClient, create_task, supplier, sup_headers):
        """供应商上传数据集应403"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=supplier.id)
        resp = client.post(
            f"/api/tasks/{task.id}/upload-dataset",
            headers=sup_headers,
            files={"file": ("test.zip", BytesIO(b"test"), "application/zip")}
        )
        assert resp.status_code == 403

    def test_upload_dataset_wrong_status(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """非UPLOADING状态上传"""
        task = create_task(status=TaskStatus.PENDING, manufacturer_id=manufacturer.id)
        resp = client.post(
            f"/api/tasks/{task.id}/upload-dataset",
            headers=mfr_headers,
            files={"file": ("test.zip", BytesIO(b"test"), "application/zip")}
        )
        assert resp.status_code == 400

    def test_upload_dataset_not_owner(self, client: TestClient, make_user, create_task, mfr_headers):
        """非项目所有者上传"""
        # 创建另一个制造商
        other_mfr = make_user(account="other_mfr", role=UserRole.MANUFACTURER)
        # 用另一个制造商创建项目
        task = create_task(status=TaskStatus.UPLOADING, manufacturer_id=other_mfr.id)
        # 当前用户(manufacturer)不是项目所有者
        resp = client.post(
            f"/api/tasks/{task.id}/upload-dataset",
            headers=mfr_headers,
            files={"file": ("test.zip", BytesIO(b"test"), "application/zip")}
        )
        assert resp.status_code == 404


class TestUploadModel:
    """POST /api/tasks/{id}/upload-model"""

    def test_upload_model_success(self, client: TestClient, create_task, supplier, sup_headers):
        """供应商正常上传模型"""
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=supplier.id)
        file_content = b"mock model content"
        resp = client.post(
            f"/api/tasks/{task.id}/upload-model",
            headers=sup_headers,
            files={"file": ("model.pt", BytesIO(file_content), "application/octet-stream")}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "model"
        assert data["ipfs_hash"].startswith("ipfs://mock/")
        assert data["filename"] == "model.pt"

    def test_upload_model_by_manufacturer(self, client: TestClient, create_task, manufacturer, mfr_headers):
        """制造商上传模型应403"""
        task = create_task(status=TaskStatus.UPLOADING, manufacturer_id=manufacturer.id)
        resp = client.post(
            f"/api/tasks/{task.id}/upload-model",
            headers=mfr_headers,
            files={"file": ("model.pt", BytesIO(b"test"), "application/octet-stream")}
        )
        assert resp.status_code == 403

    def test_upload_model_wrong_status(self, client: TestClient, create_task, supplier, sup_headers):
        """非UPLOADING状态上传"""
        task = create_task(status=TaskStatus.PENDING, supplier_id=supplier.id)
        resp = client.post(
            f"/api/tasks/{task.id}/upload-model",
            headers=sup_headers,
            files={"file": ("model.pt", BytesIO(b"test"), "application/octet-stream")}
        )
        assert resp.status_code == 400

    def test_upload_model_not_owner(self, client: TestClient, make_user, create_task, sup_headers):
        """非项目供应商上传"""
        # 创建另一个供应商
        other_sup = make_user(account="other_sup", role=UserRole.SUPPLIER)
        # 用另一个供应商创建项目
        task = create_task(status=TaskStatus.UPLOADING, supplier_id=other_sup.id)
        # 当前用户(supplier)不是项目供应商
        resp = client.post(
            f"/api/tasks/{task.id}/upload-model",
            headers=sup_headers,
            files={"file": ("model.pt", BytesIO(b"test"), "application/octet-stream")}
        )
        assert resp.status_code == 404
