"""Trainable four-layer MaAS policy controller."""
from __future__ import annotations
from typing import Any, Sequence
from ..contracts import EARLY_STOP_OPERATOR, GENERATE_OPERATOR, OPERATOR_SELECTION_THRESHOLD, FIRST_LAYER_EARLY_STOP_LOG_PROB_ADJUSTMENT

def _torch():
    try:
        import torch, torch.nn.functional as F
        return torch, F
    except ImportError as exc: raise ImportError("MultiLayerController requires PyTorch") from exc


def sample_operators(probs, threshold: float = 0.25):
    """Mirror the source MaAS cumulative, without-replacement sampler."""
    torch, _ = _torch()
    device = probs.device
    probs = probs.detach()
    num_ops = probs.size(0)
    if num_ops == 0:
        return torch.tensor([], dtype=torch.long, device=device)

    selected = torch.tensor([], dtype=torch.long, device=device)
    cumulative = 0.0
    remaining = torch.arange(num_ops, device=device)
    while cumulative < threshold and remaining.numel() > 0:
        sampled = torch.multinomial(probs[remaining], num_samples=1)
        index = remaining[sampled].squeeze()
        if not torch.any(selected == index):
            selected = torch.cat([selected, index.unsqueeze(0)])
            cumulative += probs[index].item()
        mask = torch.ones_like(remaining, dtype=torch.bool)
        mask[sampled] = False
        remaining = remaining[mask]

    if selected.numel() == 0:
        selected = probs.argmax().unsqueeze(0)
    return selected

class OperatorSelector:
    def __new__(cls, *args, **kwargs):
        torch, _ = _torch()
        class _Selector(torch.nn.Module):
            def __init__(self, input_dim=384, hidden_dim=32, is_first_layer=False):
                super().__init__(); self.is_first_layer=is_first_layer
                self.operator_encoder=torch.nn.Linear(input_dim if is_first_layer else input_dim*2, hidden_dim)
                self.query_encoder=torch.nn.Linear(input_dim, hidden_dim)
            def forward(self, query, operators, previous=None):
                _, F = _torch(); query= query.unsqueeze(0) if query.dim()==1 else query
                q=F.normalize(self.query_encoder(query),p=2,dim=1)
                op=operators
                if previous is not None and not self.is_first_layer:
                    op=torch.cat([op, previous[0].unsqueeze(0).expand(op.size(0),-1)],dim=1)
                op=F.normalize(self.operator_encoder(op),p=2,dim=1); scores=q@op.T
                return torch.log_softmax(scores,dim=1), torch.softmax(scores,dim=1)
        return _Selector(*args, **kwargs)

class MultiLayerController:
    def __new__(cls, input_dim=384, hidden_dim=32, num_layers=4, device=None, embedding_provider=None):
        torch, _ = _torch()
        class _Controller(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.device = torch.device(device) if device is not None else torch.device(
                    "cuda" if torch.cuda.is_available() else "cpu"
                )
                self.embedding_provider=embedding_provider
                self.layers=torch.nn.ModuleList([OperatorSelector(input_dim,hidden_dim,is_first_layer=i==0) for i in range(num_layers)])
                # All policy modules must exist before the module tree is moved.
                self.to(self.device)
            def forward(self, query: str, operators_embedding, selection_operator_names: Sequence[str], log_path=None):
                if self.embedding_provider is None: raise ValueError("embedding_provider is required")
                if GENERATE_OPERATOR not in selection_operator_names:
                    raise ValueError("selection_operator_names must contain Generate")
                q=self.embedding_provider.encode(query).to(self.device); ops=operators_embedding.to(self.device); logs=[]; names=[]; prev=None
                for i, layer in enumerate(self.layers):
                    lp, probs=layer(q,ops,prev); p=probs.squeeze(0)
                    selected=sample_operators(p, threshold=OPERATOR_SELECTION_THRESHOLD)
                    selected_names=[selection_operator_names[int(x)] for x in selected]
                    penalty=False
                    if i==0 and any(n.lower()==EARLY_STOP_OPERATOR.lower() for n in selected_names):
                        selected=torch.tensor([selection_operator_names.index(GENERATE_OPERATOR)],device=self.device); selected_names=[GENERATE_OPERATOR]; penalty=True
                    elif i==0 and not any("generate" in n.lower() for n in selected_names):
                        selected=torch.tensor([selection_operator_names.index(GENERATE_OPERATOR)],device=self.device); selected_names=[GENERATE_OPERATOR]
                    elif i==0 and "generate" not in selected_names[0].lower():
                        generate_position=next(
                            position for position, name in enumerate(selected_names)
                            if "generate" in name.lower()
                        )
                        order=[generate_position, *range(generate_position), *range(generate_position+1, len(selected_names))]
                        selected=selected[torch.tensor(order, dtype=torch.long, device=selected.device)]
                        selected_names=[selected_names[position] for position in order]
                    value=lp.squeeze(0)[selected].sum()
                    if penalty: value=value + torch.as_tensor(FIRST_LAYER_EARLY_STOP_LOG_PROB_ADJUSTMENT,device=value.device,dtype=value.dtype)
                    logs.append(value); names.append(selected_names); prev=ops[selected]
                    if penalty or any(n.lower()==EARLY_STOP_OPERATOR.lower() for n in selected_names): break
                return logs, names
        return _Controller()

__all__ = ["OperatorSelector", "MultiLayerController", "sample_operators"]
