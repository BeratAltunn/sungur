from .coco import COCO
from .cocoeval import COCOeval
import json
import argparse
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import average_precision_score, precision_recall_curve

def eval_json_classwise(ann_file, det_file):

    coco_gt = COCO(ann_file)
    coco_dt = coco_gt.loadRes(det_file)
    coco_eval = COCOeval(coco_gt,coco_dt,'bbox', print_res=False)

    classwise_results = {}

    for cat_id in coco_gt.getCatIds():

        class_name = coco_gt.loadCats(cat_id)[0]['name']

        print(f"Evaluating class: {class_name}")
        
        coco_eval.params.catIds = [cat_id]
        
        coco_eval.evaluate()
        coco_eval.accumulate()
        results = coco_eval.summarize()
        map30_all = round(results[7], 4)
        classwise_results[class_name] = map30_all

        print(f"Results of class: {class_name} is {map30_all}")

    return classwise_results



def eval_json(ann_file, det_file, print_res):
    coco_gt = COCO(ann_file)
    coco_dt = coco_gt.loadRes(det_file)
    coco_eval = COCOeval(coco_gt,coco_dt,'bbox', print_res=print_res)
    coco_eval.evaluate()
    coco_eval.accumulate()
    results = coco_eval.summarize()
    return results, coco_eval, coco_gt
    
def eval_PR_curve(ann_file, det_file, iou_thrs=0.5, max_dets=100, class_id=1, area_rng='all', output_dir='.'):
    results, coco_eval, coco_gt = eval_json(ann_file=ann_file, det_file=det_file, print_res=False)
    
    # Extract precision-recall data
    pr_data = extract_pr_data(coco_eval, coco_gt, class_id, iou_thrs, max_dets, area_rng)
    
    # Calculate AP using scikit-learn's function
    from sklearn.metrics import auc
    AP = auc(pr_data['recall'], pr_data['precision'])
    
    # Plot PR curve
    plot_pr_curve(pr_data['precision'], pr_data['recall'], pr_data['class_name'], 
                 iou_thrs, area_rng, output_dir, AP)
    
    return {
        'precision': pr_data['precision'].tolist(),
        'recall': pr_data['recall'].tolist(),
        'AP': float(AP),
        'class_name': pr_data['class_name'],
        'iou_threshold': iou_thrs
    }

def plot_pr_curve(precision, recall, class_name, iou_thrs, area_rng, output_dir='.', AP=None):
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
    output_file = f'{output_dir}/PR_curve_{class_name}_iou{iou_thrs}.png'
    plt.savefig(output_file)
    plt.close()
    
    print(f'Precision-Recall curve saved to {output_file}')
    

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

def get_pr_pairs_at_recalls(coco_eval, coco_gt, class_id, recall_values, iou_thrs=0.5, max_dets=100, area_rng='all'):
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
        
    Returns:
        Dictionary containing precision, recall, and score pairs for the specified recall values
    """
    # Get PR data
    pr_data = extract_pr_data(coco_eval, coco_gt, class_id, iou_thrs, max_dets, area_rng)
    
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

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Class-wise evaluation using pycocotools')
    parser.add_argument('--ann_file', type=str, default='tracking_1cls.json', help='Path to the annotation file (ground truth in COCO format)')
    parser.add_argument('--det_file', type=str, default='detections.json', help='Path to the detection file (results in COCO format)')
    parser.add_argument('--output', type=str, default='classwise_results.json', help='Output file for saving class-wise results')
    

    args = parser.parse_args()

    results, coco_eval, coco_gt = eval_json(ann_file=args.ann_file, det_file=args.det_file, print_res=False)
    pr_pairs = get_pr_pairs_at_recalls(coco_eval=coco_eval, coco_gt=coco_gt, class_id=1, recall_values=[0.5, 0.6, 0.7, 0.8, 0.9, 0.95])
    # with open(args.output, 'w') as f:
    #     json.dump(results, f, indent=4)

    print(f"Class-wise evaluation results saved to {args.output}")
