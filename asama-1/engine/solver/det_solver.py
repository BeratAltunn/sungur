"""Copyright(c) 2023 lyuwenyu. All Rights Reserved.
"""

import time 
import json
import datetime
import os
from collections import Counter

import torch 

from ..misc import dist_utils, profiler_utils

from ._solver import BaseSolver
from .det_engine import train_one_epoch, evaluate
from ..optim.lr_scheduler import FlatCosineLRScheduler


class DetSolver(BaseSolver):
    def _print_default_sampling_debug_stats(self, epoch: int, global_step: int = None):
        dataset = getattr(self.train_dataloader, 'dataset', None)
        if dataset is None or not hasattr(dataset, 'get_sampling_debug_snapshot'):
            return

        snapshot = dataset.get_sampling_debug_snapshot()
        snapshots = dist_utils.all_gather(snapshot)

        if not dist_utils.is_main_process():
            return

        merged_bucket_counts = Counter()
        merged_folder_counts = Counter()
        merged_total = 0
        configured_buckets = []

        for item in snapshots:
            merged_total += item.get('total', 0)
            merged_bucket_counts.update(item.get('bucket_counts', {}))
            merged_folder_counts.update(item.get('main_folder_counts', {}))
            if not configured_buckets:
                configured_buckets = item.get('configured_buckets', [])

        if merged_total == 0:
            return

        prefix = f"[Epoch {epoch}]"
        if global_step is not None:
            prefix = f"[Epoch {epoch} | step {global_step}]"

        print(f"{prefix} Default sampling distribution:")
        for bucket in configured_buckets:
            count = merged_bucket_counts.get(bucket, 0)
            ratio = 100.0 * count / merged_total
            print(f"  - {bucket}: {ratio:.2f}% ({count}/{merged_total})")

        print(f"{prefix} Sampled main-folder distribution:")
        for folder, count in sorted(merged_folder_counts.items(), key=lambda x: x[1], reverse=True):
            ratio = 100.0 * count / merged_total
            print(f"  - {folder}: {ratio:.2f}% ({count}/{merged_total})")

    
    def fit(self, ):
        print("Start training")
        args = self.cfg
        hp_tuning = args.global_cfg.get('hp_tuning', False)
        self.hp_tuning = hp_tuning
        self.train()
        

        self.output_dir = args.global_cfg.get('output_dir', 'output_eval_train')
        epoches_hp = args.global_cfg.get('epoches_hp', 1)
        
        if hp_tuning:
            epoches = epoches_hp
        else:
            epoches = args.global_cfg.get('epoches', 20)
        
        freeze_backbone_iters = args.global_cfg.get('freeze_backbone_iters', 1000)
        eval_freq = args.global_cfg.get('eval_freq', 12000)
        # Hard cap on the number of optimization steps (global_step). 0 disables it.
        # Expressed in the same sample-units as eval_freq and rescaled by
        # total_batch_size in YAMLConfig, so it stays on the same order as eval_freq.
        max_iters = args.global_cfg.get('max_iters', 0) or 0
        eval_freq_hp = args.global_cfg.get('eval_freq_hp', 500)
        test_freq_mul = args.global_cfg.get('test_freq_mul', 5)
        log_freq = args.global_cfg.get('log_freq', 100)
        recall_values = args.global_cfg.get('recall_values', [0.5, 1, 50])
        recall_weights = args.global_cfg.get('recall_weights', [1, 2, 2])
        freeze_neck_iters = args.global_cfg.get('freeze_neck_iters', 1000)
        target_precision = args.global_cfg.get('target_precision', 0.7)
        operating_point_precisions = args.global_cfg.get('operating_point_precisions', [0.80, 0.90, 0.95, 0.98, 0.99, 1.0])
        ar_at_start_iou = args.global_cfg.get('ar_at_start_iou', False)
        # Single-point AR for TensorBoard: one AR at a single IoU=ar_iou and budget ar_maxdets.
        ar_iou = args.global_cfg.get('ar_iou', None)
        ar_maxdets = args.global_cfg.get('ar_maxdets', None)
        sliding_nms_thresh = args.global_cfg.get('sliding_nms_thresh', 0.7)
        print_classwise = args.global_cfg.get('print_classwise', False)
        n_parameters = sum([p.numel() for p in self.model.parameters() if p.requires_grad])
        debug_images = args.global_cfg.get('debug_images', False)
        debug_val_model = args.global_cfg.get('debug_val_model', False)
        debug_base_dir = args.global_cfg.get('debug_dir', 'debug_crops_default')
        hp_tuning_logs = args.global_cfg.get('hp_tuning_logs', False)
        writer = self.writer if (not hp_tuning or hp_tuning_logs) else None

        if debug_images or debug_val_model:
            os.makedirs(debug_base_dir, exist_ok=True)

        debug_dir = debug_base_dir if debug_images else None
        debug_val_model_dir = debug_base_dir if debug_val_model else None
            
        if args.val_dataloader.collate_fn.val_type == 'sliding':
            crop_size = args.val_dataloader.dataset._transforms.transforms[0].crop_size
            resize_size = args.val_dataloader.dataset._transforms.transforms[0].resize_size
        else:
            crop_size = 1080
            
        print(f'number of trainable parameters: {n_parameters}')
        
        if not hp_tuning:
            print(f'bs: {args.global_cfg.get("train_dataloader", {}).get("total_batch_size", 1)}')
            print(f'eval_freq: {eval_freq}')
            print(f'freeze_backbone_iters: {freeze_backbone_iters}')
            print(f'freeze_neck_iters: {freeze_neck_iters}')
            print(f'test_freq_mul: {test_freq_mul}')
            print(f'log_freq: {log_freq}')
            print(f'recall_values: {recall_values}')
            print(f'lr milestones: {args.global_cfg.get("lr_scheduler", {}).get("milestones", [])}')
            print(f'lr gamma: {args.global_cfg.get("lr_scheduler", {}).get("gamma", 0.1)}')
            print(f'lr: {args.global_cfg.get("optimizer", {}).get("lr", 0.0004)}')
            print(f'Number of queries: {args.global_cfg.get("DFINETransformer", {}).get("num_queries", None)}')
            
        else:
            print(f'freeze_backbone_iters: {freeze_backbone_iters}')
            print(f'freeze_neck_iters: {freeze_neck_iters}')
            print(f'Number of queries: {args.global_cfg.get("DFINETransformer", {}).get("num_queries", None)}')
            print(f'Batch size: {args.global_cfg.get("train_dataloader", {}).get("total_batch_size", None)}')
            print(f'lr: {args.global_cfg.get("optimizer", {}).get("lr", None)}')
            print(f'sliding_nms_thresh: {sliding_nms_thresh}')
            
        best_stat = {'epoch': -1, }
        print('Num epoches: ', epoches)
        start_time = time.time()
        start_epcoch = self.last_epoch + 1
        self.best_ap_50 = 0.0
        self.best_ap_30 = 0.0
        self.average_weighted_precision = 0
        self.video_map_30_mean = 0
        self.video_map_30_geo_mean = 0
        self.video_map_30_harmonic_mean = 0
        self.first_class_metric = 0
        self.classwise_metrics = {}
        val_annotation_path = args.global_cfg['val_dataloader']['dataset']['ann_file']
        # GT for the second (low-contrast / TestDataset) eval pass must match the
        # dataloader it iterates: test_dataloader has its OWN ann_file (different
        # image_ids than val). Falling back to val's ann_file makes loadImgs() raise
        # KeyError on the first test image_id when test != a copy of val.
        test_annotation_path = (
            args.global_cfg.get('test_dataloader', {}).get('dataset', {}).get('ann_file')
            or val_annotation_path
        )
        bbox_height_counts_train = {}
        bbox_height_counts_val = {}
        bbox_location_counts_train = {}
        bbox_location_counts_val = {}
        bbox_location_counts_train_9x9 = {}
        bbox_location_counts_val_9x9 = {}
        for epoch in range(start_epcoch, epoches):
            dataset = getattr(self.train_dataloader, 'dataset', None)
            if dataset is not None and hasattr(dataset, 'reset_sampling_debug_stats'):
                dataset.reset_sampling_debug_stats()

            self.train_dataloader.set_epoch(epoch)
            # self.train_dataloader.dataset.set_epoch(epoch)
            if dist_utils.is_dist_available_and_initialized():
                self.train_dataloader.sampler.set_epoch(epoch)
                
      
            train_stats, self.best_ap_50, self.best_ap_30, average_weighted_precision, video_map_30_mean, video_map_30_geo_mean, video_map_30_harmonic_mean, self.first_class_metric, self.classwise_metrics = train_one_epoch(
                self.__dict__,
                self.model, 
                self.criterion, 
                self.train_dataloader, 
                self.optimizer, 
                self.device, 
                self.lr_scheduler,
                epoch, 
                max_norm=args.clip_max_norm, 
                print_freq=args.print_freq, 
                freeze_backbone_iters=freeze_backbone_iters,
                freeze_neck_iters=freeze_neck_iters,
                ema=self.ema, 
                scaler=self.scaler, 
                lr_warmup_scheduler=self.lr_warmup_scheduler,
                writer=writer,
                val_dataloader=self.val_dataloader,
                test_dataloader=self.test_dataloader,
                evaluator=self.evaluator,
                postprocessor=self.postprocessor,
                output_dir=self.output_dir,
                model_dir=self.model_dir,
                eval_freq=eval_freq,
                eval_freq_hp=eval_freq_hp,
                max_iters=max_iters,
                test_freq_mul=test_freq_mul,
                best_stat=best_stat,
                best_ap_50=self.best_ap_50,
                best_ap_30=self.best_ap_30,
                average_weighted_precision=self.average_weighted_precision,
                video_map_30_mean=self.video_map_30_mean,
                video_map_30_geo_mean=self.video_map_30_geo_mean,
                video_map_30_harmonic_mean=self.video_map_30_harmonic_mean,
                first_class_metric=self.first_class_metric,
                hp_tuning=hp_tuning,
                val_annotation_path=val_annotation_path,
                test_annotation_path=test_annotation_path,
                recall_values=recall_values,
                recall_weights=recall_weights,
                log_freq=log_freq,
                target_precision=target_precision,
                operating_point_precisions=operating_point_precisions,
                ar_at_start_iou=ar_at_start_iou,
                ar_iou=ar_iou,
                ar_maxdets=ar_maxdets,
                sliding_nms_thresh=sliding_nms_thresh,
                crop_size=crop_size,
                resize_size=640,
                debug_dir=debug_dir,
                debug_val_model=debug_val_model,
                debug_val_model_dir=debug_val_model_dir,
                bbox_height_counts_train=bbox_height_counts_train,
                bbox_height_counts_val=bbox_height_counts_val,
                bbox_location_counts_train=bbox_location_counts_train,
                bbox_location_counts_val=bbox_location_counts_val,
                bbox_location_counts_train_9x9=bbox_location_counts_train_9x9,
                bbox_location_counts_val_9x9=bbox_location_counts_val_9x9,
                print_classwise=print_classwise,
                classwise_metrics=self.classwise_metrics,
                sampling_debug_hook=self._print_default_sampling_debug_stats,
            )


            self.last_epoch += 1

            # If train_one_epoch hit the global-step cap this epoch, don't start a
            # new one. (epoch+1)*steps_per_epoch is the global_step the next epoch
            # would begin at, so >= max_iters means we're already done.
            if max_iters and (epoch + 1) * len(self.train_dataloader) >= max_iters:
                print(f"Reached max_iters={max_iters} global steps; stopping training after epoch {epoch}.")
                break


        total_time = time.time() - start_time
        total_time_str = str(datetime.timedelta(seconds=int(total_time)))
        print('Training time {}'.format(total_time_str))

        return self.best_ap_50, self.best_ap_30, average_weighted_precision, video_map_30_mean, video_map_30_geo_mean, video_map_30_harmonic_mean, self.first_class_metric, self.classwise_metrics

    def val(self, ):
        self.eval()
        
        module = self.ema.module if self.ema else self.model
        test_stats, coco_evaluator = evaluate(module, self.criterion, self.postprocessor,
                self.val_dataloader, self.evaluator, self.device)
                
        # if self.output_dir:
        #     dist_utils.save_on_master(coco_evaluator.coco_eval["bbox"].eval, self.output_dir / "eval.pth")
        
        return
