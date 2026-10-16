"""Explicit transfer learning. Running this command downloads official ResNet18 weights (~45 MB)."""
import argparse,json,random
from pathlib import Path
from common import validate,dataset

def main():
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('manifest');p.add_argument('--epochs',type=int,default=5);p.add_argument('--output',default='runs/experiment');a=p.parse_args()
    if not 1<=a.epochs<=100:raise ValueError('epochs must be 1..100')
    rows,meta=validate(a.csv,a.manifest)
    import torch
    from torch.utils.data import DataLoader
    from torchvision.models import resnet18,ResNet18_Weights
    torch.manual_seed(42);random.seed(42);torch.set_num_threads(2)
    model=resnet18(weights=ResNet18_Weights.DEFAULT)
    for param in model.parameters():param.requires_grad=False
    model.fc=torch.nn.Linear(model.fc.in_features,len(meta['labels']))
    opt=torch.optim.Adam(model.fc.parameters(),lr=.001);loss_fn=torch.nn.CrossEntropyLoss()
    train=DataLoader(dataset(rows,meta,'train'),batch_size=16,shuffle=True)
    val=DataLoader(dataset(rows,meta,'val'),batch_size=16)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True);history=[];best=-1
    for epoch in range(a.epochs):
        model.eval();model.fc.train();total_loss=0
        for x,y in train:
            opt.zero_grad();loss=loss_fn(model(x),y);loss.backward();opt.step();total_loss+=float(loss.detach())
        model.eval();correct=total=0
        with torch.no_grad():
            for x,y in val:correct+=int((model(x).argmax(1)==y).sum());total+=len(y)
        accuracy=correct/total
        history.append({'epoch':epoch+1,'train_loss':total_loss/len(train),'validation_accuracy':accuracy,'validation_samples':total})
        if accuracy>best:
            best=accuracy;torch.jit.script(model).save(str(out/'model.pt'))
        print(json.dumps(history[-1]))
    # Training never confers aerial deployment validation.
    meta['validated_aerial']=False
    (out/'manifest.json').write_text(json.dumps(meta,indent=2));(out/'training_metrics.json').write_text(json.dumps(history,indent=2))
if __name__=='__main__':main()
