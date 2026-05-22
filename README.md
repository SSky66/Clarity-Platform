# Clarity: 澄澈系统

> 工业视觉缺陷检测模型的链上可信审计与履约验证平台

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Vue 3](https://img.shields.io/badge/Vue-3-green.svg)](https://vuejs.org/)

## 项目简介

Clarity 面向制造企业，解决工业视觉模型交付中的核心信任问题：**制造商的数据不能出域，供应商的模型需要被验证**。

系统采用**链上存证、链下计算**的混合架构，在不暴露原始数据与模型权重的前提下，对供应商交付的工业缺陷检测模型进行自动化能力审计，生成不可篡改的技术报告，并基于智能合约完成分阶段资金托管与履约结算。

## 核心特性

- **隐私保护视觉模型审计**  
  制造商测试集加密存储于 IPFS，仅 Hash 上链；审计在本地隔离沙箱中完成，计算结束后立即销毁环境，原始数据零泄露。

- **可解释性算法验证**  
  引入 D-RISE 等可解释性算法，验证模型准确率的同时通过注意力热力图审查模型是否基于真实缺陷纹理做出判断，识别潜在的捷径学习与后门攻击。

- **双阶段履约协议**  
  链上审计定标 → 现场部署复测。智能合约根据两阶段结果执行分级结算，区分"技术不达标"与"恶意欺诈"，保护诚实供应商的同时严惩作弊行为。

- **轻量模型推理包标准**  
  定义标准化的 `supplier_package.zip` 结构（模型权重 + 推理接口 + 依赖清单），供应商无需上传过重的 Docker 镜像即可完成模型验证。

## 系统架构

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  供应商端    │◄────►│  Clarity    │◄────►│  制造商端    │
│ (上传模型包) │      │   平台       │      │ (上传测试集) │
└─────────────┘      └──────┬──────┘      └─────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
         ┌─────────┐   ┌─────────┐    ┌─────────┐
         │ 智能合约 │   │ 审计节点 │   │  IPFS   │
         │(资金存证)│   │(链下计算)│   │(加密数据)│
         └─────────┘   └─────────┘    └─────────┘
```

## 快速开始

### 1. 环境要求
- Node.js 18+
- Python 3.10+
- MySQL 5.7
- FISCO BCOS 节点

### 2. 本地启动

```bash
# 1. 克隆仓库
git clone https://github.com/SSky66/Clarity-Platform.git
cd Clarity-Platform

# 2. 启动后端
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# 3. 启动前端（新终端）
cd frontend
npm install
npm run dev

# 4. 启动本地审计节点（可选）
cd audit
cp .env.example .env
python audit_worker.py
```

## 技术选型

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3, Vite, Tailwind CSS |
| 后端 | FastAPI, SQLAlchemy, PyMySQL |
| 存储 | MySQL, IPFS |
| 审计 | PyTorch, OpenCV |
| 合约 | FISCO BCOS, Solidity |

## 项目状态

系统处于开发阶段，核心审计流程与合约框架已基本跑通，但部分模块（如多审计节点调度、TEE 可信执行环境）仍在迭代中。

对于代码/逻辑里有问题的地方，欢迎直接提 Issue，或者 Fork 过去进行修改。

## 许可证

项目采用 MIT 许可证，具体参考 [MIT](LICENSE) 文件。

---

**注意**：Clarity 是一个模型能力验证与履约监管平台，而非模型交易市场。供应商上传的模型推理包作为**技术能力基线证明**，用于链上定标与后续现场验收对照。
