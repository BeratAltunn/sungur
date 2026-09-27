"""
DEIM: DETR with Improved Matching for Fast Convergence
Copyright (c) 2024 The DEIM Authors. All Rights Reserved.
---------------------------------------------------------------------------------
Modified from RT-DETR (https://github.com/lyuwenyu/RT-DETR)
Copyright (c) 2023 lyuwenyu. All Rights Reserved.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# Disable UCX to prevent segmentation faults with PyTorch distributed
os.environ.setdefault('UCX_TLS', '')
os.environ.setdefault('UCX_MEMTYPE_CACHE', 'n')
os.environ.setdefault('UCX_IB_GPU_DIRECT_RDMA', 'no')

from engine.misc import dist_utils
from engine.misc.hydra_entry import run_with_hydra
from engine.core import YAMLConfig, yaml_utils
from engine.solver import TASKS
import cv2
cv2.setNumThreads(0)
import torch

torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True  # Kararlılık için ekleyin
debug=False

if debug:
    import torch
    def custom_repr(self):
        return f'{{Tensor:{tuple(self.shape)}}} {original_repr(self)}'
    original_repr = torch.Tensor.__repr__
    torch.Tensor.__repr__ = custom_repr

def main(args, ) -> None:
    """main
    """
    if args.device is not None and str(args.device) != "":
        os.environ['CUDA_VISIBLE_DEVICES'] = str(args.device)

    # Initialize distributed environment first
    dist_utils.setup_distributed(args.print_rank, args.print_method, seed=args.seed, deterministic=True)

    assert not all([args.tuning, args.resume]), \
        'Only support from_scrach or resume or tuning at one time'

    update_dict = yaml_utils.parse_cli(args.update)
    update_dict.update({k: v for k, v in args.__dict__.items() \
        if k not in ['update', ] and v is not None})

    cfg = YAMLConfig(args.config, **update_dict)

    if args.resume or args.tuning:
        if 'HGNetv2' in cfg.yaml_cfg:
            cfg.yaml_cfg['HGNetv2']['pretrained'] = False

    print('cfg: ', cfg.__dict__)

    # Ensure distributed is properly initialized before creating solver
    solver = TASKS[cfg.yaml_cfg['task']](cfg)

    if args.test_only:
        solver.val()
    else:
        solver.fit()

    dist_utils.cleanup()


if __name__ == '__main__':
    defaults = {
        'config': 'configs/deim_dfine/dfine_hgnetv2_m_coco.yml',
        'resume': None,
        'tuning': None,
        'device': None,
        'seed': 10,
        'use_amp': None,
        'summary_dir': None,
        'test_only': False,
        'update': None,
        'print_method': 'builtin',
        'print_rank': 0,
        'local_rank': 0,
        'master_port': 7777,
        'nproc_per_node': 1,
    }
    run_with_hydra(main, defaults, job_name='train_0')
