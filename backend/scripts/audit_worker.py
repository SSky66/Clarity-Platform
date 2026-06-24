"""
审计工作器 (Audit Worker)
========================
离线执行模型审计任务，从数据库读取待审计项目，
在隔离环境中运行模型推理，生成审计指标和可视化报告。

原文件: backend/script_audit.py
现位置: backend/scripts/audit_worker.py

运行方式:
    cd backend && python scripts/audit_worker.py --task-id <任务ID>
"""

from ultralytics import YOLO
from pathlib import Path
import numpy as np
import random
import json
from datetime import datetime
import uuid
import hashlib
import cv2
import torch
from PIL import Image
import torch.nn as nn
from tqdm import tqdm
import time
import argparse
from concurrent.futures import ThreadPoolExecutor
import functools
import sys
import gc


def set_deterministic_seed(seed=114514):
    """固定全局随机种子"""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def audit_stage1_accuracy(model_or_path, data_yaml):
    """
    Stage 1: 准确度审计
    返回: 原始指标与漏杀率/过杀率
    """
    print("[Stage 1] Accuracy Audit...")

    if isinstance(model_or_path, YOLO):
        model = model_or_path
        print("  Using pre-loaded model")
    else:
        model = YOLO(model_or_path)

    results = model.val(
        data=data_yaml,
        split='val',
        verbose=False,
        batch=64,
        half=True,
        workers=0,
        save=False,
        plots=False
    )

    map50 = results.box.map50
    f1 = np.mean(results.box.f1) if len(results.box.f1) > 0 else 0.0
    precision = np.mean(results.box.p) if hasattr(results.box, 'p') and len(results.box.p) > 0 else 0.0
    recall = np.mean(results.box.r) if hasattr(results.box, 'r') and len(results.box.r) > 0 else 0.0

    # 漏杀率：FN/(TP+FN) = 1 - Recall
    miss_rate = 1.0 - recall if recall > 0 else 0.0

    # 过杀率：FP/(TP+FP) = 1 - Precision
    overkill_rate = 1.0 - precision if precision > 0 else 0.0

    print(f"  mAP50: {map50:.4f}")
    print(f"  F1:    {f1:.4f}")
    print(f"  Precision: {precision:.4f}")
    print(f"  Recall:    {recall:.4f}")
    print(f"  [硬性指标] Miss Rate (漏杀率/漏检): {miss_rate:.4f} ({miss_rate:.2%}) ← 1-Recall (坏板流出风险)")
    print(
        f"  [硬性指标] Overkill Rate (过杀率/误杀): {overkill_rate:.4f} ({overkill_rate:.2%}) ← 1-Precision (良率虚低风险)")

    return {
        'metrics': {
            'mAP50': float(map50),
            'F1_score': float(f1),
            'precision': float(precision),
            'recall': float(recall),
            'miss_rate': float(miss_rate),
            'overkill_rate': float(overkill_rate),
        },
        'raw_predictions_hash': None,
        'note': 'Hard metrics: miss_rate=1-Recall(漏杀), overkill_rate=1-Precision(过杀)'
    }


def compute_iou(box1, box2):
    """计算两个框的IoU，格式[x1,y1,x2,y2]"""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0


def dilate_bbox(bbox, img_w, img_h, factor=1.5):
    """
    膨胀GT框，统一使用factor=1.5
    """
    x1, y1, x2, y2 = bbox
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    w = (x2 - x1) * factor
    h = (y2 - y1) * factor

    new_x1 = max(0, cx - w / 2)
    new_y1 = max(0, cy - h / 2)
    new_x2 = min(img_w, cx + w / 2)
    new_y2 = min(img_h, cy + h / 2)
    return [new_x1, new_y1, new_x2, new_y2]


def get_tp_samples(model, val_images_dir, labels_dir, conf_thresh=0.25, iou_thresh=0.5, max_samples=None):
    """获取True Positive样本，保留原始GT框"""
    val_images = list(Path(val_images_dir).glob('*.jpg'))
    tp_samples = []

    sample_indices = np.linspace(0, len(val_images) - 1, min(100, len(val_images)), dtype=int)
    selected_images = [val_images[i] for i in sample_indices]
    print(f"  Scanning {len(selected_images)} images for TP collection...")

    for img_path in selected_images:
        if max_samples is not None and len(tp_samples) >= max_samples:
            break
        img = cv2.imread(str(img_path))
        if img is None: continue
        h, w = img.shape[:2]

        label_path = Path(labels_dir) / f"{img_path.stem}.txt"
        if not label_path.exists(): continue

        gts = []
        with open(label_path, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 5:
                    cls_raw, cx, cy, bw, bh = map(float, parts)
                    x1, y1 = (cx - bw / 2) * w, (cy - bh / 2) * h
                    x2, y2 = (cx + bw / 2) * w, (cy + bh / 2) * h
                    gts.append([x1, y1, x2, y2, int(cls_raw)])

        if not gts: continue

        results = model(img_path, conf=conf_thresh, verbose=False)
        preds = results[0].boxes
        if len(preds) == 0: continue

        pred_boxes = preds.xyxy.cpu().numpy()
        pred_classes = preds.cls.cpu().numpy().astype(int)
        pred_confs = preds.conf.cpu().numpy()

        for gt in gts:
            gt_box = gt[:4]
            gt_cls = gt[4]
            best_iou = 0
            best_pred_cls = -1

            for pred_box, pred_cls in zip(pred_boxes, pred_classes):
                iou = compute_iou(pred_box, gt_box)
                if iou > best_iou:
                    best_iou = iou
                    best_pred_cls = int(pred_cls)

            # DeepPCB官方阈值
            if best_iou >= 0.33:
                # 直接传入原始的 gt_box
                tp_samples.append((str(img_path), gt_box, h, w, best_pred_cls, gt_cls))
                if max_samples is not None and len(tp_samples) >= max_samples:
                    break

    print(f"  Total TP collected: {len(tp_samples)}")
    return tp_samples


def generate_random_masks(image_shape, num_masks=1000, mask_sizes=[32, 64, 96, 128, 160]):
    """生成 Boolean 掩码，随机采样"""
    h, w = image_shape[:2]
    masks = np.ones((num_masks, h, w, 1), dtype=bool)

    for i in range(num_masks):
        mask_size = mask_sizes[i % len(mask_sizes)]
        x = np.random.randint(0, w - mask_size + 1)
        y = np.random.randint(0, h - mask_size + 1)
        masks[i, y:y + mask_size, x:x + mask_size, 0] = False

    return masks


def batch_iou(boxes1, box2):
    """向量化IoU：计算N个框与1个目标框的IoU"""
    if len(boxes1) == 0:
        return np.array([])

    b1_x1, b1_y1, b1_x2, b1_y2 = boxes1[:, 0], boxes1[:, 1], boxes1[:, 2], boxes1[:, 3]
    b2_x1, b2_y1, b2_x2, b2_y2 = box2[0], box2[1], box2[2], box2[3]

    inter_x1 = np.maximum(b1_x1, b2_x1)
    inter_y1 = np.maximum(b1_y1, b2_y1)
    inter_x2 = np.minimum(b1_x2, b2_x2)
    inter_y2 = np.minimum(b1_y2, b2_y2)

    inter_area = np.maximum(0, inter_x2 - inter_x1) * np.maximum(0, inter_y2 - inter_y1)
    b1_area = (b1_x2 - b1_x1) * (b1_y2 - b1_y1)
    b2_area = (b2_x2 - b2_x1) * (b2_y2 - b2_y1)
    union_area = b1_area + b2_area - inter_area

    ious = np.zeros_like(inter_area)
    valid = union_area > 0
    ious[valid] = inter_area[valid] / union_area[valid]

    return ious


def flexible_match_score_vectorized(pred_boxes, pred_confs, pred_classes, target_box, target_cls, iou_threshold=0.33):
    """向量化匹配打分"""
    if len(pred_boxes) == 0:
        return 0.01

    # 使用矩阵运算，一次性计算所有IoU
    ious = batch_iou(pred_boxes, target_box)

    # 第一轮：严格匹配同类与空间
    class_match = pred_classes == target_cls
    spatial_match = ious > iou_threshold
    strict_mask = class_match & spatial_match

    if np.any(strict_mask):
        scores = ious[strict_mask] * pred_confs[strict_mask]
        return np.max(scores)

    # 第二轮：类别不同但位置对（IoU>0.5），降权50%
    loose_match = ious > 0.5
    if np.any(loose_match):
        scores = ious[loose_match] * pred_confs[loose_match] * 0.5
        return np.max(scores)

    # 第三轮：附近有框但其他条件不满足
    if np.any(spatial_match):
        return 0.0

    return 0.01


# 该函数为 AI 辅助生成：Kimi K2.5, 2026-04-13
def batch_ts_inference(ts_model, batch_tensor, conf_thresh=0.05):
    """
    批量推理，直接接收GPU Tensor，并在GPU上完成置信度过滤
    """
    with torch.no_grad():
        # TorchScript前向 (输入已经是GPU Tensor)
        outputs = ts_model(batch_tensor)

        if isinstance(outputs, (tuple, list)):
            outputs = outputs[0]

        # YOLOv8输出: [B, 84, 8400] -> [B, 8400, 84] (在GPU上转置)
        outputs = outputs.transpose(1, 2)

        boxes_cxcywh = outputs[..., :4]  # [B, 8400, 4]
        class_scores = outputs[..., 4:]  # [B, 8400, 80]

        # 直接在GPU上算最大值
        confs, classes = torch.max(class_scores, dim=-1)

        results = []
        for j in range(batch_tensor.shape[0]):
            # 在GPU上生成过滤掩码
            mask = confs[j] > conf_thresh

            b_boxes = boxes_cxcywh[j][mask]
            b_confs = confs[j][mask]
            b_classes = classes[j][mask]

            if len(b_boxes) == 0:
                results.append({'boxes': np.array([]), 'confs': np.array([]), 'classes': np.array([])})
                continue

            b_boxes = b_boxes.cpu().numpy()

            x1 = b_boxes[:, 0] - b_boxes[:, 2] / 2
            y1 = b_boxes[:, 1] - b_boxes[:, 3] / 2
            x2 = b_boxes[:, 0] + b_boxes[:, 2] / 2
            y2 = b_boxes[:, 1] + b_boxes[:, 3] / 2
            b_boxes_xyxy = np.stack([x1, y1, x2, y2], axis=1)

            results.append({
                'boxes': b_boxes_xyxy,
                'confs': b_confs.cpu().numpy(),
                'classes': b_classes.cpu().numpy().astype(int)
            })

    return results


# 该函数为AI辅助生成：Kimi K2.5, 2026-04-13
def drise_attribution_multi(ts_model, device, image_path, gt_boxes_list, all_gts_in_image=None,
                            num_masks=1000, batch_size=100, debug=False, model_name='unknown',
                            preloaded_img=None):
    """
    遮罩合成100%在显存(VRAM)内完成
    """
    img = preloaded_img if preloaded_img is not None else cv2.imread(str(image_path))
    if img is None:
        return [None] * len(gt_boxes_list)

    orig_h, orig_w = img.shape[:2]
    num_targets = len(gt_boxes_list)
    if num_targets == 0:
        return []

    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_640 = cv2.resize(img_rgb, (640, 640)).astype(np.float32) / 255.0
    scale_x, scale_y = 640 / orig_w, 640 / orig_h

    gt_boxes_640 = []
    for gt_bbox, gt_cls in gt_boxes_list:
        x1, y1, x2, y2 = gt_bbox
        gt_boxes_640.append(([x1 * scale_x, y1 * scale_y, x2 * scale_x, y2 * scale_y], gt_cls))

    # 1. 把原图直接放入显存，变成[3, 640, 640]的Tensor
    img_tensor = torch.from_numpy(img_640).to(device).permute(2, 0, 1)
    mean_color_tensor = img_tensor.mean(dim=(1, 2)).view(3, 1, 1)

    # 基准推理(直接传给Tensor)
    base_input = img_tensor.unsqueeze(0)
    base_results = batch_ts_inference(ts_model, base_input, conf_thresh=0.01)[0]

    base_scores = []
    for gt_bbox_640, gt_cls in gt_boxes_640:
        score = flexible_match_score_vectorized(
            base_results['boxes'], base_results['confs'], base_results['classes'],
            gt_bbox_640, gt_cls
        )
        base_scores.append(score)

    # 2. 生成Boolean掩码，并一次性全部压入显存
    masks_bool = generate_random_masks((640, 640), num_masks=num_masks)
    # 转为GPU上的[1000, 1, 640, 640]极小内存bool Tensor
    masks_tensor = torch.from_numpy(masks_bool).to(device).squeeze(-1).unsqueeze(1)

    heatmaps_640 = [np.zeros((640, 640), dtype=np.float32) for _ in range(num_targets)]
    delta_sums = [0.0 for _ in range(num_targets)]

    # 3. 流式处理
    for start in range(0, num_masks, batch_size):
        end = min(start + batch_size, num_masks)
        actual = end - start

        # 直接在显存里切片
        batch_masks_tensor = masks_tensor[start:end]

        # 直接在GPU里完成图片遮挡合成
        masked_batch_tensor = torch.where(batch_masks_tensor, img_tensor, mean_color_tensor)

        # TorchScript GPU推理(直接传Tensor)
        batch_results = batch_ts_inference(ts_model, masked_batch_tensor, conf_thresh=0.05)

        # 累加热力图
        for t in range(num_targets):
            if base_scores[t] < 0.01:
                continue
            for j in range(actual):
                global_idx = start + j
                pred = batch_results[j]

                score = flexible_match_score_vectorized(
                    pred['boxes'], pred['confs'], pred['classes'],
                    gt_boxes_640[t][0], gt_boxes_640[t][1]
                )

                delta = max(0, base_scores[t] - score)
                if delta > 0:
                    heatmaps_640[t] += delta * (~masks_bool[global_idx, :, :, 0])
                    delta_sums[t] += delta

    # 4. 计算最终指标
    results_list = []
    for t in range(num_targets):
        if base_scores[t] < 0.01:
            results_list.append({
                'heatmap': None, 'concentration_ratio': 0.0, 'D_in': 0.0,
                'D_out': 0.0, 'base_score': 0.0, 'note': 'Low base score'
            })
            continue

        hm_640 = heatmaps_640[t]
        if delta_sums[t] > 0:
            hm_640 /= delta_sums[t]

        heatmap_orig = cv2.resize(hm_640, (orig_w, orig_h))
        noise_floor = heatmap_orig.max() * 0.15
        clean_heatmap = np.where(heatmap_orig > noise_floor, heatmap_orig, 0.0)

        dilated_gt = dilate_bbox(gt_boxes_list[t][0], orig_w, orig_h, factor=1.5)
        x1, y1, x2, y2 = map(int, dilated_gt)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(orig_w, x2), min(orig_h, y2)

        defect_mask = np.zeros((orig_h, orig_w), dtype=np.float32)
        defect_mask[y1:y2, x1:x2] = 1.0
        bg_mask = 1.0 - defect_mask

        D_in = np.sum(clean_heatmap * defect_mask) / np.sum(defect_mask) if np.sum(defect_mask) > 0 else 0
        D_out = np.sum(clean_heatmap * bg_mask) / np.sum(bg_mask) if np.sum(bg_mask) > 0 else 0
        ratio = D_in / (D_in + D_out) if (D_in + D_out) > 0 else 0.0

        results_list.append({
            'heatmap': heatmap_orig,
            'concentration_ratio': float(ratio),
            'D_in': float(D_in), 'D_out': float(D_out),
            'base_score': float(base_scores[t])
        })

    return results_list


def audit_stage2_drise_multi(ts_model, device, tp_samples, labels_dir, num_masks=1000, batch_size=100,
                             model_name='Unknown'):
    """
    Stage 2: 注意力审计
    返回: 注意力密度比 D_in/D_out
    """
    if not tp_samples:
        return {
            'metrics': {
                'concentration_ratio': 0.0,
                'D_in': 0.0,
                'D_out': 0.0,
                'sample_count': 0
            },
            'visualization_paths': [],
            'note': 'No TP samples provided'
        }

    print(f"[Stage 2] D-RISE Multi-Target Attention Audit...")

    from collections import defaultdict
    image_to_targets = defaultdict(list)
    for sample in tp_samples:
        img_path, gt_bbox, img_h, img_w, pred_cls, gt_cls = sample
        image_to_targets[img_path].append((gt_bbox, pred_cls, gt_cls))

    all_concentrations, all_D_in, all_D_out = [], [], []
    visualization_paths = []  # 记录生成的图片路径，供PDF生成使用

    save_base_dir = Path('audit_visualizations') / model_name
    save_base_dir.mkdir(parents=True, exist_ok=True)

    for img_idx, (img_path, targets) in enumerate(tqdm(list(image_to_targets.items()), desc="Auditing images")):
        try:
            gt_boxes_list = [(t[0], t[1]) for t in targets]
            img = cv2.imread(str(img_path))
            if img is None:
                continue

            # 获取全图所有GT框（用于可视化区分TP/FN）
            all_gts = []
            label_path = Path(labels_dir) / f"{Path(img_path).stem}.txt"
            if label_path.exists():
                with open(label_path, 'r') as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 5:
                            cls_raw, cx, cy, bw, bh = map(float, parts)
                            h, w = img.shape[:2]
                            x1, y1 = (cx - bw / 2) * w, (cy - bh / 2) * h
                            x2, y2 = (cx + bw / 2) * w, (cy + bh / 2) * h
                            all_gts.append([x1, y1, x2, y2])

            # 区分TP和FN
            tp_original_boxes = []
            fn_original_boxes = []
            target_boxes = [t[0] for t in targets]

            for gt in all_gts:
                is_tp = any(
                    abs(gt[0] - t_box[0]) < 2 and abs(gt[1] - t_box[1]) < 2
                    for t_box in target_boxes
                )
                if is_tp:
                    tp_original_boxes.append(gt)
                else:
                    fn_original_boxes.append(gt)

            # 执行D-RISE计算
            results = drise_attribution_multi(
                ts_model, device, img_path, gt_boxes_list,
                all_gts_in_image=None, num_masks=num_masks, batch_size=batch_size,
                preloaded_img=img
            )

            # 生成可视化并记录路径
            for t, r in enumerate(results):
                if r and r.get('heatmap') is not None:
                    hm = r['heatmap']
                    hm_norm = (hm - hm.min()) / (hm.max() - hm.min() + 1e-8)
                    hm_color = cv2.applyColorMap(np.uint8(255 * hm_norm), cv2.COLORMAP_JET)
                    overlay = cv2.addWeighted(img, 0.5, hm_color, 0.5, 0)

                    # 绘制FN(红色)
                    for fn_box in fn_original_boxes:
                        fx1, fy1, fx2, fy2 = map(int, fn_box)
                        cv2.rectangle(overlay, (fx1, fy1), (fx2, fy2), (0, 0, 255), 2)
                        cv2.putText(overlay, "FN", (fx1, max(fy1 - 5, 10)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

                    # 绘制TP(黄色)
                    for tp_box in tp_original_boxes:
                        tx1, ty1, tx2, ty2 = map(int, tp_box)
                        cv2.rectangle(overlay, (tx1, ty1), (tx2, ty2), (0, 255, 255), 2)
                        cv2.putText(overlay, "TP", (tx1, max(ty1 - 5, 10)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

                    # 当前焦点框(绿色)
                    curr_box = gt_boxes_list[t][0]
                    cx1, cy1, cx2, cy2 = map(int, curr_box)
                    cv2.rectangle(overlay, (cx1, cy1), (cx2, cy2), (0, 255, 0), 3)
                    ratio = r.get('concentration_ratio', 0.0)
                    cv2.putText(overlay, f"Ratio: {ratio:.1%}", (cx1, max(cy1 - 10, 20)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                    base_name = f"{Path(img_path).stem}_defect_{t}"
                    heatmap_path = save_base_dir / f"{base_name}_heatmap.jpg"
                    overlay_path = save_base_dir / f"{base_name}_overlay.jpg"

                    cv2.imwrite(str(heatmap_path), hm_color)
                    cv2.imwrite(str(overlay_path), overlay)

                    # 记录路径供PDF生成使用
                    visualization_paths.append({
                        'type': 'attention_heatmap',
                        'path': str(heatmap_path),
                        'concentration_ratio': float(ratio),
                        'defect_id': t
                    })
                    visualization_paths.append({
                        'type': 'attention_overlay',
                        'path': str(overlay_path),
                        'concentration_ratio': float(ratio),
                        'defect_id': t
                    })

            # 收集指标
            for r in results:
                if r and r['concentration_ratio'] > 0:
                    all_concentrations.append(r['concentration_ratio'])
                    all_D_in.append(r['D_in'])
                    all_D_out.append(r['D_out'])

        except Exception as e:
            print(f"  Error processing {img_path}: {e}")
            continue

    # 计算平均值，但不判定
    mean_concentration = np.mean(all_concentrations) if all_concentrations else 0.0
    mean_D_in = np.mean(all_D_in) if all_D_in else 0.0
    mean_D_out = np.mean(all_D_out) if all_D_out else 0.0

    print(f"\n  Mean Concentration Ratio: {mean_concentration:.2%}")
    print(f"  Mean D_in: {mean_D_in:.6f}")
    print(f"  Mean D_out: {mean_D_out:.6f}")

    # 返回纯指标与可视化证据路径，无passed/status字段
    return {
        'metrics': {
            'concentration_ratio': float(mean_concentration),  # 合约用>= 0.40判定
            'D_in': float(mean_D_in),
            'D_out': float(mean_D_out),
            'sample_count': len(all_concentrations)
        },
        'visualization_paths': visualization_paths,
        'note': 'Raw metrics only, no verdict applied'
    }


def audit_stage3_confidence(model_or_path, val_images_dir, defect_free_dir, labels_dir,
                            conf_work=0.8, conf_base=0.25, sample_count=100, model_name='Unknown'):
    """
    Stage 3: 置信度审计
    """
    print("[Stage 3] Confidence Distribution Audit...")
    print(f"  Base Threshold (for Avg): {conf_base}")
    print(f"  High Threshold (for Arrogance): {conf_work}")

    if isinstance(model_or_path, YOLO):
        model = model_or_path
        print("  Using pre-loaded model")
    else:
        model = YOLO(model_or_path)

    val_images = list(Path(val_images_dir).glob('*.jpg'))

    original_count = len(val_images)
    if len(val_images) > sample_count:
        val_images = random.sample(val_images, sample_count)
        print(f"  Sampling {sample_count}/{original_count} images")
    else:
        print(f"  Using all {original_count} images")

    total_images = len(val_images)

    total_fp_base = 0  # 置信度>=conf_base(0.2)的所有误检
    high_conf_fp = 0  # 置信度>=conf_work(0.8)的高置信度误检

    # 分布统计，用于报告展示
    fp_distribution = {
        '0.25_0.5': 0,  # 低置信度（0.2-0.5）
        '0.5_0.8': 0,  # 中置信度（0.5-0.8）
        '0.8_1.0': 0  # 高置信度（>=0.8）
    }

    save_dir = Path('audit_visualizations') / model_name / 'stage3_fp_evidence'
    save_dir.mkdir(parents=True, exist_ok=True)
    evidence_paths = []
    MAX_EVIDENCE = 5

    for val_img_path in tqdm(val_images, desc="Stage 3"):
        stem = val_img_path.stem

        # 找到成对的无缺陷图（DeepPCB 命名规则）
        temp_candidates = list(Path(defect_free_dir).glob(f'{stem}_temp.jpg'))
        if not temp_candidates:
            if '_temp' in stem:
                stem_clean = stem.replace('_temp', '')
                temp_candidates = list(Path(defect_free_dir).glob(f'{stem_clean}.jpg'))
            else:
                temp_candidates = list(Path(defect_free_dir).glob(f'*{stem}*.jpg'))

        if not temp_candidates:
            continue

        temp_img_path = temp_candidates[0]

        # 读取图像
        defective_img = cv2.imread(str(val_img_path))
        clean_template = cv2.imread(str(temp_img_path))
        if defective_img is None or clean_template is None:
            continue

        h_def, w_def = defective_img.shape[:2]

        results = model.predict(str(temp_img_path), conf=conf_base, verbose=False)

        fps_for_drawing = []
        for r in results:
            for box in r.boxes:
                conf = box.conf.item()

                # 统计基础阈值下的总误检（用于Avg）
                total_fp_base += 1

                # 分类统计（用于置信度偏差计算和分布展示）
                if conf >= conf_work:  # >= 0.8
                    high_conf_fp += 1
                    fp_distribution['0.8_1.0'] += 1
                elif conf >= 0.5:
                    fp_distribution['0.5_0.8'] += 1
                else:
                    fp_distribution['0.25_0.5'] += 1

                # 记录用于可视化
                x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                fps_for_drawing.append({'box': [x1, y1, x2, y2], 'conf': conf})

        # 保存证据图，优先保存包含高置信度误检的样本
        has_high_conf_fp = any(fp['conf'] >= conf_work for fp in fps_for_drawing)
        if has_high_conf_fp and len(evidence_paths) < MAX_EVIDENCE:

            # 图1：带灰色GT框的有缺陷原图
            img_defective_gt = defective_img.copy()
            label_path = Path(labels_dir) / f"{stem}.txt"
            if label_path.exists():
                with open(label_path, 'r') as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 5:
                            _, cx, cy, bw, bh = map(float, parts)
                            gx1 = int((cx - bw / 2) * w_def)
                            gy1 = int((cy - bh / 2) * h_def)
                            gx2 = int((cx + bw / 2) * w_def)
                            gy2 = int((cy + bh / 2) * h_def)
                            cv2.rectangle(img_defective_gt, (gx1, gy1), (gx2, gy2), (128, 128, 128), 2)
                            cv2.putText(img_defective_gt, "GT", (gx1, max(gy1 - 5, 10)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1)

            path_1 = save_dir / f"{stem}_01_defective_with_GT.jpg"
            cv2.imwrite(str(path_1), img_defective_gt)

            # 图2：纯净无缺陷模板
            path_2 = save_dir / f"{stem}_02_clean_template.jpg"
            cv2.imwrite(str(path_2), clean_template)

            # 图3：无缺陷图上的FP误检（红色标记高置信度）
            img_fp = clean_template.copy()
            for fp in fps_for_drawing:
                fx1, fy1, fx2, fy2 = fp['box']
                conf = fp['conf']
                color = (0, 0, 255) if conf >= conf_work else (0, 165, 255)
                cv2.rectangle(img_fp, (fx1, fy1), (fx2, fy2), color, 2)
                cv2.putText(img_fp, f"FP:{conf:.2f}", (fx1, max(fy1 - 5, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            path_3 = save_dir / f"{stem}_03_template_with_FP.jpg"
            cv2.imwrite(str(path_3), img_fp)

            evidence_paths.append({
                'stem': stem,
                'pair_type': 'deeppcb_paired',
                'defective_with_gt': str(path_1),
                'clean_template': str(path_2),
                'template_with_fp': str(path_3),
                'fp_count': len(fps_for_drawing),
                'high_conf_fp_count': sum(1 for fp in fps_for_drawing if fp['conf'] >= conf_work)
            })

    # Avg：平均每图的总误检数（基于conf_base=0.2）
    avg_fp_total = total_fp_base / total_images if total_images > 0 else 0.0

    # 置信度偏差：高置信度误检占总误检的比例
    arrogance_ratio = high_conf_fp / total_fp_base if total_fp_base > 0 else 0.0

    print(f"  Total FP (≥{conf_base}): {total_fp_base}")
    print(f"  High Conf FP (≥{conf_work}): {high_conf_fp}")
    print(f"  [修正] Avg (总误检率): {avg_fp_total:.4f}")
    print(f"  [保持] Arrogance Ratio: {arrogance_ratio:.2%}")

    return {
        'metrics': {
            'avg_fp_total': float(avg_fp_total),
            'arrogance_ratio': float(arrogance_ratio),
            'total_fp_base': int(total_fp_base),
            'high_conf_fp': int(high_conf_fp),
            'total_images': int(total_images),
            'fp_distribution': fp_distribution
        },
        'evidence_paths': evidence_paths,
        'sampled': original_count > sample_count,
        'note': f'Avg based on conf≥{conf_base}, Arrogance based on conf≥{conf_work}/{conf_base}'
    }


def calculate_model_hash(model_path):
    """计算模型文件SHA256"""
    sha256_hash = hashlib.sha256()
    with open(model_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def full_audit(model_name, model_path, data_yaml, val_images_dir, defect_free_dir, labels_dir):
    """
    完整审计流程
    输出: 结构化报告数据，供链上合约或上层应用使用
    """
    print(f"\n{'=' * 60}")
    print(f"Auditing: {model_name}")
    print(f"{'=' * 60}")

    report = {
        'model_metadata': {
            'name': model_name,
            'model_hash': calculate_model_hash(model_path),
            'audit_timestamp': datetime.now().isoformat(),
            'audit_id': str(uuid.uuid4())
        },
        'stage_metrics': {},
        'visualization_summary': {
            'attention_maps': [],
            'confidence_evidence': []
        }
    }

    # Stage 1: 准确度
    model = YOLO(model_path, task='detect')
    s1 = audit_stage1_accuracy(model, data_yaml)
    report['stage_metrics']['stage1_accuracy'] = s1

    # Stage 2: 注意力（需要TorchScript）
    model = YOLO(model_path, task='detect')  # 重新加载释放内存
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")

    try:
        ts_model = torch.jit.load(model_path).to(device)
        ts_model.eval()
        print("  TorchScript loaded on GPU successfully")
    except Exception as e:
        print(f"  Failed to load TorchScript: {e}")
        # 抛出异常而不是返回不完整字典，确保 main() 能捕获并 exit(1)
        raise RuntimeError(f"Failed to load TorchScript model: {e}")

    all_tp_samples = get_tp_samples(model, val_images_dir, labels_dir, max_samples=None)

    # 分组并采样
    from collections import defaultdict
    samples_by_image = defaultdict(list)
    for sample in all_tp_samples:
        samples_by_image[sample[0]].append(sample)

    # 限制审计样本数，避免过长，保留1张图的所有缺陷
    selected_image_paths = random.sample(list(samples_by_image.keys()), min(1, len(samples_by_image)))
    selected_tp = []
    for img_path in selected_image_paths:
        selected_tp.extend(samples_by_image[img_path])

    print(f"  Selected {len(selected_image_paths)} images ({len(selected_tp)} defects) for D-RISE")

    s2 = audit_stage2_drise_multi(
        ts_model, device, selected_tp, labels_dir,
        num_masks=1000, batch_size=100,
        model_name=model_name
    )
    report['stage_metrics']['stage2_attention'] = s2
    report['visualization_summary']['attention_maps'] = s2.get('visualization_paths', [])

    # Stage 3: 置信度
    s3 = audit_stage3_confidence(
        model,
        val_images_dir,
        defect_free_dir,
        labels_dir=labels_dir,
        sample_count=100,
        model_name=model_name
    )
    report['stage_metrics']['stage3_confidence'] = s3
    report['visualization_summary']['confidence_evidence'] = s3.get('evidence_paths', [])

    s1_metrics = s1['metrics']
    s2_metrics = s2['metrics']
    s3_metrics = s3['metrics']

    report['metrics_for_contract'] = {
        'mAP50_10k': int(s1_metrics['mAP50'] * 10000),
        'F1_score_10k': int(s1_metrics['F1_score'] * 10000),
        'miss_rate_10k': int(s1_metrics['miss_rate'] * 10000),
        'overkill_rate_10k': int(s1_metrics['overkill_rate'] * 10000),
        'attention_ratio_10k': int(s2_metrics['concentration_ratio'] * 10000),
        'defect_energy_Din': int(s2_metrics['D_in'] * 1000000),
        'bg_energy_Dout': int(s2_metrics['D_out'] * 1000000),
        'avg_fp_total_10k': int(s3_metrics['avg_fp_total'] * 10000),
        'arrogance_ratio_10k': int(s3_metrics['arrogance_ratio'] * 10000),
        'total_fp_base': s3_metrics['total_fp_base'],
        'sample_count': s2_metrics['sample_count']
    }

    return report


def generate_json_report(all_reports, output_file="full_audit_report.json"):
    """
    生成标准JSON报告，包含链上合约所需的格式化数据
    不包含任何判定结果，只包含计算指标和证据哈希
    """

    def convert_to_native(obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, (np.integer, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: convert_to_native(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_to_native(i) for i in obj]
        return obj

    consolidated = {
        'project': 'Clarity_Industrial_AI_Audit',
        'audit_time': datetime.now().isoformat(),
        'audit_node_version': 'v2.0-no-verdict',
        'reports': [convert_to_native(report) for report in all_reports]
    }

    # 为每个报告添加合约友好的数值格式（_10k表示法）
    for report in consolidated['reports']:
        s1 = report['stage_metrics']['stage1_accuracy']['metrics']
        s2 = report['stage_metrics']['stage2_attention']['metrics']
        s3 = report['stage_metrics']['stage3_confidence']['metrics']

        # 转换为uint256友好的整数格式，保留4位小数精度
        report['metrics_for_contract'] = {
            'mAP50_10k': int(s1['mAP50'] * 10000),
            'F1_score_10k': int(s1['F1_score'] * 10000),
            'miss_rate_10k': int(s1.get('miss_rate', 0) * 10000),
            'overkill_rate_10k': int(s1.get('overkill_rate', 0) * 10000),
            'attention_ratio_10k': int(s2['concentration_ratio'] * 10000),
            'defect_energy_Din': int(s2['D_in'] * 1000000),
            'bg_energy_Dout': int(s2['D_out'] * 1000000),
            'avg_fp_total_10k': int(s3['avg_fp_total'] * 10000),
            'arrogance_ratio_10k': int(s3['arrogance_ratio'] * 10000),
            'total_fp_base': s3['total_fp_base'],
            'sample_count': s2['sample_count']
        }

        # 添加可视化证据的IPFS占位
        report['evidence_summary'] = {
            'attention_visualization_count': len(report['visualization_summary']['attention_maps']),
            'confidence_evidence_count': len(report['visualization_summary']['confidence_evidence']),
            'evidence_local_paths': {
                'attention': [v['path'] for v in report['visualization_summary']['attention_maps']],
                'confidence': [e['template_with_fp'] for e in report['visualization_summary']['confidence_evidence']]
            }
        }

    # 计算报告整体哈希，用于链上存证
    report_str = json.dumps(consolidated, sort_keys=True, ensure_ascii=False)
    consolidated['report_hash'] = hashlib.sha256(report_str.encode()).hexdigest()

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(consolidated, f, ensure_ascii=False, indent=2)

    print(f"\nFull report saved: {output_file}")
    print(f"Report Hash: {consolidated['report_hash']}")

    return consolidated


def main():
    parser = argparse.ArgumentParser(description='Clarity Model Audit - Single Mode')
    parser.add_argument('--model', '-m', type=str, required=True,
                        help='Path to single TorchScript model (e.g., best.torchscript)')
    parser.add_argument('--model-name', '-n', type=str, default=None,
                        help='Model display name (default: auto from filename)')
    parser.add_argument('--data-yaml', type=str,
                        default='E:/Clarity_Project/DeepPCB.yaml',
                        help='Path to data.yaml')
    parser.add_argument('--val-images', type=str,
                        default='E:/Clarity_Project/DeepPCB_YOLO/images/val',
                        help='Validation images directory')
    parser.add_argument('--defect-free', type=str,
                        default='E:/Clarity_Project/DeepPCB_YOLO/defect_free',
                        help='Defect-free images directory')
    parser.add_argument('--labels', type=str,
                        default='E:/Clarity_Project/DeepPCB_YOLO/labels/val',
                        help='Labels directory')
    parser.add_argument('--output', '-o', type=str, default='single_audit_report.json',
                        help='Output JSON filename (default: single_audit_report.json)')
    parser.add_argument('--seed', type=int, default=114514,
                        help='Random seed for reproducibility')
    args = parser.parse_args()

    # 初始化
    set_deterministic_seed(args.seed)

    print(f"\n{'=' * 60}")
    print(f"Clarity Audit Node - Single Model Mode")
    print(f"{'=' * 60}")
    print(f"PyTorch available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"CUDA Memory Allocated: {torch.cuda.memory_allocated() / 1024 ** 2:.1f} MB")

    # 确定模型名
    model_name = args.model_name if args.model_name else Path(args.model).stem

    # 检查路径存在
    model_path = Path(args.model)
    if not model_path.exists():
        print(f"[ERROR] Model not found: {model_path}")
        sys.exit(1)

    paths_to_check = [
        (args.data_yaml, "Data YAML"),
        (args.val_images, "Val images"),
        (args.defect_free, "Defect-free images"),
        (args.labels, "Labels")
    ]
    for p, name in paths_to_check:
        if not Path(p).exists():
            print(f"[ERROR] {name} not found: {p}")
            sys.exit(1)

    # 执行单模型审计
    print(f"\n[START] Auditing single model: {model_name}")
    start_time = time.time()

    try:
        # 生成单个报告
        report = full_audit(
            model_name=model_name,
            model_path=str(model_path),
            data_yaml=args.data_yaml,
            val_images_dir=args.val_images,
            defect_free_dir=args.defect_free,
            labels_dir=args.labels
        )

        all_reports = [report]
        consolidated = generate_json_report(all_reports, args.output)

        # 打印结果
        m = report['metrics_for_contract']
        print(f"\n{'=' * 60}")
        print(f"[RESULT] Audit Complete for {model_name}")
        print(f"{'=' * 60}")
        print(f"  mAP50:        {m['mAP50_10k'] / 10000:.2%}")
        print(f"  F1 Score:     {m['F1_score_10k'] / 10000:.2%}")
        print(f"  Attention:    {m['attention_ratio_10k'] / 10000:.1%}")
        print(f"  Avg FP (≥0.25):{m['avg_fp_total_10k'] / 10000:.3f}")
        print(f"  Arrogance:    {m['arrogance_ratio_10k'] / 10000:.1%}")
        print(f"  Output:       {args.output}")
        print(f"  Time:         {time.time() - start_time:.1f}s")

    except Exception as e:
        print(f"\n[ERROR] Audit failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        print("\n[CLEANUP] Releasing resources...")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            print(f"  CUDA Memory after cleanup: {torch.cuda.memory_allocated() / 1024 ** 2:.1f} MB")

        # 强制垃圾回收
        gc.collect()

        print("[DONE] Process completed, exiting.")

    # 正常退出
    sys.exit(0)

if __name__ == "__main__":
    main()