""""Copyright(c) 2023 lyuwenyu. All Rights Reserved.
"""

import torch 
import torch.nn as nn 
import math
import torchvision
torchvision.disable_beta_transforms_warning()

import torchvision.transforms.v2 as T
import torchvision.transforms.v2.functional as F

import PIL
import PIL.Image

from typing import Any, Dict, List, Optional

from .._misc import convert_to_tv_tensor, _boxes_keys
from .._misc import Image, Video, Mask, BoundingBoxes
from .._misc import SanitizeBoundingBoxes

from ...core import register, GLOBAL_CONFIG
from torchvision.transforms import InterpolationMode
from typing import Union, Sequence, Tuple, List, Optional, Any, Literal, Type
from numbers import Number
import cv2
import numpy as np
from PIL import Image
# Import additional torchvision transforms

import os
import re
import glob
import json
import zipfile
import time

def _ensure_odd_kernel_size(kernel_size: int) -> int:
    return kernel_size if kernel_size % 2 == 1 else kernel_size + 1

def _to_numpy_image(image: Any) -> np.ndarray:
    if isinstance(image, np.ndarray):
        return image.copy()
    return np.array(image)

def _boxes_to_xyxy(boxes: torch.Tensor, format_str: str) -> torch.Tensor:
    xyxy_boxes = boxes.clone()

    if format_str == 'XYXY':
        return xyxy_boxes

    if format_str == 'XYWH':
        xyxy_boxes[:, 2] = xyxy_boxes[:, 0] + xyxy_boxes[:, 2]
        xyxy_boxes[:, 3] = xyxy_boxes[:, 1] + xyxy_boxes[:, 3]
        return xyxy_boxes

    if format_str == 'CXCYWH':
        cx = xyxy_boxes[:, 0]
        cy = xyxy_boxes[:, 1]
        w = xyxy_boxes[:, 2]
        h = xyxy_boxes[:, 3]
        xyxy_boxes[:, 0] = cx - (w / 2)
        xyxy_boxes[:, 1] = cy - (h / 2)
        xyxy_boxes[:, 2] = cx + (w / 2)
        xyxy_boxes[:, 3] = cy + (h / 2)
        return xyxy_boxes

    raise ValueError(f"Unsupported bbox format: {format_str}")

def _compute_box_areas(boxes: torch.Tensor, format_str: str) -> torch.Tensor:
    xyxy_boxes = _boxes_to_xyxy(boxes, format_str)
    widths = (xyxy_boxes[:, 2] - xyxy_boxes[:, 0]).clamp(min=0)
    heights = (xyxy_boxes[:, 3] - xyxy_boxes[:, 1]).clamp(min=0)
    return widths * heights

def _filter_instance_targets(targets: Dict[str, Any], keep_mask: torch.Tensor) -> Dict[str, Any]:
    filtered_targets = dict(targets)
    instance_count = int(keep_mask.numel())
    keep_mask_cpu = keep_mask.detach().cpu()
    metadata_keys = {
        'image_id',
        'orig_size',
        'size',
        'positions',
        'crop_size',
        'original_image',
        'dataset_type',
        'padding',
    }

    for key, value in targets.items():
        if key == 'boxes' or key in metadata_keys:
            continue

        if isinstance(value, torch.Tensor) and value.ndim > 0 and value.shape[0] == instance_count:
            filtered_targets[key] = value[keep_mask]
        elif isinstance(value, list) and len(value) == instance_count:
            filtered_targets[key] = [item for idx, item in enumerate(value) if bool(keep_mask_cpu[idx])]

    return filtered_targets

def _update_target_areas(targets: Dict[str, Any]) -> Dict[str, Any]:
    if 'boxes' in targets and 'area' in targets and targets['boxes'] is not None:
        boxes = targets['boxes']
        targets['area'] = _compute_box_areas(boxes, boxes.format.value)
    return targets

def _blur_regions(image: Any,
                  keep_regions: List[Sequence[float]],
                  blur_regions: List[Sequence[float]],
                  blur_kernel: int) -> Any:
    if blur_kernel <= 0 or not blur_regions:
        return image

    img_np = _to_numpy_image(image)
    ksize = _ensure_odd_kernel_size(blur_kernel)
    keep_mask = np.zeros(img_np.shape[:2], dtype=np.bool_)

    for x1, y1, x2, y2 in keep_regions:
        ix1 = max(int(x1), 0)
        iy1 = max(int(y1), 0)
        ix2 = min(int(x2), img_np.shape[1])
        iy2 = min(int(y2), img_np.shape[0])
        if ix2 > ix1 and iy2 > iy1:
            keep_mask[iy1:iy2, ix1:ix2] = True

    for x1, y1, x2, y2 in blur_regions:
        ix1 = max(int(x1), 0)
        iy1 = max(int(y1), 0)
        ix2 = min(int(x2), img_np.shape[1])
        iy2 = min(int(y2), img_np.shape[0])
        if ix2 <= ix1 or iy2 <= iy1:
            continue

        region = img_np[iy1:iy2, ix1:ix2]
        if region.size == 0:
            continue

        blurred = cv2.GaussianBlur(region, (ksize, ksize), 0)
        local_keep = keep_mask[iy1:iy2, ix1:ix2]
        blurred[local_keep] = region[local_keep]
        img_np[iy1:iy2, ix1:ix2] = blurred

    if isinstance(image, np.ndarray):
        return img_np

    return PIL.Image.fromarray(img_np)

def _crop_boxes_by_visibility(boxes: BoundingBoxes,
                              crop_left: int,
                              crop_top: int,
                              crop_width: int,
                              crop_height: int,
                              min_bbox_area_ratio: float = 0.6) -> Tuple[BoundingBoxes, torch.Tensor, List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]:
    if boxes.format.value != 'XYXY':
        raise ValueError(f"Crop visibility filtering expects XYXY boxes, got {boxes.format.value}")

    device = boxes.device
    dtype = boxes.dtype
    adjusted_boxes: List[List[float]] = []
    keep_flags: List[bool] = []
    kept_regions: List[Tuple[float, float, float, float]] = []
    partial_regions: List[Tuple[float, float, float, float]] = []

    for bbox in boxes.detach().cpu().tolist():
        x1, y1, x2, y2 = bbox
        original_area = max(x2 - x1, 0) * max(y2 - y1, 0)

        if original_area <= 0:
            keep_flags.append(False)
            continue

        clipped_x1 = max(x1 - crop_left, 0.0)
        clipped_y1 = max(y1 - crop_top, 0.0)
        clipped_x2 = min(x2 - crop_left, float(crop_width))
        clipped_y2 = min(y2 - crop_top, float(crop_height))
        clipped_area = max(clipped_x2 - clipped_x1, 0.0) * max(clipped_y2 - clipped_y1, 0.0)

        if clipped_area > 0 and clipped_area >= (min_bbox_area_ratio * original_area):
            adjusted_boxes.append([clipped_x1, clipped_y1, clipped_x2, clipped_y2])
            keep_flags.append(True)
            kept_regions.append((clipped_x1, clipped_y1, clipped_x2, clipped_y2))
        else:
            keep_flags.append(False)
            if clipped_area > 0:
                partial_regions.append((clipped_x1, clipped_y1, clipped_x2, clipped_y2))

    adjusted_boxes_tensor = torch.tensor(adjusted_boxes, dtype=dtype, device=device) if adjusted_boxes else torch.zeros((0, 4), dtype=dtype, device=device)
    keep_mask = torch.tensor(keep_flags, dtype=torch.bool, device=device)
    adjusted_boxes_tv = BoundingBoxes(adjusted_boxes_tensor, format=boxes.format, canvas_size=(crop_height, crop_width))
    return adjusted_boxes_tv, keep_mask, kept_regions, partial_regions

# Register existing transforms
RandomHorizontalFlip = register()(T.RandomHorizontalFlip)
RandomVerticalFlip = register()(T.RandomVerticalFlip)
Resize = register()(T.Resize)

ToTensor = register()(T.ToTensor)
# ToImageTensor = register()(T.ToImageTensor)
# ConvertDtype = register()(T.ConvertDtype)
# PILToTensor = register()(T.PILToTensor)
SanitizeBoundingBoxes = register(name='SanitizeBoundingBoxes')(SanitizeBoundingBoxes)
Normalize = register()(T.Normalize)
# Register new torchvision transforms

# RandomRotation = register()(T.RandomRotation)

@register()
class ResizeCV:
    def __init__(self, size: Union[int, Sequence[int]], 
                 interpolation: Union[InterpolationMode, int, str] = InterpolationMode.BILINEAR,
                 debug: bool = False,
                 return_pil: bool = False,
                 debug_dir: str = "/workspaces/deim",
                 min_bbox_area_ratio: Optional[float] = None,
                 blur_partial: int = 0) -> None:
        self.apply = cv2.resize
        self.size = size
        self.debug = debug
        self.debug_dir = debug_dir
        self.return_pil = return_pil
        self.min_bbox_area_ratio = min_bbox_area_ratio
        self.blur_partial = blur_partial
        if isinstance(interpolation, str):
            self.interpolation = cv2.INTER_CUBIC if interpolation == 'bicubic' else cv2.INTER_LINEAR
        elif isinstance(interpolation, int):
            self.interpolation = interpolation  
        else:
            self.interpolation = cv2.INTER_LINEAR
        
        # Create debug directory if it doesn't exist
        if self.debug:

            os.makedirs(self.debug_dir, exist_ok=True)
            self.debug_counter = 0

    def _draw_boxes(self, image, boxes, format_str, filename):
        """Draw bounding boxes on image and save for debugging"""

        
        # Convert PIL image to numpy if needed
        if not isinstance(image, np.ndarray):
            image = np.array(image)
        
        # Make a copy to avoid modifying the original
        debug_img = image.copy()
        
        # Convert to BGR for OpenCV if it's RGB
        if debug_img.shape[2] == 3:  # If it has 3 channels
            debug_img = cv2.cvtColor(debug_img, cv2.COLOR_RGB2BGR)
        
        # Draw each bounding box
        for box in boxes:
            if format_str == 'XYXY':
                x1, y1, x2, y2 = map(int, box)
                cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            elif format_str == 'XYWH':
                x, y, w, h = map(int, box)
                cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
            elif format_str == 'CXCYWH':
                cx, cy, w, h = map(int, box)
                x1 = int(cx - w/2)
                y1 = int(cy - h/2)
                x2 = int(cx + w/2)
                y2 = int(cy + h/2)
                cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        
        # Save the image
        cv2.imwrite(os.path.join(self.debug_dir, filename), debug_img)
        print(f"Saved debug image: {os.path.join(self.debug_dir, filename)}")

    def _transform(self, inpt: Any) -> Any:
        # Unpack the input tuple
        image, targets, dataset_obj = inpt
        
        # Convert PIL image to numpy if needed
        if not isinstance(image, np.ndarray):
            # Get original dimensions from PIL image
            if hasattr(image, 'size'):
                orig_width, orig_height = image.size
            else:
                # Fallback if size attribute doesn't exist
                orig_height, orig_width = image.shape[:2]
            # Convert to numpy array
            image = np.array(image)
        else:
            # Get dimensions from numpy array
            orig_height, orig_width = image.shape[:2]
        
        # Debug: Draw boxes on original image
        if self.debug and 'boxes' in targets and targets['boxes'] is not None:
            boxes = targets['boxes']
            bbox_format = boxes.format.value
            self._draw_boxes(
                image, 
                boxes, 
                bbox_format, 
                f"before_resize_{self.debug_counter}.jpg"
            )
        
        image_for_resize = image

        # Calculate scaling factors
        target_width, target_height = self.size
        width_scale = target_width / orig_width
        height_scale = target_height / orig_height

        # Update bounding boxes if they exist in targets
        if targets is not None:
            if 'boxes' in targets and targets['boxes'] is not None:
                boxes = targets['boxes'].clone()
                bbox_format = boxes.format

                original_boxes_xyxy = _boxes_to_xyxy(boxes, bbox_format.value)

                if bbox_format.value == 'XYXY':
                    boxes[:, 0] *= width_scale
                    boxes[:, 1] *= height_scale
                    boxes[:, 2] *= width_scale
                    boxes[:, 3] *= height_scale
                elif bbox_format.value == 'XYWH':
                    boxes[:, 0] *= width_scale
                    boxes[:, 1] *= height_scale
                    boxes[:, 2] *= width_scale
                    boxes[:, 3] *= height_scale
                elif bbox_format.value == 'CXCYWH':
                    boxes[:, 0] *= width_scale
                    boxes[:, 1] *= height_scale
                    boxes[:, 2] *= width_scale
                    boxes[:, 3] *= height_scale

                keep_mask = torch.ones((boxes.shape[0],), dtype=torch.bool, device=boxes.device)
                if self.min_bbox_area_ratio is not None and self.min_bbox_area_ratio > 0:
                    resized_boxes_xyxy = _boxes_to_xyxy(boxes, bbox_format.value)
                    original_areas = _compute_box_areas(original_boxes_xyxy, 'XYXY')
                    resized_areas = _compute_box_areas(resized_boxes_xyxy, 'XYXY')
                    keep_mask = (original_areas > 0) & (resized_areas >= (self.min_bbox_area_ratio * original_areas))

                    if self.blur_partial > 0 and (~keep_mask).any():
                        kept_regions = original_boxes_xyxy[keep_mask].detach().cpu().tolist()
                        removed_regions = original_boxes_xyxy[(~keep_mask) & (original_areas > 0)].detach().cpu().tolist()
                        image_for_resize = _blur_regions(
                            image_for_resize,
                            keep_regions=kept_regions,
                            blur_regions=removed_regions,
                            blur_kernel=self.blur_partial,
                        )

                    boxes = boxes[keep_mask]
                    targets = _filter_instance_targets(targets, keep_mask)

                targets['boxes'] = BoundingBoxes(
                    boxes, 
                    format=bbox_format, 
                    canvas_size=(target_height, target_width)
                )
                targets = _update_target_areas(targets)
                
                # Debug: Draw boxes on resized image
                if self.debug:
                    resized_preview = self.apply(src=_to_numpy_image(image_for_resize), dsize=self.size, interpolation=self.interpolation)
                    self._draw_boxes(
                        resized_preview, 
                        boxes, 
                        bbox_format.value, 
                        f"after_resize_{self.debug_counter}.jpg"
                    )
                    self.debug_counter += 1

        resized_image = self.apply(src=_to_numpy_image(image_for_resize), dsize=self.size, interpolation=self.interpolation)

        if self.return_pil and not isinstance(resized_image, PIL.Image.Image):
            resized_image = Image.fromarray(resized_image)

        return (resized_image, targets, dataset_obj)
    
    def __call__(self, *inputs: Any) -> Any:
        if len(inputs) == 1:
            inputs = inputs[0]
        return self._transform(inputs)

@register()
class RandomAffine:
    
    def __init__(self, 
                 degrees: Union[Number, Sequence], 
                 translate: Optional[Sequence[float]] = None, 
                 scale: Optional[Sequence[float]] = None, 
                 shear: Optional[Union[int, float, Sequence[float]]] = None, 
                 interpolation: Union[InterpolationMode, int] = InterpolationMode.NEAREST, 
                 fill: Union[int, float, Sequence[int], Sequence[float], None, Dict[Union[Type, str], Optional[Union[int, float, Sequence[int], Sequence[float]]]]] = 0, 
                 center: Optional[List[float]] = None,
                 p: float = 1.0) -> None:
        
        self.apply = T.RandomApply(transforms=[T.RandomAffine(degrees=degrees, 
                                                              translate=translate, 
                                                              scale=scale, 
                                                              shear=shear, 
                                                              interpolation=interpolation, 
                                                              fill=fill, 
                                                              center=center)], 
                                   p=p)

    def _transform(self, inpt: Any) -> Any:
        # Handle tuple input (image, target, dataset)
        if isinstance(inpt, tuple) and len(inpt) == 3:
            image, target, dataset = inpt
            if not isinstance(image, PIL.Image.Image):
                image = Image.fromarray(image)
            
            # T.RandomApply expects (image, target) tuple
            result = self.apply(image, target)
            # Return with dataset
            if isinstance(result, tuple):
                return result + (dataset,)
            else:
                return (result, target, dataset)
        else:
            # Single input - handle as before
            if not isinstance(inpt, PIL.Image.Image):
                if isinstance(inpt, tuple) and len(inpt) > 0:
                    image = Image.fromarray(inpt[0])
                else:
                    image = Image.fromarray(inpt)
            else:
                image = inpt
            return self.apply(image)

    def __call__(self, *inputs: Any) -> Any:
        return self._transform(*inputs)

@register() 
class RandomRotation:
    
    def __init__(self, degrees: float, fill: float = 0, p: float = 1.0) -> None:

        random_rotation = T.RandomRotation(degrees=degrees, fill=fill)
        self.apply = T.RandomApply(transforms=[random_rotation], p=p)
        
    def _transform(self, inpt: Any) -> Any:
        # Handle tuple input (image, target, dataset)
        if isinstance(inpt, tuple) and len(inpt) == 3:
            image, target, dataset = inpt
            result = self.apply(image, target)
            if isinstance(result, tuple):
                return result + (dataset,)
            else:
                return (result, target, dataset)
        else:
            return self.apply(inpt)
        
    def __call__(self, *inputs: Any) -> Any:
        return self._transform(*inputs)

        

    
import torchvision.transforms.v2 as T
from torchvision.transforms.v2 import InterpolationMode
from typing import Union, Sequence, Tuple, Optional, Any
import random
import torch

@register()
class ColorJitter:
    
    def __init__(self, 
                 brightness: Optional[Union[float, Sequence[float]]] = None, 
                 contrast: Optional[Union[float, Sequence[float]]] = None, 
                 saturation: Optional[Union[float, Sequence[float]]] = None,
                 hue: Optional[Union[float, Sequence[float]]] = None,
                 p: float = 1.0, apply_folders=None) -> None:

        self.apply = T.RandomApply(transforms=[T.ColorJitter(brightness=brightness,
                                                             contrast=contrast,
                                                             saturation=saturation,
                                                             hue=hue)],
                                   p=p)
        self.apply_folders = {f.lower() for f in apply_folders} if apply_folders else None

    def __call__(self, *inputs: Any) -> Any:
        sample = inputs[0] if len(inputs) == 1 else inputs
        if self.apply_folders is not None and isinstance(sample, tuple):
            t = sample[1] if len(sample) > 1 else None
            d = sample[2] if len(sample) > 2 else None
            if not _source_allowed(t, d, self.apply_folders):
                return sample
        return self.apply(sample)

# Single source of truth for the math used by both the standalone single-op transforms
# (ContrastGain / GammaAdjust / UnsharpMask / BilateralDenoise) and the bundled
def _enh_contrast(out, gain):
    """Global contrast gain about the per-image mean (>1 stretches contrast)."""
    if gain == 1.0:
        return out
    mean = float(out.mean())
    return (out - mean) * gain + mean

def _enh_gamma(out, g):
    """Gamma tone curve (<1 brightens faint warm targets)."""
    if g == 1.0:
        return out
    out = np.clip(out, 0, 255)
    return np.power(out / 255.0, g) * 255.0

def _enh_sharpen(out, amount, sigma):
    """Unsharp mask: out + amount*(out - GaussianBlur(out, sigma))."""
    if amount <= 0:
        return out
    blur = cv2.GaussianBlur(out, (0, 0), float(sigma)).reshape(out.shape)
    return out + amount * (out - blur)

def _enh_denoise(out, sigma, d):
    """Edge-preserving bilateral denoise (kills sensor/FPN noise, keeps edges); 1/3-ch only."""
    if sigma <= 0 or out.shape[2] not in (1, 3):
        return out
    u8 = np.clip(out, 0, 255).astype(np.uint8)
    if u8.shape[2] == 1:
        return cv2.bilateralFilter(u8[..., 0], int(d), float(sigma), float(sigma))[..., None].astype(np.float32)
    return cv2.bilateralFilter(u8, int(d), float(sigma), float(sigma)).astype(np.float32)

@register()
class EmptyTransform(T.Transform):
    def __init__(self, ) -> None:
        super().__init__()

    def forward(self, *inputs):
        inputs = inputs if len(inputs) > 1 else inputs[0]
        return inputs
    
    def _transform(self, inpt: Any, params: Dict[str, Any] = None) -> Any:
        return self.forward(inpt)

@register()
class PadToSize(T.Pad):
    _transformed_types = (
        PIL.Image.Image,
        Image,
        Video,
        Mask,
        BoundingBoxes,
    )
    def _get_params(self, flat_inputs: List[Any]) -> Dict[str, Any]:
        sp = flat_inputs[0].size
        h, w = self.size[1] - sp[0], self.size[0] - sp[1]
        self.padding = [0, 0, w, h]
        return dict(padding=self.padding)

    def __init__(self, size, fill=0, padding_mode='constant') -> None:
        if isinstance(size, int):
            size = (size, size)
        self.size = size
        self.fill = fill
        super().__init__(0, fill, padding_mode)

    def _transform(self, inpt: Any, params: Dict[str, Any]) -> Any:        
        fill = self.fill
        padding = params['padding']
        return F.pad(inpt, padding=padding, fill=fill, padding_mode=self.padding_mode)  # type: ignore[arg-type]

    def __call__(self, *inputs: Any) -> Any:
        outputs = super().forward(*inputs)
        if len(outputs) > 1 and isinstance(outputs[1], dict):
            outputs[1]['padding'] = torch.tensor(self.padding)
        return outputs

@register()
class ConvertBoxes(T.Transform):
    _transformed_types = (
        BoundingBoxes,
    )
    def __init__(self, fmt='', normalize=False) -> None:
        super().__init__()
        self.fmt = fmt
        self.normalize = normalize

    def _transform(self, inpt: Any, params: Dict[str, Any]) -> Any:  
        spatial_size = getattr(inpt, _boxes_keys[1])
        if self.fmt:
            in_fmt = inpt.format.value.lower()
            inpt = torchvision.ops.box_convert(inpt, in_fmt=in_fmt, out_fmt=self.fmt.lower())
            inpt = convert_to_tv_tensor(inpt, key='boxes', box_format=self.fmt.upper(), spatial_size=spatial_size)
            
        if self.normalize:
            inpt = inpt / torch.tensor(spatial_size[::-1]).tile(2)[None]

        return inpt

@register()
class ConvertPILImage(T.Transform):
    _transformed_types = (
        PIL.Image.Image,
    )
    def __init__(self, dtype='float32', scale=True) -> None:
        super().__init__()
        self.dtype = dtype
        self.scale = scale

    def _transform(self, inpt: Any, params: Dict[str, Any]) -> Any:  
        inpt = F.pil_to_tensor(inpt)
        if self.dtype == 'float32':
            inpt = inpt.float()

        if self.scale:
            inpt = inpt / 255.

        inpt = Image(inpt)

        return inpt
    

    

    

def _sample_source_path_segments(target, dataset):
    """Resolve the source-relevant path of the current sample as a list of lowercase
    segments (e.g. ['sample', 'sample', 'dji_...', 'frame_000000.png']).

    Mirrors dataset._extract_main_folder's normalization (drop everything up to and
    including an 'images' segment if present) but keeps ALL remaining segments instead
    of just the first — this is what lets apply_folders gate on nested sub-paths like
    'sample/sample'. Returns None if it can't be resolved."""
    try:
        if not isinstance(target, dict) or dataset is None:
            return None
        img_id = target.get('image_id')
        if img_id is None:
            return None
        img_id = int(img_id.item()) if hasattr(img_id, 'item') else int(img_id)
        path = dataset.coco.loadImgs(img_id)[0]['file_name']
        parts = [p for p in path.replace('\\', '/').strip('/').split('/') if p]
        if not parts:
            return None
        if 'images' in parts:
            parts = parts[parts.index('images') + 1:]
        return [p.lower() for p in parts]
    except Exception:
        return None

def _source_allowed(target, dataset, apply_folders):
    """Source gate for source-conditional augmentations. `apply_folders` is a set/list
    of lowercase names (or None/empty = all sources). Each entry is either:
      * a single top-level folder ('sample')      -> matched against the sample's main
        source folder (the segment after 'images', else the first path segment), or
      * a nested sub-path ('sample/sample') -> matched as a segment-aware prefix
        of the sample's source path, so 'sample/sample' does NOT match an
        'sample/sample' sample.
    Note _extract_main_folder collapses every 'sample/*' to 'sample', so a
    nested entry is the ONLY way to scope to a single empty-frame sub-source.
    Returns True if allowed; False if the source can't be resolved while gating is on
    (so a gated transform skips, staying safe)."""
    if not apply_folders:
        return True
    segs = _sample_source_path_segments(target, dataset)
    if not segs:
        return False
    # single-segment (main-folder) match — back-compat
    if segs[0] in apply_folders:
        return True
    # nested sub-path match — segment-aware prefix
    for entry in apply_folders:
        if '/' in entry:
            sub = entry.split('/')
            if segs[:len(sub)] == sub:
                return True
    return False

# ===========================================================================
# Copy-Paste augmentation (runtime / "phase 2")
# ===========================================================================
# Phase 1 (offline, GPU, in the sam2 repo) segments the copy-FROM objects and
# writes their masks as compressed RLE into a COCO json. Phase 2 (this transform)
# runs inside the training dataloader: it loads that json ONCE at construction,
# decodes every object's mask a SINGLE time into a small bbox-cropped RGB + alpha
# patch held in RAM, and from then on every paste is pure numpy slicing + one
# alpha blend -- no RLE decode, no image open, no full-frame allocation in the
# hot loop. Tiny IR targets make the in-RAM pool cheap.
#
# Inserted EARLY in the transform `ops` (before geometric/photometric augs and
# ResizeCV/ToTensor): it works at full source resolution, the pasted boxes then
# flow through the SAME flip/affine/resize/normalize as real boxes, and the
# brightness / tone math operates on uint8 like the other photometric ops.

_CP_ALT_RE = re.compile(r"(\d+\.\d+-\d+\.\d+)m")
_CP_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)

def _cp_parse_altitude(name):
    m = _CP_ALT_RE.search(name or '')
    return m.group(1) if m else None

# ratio band (dest_mid / src_mid, either direction) counted as "roughly 2x"
_CP_2X_LO, _CP_2X_HI = 1.5, 2.5

def _cp_altitude_mid(token):
    """Midpoint (mean of lo-hi) of a '<lo>-<hi>' altitude token, or None.

    e.g. '30.0-40.0' -> 35.0. Used for altitude-ratio scaling and 2x pairing."""
    if not token:
        return None
    try:
        lo, hi = token.split('-')
        return (float(lo) + float(hi)) / 2.0
    except (ValueError, AttributeError):
        return None

def _cp_read_pool_dict(path):
    """Load a COCO-style pool dict from a .json file or a .zip archive.

    For a .zip, the inner ``seg.json`` is preferred, else the first ``*.json``."""
    if str(path).lower().endswith('.zip'):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith('.json')]
            if not names:
                return None
            inner = next((n for n in names
                          if os.path.basename(n).lower() == 'seg.json'), names[0])
            with z.open(inner) as f:
                return json.load(f)
    with open(path, 'r') as f:
        return json.load(f)

def _cp_iter_pool_sources(pool_ann):
    """Yield (tag, group, data_dict) for every pool source in ``pool_ann``.

    ``pool_ann`` may be a single ``.json``/``.zip`` path, a directory (searched
    RECURSIVELY for every ``*.json`` and ``*.zip``), or a list of any of those.

    ``tag`` is the source basename minus the ``.json``/``.zip`` extension and a
    trailing ``_seg`` (i.e. the video/sequence name).

    ``group`` is the source file's directory RELATIVE to ``pool_ann`` -- e.g. a zip
    at ``<pool_ann>/sample/<seq>_seg.zip`` yields ``group='sample'``; one directly in
    ``pool_ann`` (or a single file / explicit list) yields ``group=''``. Because the
    seg.json itself records NO subfolder (bare ``file_name``, empty ``info``), the
    directory you drop the zip in is the ONLY source of the sample/sample identity:
    ``_build_pool`` prefixes ``<group>/<tag>/`` onto bare ``file_name``s so each mask
    resolves under ``<images_root>/<group>/<tag>/...`` AND carries the subfolder name,
    which is what makes ``from_folders`` (and folder-scoped altitude) work on the pool."""
    if isinstance(pool_ann, (list, tuple)):
        items = [(str(p), '') for p in pool_ann]
    elif os.path.isdir(pool_ann):
        # recurse: prefer *_seg.zip (the mask archives); only fall back to every *.zip
        # when none exist, so a tree mixing mask + plain-instance archives picks the masks
        seg_zips = glob.glob(os.path.join(pool_ann, '**', '*_seg.zip'), recursive=True)
        zips = seg_zips or glob.glob(os.path.join(pool_ann, '**', '*.zip'), recursive=True)
        jsons = glob.glob(os.path.join(pool_ann, '**', '*.json'), recursive=True)
        items = []
        for p in sorted(jsons + zips):
            rel = os.path.relpath(os.path.dirname(p), pool_ann).replace('\\', '/')
            items.append((p, '' if rel == '.' else rel))
    else:
        items = [(pool_ann, '')]
    for it, group in items:
        tag = re.sub(r'\.(json|zip)$', '', os.path.basename(it), flags=re.I)
        tag = re.sub(r'_seg$', '', tag, flags=re.I)
        try:
            data = _cp_read_pool_dict(it)
        except Exception:
            data = None
        if data:
            yield tag, group, data

def _cp_folder_match(file_name, folder_set):
    """True if any name in ``folder_set`` matches ``file_name``'s path.

    A bare name (e.g. 'sample') matches ONLY the top-level / main folder -- the
    component after 'images/' if present, else the first one -- so 'sample' matches
    'sample/<vid>/frame.png' but NOT 'sample/sample/<vid>/frame.png'. To reach a
    nested folder, give a slash-bearing token: 'sample/sample' matches that
    contiguous sub-path anywhere, and 'sample' (bare) matches every frame
    whose main folder is sample. An empty / None set matches everything; the
    trailing frame filename is ignored so a name only ever matches folders."""
    if not folder_set:
        return True
    parts = [p for p in file_name.replace('\\', '/').strip('/').lower().split('/') if p]
    dirs = parts[:-1] if len(parts) > 1 else parts   # drop the frame filename
    if not dirs:
        return False
    if 'images' in dirs:
        i = dirs.index('images')
        main = dirs[i + 1] if i + 1 < len(dirs) else dirs[0]
    else:
        main = dirs[0]
    for f in folder_set:
        f = f.strip('/').lower()
        if not f:
            continue
        if '/' in f:
            toks = [t for t in f.split('/') if t]
            n = len(toks)
            if n and any(dirs[i:i + n] == toks for i in range(len(dirs) - n + 1)):
                return True
        elif f == main:
            return True
    return False

def _cp_iou_xyxy(a, b) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0

def _cp_decode_rle(seg):
    """Compressed-RLE dict -> HxW uint8 mask (pycocotools, lazy import)."""
    from pycocotools import mask as mask_utils
    counts = seg['counts']
    rle = {'size': seg['size'],
           'counts': counts.encode('ascii') if isinstance(counts, str) else counts}
    m = mask_utils.decode(rle)
    if m.ndim == 3:          # defensive: collapse a trailing singleton channel
        m = m[..., 0]
    return m

