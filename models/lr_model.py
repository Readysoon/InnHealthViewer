"""L/R classification model (MobileNetV3-Small, 2 classes). Used by VideoClassifier."""
import torch
from torchvision import models


def build_model(num_classes=2, device=None):
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = models.mobilenet_v3_small(weights="IMAGENET1K_V1")
    model.classifier[3] = torch.nn.Linear(
        model.classifier[3].in_features, num_classes
    )
    return model.to(device)
