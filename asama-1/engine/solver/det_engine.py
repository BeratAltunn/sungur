"""
Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
https://github.com/facebookresearch/detr/blob/main/engine.py

Copyright(c) 2023 lyuwenyu. All Rights Reserved.
"""

import sys
import math
from typing import Iterable
from collections import Counter

import torch
import torch.amp 
from torch.utils.tensorboard import SummaryWriter
from torch.cuda.amp.grad_scaler import GradScaler

from ..optim import ModelEMA, Warmup
from ..data import CocoEvaluator
from ..misc import MetricLogger, SmoothedValue, dist_utils
from torchvision.utils import save_image, draw_bounding_boxes
from datetime import datetime
import matplotlib.pyplot as plt
import json
from evaluation.pycocotools.coco import COCO
from evaluation.pycocotools.cocoeval import COCOeval
import numpy as np
import os
import cv2 
import torchvision.transforms as T
from PIL import Image, ImageDraw
import torch.nn.functional as F
import torchvision.transforms.v2.functional as F_v2
from scipy.stats import gmean, hmean
import time
from torchvision.tv_tensors import BoundingBoxes
import torchvision.ops as tv_ops
def save_bbox_height_distribution_plot(train_counts, model_dir, global_step, val_counts=None):
    """Saves separate bar plots for training and validation bounding box height distributions."""
    output_dir = os.path.join(model_dir, 'bbox_logs')
    os.makedirs(output_dir, exist_ok=True)
    
    # --- Training Plot ---
    train_heights = sorted(list(train_counts.keys()))
    if train_heights:
        train_output_path = os.path.join(output_dir, f'logs_train_{global_step}.png')
        train_values = [train_counts.get(h, 0) for h in train_heights]
        
        x = np.arange(len(train_heights))
        width = 0.7  # Wider bars since it's a single plot

        fig, ax = plt.subplots(figsize=(20, 10))
        rects = ax.bar(x, train_values, width, label='Train', color='tab:blue')

        ax.set_ylabel('Frequency')
        ax.set_xlabel('Bounding Box Height (pixels)')
        ax.set_title(f'Training Bounding Box Height Distribution at Step {global_step}')
        ax.set_xticks(x)
        
        if len(train_heights) > 20:
            ax.set_xticklabels(train_heights, rotation=90, fontsize='small')
        else:
            ax.set_xticklabels(train_heights)
            
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.6)

        fig.tight_layout()
        plt.savefig(train_output_path)
        plt.close(fig)
        print(f"Saved training bbox height plot to {train_output_path}")
    else:
        print("No training bounding box height data to plot.")

    # --- Validation Plot ---
    if val_counts is not None:
        val_heights = sorted(list(val_counts.keys()))
        if val_heights:
            val_output_path = os.path.join(output_dir, f'logs_val_{global_step}.png')
            val_values = [val_counts.get(h, 0) for h in val_heights]
            
            x = np.arange(len(val_heights))
            width = 0.7

            fig, ax = plt.subplots(figsize=(20, 10))
            rects = ax.bar(x, val_values, width, label='Validation', color='tab:orange')

            ax.set_ylabel('Frequency')
            ax.set_xlabel('Bounding Box Height (pixels)')
            ax.set_title(f'Validation Bounding Box Height Distribution at Step {global_step}')
            ax.set_xticks(x)
            
            if len(val_heights) > 20:
                ax.set_xticklabels(val_heights, rotation=90, fontsize='small')
            else:
                ax.set_xticklabels(val_heights)
                
            ax.legend()
            ax.grid(True, linestyle='--', alpha=0.6)

            fig.tight_layout()
            plt.savefig(val_output_path)
            plt.close(fig)
            print(f"Saved validation bbox height plot to {val_output_path}")
        else:
            print("No validation bounding box height data to plot.")

def save_bbox_location_heatmap(counts, model_dir, global_step, prefix='train', grid_size=3):
    """Saves a heatmap for bounding box location distributions."""
    output_dir = os.path.join(model_dir, 'bbox_locations')
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize grid
    heatmap_data = np.zeros((grid_size, grid_size))
    
    for i in range(grid_size):
        for j in range(grid_size):
            cell_id = i * grid_size + j + 1
            heatmap_data[i, j] = counts.get(cell_id, 0)
            
    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(heatmap_data, cmap='viridis')
    
    # Add counts as text
    for i in range(grid_size):
        for j in range(grid_size):
            text = ax.text(j, i, int(heatmap_data[i, j]),
                           ha="center", va="center", color="w")
                           
    ax.set_title(f'{prefix.capitalize()} Bbox Location Heatmap ({grid_size}x{grid_size}) at Step {global_step}')
    fig.colorbar(im)
    
    output_path = os.path.join(output_dir, f'locations_{prefix}_{grid_size}x{grid_size}_{global_step}.png')
    plt.savefig(output_path)
    plt.close(fig)
    print(f"Saved {prefix} bbox location heatmap to {output_path}")

def save_bbox_location_distribution_plot(train_counts, model_dir, global_step, val_counts=None):
    """Saves separate bar plots for training and validation bounding box location distributions."""
    output_dir = os.path.join(model_dir, 'bbox_locations')
    os.makedirs(output_dir, exist_ok=True)

    grid_cells = list(range(1, 10))
    
    # --- Training Plot ---
    train_values = [train_counts.get(i, 0) for i in grid_cells]
    
    x = np.arange(len(grid_cells))
    width = 0.7

    train_output_path = os.path.join(output_dir, f'locations_train_{global_step}.png')
    
    fig, ax = plt.subplots(figsize=(12, 8))
    rects = ax.bar(x, train_values, width, label='Train', color='tab:blue')

    ax.set_ylabel('Frequency')
    ax.set_xlabel('Grid Cell Location (3x3 Grid)')
    ax.set_title(f'Training Bounding Box Location Distribution at Step {global_step}')
    ax.set_xticks(x)
    ax.set_xticklabels(grid_cells)
    ax.legend()
    ax.grid(True, linestyle='--', alpha=0.6)

    fig.tight_layout()
    plt.savefig(train_output_path)
    plt.close(fig)
    print(f"Saved training bbox location plot to {train_output_path}")

    # --- Validation Plot ---
    if val_counts is not None:
        val_values = [val_counts.get(i, 0) for i in grid_cells]
        
        val_output_path = os.path.join(output_dir, f'locations_val_{global_step}.png')
        
        fig, ax = plt.subplots(figsize=(12, 8))
        rects = ax.bar(x, val_values, width, label='Validation', color='tab:orange')

        ax.set_ylabel('Frequency')
        ax.set_xlabel('Grid Cell Location (3x3 Grid)')
        ax.set_title(f'Validation Bounding Box Location Distribution at Step {global_step}')
        ax.set_xticks(x)
        ax.set_xticklabels(grid_cells)
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.6)

        fig.tight_layout()
        plt.savefig(val_output_path)
        plt.close(fig)
        print(f"Saved validation bbox location plot to {val_output_path}")

def fast_nms(boxes, scores, iou_threshold):
    """
    Fast Non-Maximum Suppression implementation using NumPy vectorization
    
    Args:
        boxes: tensor of shape (N, 4) containing bounding boxes
        scores: tensor of shape (N,) containing confidence scores
        iou_threshold: IoU threshold for suppression
        
    Returns:
        keep: indices of boxes to keep
    """
    # Convert tensors to numpy arrays for faster computation
    if isinstance(boxes, torch.Tensor):
        boxes_np = boxes.detach().cpu().numpy()
        scores_np = scores.detach().cpu().numpy()
    else:
        boxes_np = boxes
        scores_np = scores
    
    # Get coordinates for easier computation
    x1 = boxes_np[:, 0]
    y1 = boxes_np[:, 1]
    x2 = boxes_np[:, 2]
    y2 = boxes_np[:, 3]
    
    # Compute areas of boxes
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    
    # Sort boxes by scores in descending order
    order = np.argsort(scores_np)[::-1]
    
    keep = []
    while order.size > 0:
        # Pick the box with highest score
        i = order[0]
        keep.append(i)
        
        # Find intersection with remaining boxes
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        
        # Compute intersection area
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        
        # Compute IoU
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        
        # Get indices of boxes to keep (IoU < threshold)
        inds = np.where(ovr <= iou_threshold)[0]
        # Adjust indices (adding 1 because we skipped the first element)
        order = order[inds + 1]
    
    # Return as tensor for compatibility
    return keep

def draw(image, labels, boxes, scores, thrh=0.4):
    """Draw bounding boxes and labels on images without saving them"""
    
    # Create a copy to avoid modifying the original
    draw_image = image.copy()
    draw = ImageDraw.Draw(draw_image)

    lab = labels[scores > thrh]
    box = boxes[scores > thrh]
    scrs = scores[scores > thrh]

    for j, b in enumerate(box):
        draw.rectangle(list(b), outline='red')
        draw.text((b[0], b[1]), text=f"{lab[j].item()} {round(scrs[j].item(), 2)}", fill='blue')

    return draw_image

def tensors_equal(tensor1, tensor2):
    return torch.equal(tensor1, tensor2)

def prepare_image_for_tensorboard(image):
    """Convert an OpenCV image (numpy array) to a format suitable for TensorBoard.
    
    Args:
        image (numpy.ndarray): OpenCV image in BGR format with shape (H, W, C)
        
    Returns:
        torch.Tensor: Tensor in RGB format with shape (C, H, W) and values in [0, 1]
    """
    # Convert BGR to RGB
    if len(image.shape) == 3 and image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
    # Convert to torch tensor
    if not isinstance(image, torch.Tensor):
        image = torch.from_numpy(image)
    
    # Ensure float
    if image.dtype != torch.float32:
        image = image.float() / 255.0
    
    # Permute dimensions from HWC to CHW if needed
    if len(image.shape) == 3 and image.shape[2] == 3:
        image = image.permute(2, 0, 1)
    
    return image

def log_eval_to_tensorboard(writer, prefix, stats, all_pr_pairs, video_map,
                            operating_points, stat_names, ar_tag, global_step):
    """Log one eval pass (val or test) to TensorBoard under `prefix`.

    Shared by the val and test dataloaders so both produce an identical family
    of curves. `prefix=''` keeps the historical top-level val tag names; the
    test dataloader passes `prefix='TestDataset/'`. Logging only — checkpoint / best_stat
    bookkeeping stays in the val path. The PR/per-video/AP-array tags are written
    on every rank (matching the val behaviour); the AP50/AP30/AR/operating-point
    scalars are main-process only.
    """
    if writer is None:
        return

    # PR pairs per class
    for class_key, pr_data in all_pr_pairs.items():
        for pair in pr_data['pairs']:
            writer.add_scalar(f'{prefix}{class_key}/PR{int(pair["actual_recall"] * 100)} ',
                              pair['precision'], global_step)

    # per-video (video-based) maps
    for video_id, video_results in video_map.items():
        video_name = video_id.replace('/', '_')
        for map_name, map_value in video_results.items():
            if isinstance(map_value, (int, float, np.floating)):
                writer.add_scalar(f'{prefix}{video_name}/{map_name}', float(map_value), global_step)
            elif isinstance(map_value, dict):
                for class_key, class_metric in map_value.items():
                    if isinstance(class_metric, (int, float, np.floating)):
                        writer.add_scalar(f'{prefix}{video_name}/{map_name}/{class_key}',
                                          float(class_metric), global_step)

    # full AP/AR stats array
    for k in stats:
        for j, v in enumerate(stats[k]):
            if j < len(stat_names):
                writer.add_scalar(f'{prefix}Average Precision/{stat_names[j]}', v, global_step)

    if dist_utils.is_main_process():
        bbox = stats.get('coco_eval_bbox', [])
        if len(bbox) > 21:
            writer.add_scalar(f'{prefix}AP50', bbox[1], global_step)
            writer.add_scalar(f'{prefix}AP30', bbox[7], global_step)
            # Single-point Average Recall at IoU=ar_iou, maxDets=ar_maxdets (stats[21]).
            writer.add_scalar(f'{prefix}{ar_tag}', bbox[21], global_step)
        # operating points at precision floors, logged next to AP (IoU=0.30)
        for ckey, ops in operating_points.items():
            for tp, op in ops.items():
                pp = int(round(tp * 100))
                writer.add_scalar(f'{prefix}OperatingPoint/{ckey}/recall@P{pp}',
                                  op['actual_recall'], global_step)
                if op['score'] is not None:
                    writer.add_scalar(f'{prefix}OperatingPoint/{ckey}/score@P{pp}',
                                      op['score'], global_step)

def train_one_epoch(cfg_dict: dict,
                    model: torch.nn.Module,
                    criterion: torch.nn.Module,
                    data_loader: Iterable, 
                    optimizer: torch.optim.Optimizer,
                    device: torch.device, 
                    lr_scheduler: torch.optim.lr_scheduler._LRScheduler, 
                    epoch: int, max_norm: float = 0,
                    freeze_backbone_iters: int = 1000, 
                    freeze_neck_iters: int = 1000,
                    postprocessor: torch.nn.Module = None,
                    val_dataloader: Iterable = None,
                    test_dataloader: Iterable = None,
                    evaluator: CocoEvaluator = None,
                    output_dir: str = None,
                    model_dir: str = None,
                    eval_freq: int = 20,
                    eval_freq_hp: int = 500,
                    max_iters: int = 0,
                    test_freq_mul: int = 5,
                    best_stat: dict = None,
                    log_freq: int = 10,
                    checkpoint_freq: int = -1,
                    not_freezed_params: list = [],
                    best_ap_50: float = 0,
                    best_ap_30: float = 0,
                    video_map_30_mean: float = 0,
                    video_map_30_geo_mean: float = 0,
                    video_map_30_harmonic_mean: float = 0,
                    average_weighted_precision: float = 0,
                    first_class_metric: float = 0,
                    hp_tuning: bool = False,
                    val_annotation_path: str = None,
                    test_annotation_path: str = None,
                    log_images: bool = False,
                    target_precision: float = 0.7,
                    sliding_nms_thresh: float = 0.7,
                    crop_size: int = 720,
                    resize_size: int = 512,
                    bbox_height_counts_train: dict = None,
                    bbox_height_counts_val: dict = None,
                    bbox_location_counts_train: dict = None,
                    bbox_location_counts_val: dict = None,
                    bbox_location_counts_train_9x9: dict = None,
                    bbox_location_counts_val_9x9: dict = None,
                    val_is_saved: bool = False,
                    **kwargs):

    print("Train dataset annotation path: ", data_loader.dataset.ann_file)
    print("Validation dataset annotation path: ", val_dataloader.dataset.ann_file)
    model.train()
    criterion.train()
    metric_logger = MetricLogger(delimiter="  ")
    metric_logger.add_meter('lr', SmoothedValue(window_size=1, fmt='{value:.6f}'))
    header = 'Epoch: [{}]'.format(epoch)
    
    if hp_tuning:
        
        if eval_freq_hp == -1:
            eval_freq = len(data_loader)
            print("Eval freq: ", eval_freq)
        else:
            eval_freq = eval_freq_hp
        
    if checkpoint_freq == -1:
        checkpoint_freq = eval_freq 
        
    print_freq = kwargs.get('print_freq', 10)
    writer :SummaryWriter = kwargs.get('writer', None)

    ema :ModelEMA = kwargs.get('ema', None)
    scaler :GradScaler = kwargs.get('scaler', None)
    debug_dir = kwargs.get('debug_dir', None)
    lr_warmup_scheduler :Warmup = kwargs.get('lr_warmup_scheduler', None)
    recall_values = kwargs.get('recall_values', [0.5, 0.6, 0.7, 0.8, 0.9, 0.95])
    recall_weights = kwargs.get('recall_weights', [1, 2, 2, 1, 1, 1])
    operating_point_precisions = kwargs.get('operating_point_precisions', [0.80, 0.90, 0.95, 0.98, 0.99, 1.0])
    ar_at_start_iou = kwargs.get('ar_at_start_iou', False)
    # Single-point AR knobs (config: ar_iou / ar_maxdets) for the TensorBoard AR scalar.
    ar_iou = kwargs.get('ar_iou', None)
    ar_maxdets = kwargs.get('ar_maxdets', None)
    classwise_metrics = kwargs.get('classwise_metrics', {})
    sampling_debug_hook = kwargs.get('sampling_debug_hook', None)
    sliding = cfg_dict['val_dataloader'].collate_fn.val_type == 'sliding'
    sampling_debug_bucket_counts = Counter()
    sampling_debug_main_folder_counts = Counter()
    sampling_debug_total = 0
    sampling_debug_bucket_order = []
    train_dataset = getattr(data_loader, 'dataset', None)
    if train_dataset is not None:
        default_probs = getattr(train_dataset, 'default_sampling_probs', None)
        if isinstance(default_probs, dict):
            sampling_debug_bucket_order = list(default_probs.keys())
    # debug_images = cfg_dict['debug_images']
    # debug_dir = cfg_dict['debug_dir']
    # Freeze backbone initially

    if freeze_backbone_iters > 0 and (epoch == 0):
        for param in model.backbone.parameters():
            param.requires_grad = False
        print('backbone freezed')
    # Freeze neck initially

    if (epoch == 0) and (freeze_neck_iters > 0):

        for param in model.decoder.parameters():
            if not param.requires_grad:
                not_freezed_params.append(param)
                print(param.item())
            param.requires_grad = False
        print('decoder freezed')
            
        for param in model.encoder.parameters():
            if not param.requires_grad:
                not_freezed_params.append(param)
                print(param.item())
            param.requires_grad = False
        print('encoder freezed')
        for param in model.decoder.denoising_class_embed.parameters():
            param.requires_grad = True
        for param in model.decoder.enc_score_head.parameters():
            param.requires_grad = True
        for param in model.decoder.dec_score_head.parameters():
            param.requires_grad = True
            
            
    for i, (samples, targets) in enumerate(metric_logger.log_every(data_loader, print_freq, header)):
        if i == 0:
            print(f"\n--- [DEBUG] train batch samples shape: {list(samples.shape)} ---\n")
        if train_dataset is not None and hasattr(train_dataset, 'coco'):
            for target in targets:
                image_id_tensor = target.get('image_id')
                if image_id_tensor is None:
                    continue
                try:
                    image_id = int(image_id_tensor.item())
                except Exception:
                    continue

                img_info = train_dataset.coco.loadImgs(image_id)[0]
                img_path = img_info.get('file_name', '')
                if hasattr(train_dataset, '_extract_main_folder'):
                    main_folder = train_dataset._extract_main_folder(img_path)
                else:
                    main_folder = img_path.replace('\\', '/').strip('/').split('/')[0].lower() if img_path else 'unknown'

                if hasattr(train_dataset, '_map_main_folder_to_default_bucket'):
                    bucket = train_dataset._map_main_folder_to_default_bucket(main_folder, img_path)
                else:
                    bucket = 'others'

                sampling_debug_main_folder_counts[main_folder] += 1
                sampling_debug_bucket_counts[bucket] += 1
                sampling_debug_total += 1
        
        for target in targets:
            if 'boxes' in target and 'orig_size' in target and target['boxes'].numel() > 0:
                orig_w, orig_h = target['orig_size'][0].item(), target['orig_size'][1].item()
                for box in target['boxes']:
                    # Assuming box format is [cx, cy, w, h] normalized
                    box_h_normalized = box[3].item()
                    real_box_h = int(box_h_normalized * orig_h)
                    group_h = int(math.ceil(real_box_h / 10) * 10)
                    if group_h == 0: group_h = 10
                    bbox_height_counts_train[group_h] = bbox_height_counts_train.get(group_h, 0) + 1

                    # Bbox location
                    abs_cx = box[0].item() * orig_w
                    abs_cy = box[1].item() * orig_h
                    col = min(int(abs_cx / (orig_w / 3)), 2)
                    row = min(int(abs_cy / (orig_h / 3)), 2)
                    grid_cell = row * 3 + col + 1
                    bbox_location_counts_train[grid_cell] = bbox_location_counts_train.get(grid_cell, 0) + 1

                    # 9x9 Grid
                    col_9 = min(int(abs_cx / (orig_w / 9)), 8)
                    row_9 = min(int(abs_cy / (orig_h / 9)), 8)
                    grid_cell_9 = row_9 * 9 + col_9 + 1
                    if bbox_location_counts_train_9x9 is not None:
                        bbox_location_counts_train_9x9[grid_cell_9] = bbox_location_counts_train_9x9.get(grid_cell_9, 0) + 1

        if debug_dir is not None:
            
            try:
                # The samples can be a NestedTensor, get the tensor
                image_tensor = samples.tensors[0] if hasattr(samples, 'tensors') else samples[0]
                
                # De-normalize image tensor for visualization
                image_to_draw = image_tensor.cpu().clone()
                image_uint8 = (image_to_draw * 255).to(torch.uint8)

                # Get ground truth boxes for the first image
                if 'boxes' in targets[0] and len(targets[0]['boxes']) > 0:
                    gt_boxes = targets[0]['boxes'].cpu() # format is [cx, cy, w, h] normalized

                    # Convert boxes to [x1, y1, x2, y2] format
                    _, h, w = image_uint8.shape
                    boxes_abs = gt_boxes.clone()
                    boxes_abs[:, 0] = (gt_boxes[:, 0] - gt_boxes[:, 2] / 2) * w
                    boxes_abs[:, 1] = (gt_boxes[:, 1] - gt_boxes[:, 3] / 2) * h
                    boxes_abs[:, 2] = (gt_boxes[:, 0] + gt_boxes[:, 2] / 2) * w
                    boxes_abs[:, 3] = (gt_boxes[:, 1] + gt_boxes[:, 3] / 2) * h
                    
                    # Draw bounding boxes
                    image_with_boxes = draw_bounding_boxes(image_uint8, boxes_abs, colors="red", width=2)
                    
                    time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    save_image(image_with_boxes.float() / 255.0, f'{debug_dir}/train_samples_{time_str}_{i}.png')
            except Exception as e:
                print(f"Could not draw GT boxes for debugging: {e}")

        # Unfreeze backbone after specified iterations
# Unfreeze backbone after specified iterations

        global_step = epoch * len(data_loader) + i
        if global_step == freeze_backbone_iters and freeze_backbone_iters != 0:
            for param in model.backbone.parameters():
                param.requires_grad = True
            print('backbone unfreezed')

        # Unfreeze neck after specified iterations
        if global_step == freeze_neck_iters and freeze_neck_iters != 0:
            for param in model.decoder.parameters():
                if any(tensors_equal(param, p) for p in not_freezed_params):
                    continue
                param.requires_grad = True

            print('decoder unfreezed')
            for param in model.encoder.parameters():
                if any(tensors_equal(param, p) for p in not_freezed_params):
                    continue
                param.requires_grad = True
            print('encoder unfreezed')
        # try:
        # if i == 0:
        #     print('Debug')
        #     save_image(samples, f'{epoch}_img.jpg')
        if not model.training:
            model.train()
        if not criterion.training:
            criterion.train()
            
        samples = samples.to(device)
        targets = [{k: v.to(device) for k, v in t.items()} for t in targets]
        
        metas = dict(epoch=epoch, step=i, global_step=global_step)

        if scaler is not None:
            with torch.autocast(device_type=str(device), cache_enabled=True):
                outputs = model(samples, targets=targets)
            
            with torch.autocast(device_type=str(device), enabled=False):
                loss_dict = criterion(outputs, targets, **metas)

            loss = sum(loss_dict.values())
            scaler.scale(loss).backward()
            
            if max_norm > 0:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm)

            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad()

        else:
            outputs = model(samples, targets=targets)
            loss_dict = criterion(outputs, targets, **metas)
            
            loss : torch.Tensor = sum(loss_dict.values())
            optimizer.zero_grad()
            loss.backward()
            
            if max_norm > 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm)

            optimizer.step()
        
        # ema 
        if ema is not None:
            ema.update(model)

        if lr_warmup_scheduler is not None:
            lr_warmup_scheduler.step()
            
        if lr_warmup_scheduler is None or lr_warmup_scheduler.finished():
            lr_scheduler.step()
            

        loss_dict_reduced = dist_utils.reduce_dict(loss_dict)
        loss_value = sum(loss_dict_reduced.values())

        if not math.isfinite(loss_value):
            print("Loss is {}, stopping training".format(loss_value))
            print(loss_dict_reduced)
            sys.exit(1)

        metric_logger.update(loss=loss_value, **loss_dict_reduced)
        metric_logger.update(lr=optimizer.param_groups[0]["lr"])
        
        if log_freq > 0 and i % log_freq == 0:
            if writer and dist_utils.is_main_process():
                writer.add_scalar('Loss/total', loss_value.item(), global_step)
                for j, pg in enumerate(optimizer.param_groups):
                    writer.add_scalar(f'Lr/pg_{j}', pg['lr'], global_step)
                for k, v in loss_dict_reduced.items():
                    writer.add_scalar(f'Loss/{k}', v.item(), global_step)
        # except Exception as e:
        #     print(f"Error in train_one_epoch: {e}")
        
        if (global_step+1) % eval_freq == 0:
            if callable(sampling_debug_hook):
                sampling_debug_hook(epoch, global_step)
            sampling_snapshot = {
                'total': sampling_debug_total,
                'bucket_counts': dict(sampling_debug_bucket_counts),
                'main_folder_counts': dict(sampling_debug_main_folder_counts),
                'bucket_order': sampling_debug_bucket_order,
            }
            sampling_snapshots = dist_utils.all_gather(sampling_snapshot)
            if dist_utils.is_main_process():
                merged_bucket_counts = Counter()
                merged_folder_counts = Counter()
                merged_total = 0
                merged_bucket_order = []

                for item in sampling_snapshots:
                    merged_total += item.get('total', 0)
                    merged_bucket_counts.update(item.get('bucket_counts', {}))
                    merged_folder_counts.update(item.get('main_folder_counts', {}))
                    if not merged_bucket_order:
                        merged_bucket_order = item.get('bucket_order', [])

                if merged_total > 0:
                    print(f"[Epoch {epoch} | step {global_step}] Default sampling distribution:")
                    for bucket in merged_bucket_order:
                        count = merged_bucket_counts.get(bucket, 0)
                        ratio = 100.0 * count / merged_total
                        print(f"  - {bucket}: {ratio:.2f}% ({count}/{merged_total})")

                    print(f"[Epoch {epoch} | step {global_step}] Sampled main-folder distribution:")
                    for folder, count in sorted(merged_folder_counts.items(), key=lambda x: x[1], reverse=True):
                        ratio = 100.0 * count / merged_total
                        print(f"  - {folder}: {ratio:.2f}% ({count}/{merged_total})")
            
            module = ema.module if ema else model
            
            if val_is_saved:
                bbox_location_counts_val = None
                bbox_height_counts_val = None
                bbox_location_counts_val_9x9 = None
            #stats, coco_evaluator = evaluate(module, criterion, postprocessor, val_dataloader, evaluator, device)
            stats, all_pr_pairs, video_map, scores_at_p70, bbox_height_counts_val, bbox_location_counts_val, bbox_location_counts_val_9x9, first_class_ap30, operating_points = evaluate_custom_metrics(module, criterion, postprocessor, val_dataloader, evaluator, device, val_annotation_path, model_dir, global_step, recall_values=recall_values, sliding=sliding, target_precision=target_precision, operating_point_precisions=operating_point_precisions, ar_at_start_iou=ar_at_start_iou, ar_iou=ar_iou, ar_maxdets=ar_maxdets, sliding_nms_thresh=sliding_nms_thresh, bbox_height_counts=bbox_height_counts_val, bbox_location_counts=bbox_location_counts_val, bbox_location_counts_9x9=bbox_location_counts_val_9x9, crop_size=crop_size, resize_size=resize_size, hp_tuning=hp_tuning, debug_val_model=kwargs.get('debug_val_model', False), debug_val_model_dir=kwargs.get('debug_val_model_dir', None), debug_draw_threshold=cfg_dict['cfg'].global_cfg.get('debug_thr', cfg_dict['cfg'].global_cfg.get('draw_thr', 0.3)), eval_per_video_map=cfg_dict['cfg'].global_cfg.get('eval_per_video_map', True), debug_images_dir=kwargs.get('debug_dir', None))      
            average_weighted_precision = calculate_average_precision(pr_data=all_pr_pairs, weights=recall_weights, exclude_last=False)
            first_class_metric = first_class_ap30
            video_map_30 = [result['map30'] for result in video_map.values()]
            if len(video_map_30) > 0:
                video_map_30_mean = np.mean(video_map_30)
                video_map_30_geo_mean = gmean(video_map_30)
                video_map_30_non_negative = [val for val in video_map_30 if val >= 0]
                if len(video_map_30_non_negative) > 0:
                    video_map_30_harmonic_mean = hmean(video_map_30_non_negative)
                else:
                    video_map_30_harmonic_mean = 0.0
            else:
                video_map_30_mean = 0.0
                video_map_30_geo_mean = 0.0
                video_map_30_harmonic_mean = 0.0

            save_bbox_height_distribution_plot(
                train_counts=bbox_height_counts_train,
                model_dir=model_dir,
                global_step=global_step,
                val_counts=bbox_height_counts_val
            )
            save_bbox_location_heatmap(bbox_location_counts_train, model_dir, global_step, prefix='train', grid_size=3)
            if bbox_location_counts_val is not None:
                save_bbox_location_heatmap(bbox_location_counts_val, model_dir, global_step, prefix='val', grid_size=3)

            if bbox_location_counts_train_9x9 is not None:
                save_bbox_location_heatmap(bbox_location_counts_train_9x9, model_dir, global_step, prefix='train', grid_size=9)
            if bbox_location_counts_val_9x9 is not None:
                save_bbox_location_heatmap(bbox_location_counts_val_9x9, model_dir, global_step, prefix='val', grid_size=9)
            
            if not val_is_saved:
                val_is_saved = True
                
            if (global_step+1) % (eval_freq * test_freq_mul) == 0:
                # Initialize with default values from config or safe defaults
                draw_thr = cfg_dict['cfg'].global_cfg.get('draw_thr', 0.3)
                precision_video = 0.5
                recall_video = 0.5

                # Try to get metrics from scores_at_p70 for the target class
                if scores_at_p70:
                    # Prefer class '1' if available, otherwise use the first available class
                    target_class_key = '1' if '1' in scores_at_p70 else list(scores_at_p70.keys())[0]
                    target_class_data = scores_at_p70.get(target_class_key)
                    
                    if target_class_data is not None:
                        if target_class_data.get('score') is not None:
                            draw_thr = target_class_data['score']
                        precision_video = target_class_data.get('actual_precision', 0.5)
                        recall_video = target_class_data.get('actual_recall', 0.5)
                num_queries_test = cfg_dict['cfg'].global_cfg['num_queries_test']
                original_num_queries = cfg_dict['cfg']._model.decoder.num_queries
                
                
                if num_queries_test is not None:
                    debug_video_method = cfg_dict['cfg'].global_cfg.get('debug_video_method', 'sliding')
                    if debug_video_method == 'normal':
                        debug_video_method = 'opencv'
                    for num_queries in num_queries_test:
                        debug_samples = generate_debug_video(model=module,
                                criterion=criterion,
                                postprocessor=postprocessor,
                                precision_video=precision_video,
                                # data_loader=test_dataloader,
                                img_size=data_loader.collate_fn.base_size,
                                current_step=global_step,
                                draw_thr=draw_thr,
                                input_video=cfg_dict['cfg'].global_cfg['test_video'],
                                out_video_path=cfg_dict['model_dir'],
                                num_queries=num_queries,
                                crop_size=crop_size,
                                original_num_queries=original_num_queries,
                                recall_video=recall_video,
                                method=debug_video_method)
                        if log_images:
                            for i, sample in enumerate(debug_samples):
                                # Convert the sample to a format suitable for TensorBoard
                                tb_image = prepare_image_for_tensorboard(sample)
                            writer.add_image(f'Debug/nq_{num_queries}/step_{global_step}/sample_{i}', tb_image, global_step)
            
            
            # Single-point AR tag (config: ar_iou / ar_maxdets). stats[21] is THE Average Recall
            # at this single IoU + detection budget; label it e.g. 'AR30_maxDets5'.
            _ar_md = ar_maxdets if ar_maxdets is not None else 100
            _ar_tag = (f'AR{int(round(ar_iou * 100))}_maxDets{_ar_md}'
                       if ar_iou is not None else f'AR_maxDets{_ar_md}')
            stat_names = [
                'AP', 'AP50', 'AP50_small', 'AP50_medium', 'AP50_large', 'AP50_optimum', 'AP50_rare',
                'AP30', 'AP30_small', 'AP30_medium', 'AP30_large', 'AP30_optimum', 'AP30_rare',
                'AP75', 'AP_small', 'AP_medium', 'AP_large', 'AP_optimum', 'AP_rare',
                'AR1', 'AR10', _ar_tag, 'AR_small', 'AR_medium', 'AR_large'
            ]

            ap_50 = stats['coco_eval_bbox'][1]
            best_ap_50 = max(best_ap_50, ap_50)
            ap_30 = stats['coco_eval_bbox'][7]
            best_ap_30 = max(best_ap_30, ap_30)

            # best_stat bookkeeping (val drives checkpoints / best-epoch tracking)
            for k in stats:
                if k in best_stat:
                    best_stat['epoch'] = epoch if stats[k][0] > best_stat[k] else best_stat['epoch']
                    best_stat[k] = max(best_stat[k], stats[k][0])
                else:
                    best_stat['epoch'] = epoch
                    best_stat[k] = stats[k][0]

            # log the full val eval (PR / per-video / AP / AR / operating points) to TB
            log_eval_to_tensorboard(writer, '', stats, all_pr_pairs, video_map,
                                    operating_points, stat_names, _ar_tag, global_step)

            # --- Second eval pass: the test_dataloader (on-the-fly) ---
            # The original val above drives checkpoints / best_stat. This extra pass
            # only REPORTS metrics on the test_dataloader, which may be a low-contrast
            # copy of val (same images+GT, e.g. a mild AGCRenormSim) OR a genuinely
            # separate test set. Either way the GT MUST be test_dataloader's own
            # ann_file (test_annotation_path), NOT val's: a separate test set has its
            # own image_ids, so reusing val's GT makes coco_gt.loadImgs() KeyError on
            # the first test image_id. Opt-in via `eval_low_contrast: True`.
            #
            # NOTE: this MUST go through evaluate_custom_metrics (NOT the plain
            # evaluate()), exactly like the val pass above. evaluate() uses the standard
            # CocoEvaluator whose COCOeval has iouThrs=[.5:.95], so its stats array has
            # NO AP@0.30 at all -> index 7 is AR@10 (recall, maxDets=10). Logging that as
            # "AP30" via stat_names made AP30 look smaller than AP50. evaluate_custom_metrics
            # uses the custom COCOeval (start_iou=0.3) so stats[7] is a true AP@0.30
            # (>= AP50) and we also get the per-video (video-based) map30/map50.
            if cfg_dict['cfg'].global_cfg.get('eval_low_contrast', False) and test_dataloader is not None:
                # Same operating-point precision floors + single-point AR knobs as the val
                # pass above, so the test (low-contrast) set is reported identically.
                lc_stats, lc_pr_pairs, lc_video_map, _, _, _, _, _, lc_operating_points = evaluate_custom_metrics(
                    module, criterion, postprocessor, test_dataloader, evaluator, device,
                    test_annotation_path or val_annotation_path, model_dir, global_step,
                    recall_values=recall_values, sliding=sliding,
                    target_precision=target_precision, operating_point_precisions=operating_point_precisions,
                    ar_at_start_iou=ar_at_start_iou, ar_iou=ar_iou, ar_maxdets=ar_maxdets, sliding_nms_thresh=sliding_nms_thresh,
                    crop_size=crop_size, resize_size=resize_size, hp_tuning=hp_tuning,
                    eval_per_video_map=cfg_dict['cfg'].global_cfg.get('eval_per_video_map', True),
                    eval_tag='TestDataset')
                lc_bbox = lc_stats.get('coco_eval_bbox', [])
                lc_vid30 = [r['map30'] for r in lc_video_map.values()]
                lc_vid50 = [r['map50'] for r in lc_video_map.values()]
                lc_map30_video = float(np.mean(lc_vid30)) if lc_vid30 else 0.0
                lc_map50_video = float(np.mean(lc_vid50)) if lc_vid50 else 0.0
                # Full mirror of the val logging (PR / per-video / AP / AR / operating
                # points), under the 'TestDataset/' namespace so test == val in TensorBoard.
                log_eval_to_tensorboard(writer, 'TestDataset/', lc_stats, lc_pr_pairs, lc_video_map,
                                        lc_operating_points, stat_names, _ar_tag, global_step)
                if writer and dist_utils.is_main_process() and lc_bbox:
                    # extra aggregate: mean per-video AP across the test videos
                    writer.add_scalar('TestDataset/AP30_video', lc_map30_video, global_step)
                    writer.add_scalar('TestDataset/AP50_video', lc_map50_video, global_step)
                if lc_bbox and len(lc_bbox) > 7:
                    print(f"[TestDataset eval | video-based] "
                          f"AP50={lc_bbox[1]:.4f} (orig {ap_50:.4f}) | "
                          f"AP30={lc_bbox[7]:.4f} (orig {ap_30:.4f}) | "
                          f"video AP50={lc_map50_video:.4f} AP30={lc_map30_video:.4f}")

            if not hp_tuning:
                ap_50_rounded = int(1000*ap_50)
                checkpoint_path = f'{model_dir}/ckpts/model_epoch_{epoch}_iter_{global_step}_ap50_{ap_50_rounded}.pth'
                ema_path = f'{model_dir}/ckpts/ema_model_epoch_{epoch}_iter_{global_step}_ap50_{ap_50_rounded}.pth'
                os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
                dist_utils.save_on_master(get_state_dict(cfg_dict), checkpoint_path)
                print(f"New best model saved with AP@50: {ap_50}")
                print(f"average_weighted_precision: {average_weighted_precision}")

        # Stop once the global step reaches max_iters. Placed at the end of the
        # loop body so an eval/checkpoint at an eval_freq boundary (when max_iters
        # is a multiple of eval_freq) still runs before we break.
        if max_iters and (global_step + 1) >= max_iters:
            print(f"[Epoch {epoch} | step {global_step}] Reached max_iters={max_iters}; stopping epoch early.")
            break
    # gather the stats from all processes
    metric_logger.synchronize_between_processes()
    print("Averaged stats:", metric_logger)

    return {k: meter.global_avg for k, meter in metric_logger.meters.items()}, best_ap_50, best_ap_30, average_weighted_precision, video_map_30_mean, video_map_30_geo_mean, video_map_30_harmonic_mean, first_class_metric, classwise_metrics

def get_state_dict(cfg_dict):
    """state dict, train/eval
    """
    state = {}
    state['date'] = datetime.now().isoformat()

    for k, v in cfg_dict.items():
        if hasattr(v, 'state_dict'):
            v = dist_utils.de_parallel(v)
            state[k] = v.state_dict() 

    return state
    
@torch.no_grad()
def evaluate(model: torch.nn.Module, criterion: torch.nn.Module, postprocessor, data_loader, coco_evaluator: CocoEvaluator, device):
    model.eval()
    criterion.eval()
    coco_evaluator.cleanup()
    iou_types = coco_evaluator.iou_types

    metric_logger = MetricLogger(delimiter="  ")
    header = 'Test:'
    
    for samples, targets in metric_logger.log_every(data_loader, 10, header):
        samples = samples.to(device)
        targets = [{k: v.to(device) for k, v in t.items()} for t in targets]

        outputs = model(samples)

        # TODO (lyuwenyu), fix dataset converted using `convert_to_coco_api`?
        orig_target_sizes = torch.stack([t["orig_size"] for t in targets], dim=0)
        
        results = postprocessor(outputs, orig_target_sizes)

        # if 'segm' in postprocessor.keys():
        #     target_sizes = torch.stack([t["size"] for t in targets], dim=0)
        #     results = postprocessor['segm'](results, outputs, orig_target_sizes, target_sizes)

        res = {target['image_id'].item(): output for target, output in zip(targets, results)}
        if coco_evaluator is not None:
            coco_evaluator.update(res)

    # gather the stats from all processes
    metric_logger.synchronize_between_processes()
    print("Averaged stats:", metric_logger)
    if coco_evaluator is not None:
        coco_evaluator.synchronize_between_processes()

    # accumulate predictions from all images
    if coco_evaluator is not None:
        coco_evaluator.accumulate()
        coco_evaluator.summarize()

    stats = {}
    # stats = {k: meter.global_avg for k, meter in metric_logger.meters.items()}
    if coco_evaluator is not None:
        if 'bbox' in iou_types:
            stats['coco_eval_bbox'] = coco_evaluator.coco_eval['bbox'].stats.tolist()
        if 'segm' in iou_types:
            stats['coco_eval_masks'] = coco_evaluator.coco_eval['segm'].stats.tolist()
            
    return stats, coco_evaluator

def extract_pr_data(coco_eval, coco_gt, class_id, iou_thrs=0.5, max_dets=100, area_rng='all'):
    """
    Extract precision-recall data from COCO evaluation results
    
    Args:
        coco_eval: COCOeval object with evaluation results
        coco_gt: COCO ground truth object
        class_id: Class ID to extract data for
        iou_thrs: IoU threshold for evaluation (default: 0.5)
        max_dets: Maximum number of detections (default: 100)
        area_rng: Area range for evaluation ('all', 'small', 'medium', 'large')
        
    Returns:
        Dictionary containing class_name, precision, recall, scores, and parameters
    """
    # Get class name
    class_name = coco_gt.loadCats(class_id)[0]['name']
    params = coco_eval.params
    
    # Find indices for the specified parameters
    iou_idx = np.where(params.iouThrs == iou_thrs)[0][0]
    max_dets_idx = params.maxDets.index(max_dets)
    cat_idx = params.catIds.index(class_id)
    area_idx = params.areaRngLbl.index(area_rng)
    
    # Extract precision, recall, and scores
    precision = coco_eval.eval['precision'][iou_idx, :, cat_idx, area_idx, max_dets_idx]
    recall = np.linspace(0, 1, num=precision.shape[0])  # COCO uses 101 recall points (0, 0.01, ..., 1)
    scores = coco_eval.eval['scores'][iou_idx, :, cat_idx, area_idx, max_dets_idx]
    
    return {
        'class_name': class_name,
        'precision': precision,
        'recall': recall,
        'scores': scores,
        'params': {
            'iou_threshold': iou_thrs,
            'max_detections': max_dets,
            'area_range': area_rng
        }
    }
    

def get_pr_pairs_at_recalls(coco_eval, coco_gt, class_id, recall_values, iou_thrs=0.5, max_dets=100, area_rng='all', draw_pr_curve=False, output_dir='.', global_step=0, hp_tuning=False):
    """
    Get precision, recall, and score pairs at specific recall values
    
    Args:
        coco_eval: COCOeval object with evaluation results
        coco_gt: COCO ground truth object
        class_id: Class ID to extract data for
        recall_values: Single recall value or list of recall values to get pairs for
        iou_thrs: IoU threshold for evaluation (default: 0.5)
        max_dets: Maximum number of detections (default: 100)
        area_rng: Area range for evaluation ('all', 'small', 'medium', 'large')
        hp_tuning: If True, skip saving PR curves
        
    Returns:
        Dictionary containing precision, recall, and score pairs for the specified recall values
    """
    # Get PR data
    pr_data = extract_pr_data(coco_eval, coco_gt, class_id, iou_thrs, max_dets, area_rng)
    
    if draw_pr_curve and not hp_tuning:
        from sklearn.metrics import auc
        AP = auc(pr_data['recall'], pr_data['precision'])
        
        # Plot PR curve
        output_dir = f'{output_dir}/PR'
        os.makedirs(output_dir, exist_ok=True)
        plot_pr_curve(pr_data['precision'], pr_data['recall'], pr_data['class_name'], 
                    iou_thrs, area_rng, output_dir, AP, global_step)
    # Convert single recall value to list if needed
    if not isinstance(recall_values, (list, tuple, np.ndarray)):
        recall_values = [recall_values]
    
    # Initialize results
    results = {
        'class_name': pr_data['class_name'],
        'pairs': []
    }
    
    # COCO uses 101 recall points from 0 to 1
    coco_recalls = pr_data['recall']
    precisions = pr_data['precision']
    scores = pr_data['scores']
    
    # Find the closest recall values and corresponding precision and score
    for target_recall in recall_values:
        # Find the index of the closest recall value
        idx = np.abs(coco_recalls - target_recall).argmin()
        actual_recall = coco_recalls[idx]
        precision = precisions[idx]
        
        # Scores might have NaN values, handle them
        score = scores[idx] if idx < len(scores) and not np.isnan(scores[idx]) else None
        
        results['pairs'].append({
            'target_recall': target_recall,
            'actual_recall': float(actual_recall),
            'precision': float(precision),
            'score': float(score) if score is not None else None
        })
    
    return results

def get_score_at_precision(coco_eval, coco_gt, class_id, target_precision, iou_thrs=0.5, max_dets=100, area_rng='all'):
    """
    Get score at a specific precision value.
    
    Args:
        coco_eval: COCOeval object with evaluation results
        coco_gt: COCO ground truth object
        class_id: Class ID to extract data for
        target_precision: The target precision value
        iou_thrs: IoU threshold for evaluation (default: 0.5)
        max_dets: Maximum number of detections (default: 100)
        area_rng: Area range for evaluation ('all', 'small', 'medium', 'large')
        
    Returns:
        Dictionary containing the score and actual precision for the target precision.
    """
    # Get PR data
    pr_data = extract_pr_data(coco_eval, coco_gt, class_id, iou_thrs, max_dets, area_rng)
    
    precisions = pr_data['precision']
    scores = pr_data['scores']
    recalls = pr_data['recall']
    # Find the index of the closest precision value
    # We look for the first precision value that is >= target_precision.
    # Since precision is non-increasing, this gives us the highest recall for that precision level.
    indices = np.where(precisions >= target_precision)[0]
    
    if len(indices) > 0:
        # Get the index corresponding to the lowest precision that is still >= target_precision
        # This corresponds to the highest recall.
        idx = indices[-1]
    else:
        # If no precision is >= target_precision, find the closest one.
        idx = np.abs(precisions - target_precision).argmin()

    actual_precision = precisions[idx]
    score = scores[idx] if idx < len(scores) and not np.isnan(scores[idx]) else None
    
    return {
        'class_name': pr_data['class_name'],
        'target_precision': target_precision,
        'actual_precision': float(actual_precision),
        'score': float(score) if score is not None else None,
        'actual_recall': float(recalls[idx])
    }
    

def plot_pr_curve(precision, recall, class_name, iou_thrs, area_rng, output_dir='.', AP=None, global_step=0):
    """
    Plot precision-recall curve and save it to a file
    
    Args:
        precision: Array of precision values
        recall: Array of recall values
        class_name: Name of the class
        iou_thrs: IoU threshold used for evaluation
        area_rng: Area range used for evaluation
        output_dir: Directory to save the output plot
        AP: Average Precision value (if None, will be calculated)
    """
    # Plot precision-recall curve
    plt.figure(figsize=(10, 8))
    plt.plot(recall, precision, 'b-', linewidth=2)
    plt.xlabel('Recall', fontsize=14)
    plt.ylabel('Precision', fontsize=14)
    plt.title(f'Precision-Recall Curve for {class_name}\nIoU={iou_thrs}, Area={area_rng}', fontsize=16)
    plt.xlim([0, 1])
    plt.ylim([0, 1.05])
    plt.grid(True)
    
    # Calculate AP if not provided
    if AP is None:
        from sklearn.metrics import auc
        AP = auc(recall, precision)
    
    plt.text(0.5, 0.2, f'AP = {AP:.4f}', fontsize=14, bbox=dict(facecolor='white', alpha=0.8))
    
    # Fill the area under the curve
    plt.fill_between(recall, 0, precision, alpha=0.2, color='b')
    
    # Save the plot
    output_file = f'{output_dir}/PR_curve_{class_name}_iou{iou_thrs}_iter{global_step}.png'
    plt.savefig(output_file)
    plt.close()
    
    print(f'Precision-Recall curve saved to {output_file}')
    
def crop_boxes(boxes, x_offset, crop_width=720):
    # Shift x coordinates
    

    format = boxes.format
    boxes = boxes.clone()
    boxes[:, [0, 2]] -= x_offset

    # Clip to crop boundaries
    boxes[:, 0::2] = boxes[:, 0::2].clamp(0, crop_width)
    
    # Remove boxes that are too small or outside
    keep = ((boxes[:, 2] - boxes[:, 0]) > 1) & ((boxes[:, 3] - boxes[:, 1]) > 1)
    boxes = boxes[keep]

    boxes = BoundingBoxes(boxes, format=format, canvas_size=(crop_width, crop_width))
    return boxes, keep

def _to_debug_bgr_image(image):
    """Convert PIL / tensor / numpy images to a uint8 OpenCV BGR image."""
    if isinstance(image, Image.Image):
        rgb_image = np.array(image.convert("RGB"))
    elif isinstance(image, torch.Tensor):
        tensor = image.detach().cpu()
        if tensor.dim() == 4:
            tensor = tensor[0]
        if tensor.dim() == 3 and tensor.shape[0] in (1, 3):
            tensor = tensor.permute(1, 2, 0)
        rgb_image = tensor.numpy()
        if rgb_image.dtype != np.uint8:
            rgb_image = np.clip(rgb_image, 0.0, 1.0)
            rgb_image = (rgb_image * 255).astype(np.uint8)
    elif isinstance(image, np.ndarray):
        rgb_image = image.copy()
        if rgb_image.dtype != np.uint8:
            rgb_image = np.clip(rgb_image, 0.0, 255.0).astype(np.uint8)
    else:
        raise TypeError(f"Unsupported image type for debug export: {type(image)}")

    if rgb_image.ndim == 2:
        rgb_image = cv2.cvtColor(rgb_image, cv2.COLOR_GRAY2RGB)

    if rgb_image.shape[-1] != 3:
        raise ValueError(f"Expected 3-channel image for debug export, got shape {rgb_image.shape}")

    return cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)

def save_validation_model_debug_image(image,
                                      boxes,
                                      labels,
                                      scores,
                                      image_base_name: str,
                                      debug_dir: str,
                                      iteration_index: int,
                                      draw_threshold: float = 0.3,
                                      labels_names=None) -> None:
    """Save validation model predictions drawn on top of the original image."""
    os.makedirs(debug_dir, exist_ok=True)

    debug_image = _to_debug_bgr_image(image)
    if labels_names is None or len(labels_names) == 0:
        labels_names = {int(label): str(int(label)) for label in np.unique(labels)}

    annotated_image = draw_boxes_fn(
        image=debug_image,
        bboxes=boxes,
        labels=labels,
        scores=scores,
        draw_threshold=draw_threshold,
        labels_names=labels_names,
        color='blue'
    )

    output_path = os.path.join(debug_dir, f"{image_base_name}_model_{iteration_index}.jpg")
    cv2.imwrite(output_path, annotated_image)
    print(f"Saved validation model debug image to {output_path}")
    
@torch.no_grad()
def evaluate_custom_metrics(model: torch.nn.Module, 
                            criterion: torch.nn.Module, 
                            postprocessor, 
                            data_loader, 
                            coco_evaluator: CocoEvaluator, 
                            device, 
                            annotation_path, 
                            out_path, 
                            global_step, 
                            recall_values=[0.5, 1],
                            iou_thrs=0.3,
                            target_precision=0.7,
                            operating_point_precisions=(0.80, 0.90, 0.95, 0.98, 0.99, 1.0),
                            ar_at_start_iou=False,
                            ar_iou=None,
                            ar_maxdets=None,
                            sliding=False,
                            sliding_nms_thresh=0.7,
                            crop_size=720,
                            resize_size=512,
                            bbox_height_counts=None,
                            bbox_location_counts=None,
                            bbox_location_counts_9x9=None,
                            hp_tuning=False,
                            debug_val_model=False,
                            debug_val_model_dir=None,
                            debug_draw_threshold=0.3,
                            eval_per_video_map=True,
                            debug_images_dir=None,
                            eval_tag='val'):
    
    # recall_values = np.linspace(recall_values[0], recall_values[1], recall_values[2])
    recall_values = np.array(recall_values)
    model.eval()
    criterion.eval()
    coco_evaluator.cleanup()
    iou_types = coco_evaluator.iou_types

    metric_logger = MetricLogger(delimiter="  ")
    header = 'Validation:'
    detections = []
    coco_gt = COCO(annotation_path)
    labels_names = {cat['id']: cat['name'] for cat in coco_gt.loadCats(coco_gt.getCatIds())}

    raise RuntimeError('Sliding-window eval kaldırıldı (SlidingRandomCrop silindi).')
    # Save an iteration index for naming debug images
    iter_counter = 0
    val_gt_debug_i = 0
    j = 0
    for samples, targets in metric_logger.log_every(data_loader, 10, header):
        raw_target = targets[0]
        if debug_images_dir is not None:
            try:
                image_tensor = samples[0].detach().cpu().clone()
                image_uint8 = (image_tensor * 255).to(torch.uint8)
                _, h, w = image_uint8.shape
                gt_boxes = raw_target.get('boxes')
                boxes_abs = _gt_boxes_to_xyxy_for_debug(gt_boxes, h, w)
                if boxes_abs.numel() > 0:
                    image_with_boxes = draw_bounding_boxes(image_uint8, boxes_abs, colors="red", width=2)
                else:
                    image_with_boxes = image_uint8
                time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                os.makedirs(debug_images_dir, exist_ok=True)
                out_path = os.path.join(debug_images_dir, f'val_samples_{time_str}_{val_gt_debug_i}.png')
                save_image(image_with_boxes.float() / 255.0, out_path)
            except Exception as e:
                print(f"Could not save validation GT debug image: {e}")
            val_gt_debug_i += 1
        # Convert to device
        samples = samples.to(device)
        
        for target in targets:
            if 'boxes' in target and 'orig_size' in target and target['boxes'].numel() > 0:
                orig_w, orig_h = target['orig_size'][0].item(), target['orig_size'][1].item()
                for box in target['boxes']:
                    # Assuming box format is [x, y, w, h] unnormalized
                    real_box_h = int(box[3].item())
                    group_h = int(math.ceil(real_box_h / 10) * 10)
                    if group_h == 0: group_h = 10
                    if bbox_height_counts is not None:
                        bbox_height_counts[group_h] = bbox_height_counts.get(group_h, 0) + 1
                        
                    if not sliding:
                        abs_cx = box[0].item() + box[2].item() / 2
                        abs_cy = box[1].item() + box[3].item() / 2
                        col = min(int(abs_cx / (orig_w / 3)), 2)
                        row = min(int(abs_cy / (orig_h / 3)), 2)
                        grid_cell = row * 3 + col + 1
                        if bbox_location_counts is not None:
                            bbox_location_counts[grid_cell] = bbox_location_counts.get(grid_cell, 0) + 1
                        
                        if bbox_location_counts_9x9 is not None:
                            col_9 = min(int(abs_cx / (orig_w / 9)), 8)
                            row_9 = min(int(abs_cy / (orig_h / 9)), 8)
                            grid_cell_9 = row_9 * 9 + col_9 + 1
                            bbox_location_counts_9x9[grid_cell_9] = bbox_location_counts_9x9.get(grid_cell_9, 0) + 1
                    
                if bbox_location_counts is not None and sliding:
                    positions = target['positions']

                    for crop_idx in range(len(positions)):
                        boxes = target['boxes']
                        boxes_cropped, _ = crop_boxes(boxes, positions[crop_idx], crop_width=crop_size)
                        
                        
                        # image = samples[crop_idx, :, :, :].detach().cpu().numpy() * 255
                        # image = image.astype(np.uint8)
                        # image = image.transpose(1, 2, 0)
                        # image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                        # image = cv2.resize(image, (720, 720))
                       
                        for box in boxes_cropped:
                            # x1, y1, x2, y2 = box
                            # x1 = int(x1)
                            # y1 = int(y1)
                            # x2 = int(x2)
                            # y2 = int(y2)
                            # image = cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)

                            abs_cx = box[0].item() + box[2].item() / 2
                            abs_cy = box[1].item() + box[3].item() / 2
                            col = min(int(abs_cx / (orig_w / 3)), 2)
                            row = min(int(abs_cy / (orig_h / 3)), 2)
                            grid_cell = row * 3 + col + 1
                            bbox_location_counts[grid_cell] = bbox_location_counts.get(grid_cell, 0) + 1

                            if bbox_location_counts_9x9 is not None:
                                col_9 = min(int(abs_cx / (orig_w / 9)), 8)
                                row_9 = min(int(abs_cy / (orig_h / 9)), 8)
                                grid_cell_9 = row_9 * 9 + col_9 + 1
                                bbox_location_counts_9x9[grid_cell_9] = bbox_location_counts_9x9.get(grid_cell_9, 0) + 1
                        # cv2.imwrite(f'{out_path}/debug_val_son_{j}_{crop_idx}_box.jpg', image)
                        # j += 1

        if sliding:
            original_images = targets[0]['original_image']
            
            positions = targets[0]['positions']
            crop_sizes = [torch.tensor([t["crop_size"], t["crop_size"]], device=device) for t in targets]
            input_h, input_w = samples.shape[2:]
            scale_x = crop_sizes[0][0].item() / input_w
            scale_y = crop_sizes[0][0].item() / input_h

        else:
            positions = None  
              
        targets = [{k: v.to(device) for k, v in t.items() if isinstance(v, torch.Tensor)} for t in targets]

        outputs = model(samples)

        # TODO (lyuwenyu), fix dataset converted using `convert_to_coco_api`?
        if sliding:
            orig_target_sizes = torch.stack(crop_sizes, dim=0)
            
        else:
            orig_target_sizes = torch.stack([t["orig_size"] for t in targets], dim=0)
        
        results = postprocessor(outputs, orig_target_sizes)

        # if 'segm' in postprocessor.keys():
        #     target_sizes = torch.stack([t["size"] for t in targets], dim=0)
        #     results = postprocessor['segm'](results, outputs, orig_target_sizes, target_sizes)
        image_id = targets[0]['image_id'].item()
        image_info = coco_gt.loadImgs(image_id)[0]
        image_base_name = os.path.splitext(os.path.basename(image_info.get('file_name', f'image_{image_id}')))[0]
        
        if not sliding:
            
            boxes = results[0]['boxes'].detach().cpu().numpy()
            scores = results[0]['scores'].detach().cpu().numpy()
            labels = results[0]['labels'].detach().cpu().numpy()
            
        else:
            
            boxes, scores, labels = [], [], []
            
            for i, res in enumerate(results):
                x_offset = positions[i]
                labels.append(res['labels'].detach().cpu().numpy())
                box = res['boxes'].detach().cpu().numpy()
                box[:, 0] += x_offset
                box[:, 2] += x_offset
                boxes.append(box)
                scores.append(res['scores'].detach().cpu().numpy())
                # image = samples[i, :, :, :].detach().cpu().numpy() * 255
                # image = image.astype(np.uint8)
                # image = image.transpose(1, 2, 0)
                # image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                # image = cv2.resize(image, (720, 720))
                # cv2.imwrite(f'debug_val_son_{i}.jpg', image)
                # for box_1 in box:
                #     x1, y1, x2, y2 = box_1
                #     x1 = int(x1)
                #     y1 = int(y1)
                #     x2 = int(x2)
                #     y2 = int(y2)
                #     image = cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
                # cv2.imwrite(f'debug_val_son_{i}.jpg', image)

                # pass
            boxes = np.concatenate(boxes, axis=0)
            scores = np.concatenate(scores, axis=0)
            labels = np.concatenate(labels, axis=0)
            
            sort_indices = np.argsort(-scores)  # Negative sign for descending order
            boxes = boxes[sort_indices]
            scores = scores[sort_indices]
            labels = labels[sort_indices]

            orig_length = int(len(boxes) / 3)  # Convert to integer
            boxes = boxes[:orig_length]
            scores = scores[:orig_length]
            labels = labels[:orig_length]
            keep = fast_nms(boxes, scores, sliding_nms_thresh)
            # result2 = draw(original_images, labels, boxes, scores, thrh=0.3)
            # result2.save('debug_validation_before_nms.jpg')
            boxes = boxes[keep]
            scores = scores[keep]
            labels = labels[keep]
            
            # result2 = draw(original_images, labels, boxes, scores, thrh=0.3)
            # result2.save('debug_validation.jpg')
        # numpy_array = np.array(original_images)
        
        # Check for NaN/Inf in model outputs before processing
        if np.isnan(boxes).any() or np.isinf(boxes).any():
            print("Uyarı: Model NaN/Inf üretti! Bu trial sonlandırılıyor.")
            raise ValueError("Model produced NaN/Inf values in boxes. Trial terminated.")
        if np.isnan(scores).any() or np.isinf(scores).any():
            print("Uyarı: Model NaN/Inf üretti! Bu trial sonlandırılıyor.")
            raise ValueError("Model produced NaN/Inf values in scores. Trial terminated.")
        if np.isnan(labels).any() or np.isinf(labels).any():
            print("Uyarı: Model NaN/Inf üretti! Bu trial sonlandırılıyor.")
            raise ValueError("Model produced NaN/Inf values in labels. Trial terminated.")

        if debug_val_model and debug_val_model_dir is not None:
            original_image = raw_target.get('original_image')
            if original_image is not None:
                save_validation_model_debug_image(
                    image=original_image,
                    boxes=boxes,
                    labels=labels,
                    scores=scores,
                    image_base_name=image_base_name,
                    debug_dir=debug_val_model_dir,
                    iteration_index=iter_counter,
                    draw_threshold=debug_draw_threshold,
                    labels_names=labels_names,
                )
            else:
                print(f"Skipping validation model debug image for image_id={image_id}: original_image not available.")
            iter_counter += 1
        
        # Process each detection and add to all_detections
        for box, score, label in zip(boxes, scores, labels):
            # Convert box from [x1, y1, x2, y2] to [x, y, width, height] format
            x1, y1, x2, y2 = box
            bbox = [float(x1), float(y1), float(x2 - x1), float(y2 - y1)]
            
            # Create detection dictionary
            detection = {
                'image_id': int(image_id),  # Use the image_id from the annotation file
                'category_id': int(label),
                'bbox': [float(coord) for coord in bbox],
                'score': float(score)
            }
            detections.append(detection)
            # x1, y1, w, h = detection['bbox']
            # x1 = int(x1)
            # y1 = int(y1)
            # x2 = int(x1 + w)
            # y2 = int(y1 + h)
            # original_images = np.asarray(original_images)
            # original_images = cv2.rectangle(original_images, (x1, y1), (x2, y2), (0, 0, 255), 2)
        # cv2.imwrite('debug_val_son.jpg', original_images)
        # pass
    detections_path = f'{out_path}/detections/detections_{global_step}.json'
    os.makedirs(os.path.dirname(detections_path), exist_ok=True)
    
    # Check for NaN/Inf values in detections before saving
    has_nan_or_inf = False
    for detection in detections:
        # Check bbox values
        bbox = detection['bbox']
        if any(math.isnan(val) or math.isinf(val) for val in bbox):
            has_nan_or_inf = True
            print(f"Warning: NaN/Inf found in bbox: {bbox}")
            break
        # Check score value
        score = detection['score']
        if math.isnan(score) or math.isinf(score):
            has_nan_or_inf = True
            print(f"Warning: NaN/Inf found in score: {score}")
            break
    
    # Also check boxes, scores, labels arrays if they exist in the last iteration
    # (This is a safety check, though they should have been checked during the loop)
    
    if has_nan_or_inf:
        print("Uyarı: Model NaN/Inf üretti! Bu trial sonlandırılıyor.")
        # Return a zero metric to indicate failure
        # This will be caught by the exception handler in hp_tuning.py
        raise ValueError("Model produced NaN/Inf values in detections. Trial terminated.")
    
    with open(detections_path, 'w') as f:
        json.dump(detections, f)

    coco_dt = coco_gt.loadRes(detections)
    if eval_per_video_map:
        coco_eval = COCOeval(coco_gt, coco_dt, 'bbox', ar_at_start_iou=ar_at_start_iou, ar_iou=ar_iou, ar_maxdets=ar_maxdets)
        video_map = coco_eval.evaluate_video()

        # Print video-based results
        print("\n" + "="*80)
        print("VIDEO-BASED EVALUATION RESULTS")
        print("="*80)
        for video_id, metrics in video_map.items():
            print(f"\nVideo ID: {video_id}")
            print(f"  mAP@0.50:    {metrics.get('map50', 0.0):.4f}")
            print(f"  mAP@0.30:    {metrics.get('map30', 0.0):.4f}")
            print(f"  mAP@0.30opt: {metrics.get('map30opt', 0.0):.4f}")
            print(f"  mAP@0.30rare: {metrics.get('map30rare', 0.0):.4f}")
            class_map30 = metrics.get('class_map30', {})
            if class_map30:
                print("  Class AP@0.30:")
                for class_key, class_ap in sorted(class_map30.items(), key=lambda x: x[0]):
                    print(f"    {class_key}: {class_ap:.4f}")

        # Calculate and print average metrics across all videos
        if video_map:
            def _is_sample_video(video_id):
                normalized = str(video_id).replace('\\', '/').lower()
                return 'sample' in normalized.split('/')

            video_map_for_avg = {
                vid: m for vid, m in video_map.items()
                if not _is_sample_video(vid)
            }

            # Helper function to compute average excluding -1 values
            def compute_avg(metric_key):
                values = [m.get(metric_key, -1.0) for m in video_map_for_avg.values()]
                valid_values = [v for v in values if v != -1.0]
                if not valid_values:
                    return -1.0
                return sum(valid_values) / len(valid_values)

            avg_map50 = compute_avg('map50')
            avg_map30 = compute_avg('map30')
            avg_map30opt = compute_avg('map30opt')
            avg_map30rare = compute_avg('map30rare')

            print("\n" + "-"*80)
            print("AVERAGE METRICS ACROSS ALL VIDEOS:")
            print("-"*80)
            print(f"  Average mAP@0.50:    {avg_map50:.4f}")
            print(f"  Average mAP@0.30:    {avg_map30:.4f}")
            print(f"  Average mAP@0.30opt: {avg_map30opt:.4f}")
            print(f"  Average mAP@0.30rare: {avg_map30rare:.4f}")
            print("="*80 + "\n")
    else:
        video_map = {}
        print("eval_per_video_map=False: skipped per-video COCO evaluation (full-image COCO metrics still computed below).")
    
    # Create a fresh COCOeval object for overall evaluation
    # evaluate_video() modifies the internal state, so we need a clean object
    coco_eval = COCOeval(coco_gt, coco_dt, 'bbox', ar_at_start_iou=ar_at_start_iou, ar_iou=ar_iou, ar_maxdets=ar_maxdets)
    coco_eval.evaluate()
    coco_eval.accumulate()
    coco_eval.summarize()

    stats = {'coco_eval_bbox': coco_eval.stats.tolist()}
    
    # Get all category IDs and their info
    class_ids = coco_gt.getCatIds()
    categories = coco_gt.loadCats(class_ids)
    
    # Dictionary to store PR pairs for all categories
    all_pr_pairs = {}
    
    scores_at_p70 = {}

    # operating points at precision floors {f"{id}_{name}": {target_precision: get_score_at_precision(...)}}
    operating_points = {}

    first_class_ap30 = 0.0
    # Get PR pairs for each category
    for i, class_id in enumerate(class_ids):
        try:
            if i == 0:
                pr_data_full = extract_pr_data(coco_eval, coco_gt, class_id, iou_thrs=iou_thrs)
                prec = pr_data_full['precision']
                if len(prec[prec > -1]) > 0:
                    first_class_ap30 = np.mean(prec[prec > -1])
                else:
                    first_class_ap30 = 0.0

            category_pr_pairs = get_pr_pairs_at_recalls(
                coco_eval=coco_eval, 
                coco_gt=coco_gt, 
                class_id=class_id, 
                recall_values=recall_values,
                draw_pr_curve=True,
                output_dir=out_path,
                global_step=global_step,
                iou_thrs=iou_thrs,
                hp_tuning=hp_tuning
            )
            # Store with both ID and name for easier reference
            category_name = category_pr_pairs['class_name']
            all_pr_pairs[f"{class_id}_{category_name}"] = category_pr_pairs

            score_p70_data = get_score_at_precision(
                coco_eval=coco_eval,
                coco_gt=coco_gt,
                class_id=class_id,
                target_precision=target_precision,
                iou_thrs=iou_thrs
            )
            scores_at_p70[f"{class_id}"] = score_p70_data

            # ---- operating points at precision floors (validation set) ----
            # For each precision floor, the highest-recall point with precision >= target and the
            # detection-confidence score that achieves it (custom COCOeval -> iou_thrs is AP@0.30).
            # Printed here; also returned so train_one_epoch logs them to tensorboard next to AP.
            op_for_class = {}
            for tp in operating_point_precisions:
                op = get_score_at_precision(coco_eval=coco_eval, coco_gt=coco_gt,
                                            class_id=class_id, target_precision=tp, iou_thrs=iou_thrs)
                op_for_class[tp] = op
                sc = op['score']
                sc_str = f"{sc:.4f}" if sc is not None else "n/a"
                print(f"[operating-point][{eval_tag}] {category_name} @P>={tp:g} (IoU={iou_thrs:g}): "
                      f"precision={op['actual_precision']:.4f} recall={op['actual_recall']:.4f} score={sc_str}")
            operating_points[f"{class_id}_{category_name}"] = op_for_class
        except Exception as e:
            print(f"Error processing category ID {class_id}: {e}")
            continue
    
    # Save all_pr_pairs to a JSON file
    if not hp_tuning:
        try:
            # Convert numpy arrays and other non-serializable objects to lists
            json_serializable_pr_pairs = {}
            for class_key, pr_data in all_pr_pairs.items():
                # Create a serializable copy
                serializable_data = {
                    'class_name': pr_data['class_name'],
                    'pairs': pr_data['pairs']
                }
                json_serializable_pr_pairs[class_key] = serializable_data
            
            # Save to JSON file
            
            pr_pairs_file = f'{out_path}/PR/pr_pairs_{global_step}.json'
            os.makedirs(os.path.dirname(pr_pairs_file), exist_ok=True)
            with open(pr_pairs_file, 'w') as f:
                json.dump(json_serializable_pr_pairs, f, indent=2)
            print(f"Saved PR pairs data to {pr_pairs_file}")
        except Exception as e:
            print(f"Error saving PR pairs to JSON: {e}")
    
    return stats, all_pr_pairs, video_map, scores_at_p70, bbox_height_counts, bbox_location_counts, bbox_location_counts_9x9, first_class_ap30, operating_points

def generate_debug_video_from_dataset(model,
                                      data_loader,
                                      output_video_path,
                                      postprocessor,
                                      device=None,
                                      draw_threshold=0.3):
    """
    Generates a debug video from a dataset showing model predictions and ground truth annotations.
    
    Args:
        model (torch.nn.Module): The model to evaluate
        data_loader (torch.utils.data.DataLoader): DataLoader for the dataset
        annotation_path (str): Path to the COCO annotation file
        images_path (str): Path to the directory containing images
        output_video_path (str): Path to save the output video
        postprocessor: The postprocessor to convert model outputs to bounding boxes
        device (torch.device, optional): Device to run the model on. Defaults to cuda if available.
        draw_threshold (float, optional): Threshold for drawing predicted boxes. Defaults to 0.3.
        
    Returns:
        None: The function saves the video to the specified output path
    """
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    # Ensure the directory exists
    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
    
    # Initialize COCO API for dataset
    anno = COCO(data_loader.sampler.data_source.ann_file)
    images_path = data_loader.sampler.data_source.img_folder
    
    labels_names = {}
    
    for lbl in anno.cats:
        labels_names[lbl] = anno.cats[lbl]['name']
    
    # Set up logging
    test_logger = MetricLogger(delimiter="  ")
    header = 'Creating Debug Video:'
    
    # Get a sample to determine video dimensions
    sample, target = data_loader.dataset.__getitem__(0)
    
    image_id = target['image_id'].item()
    img_file_name = anno.loadImgs(image_id)[0]['file_name']
    img_path = os.path.join(images_path, img_file_name)
    sample_img = cv2.imread(img_path)
    h, w, _ = sample_img.shape
    
    # Initialize video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_video_path, fourcc, 20.0, (w, h))
    
    # Process each sample
    for samples, targets in test_logger.log_every(data_loader, 10, header):
        samples = samples.to(device)
        targets = [{k: v.to(device) for k, v in t.items()} for t in targets]
        
        # Get model predictions
        with torch.no_grad():
            outputs = model(samples)
        
        # Get target sizes for postprocessing
        orig_target_sizes = torch.stack([t["orig_size"] for t in targets], dim=0)
        
        # Apply postprocessing
        results = postprocessor(outputs, orig_target_sizes)
        
        # Get the image ID and file path
        image_id = targets[0]['image_id'].item()
        img_file_name = anno.loadImgs(image_id)[0]['file_name']
        img_path = os.path.join(images_path, img_file_name)
        sample_img = cv2.imread(img_path)
        
        # Extract predicted boxes, scores, and labels
        boxes = results[0]['boxes'].detach().cpu().numpy()
        scores = results[0]['scores'].detach().cpu().numpy()
        labels = results[0]['labels'].detach().cpu().numpy()
        
        # Draw predicted boxes in blue
        sample_img = draw_boxes_fn(image=sample_img, bboxes=boxes, labels=labels, scores=scores,
                                   labels_names=labels_names, color='blue', draw_threshold=draw_threshold)
        
        # Get ground truth annotations
        sample_anns = anno.imgToAnns[image_id]
        tmp_ann_bboxes, tmp_cat_ids = [], []
        
        # Process ground truth annotations
        for ann in sample_anns:
            bbox = ann['bbox']
            x1, y1, x2, y2 = bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3]
            bbox = [x1, y1, x2, y2]
            
            tmp_ann_bboxes.append(bbox)
            tmp_cat_ids.append(ann['category_id'])
        
        # Draw ground truth boxes in red
        sample_img = draw_boxes_fn(image=sample_img, bboxes=tmp_ann_bboxes, labels=tmp_cat_ids,
                                  labels_names=labels_names, color='red')
        
        # Write the frame to the video
        out.write(sample_img)
    
    # Close the video writer
    out.release()
    print(f"Debug video saved to {output_video_path}")

def generate_debug_video(model,
                         criterion,
                         postprocessor,
                        #  clearml_logger,
                         current_step,
                         draw_thr,
                         img_size=1920,
                         data_loader=None,
                         input_video=None,
                         crop_size=720,
                         phase='test',
                         num_queries=100,
                         out_video_path='test',
                         original_num_queries=300,
                         device=None,
                         precision_video=None,
                         recall_video=None,
                         method='sliding'):

    
    if not os.path.exists(out_video_path):
        os.makedirs(out_video_path)
        
    out_video_path = os.path.join(out_video_path, f'iter_{current_step}_nq_{num_queries}.mp4')
    model.decoder.num_queries = num_queries
    postprocessor.num_top_queries = num_queries
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    
    test_logger = MetricLogger(delimiter="  ")
    header = 'Test:'
    
    debug_samples = []
    
    
    if data_loader is not None: 
        generate_debug_video_from_dataset(model, data_loader, out_video_path, postprocessor, device, draw_threshold=draw_thr)
    if input_video is not None:
        debug_samples = generate_debug_video_from_video(model, input_video, out_video_path, postprocessor, img_size, device, crop_size=crop_size, draw_threshold=draw_thr, precision_video=precision_video, recall_video=recall_video, method=method)
    
    model.decoder.num_queries = original_num_queries
    postprocessor.num_top_queries = original_num_queries

    return debug_samples

def preprocess_frame(frame_rgb, method='opencv', input_size=512, crop_size=720, device=None):
    
    if isinstance(input_size, (list, tuple)):
        h_size, w_size = input_size
    else:
        h_size, w_size = input_size, input_size

    if method == 'opencv':
        
        h, w = frame_rgb.shape[:2]
        orig_size = torch.tensor([[w, h]]).to(device)
        # Resize to w_size x h_size (cv2.resize expects (width, height))
        frame_resized = cv2.resize(frame_rgb, (w_size, h_size))
        
        # Convert to tensor
        frame_tensor = torch.from_numpy(frame_resized).permute(2, 0, 1).float() / 255.0
        im_data = frame_tensor.unsqueeze(0).to(device)
        blob = {'images': im_data, 'orig_target_sizes': orig_size}
        
    elif method == 'pil':
        
        pil_image = Image.fromarray(frame_rgb)
        
        # Process the frame
        w, h = pil_image.size
        orig_size = torch.tensor([[w, h]]).to(device)
        transforms = T.Compose([
            T.Resize((h_size, w_size)),
            T.ToTensor(),
        ])
        im_data = transforms(pil_image).unsqueeze(0).to(device)
        blob = {'images': im_data, 'orig_target_sizes': orig_size}
        
    elif method == 'sliding':
        preprocess_fn = SlidingRandomCropCV(crop_size=crop_size, resize_size=input_size, debug=False)
        blob, preprocess_time = preprocess_fn(frame_rgb, input_size, 'bilinear', device)
        
    
    return blob

def generate_debug_video_from_video(model,
                                   input_video,
                                   output_video_path,
                                   postprocessor,
                                   input_size=1920,
                                   device=None,
                                   draw_threshold=0.3,
                                   fps=None,
                                   labels_names=None,
                                   sample_freq=1,
                                   method='sliding',
                                   crop_size=720,
                                   precision_video=None,
                                   recall_video=None):
    """
    Generates a debug video showing model predictions on each frame of an input video.
    
    Args:
        model (torch.nn.Module): The model to evaluate
        input_video (str): Path to the input video file
        output_video_path (str): Path to save the output video
        postprocessor: The postprocessor to convert model outputs to bounding boxes
        device (torch.device, optional): Device to run the model on. Defaults to cuda if available.
        draw_threshold (float, optional): Threshold for drawing predicted boxes. Defaults to 0.3.
        fps (float, optional): Frames per second for the output video. If None, use the same as input.
        labels_names (dict, optional): Dictionary mapping label indices to names. If None, will use numbers.
        
    Returns:
        None: The function saves the video to the specified output path
    """
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    model.eval()
    
    if isinstance(input_size, (list, tuple)):
        h_size, w_size = input_size
    else:
        h_size, w_size = input_size, input_size

    transforms = T.Compose([
        T.Resize((h_size, w_size)),
        T.ToTensor(),
    ])
    # Ensure the directory exists
    
    
    # Open the input video
    cap = cv2.VideoCapture(input_video)
    
    if not cap.isOpened():
        print(f"Error: Could not open video {input_video}")
        return
    
    # Get video properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    input_fps = cap.get(cv2.CAP_PROP_FPS)
    
    # Use input fps if not specified
    if fps is None:
        fps = input_fps
    
    # Initialize video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    output_video_path = f'{os.path.dirname(output_video_path)}/test_outs/test_out_{os.path.basename(output_video_path)}'
    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
    
    # If labels_names not provided, create a placeholder
    if labels_names is None:
        labels_names = {i: str(i) for i in range(1, 10)}  # Assuming max 100 classes
    
    # Process each frame
    frame_count = 0
    print(f"Processing video with {total_frames} frames...")
    
    debug_samples = []

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_count += 1
        if frame_count % 10 == 0:
            print(f"Processing frame {frame_count}/{total_frames}")
            
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Get model predictions
        with torch.no_grad():
            blob = preprocess_frame(frame_rgb, method, input_size, crop_size, device)
            outputs = model(blob['images'])
        
        # Apply postprocessing
        results = postprocessor(outputs, blob['orig_target_sizes'])
    
        # Extract predicted boxes, scores, and labels
        if method == 'sliding':
            # For sliding window, results is a list of dicts, one for each crop
            boxes = [r['boxes'] for r in results]
            scores = [r['scores'] for r in results]
            labels = [r['labels'] for r in results]
            boxes, scores, labels = postprocess_boxes_slide(boxes, scores, labels, blob['positions'], conf_threshold=draw_threshold)
        else:
            # For other methods, results is a list with a single dict
            boxes = results[0]['boxes'].detach().cpu().numpy()
            scores = results[0]['scores'].detach().cpu().numpy()
            labels = results[0]['labels'].detach().cpu().numpy()
        
        if method == 'opencv' or method == 'sliding':
            annotated_frame = draw_opencv(frame, labels, boxes, scores, thrh=draw_threshold, precision_video=precision_video, recall_video=recall_video)
            
        else:
            # Draw predicted boxes
            annotated_frame = draw_boxes_fn(
                image=frame,
                bboxes=boxes,
                labels=labels,
                scores=scores,
                labels_names=labels_names,
                color='blue',
                draw_threshold=draw_threshold
            )
        
        # Write the frame to the output video
        out.write(annotated_frame)

        if frame_count % sample_freq == 0:
            debug_samples.append(annotated_frame)
    # Release resources
    cap.release()
    out.release()
    print(f"Debug video saved to {output_video_path}")

    return debug_samples

def draw_boxes_fn(image, bboxes, labels, scores=None, draw_threshold=0.3, labels_names=None, color='green'):
    """Draws bounding boxes, labels, and optionally scores on an image with a specified color.

    Args:
        image (numpy.ndarray): The image on which to draw the bounding boxes.
        bboxes (list of list of float): A list of bounding boxes, where each bounding box is 
            represented as [x1, y1, x2, y2].
        labels (list of int): A list of labels corresponding to the bounding boxes.
        scores (list of float, optional): A list of confidence scores corresponding to the bounding boxes.
            If not provided, only the labels and bounding boxes will be drawn.
        draw_threshold (float): The threshold above which to draw the bounding boxes. Only used if `scores` is provided.
        labels_names (dict): A dictionary mapping label indices to label names.
        color (str): The color of the bounding box. Options are 'red', 'green', and 'blue'.
            Defaults to 'green'.

    Returns:
        numpy.ndarray: The image with bounding boxes, labels, and optionally scores drawn on it.
    """
    color_map = {
        'red': (0, 0, 255),
        'green': (0, 255, 0),
        'blue': (255, 0, 0)
    }

    box_color = color_map.get(color, (0, 255, 0))

    for i, bbox in enumerate(bboxes):

        label_idx = int(labels[i])
        if type(list(labels_names.keys())[0]) == str:
            label_idx = str(label_idx)
        if label_idx == 0:
            continue
        label = labels_names[label_idx]
        x1, y1, x2, y2 = bbox
        x1 = int(x1)
        y1 = int(y1)
        x2 = int(x2)
        y2 = int(y2)
        pt1 = (x1, y1)
        pt2 = (x2, y2)
        #image = cv2.rectangle(image, pt1, pt2, box_color, 1)

        # If scores are provided, check the score against the threshold and add it to the label
        if scores is not None and scores[i] >= draw_threshold:
            label_with_score = f"{label}: {scores[i]:.2f}"
            # Get text size for background box
            (w, h), _ = cv2.getTextSize(label_with_score, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            image = cv2.rectangle(image, (x1, y1 - 20), (x1 + w, y1), box_color, -1)
            image = cv2.rectangle(image, pt1, pt2, box_color, 1)
            image = cv2.putText(image, label_with_score, (int(x1), int(y1) - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        elif scores is None:
            label_with_score = label

            # Get text size for background box
            (w, h), _ = cv2.getTextSize(label_with_score, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            image = cv2.rectangle(image, (x1, y2 + 20), (x1 + w, y2), box_color, -1)
            image = cv2.rectangle(image, pt1, pt2, box_color, 1)
            image = cv2.putText(image, label_with_score, (int(x1), int(y2) + 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        
    return image

def draw_opencv(image, labels, boxes, scores, thrh=0.4, precision_video=None, recall_video=None):
    """Draw bounding boxes on image using OpenCV"""
    # Make a copy to avoid modifying the original
    img_draw = image.copy()
    
    # Filter by threshold
    valid_indices = scores > thrh
    filtered_labels = labels[valid_indices]
    filtered_boxes = boxes[valid_indices]
    filtered_scores = scores[valid_indices]
    
    for i in range(len(filtered_labels)):
        label = filtered_labels[i].item()
        box = filtered_boxes[i].tolist()
        score = filtered_scores[i].item()
        
        # Draw rectangle
        cv2.rectangle(img_draw, 
                     (int(box[0]), int(box[1])), 
                     (int(box[2]), int(box[3])), 
                     (0, 0, 255), 2)  # Red color, thickness 2
        
        # Draw text
        text = f"{label} {round(score, 2)}"
        cv2.putText(img_draw, text, 
                   (int(box[0]), int(box[1]) - 5), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        cv2.putText(img_draw, 'thr: ' + str(round(thrh, 2)) + ' prec: ' + str(round(precision_video, 2)) + ' recall: ' + str(round(recall_video, 2)), (20, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

    return img_draw

def calculate_average_precision(pr_data, exclude_last=True, weights=None):
    """
    Calculate the average precision across all classes, optionally using weighted sum.
    
    Args:
        pr_data (dict or list): Either a dictionary with class keys and PR data as values,
                               or a list of PR data points for a single class.
        exclude_last (bool): Whether to exclude the last data point (typically recall=1.0, precision=0.0).
                            Default is True.
        weights (list, optional): List of weights for each precision value. If None, calculates a simple average.
                                 For dictionary input, weights are applied to all classes.
    
    Returns:
        float: The average precision (weighted or simple) across all classes.
    """
    # Initialize counters for sum and count of precision values
    precision_sum = 0.0
    weight_sum = 0.0
    precision_count = 0
    
    # Handle the case where pr_data is a dictionary of class PR pairs
    if isinstance(pr_data, dict):
        all_precisions = []
        # First pass to collect all precisions
        for class_key, class_pr_data in pr_data.items():
            # Get the pairs from the class data
            pairs = class_pr_data.get('pairs', class_pr_data)
            
            # Skip the last data point if requested
            data_points = pairs[:-1] if exclude_last else pairs
            
            # Collect precision values
            for point in data_points:
                all_precisions.append(point['precision'])
        
        # Apply weights
        if weights is not None:
            if len(weights) != len(all_precisions):
                print(f"Warning: Weights length ({len(weights)}) doesn't match precision values ({len(all_precisions)}). Using simple average.")
                weights = None
                
        # Calculate weighted or simple average
        if weights is not None:
            for i, precision in enumerate(all_precisions):
                precision_sum += precision * weights[i]
                weight_sum += weights[i]
        else:
            precision_sum = sum(all_precisions)
            precision_count = len(all_precisions)
    
    # Handle the case where pr_data is a list of PR pairs for a single class
    elif isinstance(pr_data, list):
        # Skip the last data point if requested
        data_points = pr_data[:-1] if exclude_last else pr_data
        
        # Verify weights if provided
        if weights is not None and len(weights) != len(data_points):
            print(f"Warning: Weights length ({len(weights)}) doesn't match precision values ({len(data_points)}). Using simple average.")
            weights = None
        
        # Calculate weighted or simple average
        if weights is not None:
            for i, point in enumerate(data_points):
                precision_sum += point['precision'] * weights[i]
                weight_sum += weights[i]
        else:
            # Sum up the precision values
            for point in data_points:
                precision_sum += point['precision']
                precision_count += 1
    
    # Calculate the average precision
    if weights is not None and weight_sum > 0:
        return precision_sum / weight_sum
    elif precision_count > 0:
        return precision_sum / precision_count
    else:
        return 0.0

def _gt_boxes_to_xyxy_for_debug(gt_boxes, h: int, w: int) -> torch.Tensor:
    """Nx4 xyxy in pixel coords for draw_bounding_boxes (matches train / val target conventions)."""
    if gt_boxes is None:
        return torch.zeros(0, 4, dtype=torch.float32)
    if isinstance(gt_boxes, BoundingBoxes):
        if len(gt_boxes) == 0:
            return torch.zeros(0, 4, dtype=torch.float32)
        t = torch.as_tensor(gt_boxes, dtype=torch.float32).reshape(-1, 4)
        fmt = gt_boxes.format.value.lower()
        return tv_ops.box_convert(t, in_fmt=fmt, out_fmt='xyxy')
    t = torch.as_tensor(gt_boxes, dtype=torch.float32).reshape(-1, 4)
    if t.numel() == 0:
        return t
    if float(t.max()) <= 1.0 + 1e-5:
        cx, cy, bw, bh = t[:, 0], t[:, 1], t[:, 2], t[:, 3]
        x1 = (cx - bw / 2) * w
        y1 = (cy - bh / 2) * h
        x2 = (cx + bw / 2) * w
        y2 = (cy + bh / 2) * h
        return torch.stack([x1, y1, x2, y2], dim=1)
    x1 = t[:, 0]
    y1 = t[:, 1]
    x2 = t[:, 0] + t[:, 2]
    y2 = t[:, 1] + t[:, 3]
    return torch.stack([x1, y1, x2, y2], dim=1)

def save_validation_debug_images(samples_tensor, image_base_name: str, debug_dir: str, iteration_index: int) -> None:
    """Save validation input crops for debugging with a specific naming pattern.
    
    Saves up to 3 crops with suffixes 0, 1, and 3 as requested, using the
    filename pattern: `{image_base_name}_{suffix}_{iteration_index}.jpg`.
    """
    os.makedirs(debug_dir, exist_ok=True)

    samples_cpu = samples_tensor.detach().cpu()
    if samples_cpu.dim() == 3:
        samples_cpu = samples_cpu.unsqueeze(0)

    # Map crop indices to requested suffixes (0 -> '0', 1 -> '1', 2 -> '3')
    idx_to_suffix = {0: '0', 1: '1', 2: '3'}

    num_to_save = min(3, samples_cpu.size(0))
    for crop_idx in range(num_to_save):
        suffix = idx_to_suffix.get(crop_idx, str(crop_idx))
        out_file = os.path.join(debug_dir, f"{image_base_name}_{suffix}_{iteration_index}.jpg")
        save_image(samples_cpu[crop_idx], out_file)
        

class SlidingRandomCropCV:
    """
    OpenCV version of SlidingRandomCrop that returns all 3 crops (left, center, right) during inference.
    Only supports 'all' mode for validation/inference.
    Supports image + target (detection dict with 'boxes').
    """
    def __init__(self, crop_size=720, resize_size=512, debug=False, debug_dir="/workspaces/deim"):
        self.crop_size = crop_size

        self.debug = debug
        self.debug_dir = debug_dir
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        # Create debug directory if it doesn't exist
        if self.debug:
            import os
            os.makedirs(self.debug_dir, exist_ok=True)
            self.debug_counter = 0

    def __call__(self, img, input_size, interpolation, device, stream=None):
        """
        Process the input image and return all 3 crops (left, center, right)
        
        Args:
            img: numpy array (H, W, C) in RGB format
        
        Returns:
            list: 3 cropped, resized, and normalized images as numpy arrays (H, W, C) with values in [0, 1]
        """
        if stream is None:
            stream = torch.cuda.Stream()
        # Ensure input is numpy array
        if not isinstance(img, np.ndarray):
            raise ValueError("Input must be a numpy array")
        
        h, w = img.shape[:2]
        
        if isinstance(input_size, int):
            input_size = (input_size, input_size)
        else:
            input_size = tuple(input_size)
        
        
        if interpolation == 'bicubic':
            interpolation = cv2.INTER_CUBIC
        elif interpolation == 'lanczos':
            interpolation = cv2.INTER_LANCZOS4
        else:
            interpolation = cv2.INTER_LINEAR
            
        if w < self.crop_size or h < self.crop_size:
            raise ValueError(f"Image size ({w},{h}) smaller than crop {self.crop_size}")

        # Calculate crop positions: left, center, right
        positions = [
            0,  # left
            (w // 2) - (self.crop_size // 2),  # center
            w - self.crop_size  # right
        ]

        images = []
        start_time = time.time()    
        for x_start in positions:

            with torch.cuda.stream(stream):

                img_tensor = torch.from_numpy(img).pin_memory().to(device, non_blocking=True)

                img_cropped_tensor = img_tensor[:, x_start:x_start + self.crop_size, :]

                img_cropped_tensor = img_cropped_tensor[:, :, [2, 1, 0]].permute(2, 0, 1).contiguous().unsqueeze(0).float()
                frame_resized = torch.nn.functional.interpolate(
                    img_cropped_tensor,
                    size=input_size,
                    mode='bilinear',
                    align_corners=False
                )
                img_tensor = frame_resized * (1.0 / 255.0)

            images.append(img_tensor)

        orig_target_sizes = torch.tensor([[self.crop_size, self.crop_size]] * 3, device=device, dtype=torch.int32)
        images_batch = torch.stack([img.squeeze() for img in images])
        end_time = time.time()
        preprocess_time = (end_time - start_time) * 1000
        blob = {
            'images': images_batch,
            'orig_target_sizes': orig_target_sizes,
            'positions': positions
        }
        
        return blob, preprocess_time
    
    def preprocess_image_crop(self, img, crop_st, crop_end, size, interpolation, device):
        
        img_tensor = torch.from_numpy(img).pin_memory().to(device, non_blocking=True)

        img_cropped_tensor = img_tensor[:, crop_st:crop_end, :]

        img_cropped_tensor = img_cropped_tensor[:, :, [2, 1, 0]].permute(2, 0, 1).contiguous().unsqueeze(0).float()
        frame_resized = torch.nn.functional.interpolate(
            img_cropped_tensor,
            size=size,
            mode='bilinear',
            align_corners=False
        )
        img_tensor = frame_resized * (1.0 / 255.0)
        
        return img_tensor
    

def postprocess_boxes_slide(boxes, scores, labels, positions, iou_threshold=0.7, conf_threshold=0.3):
    all_boxes, all_scores, all_labels = [], [], []

    for i in range(len(boxes)):
        
        x_offset = positions[i]
        
        # Detach and move to CPU
        boxes_np = boxes[i].detach().cpu().numpy()
        scores_np = scores[i].detach().cpu().numpy()
        labels_np = labels[i].detach().cpu().numpy()

        # Add the x_offset to the x-coordinates (indices 0 and 2)
        boxes_np[:, 0] += x_offset
        boxes_np[:, 2] += x_offset
        
        all_boxes.append(boxes_np)
        all_scores.append(scores_np)
        all_labels.append(labels_np)

    # Concatenate all results
    all_boxes = np.concatenate(all_boxes, axis=0)
    all_scores = np.concatenate(all_scores, axis=0)
    all_labels = np.concatenate(all_labels, axis=0)
    
    # Apply confidence threshold
    high_conf_indices = all_scores >= conf_threshold
    all_boxes = all_boxes[high_conf_indices]
    all_scores = all_scores[high_conf_indices]
    all_labels = all_labels[high_conf_indices]
    
    # Sort by score
    sorted_indices = np.argsort(-all_scores)
    
    all_boxes = all_boxes[sorted_indices]
    all_scores = all_scores[sorted_indices]
    all_labels = all_labels[sorted_indices]
    
    # Apply NMS
    keep = fast_nms(all_boxes, all_scores, iou_threshold)

    final_boxes = all_boxes[keep]
    final_scores = all_scores[keep]
    final_labels = all_labels[keep]
    
    return final_boxes, final_scores, final_labels

