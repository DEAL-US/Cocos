from typing import List, Iterable
import torch
import torch.nn as nn
from pathlib import Path
from prediction.adapters import (
    ANY_ORGANISM,
    ModelInterface,
    get_columns_from_pickle,
    get_model_weights_path,
    presence_from_list,
    register_model,
)

# --- Model definition ---
class BaselineMLP(nn.Module):
    """
    Simple feed-forward MLP for binary classification.

    Architecture: [Linear -> ReLU -> Dropout] x N  ->  Linear(last_dim, 1)
    Output: raw logits (use BCEWithLogitsLoss for training).
    """

    def __init__(self, input_dim: int, hidden_dims: List[int], dropout: float):
        super().__init__()
        layers: List[nn.Module] = []
        last_dim = input_dim
        for h in hidden_dims:
            layers.append(nn.Linear(last_dim, h))
            layers.append(nn.ReLU(inplace=True))
            if dropout and dropout > 0:
                layers.append(nn.Dropout(dropout))
            last_dim = h
        layers.append(nn.Linear(last_dim, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)

# --- Model Adapter ---
@register_model("base_bakta_90")
class BaseBakta90Adapter(ModelInterface):
    """
    Adapter class from BaselineMLP to the ModelInterface expected by the framework.
    """
    supported_organisms = ANY_ORGANISM

    def __init__(self, antibiotic: str, model_name: str | None = None):
        self.model_name = model_name or "base_bakta_90"
        self.antibiotic = antibiotic
        self.column_file_name = 'columns.pkl'
        self.hidden_dims = [512, 256]
        self.dropout = 0.2

        self._model = None
        self._columns = None
        self._input_dim = None

    def features(self) -> list[str]:
        if self._columns is None:
            self._columns = get_columns_from_pickle(self.model_name, self.column_file_name)
            self._columns = self._process_column_names(self._columns)

        if self._input_dim is None:
            self._input_dim = len(self._columns)
        return self._columns

    def load(self) -> None:
        self.features()
        model = BaselineMLP(input_dim=self._input_dim, hidden_dims=self.hidden_dims, dropout=self.dropout)
        resolved_path = get_model_weights_path(self.antibiotic, self.model_name)

        if not Path(resolved_path).exists():
            raise FileNotFoundError(f"Weights file not found for {self.model_name}/{self.antibiotic}: {resolved_path}")
        
        checkpoint = torch.load(resolved_path, map_location='cpu')
        if isinstance(checkpoint, dict) and 'state_dict' in checkpoint:
            state_dict = checkpoint['state_dict']
        else:
            state_dict = checkpoint

        model.load_state_dict(state_dict)
        model.eval()
        self.model = model

    def predict(self, file) -> float:
        presence = presence_from_list(self._columns, file)

        tensor = torch.FloatTensor([list(presence)])
        with torch.no_grad():
            raw = self.model(tensor)
            prob = torch.sigmoid(raw).squeeze().item()
        return float(prob)
    
    def _process_column_names(self, names: Iterable[str]) -> list[str]:
        names = [n for n in names if not str(n).startswith("a_")]
        out = [n if str(n).startswith("UniRef:UniRef90_") else f"UniRef:UniRef90_{n}" for n in names]
        return out