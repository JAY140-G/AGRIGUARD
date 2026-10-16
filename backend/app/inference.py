from typing import Protocol
from .schemas import Prediction

class InferenceAdapter(Protocol):
    def analyze(self, data: bytes, crop: str, domain: str) -> Prediction: ...

class DemoAnalyzer:
    """Deterministic display data; no trained model and no diagnostic claims."""
    def analyze(self, data: bytes, crop: str, domain: str) -> Prediction:
        import hashlib
        supported=domain in ('aerial','closeup') and crop.lower() in ('wheat','rice','maize','corn','soybean','cotton')
        labels=['No simulated alert','Suspected water stress','Suspected canopy anomaly'] if domain=='aerial' else ['No simulated alert','Suspected leaf spot','Suspected discoloration']
        label=labels[int(hashlib.sha256(data).hexdigest()[:8],16)%len(labels)] if supported else 'Unsupported crop or image domain'
        return Prediction(label=label,score=None,model_version='demo-hash-v1',supported_crops=['wheat','rice','maize','corn','soybean','cotton'],domain=domain,uncertain=True,unsupported=not supported,simulated=True,analysis_mode='Simulated analysis')

class TorchScriptAdapter:
    """Opt-in extension; never selected automatically. Manifest and domain are mandatory."""
    def __init__(self, model_path, manifest_path):
        import json, torch
        self.torch=torch
        self.meta=json.load(open(manifest_path))
        for key in ('version','domain','crops','labels','validated_aerial'):
            if key not in self.meta: raise ValueError(f'Missing manifest field: {key}')
        if self.meta['domain']=='aerial' and not self.meta['validated_aerial']:
            raise ValueError('Aerial deployment requires labelled aerial evaluation')
        self.model=torch.jit.load(model_path,map_location='cpu').eval()
    def analyze(self,data,crop,domain):
        from PIL import Image
        from io import BytesIO
        from torchvision.transforms import Compose, Resize, ToTensor, Normalize
        unsupported=domain!=self.meta['domain'] or crop.lower() not in self.meta['crops']
        base=dict(model_version=self.meta['version'],supported_crops=self.meta['crops'],domain=self.meta['domain'],simulated=False,analysis_mode='Model prediction')
        if unsupported: return Prediction(label='Unsupported crop or domain',uncertain=True,unsupported=True,**base)
        x=Compose([Resize((224,224)),ToTensor(),Normalize([.485,.456,.406],[.229,.224,.225])])(Image.open(BytesIO(data)).convert('RGB'))
        with self.torch.no_grad(): scores=self.model(x.unsqueeze(0)).softmax(1)[0]
        idx=int(scores.argmax()); score=float(scores[idx])
        return Prediction(label=self.meta['labels'][idx],score=score,uncertain=score<.8,unsupported=False,**base)
