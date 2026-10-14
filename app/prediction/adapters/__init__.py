"""What a prediction model adapter needs: the interface, the registry decorator and input helpers.

    from prediction.adapters import ANY_ORGANISM, ModelInterface, register_model
"""
from .input_utils import get_columns_from_pickle, get_model_weights_path, presence_from_list
from .interface import ModelInterface
from .registry import ANY_ORGANISM, register_model

__all__ = [
    'ANY_ORGANISM',
    'ModelInterface',
    'get_columns_from_pickle',
    'get_model_weights_path',
    'presence_from_list',
    'register_model',
]
