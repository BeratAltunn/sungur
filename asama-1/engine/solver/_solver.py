"""Copyright(c) 2023 lyuwenyu. All Rights Reserved.
"""

import torch 
import torch.nn as nn 

from datetime import datetime
from pathlib import Path 
from typing import Dict
import atexit
import time
from ..misc import dist_utils
from ..core import BaseConfig
import os

def to(m: nn.Module, device: str):
    if m is None:
        return None 
    return m.to(device) 


def remove_module_prefix(state_dict):
    new_state_dict = {}
    for k, v in state_dict.items():
        if k.startswith('module.'):
            new_state_dict[k[7:]] = v
        else:
            new_state_dict[k] = v
    return new_state_dict


class BaseSolver(object):
    def __init__(self, cfg: BaseConfig) -> None:
        self.cfg = cfg 
        self.hp_tuning = cfg.global_cfg.get('hp_tuning', False)

    def _setup(self, ):
        """Avoid instantiating unnecessary classes 
        """
        cfg = self.cfg
        if cfg.device:
            device = torch.device(cfg.device)
        else:
            device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        self.model = cfg.model
        
        # NOTE (lyuwenyu): must load_tuning_state before ema instance building
        if self.cfg.tuning:
            print(f'tuning checkpoint from {self.cfg.tuning}')
            self.load_tuning_state(self.cfg.tuning)

        self.model = dist_utils.warp_model(
            self.model.to(device), sync_bn=cfg.sync_bn, find_unused_parameters=cfg.find_unused_parameters
        )

        self.criterion = self.to(cfg.criterion, device)
        self.postprocessor = self.to(cfg.postprocessor, device)

        self.ema = self.to(cfg.ema, device)
        self.scaler = cfg.scaler

        self.device = device
        self.last_epoch = self.cfg.last_epoch
        
        self.output_dir = cfg.output_dir
        if self.hp_tuning:
            # self.model_dir = f'{self.output_dir}/checkpoints/{time.strftime("%d%m%Y_%H%M%S")}_hp_tuning'
            self.model_dir = f'{self.output_dir}/checkpoints/hp_tuning/{time.strftime("%d%m%Y_%H%M%S")}'
        else:
            self.model_dir = f'{self.output_dir}/checkpoints/{time.strftime("%d%m%Y_%H%M%S")}'
        
        if not os.path.exists(self.model_dir):
            os.makedirs(self.model_dir)
        cfg.summary_dir = self.model_dir
        self.writer = cfg.writer
        self.writer.logdir = self.model_dir
        
        if self.writer:
            atexit.register(self.writer.close)
            if dist_utils.is_main_process():
                self.writer.add_text(f'config', '{:s}'.format(cfg.__repr__()), 0)
    def cleanup(self, ):
        if self.writer:
            atexit.register(self.writer.close)

    def train(self, ):
        self._setup()
        self.optimizer = self.cfg.optimizer
        self.lr_scheduler = self.cfg.lr_scheduler
        self.lr_warmup_scheduler = self.cfg.lr_warmup_scheduler

        self.train_dataloader = dist_utils.warp_loader(
            self.cfg.train_dataloader, shuffle=self.cfg.train_dataloader.shuffle
        )
        self.val_dataloader = dist_utils.warp_loader(
            self.cfg.val_dataloader, shuffle=self.cfg.val_dataloader.shuffle
        )
        self.test_dataloader = dist_utils.warp_loader(
            self.cfg.test_dataloader, shuffle=self.cfg.test_dataloader.shuffle
        )
        self.evaluator = self.cfg.evaluator

        # NOTE instantiating order
        if self.cfg.resume:
            print(f'Resume checkpoint from {self.cfg.resume}')
            self.load_resume_state(self.cfg.resume)

    def eval(self, ):
        self._setup()

        self.val_dataloader = dist_utils.warp_loader(
            self.cfg.val_dataloader, shuffle=self.cfg.val_dataloader.shuffle
        )

        self.evaluator = self.cfg.evaluator
        
        if self.cfg.resume:
            print(f'Resume checkpoint from {self.cfg.resume}')
            self.load_resume_state(self.cfg.resume)

    def to(self, module, device):
        return module.to(device) if hasattr(module, 'to') else module

    def state_dict(self):
        """state dict, train/eval
        """
        state = {}
        state['date'] = datetime.now().isoformat()
        
        # TODO for resume
        state['last_epoch'] = self.last_epoch

        for k, v in self.__dict__.items():
            if hasattr(v, 'state_dict'):
                v = dist_utils.de_parallel(v)
                state[k] = v.state_dict() 

        return state


    def load_state_dict(self, state):
        """load state dict, train/eval
        """
        # TODO
        if 'last_epoch' in state:
            self.last_epoch = state['last_epoch']
            print('Load last_epoch')

        for k, v in self.__dict__.items():
            if hasattr(v, 'load_state_dict') and k in state:
                v = dist_utils.de_parallel(v)
                v.load_state_dict(state[k])
                print(f'Load {k}.state_dict')

            if hasattr(v, 'load_state_dict') and k not in state:
                if k == 'ema':
                    model = getattr(self, 'model', None)
                    if model is not None:
                        ema = dist_utils.de_parallel(v)
                        model_state_dict = remove_module_prefix(model.state_dict())
                        ema.load_state_dict({'module': model_state_dict})
                        print(f'Load {k}.state_dict from model.state_dict')
                else:
                    print(f'Not load {k}.state_dict')


    def load_resume_state(self, path: str):
        """load resume
        """
        # for cuda:0 memory
        if path.startswith('http'):
            state = torch.hub.load_state_dict_from_url(path, map_location='cpu')
        else:
            state = torch.load(path, map_location='cpu')

        self.load_state_dict(state)

    
    def load_tuning_state(self, path: str,):
        """only load model for tuning and skip missed/dismatched keys
        """
        if path.startswith('http'):
            state = torch.hub.load_state_dict_from_url(path, map_location='cpu')
        else:
            state = torch.load(path, map_location='cpu')

        module = dist_utils.de_parallel(self.model)
        
        # TODO hard code
        if 'ema' in state:
            pretrain_state_dict = state['ema']['module']
        else:
            pretrain_state_dict = state['model']

        # Adjust head parameters between datasets
        try:
            adjusted_state_dict = self._adjust_head_parameters(module.state_dict(), pretrain_state_dict)
            stat, infos = self._matched_state(module.state_dict(), adjusted_state_dict)
        except Exception:
            stat, infos = self._matched_state(module.state_dict(), pretrain_state_dict)

        module.load_state_dict(stat, strict=False)
        print(f'Load model.state_dict, {infos}')


    @staticmethod
    def _matched_state(state: Dict[str, torch.Tensor], params: Dict[str, torch.Tensor]):
        missed_list = []
        unmatched_list = []
        matched_state = {}
        for k, v in state.items():
            if k in params:
                if v.shape == params[k].shape:
                    matched_state[k] = params[k]
                else:
                    unmatched_list.append(k)
            else:
                missed_list.append(k)

        return matched_state, {'missed': missed_list, 'unmatched': unmatched_list}

    def _adjust_head_parameters(self, cur_state_dict, pretrain_state_dict):
        """Adjust head parameters between datasets."""
        # List of parameters to adjust
        if pretrain_state_dict['decoder.denoising_class_embed.weight'].size() != \
                cur_state_dict['decoder.denoising_class_embed.weight'].size():
            del pretrain_state_dict['decoder.denoising_class_embed.weight']

        head_param_names = [
            'decoder.enc_score_head.weight',
            'decoder.enc_score_head.bias'
        ]
        for i in range(8):
            head_param_names.append(f'decoder.dec_score_head.{i}.weight')
            head_param_names.append(f'decoder.dec_score_head.{i}.bias')

        adjusted_params = []

        for param_name in head_param_names:
            if param_name in cur_state_dict and param_name in pretrain_state_dict:
                cur_tensor = cur_state_dict[param_name]
                pretrain_tensor = pretrain_state_dict[param_name]
                adjusted_tensor = self.map_class_weights(cur_tensor, pretrain_tensor)
                if adjusted_tensor is not None:
                    pretrain_state_dict[param_name] = adjusted_tensor
                    adjusted_params.append(param_name)
                else:
                    print(f"Cannot adjust parameter '{param_name}' due to size mismatch.")

        return pretrain_state_dict

    def map_class_weights(self, cur_tensor, pretrain_tensor):
        """Map class weights from pretrain model to current model based on class IDs."""
        if pretrain_tensor.size() == cur_tensor.size():
            return pretrain_tensor

        adjusted_tensor = cur_tensor.clone()
        adjusted_tensor.requires_grad = False

        if pretrain_tensor.size() > cur_tensor.size():
            for coco_id, obj_id in enumerate(self.obj365_ids):
                adjusted_tensor[coco_id] = pretrain_tensor[obj_id+1]
        else:
            for coco_id, obj_id in enumerate(self.obj365_ids):
                adjusted_tensor[obj_id+1] = pretrain_tensor[coco_id]

        return adjusted_tensor

    def fit(self):
        raise NotImplementedError('')


    def val(self, ):
        raise NotImplementedError('')
