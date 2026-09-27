from .coco import COCO
from .cocoeval import COCOeval
from .mask import encode, decode
from .eval import eval_json_classwise, eval_json, eval_PR_curve, plot_pr_curve, extract_pr_data, get_pr_pairs_at_recalls

__version__ = '2.0' 