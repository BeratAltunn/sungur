import os
import json
import cv2
from pycocotools.coco import COCO

def draw_detections_from_json(detections_path, annotation_path, images_dir, output_dir, score_threshold=0.3):
    """
    Draws bounding boxes from a detections.json file onto the corresponding images.

    Args:
        detections_path (str): Path to the detections JSON file.
        annotation_path (str): Path to the COCO annotation file.
        images_dir (str): Path to the directory containing the images.
        output_dir (str): Directory to save the output images.
        score_threshold (float): Threshold for drawing detections.
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Load detections
    with open(detections_path, 'r') as f:
        detections = json.load(f)

    # Initialize COCO API
    coco = COCO(annotation_path)

    # Group detections by image_id for efficient processing
    detections_by_image = {}
    for det in detections:
        img_id = det['image_id']
        if img_id not in detections_by_image:
            detections_by_image[img_id] = []
        detections_by_image[img_id].append(det)

    # Process each image that has detections
    for img_id, dets in detections_by_image.items():
        # Get image info
        img_info = coco.loadImgs(img_id)[0]
        img_path = os.path.join(images_dir, img_info['file_name'])
        
        if not os.path.exists(img_path):
            print(f"Warning: Image not found at {img_path}")
            continue

        image = cv2.imread(img_path)

        # Draw each detection on the image
        for det in dets:
            if det['score'] >= score_threshold:
                bbox = det['bbox']
                x, y, w, h = bbox
                x1, y1, x2, y2 = int(x), int(y), int(x + w), int(y + h)
                
                # Draw rectangle
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2) # Red color

                # Prepare text
                label = coco.loadCats(det['category_id'])[0]['name']
                text = f"{label}: {det['score']:.2f}"
                
                # Draw text with a background
                (text_w, text_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                cv2.rectangle(image, (x1, y1 - 20), (x1 + text_w, y1), (0, 0, 255), -1)
                cv2.putText(image, text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # Save the annotated image
        output_image_path = os.path.join(output_dir, f"det_{img_info['file_name']}")
        cv2.imwrite(output_image_path, image)
        print(f"Saved annotated image to {output_image_path}")
        
        
draw_detections_from_json(
    detections_path='output_trk_sliding/checkpoints/22082025_155605/detections/detections_9.json',
    annotation_path='tracking_dataset_v2/annotations/tracking_1cls_hp.json',
    images_dir='tracking_dataset_v2/images',
    output_dir='output_trk_sliding/debug_images'
)