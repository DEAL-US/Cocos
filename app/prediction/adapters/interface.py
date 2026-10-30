"""AI Model interface and registry.

Provides `ModelInterface` base class and a simple registry to register
model implementations by name. Use `@register_model()` on a subclass
to make it discoverable.
"""


class ModelInterface:
    """
    Model interface for predicting antibiotic resistance from a `File`.

    Implementations should provide:
      - `features()` -> Input features for the model (e.g. genes)
      - `load()` -> None
      - `predict(file)` -> float, or a result (see prediction.results)

    file is expected to be an identifier for a bakta-annotated file in the database (File instance))

    What the model supports (organisms, antibiotics, input) is declared in the descriptor.ttl
    next to it, not in the adapter.
    """

    def features(self) -> list:
        """
        Return the features needed by the model (e.g. gene identifiers).
        """
        raise NotImplementedError()

    def load(self) -> None:
        """
        Load model weights and prepare for prediction.
        """
        raise NotImplementedError()

    def predict(self, file):
        """
        Predict resistance for a given json bakta file: the probability of resistance, or a dict
        with a `call` ('R', 'S' or 'not_detected'), a `score` or both, and optionally its `evidence`.
        """
        raise NotImplementedError()