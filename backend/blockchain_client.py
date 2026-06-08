"""
WeBASE-Front HTTP客户端与智能合约交互封装
通过普通requests调用WeBASE-Front的REST API，无需证书

部署流程：
  1. 部署6个合约到链上
  2. 通过/api/admin/contract-config保存合约地址
  3. 调用setTrustedContract设置可信合约
  4. 调用setAuthorizedAuditor授权审计节点
  5. 系统开始通过合约交互（而非直接改数据库）
"""
import os
import time
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
import requests

WEBASE_FRONT_URL = os.getenv("WEBASE_FRONT_URL", "http://127.0.0.1:5002").rstrip("/")
GROUP_ID = os.getenv("WEBASE_GROUP_ID", "group0")

# 缓存
_cache = {
    "block_height": None,
    "active_nodes": None,
    "timestamp": 0
}
CACHE_TTL = 5  # 缓存5秒


def _url(path: str) -> str:
    return f"{WEBASE_FRONT_URL}{path}"


# 基础链上查询

def _fetch_block_number() -> Optional[int]:
    """获取区块高度"""
    try:
        resp = requests.get(
            _url(f"/WeBASE-Front/{GROUP_ID}/web3/blockNumber"),
            timeout=3
        )
        text = resp.text.strip()
        if resp.status_code == 200 and text.isdigit():
            return int(text)
        return None
    except Exception:
        return None


def _fetch_node_count() -> Optional[int]:
    """获取共识节点数量"""
    try:
        resp = requests.get(
            _url(f"/WeBASE-Front/{GROUP_ID}/web3/groupPeers"),
            timeout=3
        )
        data = resp.json()
        if isinstance(data, list):
            return len(data)
        return None
    except Exception:
        return None


def get_chain_stats() -> Dict[str, Any]:
    """
    获取链上统计信息
    并行请求blockNumber与groupPeers，结果缓存5秒
    """
    global _cache

    now = time.time()
    if now - _cache["timestamp"] < CACHE_TTL and _cache["block_height"] is not None:
        return {
            "block_height": _cache["block_height"],
            "total_transactions": None,
            "active_nodes": _cache["active_nodes"],
            "connected": True,
            "error": None
        }

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_block = executor.submit(_fetch_block_number)
        future_nodes = executor.submit(_fetch_node_count)
        block_height = future_block.result()
        active_nodes = future_nodes.result()

    if block_height is None:
        return {
            "block_height": None,
            "total_transactions": None,
            "active_nodes": None,
            "connected": False,
            "error": "无法连接 WeBASE-Front"
        }

    _cache = {
        "block_height": block_height,
        "active_nodes": active_nodes,
        "timestamp": now
    }

    return {
        "block_height": block_height,
        "total_transactions": None,
        "active_nodes": active_nodes,
        "connected": True,
        "error": None
    }


# 钱包管理

def create_wallet(sign_user_id: str, app_id: str = "clarity") -> Optional[Dict[str, Any]]:
    """
    通过WeBASE-Front创建链上钱包地址
    返回: {address, publicKey, signUserId, appId}
    """
    try:
        resp = requests.get(
            _url("/WeBASE-Front/privateKey"),
            params={
                "groupId": GROUP_ID,
                "appId": app_id,
                "signUserId": sign_user_id,
                "description": "Clarity user wallet"
            },
            timeout=5
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("address"):
            return {
                "address": data["address"],
                "public_key": data.get("publicKey"),
                "sign_user_id": data.get("signUserId"),
                "app_id": data.get("appId")
            }
        return None
    except Exception as e:
        print(f"创建钱包失败: {e}")
        return None


def get_wallet_list() -> List[Dict[str, Any]]:
    """获取WeBASE-Front中已创建的钱包列表（本地密钥库）"""
    try:
        resp = requests.get(
            _url("/WeBASE-Front/privateKey/localKeyStores"),
            timeout=5
        )
        data = resp.json()
        if resp.status_code == 200 and isinstance(data, dict) and "data" in data:
            return data["data"]
        return []
    except Exception as e:
        print(f"获取钱包列表失败: {e}")
        return []


def check_wallet_exists(sign_user_id: str, app_id: str = "clarity") -> Dict[str, Any]:
    """
    检查指定signUserId的钱包是否存在于WeBASE-Front
    
    WeBASE-Front行为:
    1.钱包不存在: 返回200 + 创建新钱包
    2.钱包已存在: 返回422 + code=303001 "already exists"
    
    返回: {exists: bool, can_sign: bool, error: Optional[str]}
    """
    try:
        resp = requests.get(
            _url("/WeBASE-Front/privateKey"),
            params={
                "groupId": GROUP_ID,
                "appId": app_id,
                "signUserId": sign_user_id,
                "returnPrivateKey": "false"
            },
            timeout=5
        )
        data = resp.json()
        
        if resp.status_code == 200 and data.get("address"):
            # 钱包刚创建或已存在且返回了地址
            return {
                "exists": True,
                "can_sign": True,
                "address": data.get("address"),
                "error": None
            }
        elif data.get("code") == 303001:
            # 钱包已存在（WeBASE-Front 返回已存在错误，但这是正常状态）
            return {
                "exists": True,
                "can_sign": True,
                "address": None,  # 地址需要从数据库获取
                "error": None
            }
        else:
            return {
                "exists": False,
                "can_sign": False,
                "address": None,
                "error": data.get("errorMessage") or str(data)
            }
    except Exception as e:
        return {"exists": False, "can_sign": False, "address": None, "error": str(e)}


# 合约ABI缓存

# Identity.sol身份合约核心接口
IDENTITY_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_contract", "type": "address"},
            {"name": "_status", "type": "bool"}
        ],
        "name": "setTrustedContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_user", "type": "address"},
            {"name": "_reason", "type": "string"}
        ],
        "name": "blacklist",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_user", "type": "address"}
        ],
        "name": "whitelist",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_user", "type": "address"}],
        "name": "getRole",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_user", "type": "address"}],
        "name": "getReputation",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_user", "type": "address"}],
        "name": "isValidUser",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_user", "type": "address"}],
        "name": "isBlacklisted",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_user", "type": "address"}],
        "name": "getStakeRatio",
        "outputs": [{"name": "ratio", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_user", "type": "address"}
        ],
        "name": "getProfile",
        "outputs": [
            {"name": "role", "type": "uint8"},
            {"name": "reputation", "type": "uint256"},
            {"name": "successCount", "type": "uint256"},
            {"name": "slashCount", "type": "uint256"},
            {"name": "registerTime", "type": "uint256"},
            {"name": "active", "type": "bool"},
            {"name": "claimCount", "type": "uint256"}
        ],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_supplier", "type": "address"},
            {"name": "_manufacturer", "type": "address"},
            {"name": "_isSuccess", "type": "bool"},
            {"name": "_supplierSlash", "type": "bool"},
            {"name": "_manufacturerSlash", "type": "bool"}
        ],
        "name": "settleProjectReputation",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_user", "type": "address"}
        ],
        "name": "updateClaimCount",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
]

# Audit.sol审计合约核心接口
AUDIT_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_auditor", "type": "address"},
            {"name": "_status", "type": "bool"}
        ],
        "name": "setAuthorizedAuditor",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_fund", "type": "address"}
        ],
        "name": "setFundContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_evidence", "type": "address"}
        ],
        "name": "setEvidenceContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_tradeId", "type": "bytes32"}],
        "name": "getVerdict",
        "outputs": [
            {"name": "", "type": "uint8"},
            {"name": "", "type": "string"}
        ],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
]

# Fund.sol资金合约核心接口
FUND_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_identity", "type": "address"}
        ],
        "name": "setIdentityContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_evidence", "type": "address"}
        ],
        "name": "setEvidenceContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_audit", "type": "address"}
        ],
        "name": "setAuditContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_appeal", "type": "address"}
        ],
        "name": "setAppealContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_association", "type": "address"}
        ],
        "name": "setAssociationAddress",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_tradeId", "type": "bytes32"}],
        "name": "getTradeStatus",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_user", "type": "address"}],
        "name": "getStakeRatio",
        "outputs": [{"name": "ratioBp", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
]

# Dispute.sol申诉合约核心接口
DISPUTE_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_fund", "type": "address"}
        ],
        "name": "setFundContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_identity", "type": "address"}
        ],
        "name": "setIdentityContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_evidence", "type": "address"}
        ],
        "name": "setEvidenceContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
]

# Evidence.sol存证合约核心接口
EVIDENCE_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_fund", "type": "address"}
        ],
        "name": "setFundContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_audit", "type": "address"}
        ],
        "name": "setAuditContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_settlement", "type": "address"}
        ],
        "name": "setSettlementContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_dispute", "type": "address"}
        ],
        "name": "setDisputeContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
]

# Settlement.sol履约合约核心接口
SETTLEMENT_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_fund", "type": "address"}
        ],
        "name": "setFundContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_evidence", "type": "address"}
        ],
        "name": "setEvidenceContract",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
]

# 合约ABI映射表
CONTRACT_ABIS = {
    "identity": IDENTITY_ABI,
    "fund": FUND_ABI,
    "audit": AUDIT_ABI,
    "dispute": DISPUTE_ABI,
    "evidence": EVIDENCE_ABI,
    "settlement": SETTLEMENT_ABI,
}


# 核心：合约调用封装

def call_contract_method(
    contract_address: str,
    contract_name: str,
    method_name: str,
    params: List[Any],
    from_address: str,
    sign_user_id: Optional[str] = None,
    is_view: bool = False
) -> Dict[str, Any]:
    """
    调用智能合约方法（通过WeBASE-Front）

    Args:
        contract_address: 合约部署地址
        contract_name: 合约名称（identity/fund/audit/dispute/evidence/settlement）
        method_name: 合约方法名
        params: 方法参数列表
        from_address: 调用者地址
        sign_user_id: WeBASE-Front 签名用户ID（交易调用时需要）
        is_view: 是否为 view/pure 方法（只读，不上链）

    Returns:
        {success: bool, data: Any, tx_hash: Optional[str], error: Optional[str]}
    """
    abi = CONTRACT_ABIS.get(contract_name.lower())
    if not abi:
        return {"success": False, "error": f"未知合约: {contract_name}", "data": None, "tx_hash": None}

    # 找到对应的方法ABI
    func_abi = None
    for item in abi:
        if item.get("name") == method_name:
            func_abi = item
            break

    if not func_abi:
        return {"success": False, "error": f"合约 {contract_name} 中未找到方法 {method_name}", "data": None, "tx_hash": None}

    try:
        if is_view or func_abi.get("stateMutability") in ["view", "pure"]:
            # 调用view/pure方法（不上链）
            return _call_contract_view(
                contract_address, func_abi, params, from_address
            )
        else:
            # 发送交易（上链）
            if not sign_user_id:
                return {"success": False, "error": "发送交易需要 sign_user_id", "data": None, "tx_hash": None}
            return _send_contract_transaction(
                contract_address, func_abi, params, from_address, sign_user_id
            )
    except Exception as e:
        return {"success": False, "error": str(e), "data": None, "tx_hash": None}


def _call_contract_view(
    contract_address: str,
    func_abi: Dict[str, Any],
    params: List[Any],
    from_address: str
) -> Dict[str, Any]:
    """调用合约view/pure方法（WeBASE-Front/trans/handle的查询模式）"""
    # WeBASE-Front使用/trans/handle接口，对于view方法可以直接调用
    # 实际上WeBASE-Front的/trans/handle支持所有方法，view方法不会上链
    payload = {
        "groupId": GROUP_ID,
        "contractAddress": contract_address,
        "contractAbi": [func_abi],
        "funcName": func_abi["name"],
        "funcParam": params,
        "user": from_address,
    }

    try:
        resp = requests.post(
            _url("/WeBASE-Front/trans/handle"),
            json=payload,
            timeout=10
        )
        data = resp.json()

        if resp.status_code == 200:
            # view方法返回结果直接在data中
            return {
                "success": True,
                "data": data,
                "tx_hash": None,
                "error": None
            }
        else:
            return {
                "success": False,
                "error": f"WeBASE-Front 错误: {data}",
                "data": None,
                "tx_hash": None
            }
    except Exception as e:
        return {"success": False, "error": f"请求异常: {e}", "data": None, "tx_hash": None}


def _send_contract_transaction(
    contract_address: str,
    func_abi: Dict[str, Any],
    params: List[Any],
    from_address: str,
    sign_user_id: str
) -> Dict[str, Any]:
    """发送合约交易（上链）"""
    payload = {
        "groupId": GROUP_ID,
        "contractAddress": contract_address,
        "contractAbi": [func_abi],
        "funcName": func_abi["name"],
        "funcParam": params,
        "user": from_address,
        "useAes": False,
        "signUserId": sign_user_id,
    }

    try:
        resp = requests.post(
            _url("/WeBASE-Front/trans/handle"),
            json=payload,
            timeout=30
        )
        data = resp.json()

        if resp.status_code == 200 and data.get("status") == "0x0":
            # 交易成功
            return {
                "success": True,
                "data": data,
                "tx_hash": data.get("transactionHash"),
                "error": None
            }
        elif resp.status_code == 200:
            # 交易已发送但可能失败
            return {
                "success": data.get("status") == "0x0",
                "data": data,
                "tx_hash": data.get("transactionHash"),
                "error": data.get("message") or "交易状态异常"
            }
        else:
            return {
                "success": False,
                "error": f"WeBASE-Front 错误: {data}",
                "data": None,
                "tx_hash": None
            }
    except Exception as e:
        return {"success": False, "error": f"请求异常: {e}", "data": None, "tx_hash": None}


# 便捷封装：部署配置专用

def deploy_contract(
    contract_name: str,
    abi: List[Dict],
    bytecode: str,
    constructor_params: List[Any],
    from_address: str,
    sign_user_id: str
) -> Dict[str, Any]:
    """
    部署智能合约

    Args:
        contract_name: 合约名称
        abi: 完整ABI
        bytecode: 合约字节码（hex string，0x开头）
        constructor_params: 构造函数参数列表
        from_address: 部署者地址
        sign_user_id: 签名用户ID

    Returns:
        {success: bool, contract_address: Optional[str], tx_hash: Optional[str], error: Optional[str]}
    """
    payload = {
        "groupId": GROUP_ID,
        "contractName": contract_name,
        "abiInfo": abi,
        "bytecodeBin": bytecode,
        "funcParam": constructor_params,
        "user": from_address,
        "signUserId": sign_user_id,
    }

    try:
        resp = requests.post(
            _url("/WeBASE-Front/contract/deploy"),
            json=payload,
            timeout=60
        )
        data = resp.json()

        if resp.status_code == 200 and data.get("contractAddress"):
            return {
                "success": True,
                "contract_address": data["contractAddress"],
                "tx_hash": data.get("transactionHash"),
                "error": None
            }
        else:
            return {
                "success": False,
                "contract_address": None,
                "tx_hash": data.get("transactionHash"),
                "error": data.get("message") or str(data)
            }
    except Exception as e:
        return {"success": False, "contract_address": None, "tx_hash": None, "error": str(e)}


def set_trusted_contract(
    identity_contract: str,
    target_contract: str,
    status: bool,
    admin_address: str,
    admin_sign_user_id: str
) -> Dict[str, Any]:
    """
    设置可信合约，对应Identity.setTrustedContract
    部署后必须调用，让Fund/Audit/Dispute等合约能调用Identity
    """
    return call_contract_method(
        contract_address=identity_contract,
        contract_name="identity",
        method_name="setTrustedContract",
        params=[target_contract, status],
        from_address=admin_address,
        sign_user_id=admin_sign_user_id,
        is_view=False
    )


def set_authorized_auditor(
    audit_contract: str,
    auditor_address: str,
    status: bool,
    admin_address: str,
    admin_sign_user_id: str
) -> Dict[str, Any]:
    """
    授权审计节点，对应Audit.setAuthorizedAuditor
    """
    return call_contract_method(
        contract_address=audit_contract,
        contract_name="audit",
        method_name="setAuthorizedAuditor",
        params=[auditor_address, status],
        from_address=admin_address,
        sign_user_id=admin_sign_user_id,
        is_view=False
    )


def set_contract_address(
    caller_contract: str,
    caller_name: str,
    method_name: str,
    target_address: str,
    admin_address: str,
    admin_sign_user_id: str
) -> Dict[str, Any]:
    """
    通用：设置合约间地址关联
    例如: Fund.setIdentityContract, Audit.setFundContract等
    """
    return call_contract_method(
        contract_address=caller_contract,
        contract_name=caller_name,
        method_name=method_name,
        params=[target_address],
        from_address=admin_address,
        sign_user_id=admin_sign_user_id,
        is_view=False
    )


# 便捷封装：业务调用

def query_contract_stake_ratio(
    fund_contract: str,
    user_address: str
) -> Dict[str, Any]:
    """
    查询链上动态质押比例，对应Fund.getStakeRatio
    用于校验后端计算是否正确
    """
    return call_contract_method(
        contract_address=fund_contract,
        contract_name="fund",
        method_name="getStakeRatio",
        params=[user_address],
        from_address=user_address,
        is_view=True
    )


def query_identity_stake_ratio(
    identity_contract: str,
    user_address: str
) -> Dict[str, Any]:
    """
    查询链上动态质押比例，对应Identity.getStakeRatio
    """
    return call_contract_method(
        contract_address=identity_contract,
        contract_name="identity",
        method_name="getStakeRatio",
        params=[user_address],
        from_address=user_address,
        is_view=True
    )


def query_trade_status(
    fund_contract: str,
    trade_id_hex: str,
    from_address: str
) -> Dict[str, Any]:
    """
    查询链上项目状态，对应Fund.getTradeStatus
    trade_id_hex: bytes32的hex字符串（0x+64位）
    """
    return call_contract_method(
        contract_address=fund_contract,
        contract_name="fund",
        method_name="getTradeStatus",
        params=[trade_id_hex],
        from_address=from_address,
        is_view=True
    )


def settle_reputation_onchain(
    identity_contract: str,
    supplier_address: str,
    manufacturer_address: str,
    is_success: bool,
    supplier_slash: bool,
    manufacturer_slash: bool,
    caller_address: str,
    caller_sign_user_id: str
) -> Dict[str, Any]:
    """
    链上信誉结算，对应Identity.settleProjectReputation
    需要调用者是trustedContract或owner或super_admin或arbitrator
    """
    return call_contract_method(
        contract_address=identity_contract,
        contract_name="identity",
        method_name="settleProjectReputation",
        params=[
            supplier_address,
            manufacturer_address,
            is_success,
            supplier_slash,
            manufacturer_slash
        ],
        from_address=caller_address,
        sign_user_id=caller_sign_user_id,
        is_view=False
    )


def update_claim_count_onchain(
    identity_contract: str,
    manufacturer_address: str,
    caller_address: str,
    caller_sign_user_id: str
) -> Dict[str, Any]:
    """
    链上更新制造商出险计数，对应Identity.updateClaimCount
    """
    return call_contract_method(
        contract_address=identity_contract,
        contract_name="identity",
        method_name="updateClaimCount",
        params=[manufacturer_address],
        from_address=caller_address,
        sign_user_id=caller_sign_user_id,
        is_view=False
    )


# 链上事件监听（轮询方式）

def get_transaction_receipt(tx_hash: str) -> Optional[Dict[str, Any]]:
    """
    获取交易回执
    用于确认交易是否成功，以及解析事件日志
    """
    try:
        resp = requests.get(
            _url(f"/WeBASE-Front/{GROUP_ID}/web3/transactionReceipt/{tx_hash}"),
            timeout=5
        )
        data = resp.json()
        if resp.status_code == 200:
            return data
        return None
    except Exception as e:
        print(f"获取交易回执失败: {e}")
        return None


def poll_transaction_status(
    tx_hash: str,
    max_attempts: int = 30,
    interval_seconds: int = 2
) -> Dict[str, Any]:
    """
    轮询交易状态，直到确认或超时

    Returns:
        {success: bool, receipt: Optional[dict], error: Optional[str]}
    """
    for i in range(max_attempts):
        receipt = get_transaction_receipt(tx_hash)
        if receipt:
            status = receipt.get("status", "0x0")
            if status == "0x0":
                return {"success": True, "receipt": receipt, "error": None}
            else:
                return {"success": False, "receipt": receipt, "error": f"交易失败，status={status}"}
        time.sleep(interval_seconds)

    return {"success": False, "receipt": None, "error": "轮询超时，交易尚未确认"}
