import pickle
from pathlib import Path

# --- For input parsing from db ---
def presence_from_list(model_features, file):
    """
    Create presence/absence vector for `model_features` based on a single `file`.

    Args:
        model_features: iterable of feature names expected by the model (e.g. gene identifiers)
        file: a single `File` instance with a `genes` related manager
    Returns:
        A list of 0/1 values indicating absence/presence of each feature in `model_features`.
    """

    # If file is None or doesn't have genes, return all zeros
    present_features = set()
    genes = getattr(file, 'genes', None)
    if genes is None:
        return [0] * len(list(model_features))

    # Iterate genes and gather identifier lists
    gene_iter = genes.all()

    for gene in gene_iter:
        ids = gene.identifiers_list() or []

        for gid in ids:
            present_features.add(str(gid).strip().lower())

    # Normalize
    model_features_norm = [str(f).strip().lower() for f in model_features]

    presence_vector = [1 if feat in present_features else 0 for feat in model_features_norm]

    return presence_vector

# --- For model loading and prediction ---
def get_columns_from_pickle(model_name: str, column_file_name: str) -> list:
    """
    Load column names from a pickle file for a given model.
    Args:
        model_name: name of the model (used to locate the correct directory)
        column_file_name: name of the pickle file containing the columns (e.g. 'columns.pkl')
    Returns: 
        A list of column names loaded from the pickle file.
    """
    base_dir = Path(__file__).resolve().parents[2]
    pkl_path = base_dir / 'ai_models' / model_name / column_file_name
    with open(pkl_path, 'rb') as f:
        columns = pickle.load(f)
    return columns

def get_model_weights_path(antibiotic: str, model_name: str) -> str:
    """
    Resolve the path to the model weights file based on the antibiotic name and model name.
    Args:
        antibiotic: name of the antibiotic (e.g. 'ampicillin')
        model_name: name of the model (used to locate the correct directory)
    Returns:
        A string path to the .pt file containing the model weights.
    """
    base_dir = Path(__file__).resolve().parents[2]
    weights_dir = base_dir / 'ai_models' / model_name / 'weights'
    candidate = weights_dir / f"{antibiotic}.pt"
    if not candidate.exists():
        raise FileNotFoundError(f"Weights file not found: {candidate}")
    return str(candidate)