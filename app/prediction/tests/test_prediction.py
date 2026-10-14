from unittest.mock import MagicMock, patch, sentinel

from django.test import TestCase

from prediction.prediction import get_prediction, prepare_prediction_csv

GET_MODEL_ADAPTER = "prediction.prediction.get_model_adapter_class"


def make_mock_adapter(predict_return_value=0.73):
    fake_adapter = MagicMock()
    fake_adapter.predict.return_value = predict_return_value
    fake_cls = MagicMock(return_value=fake_adapter)
    return fake_cls, fake_adapter


class GetPredictionTests(TestCase):
    @patch(GET_MODEL_ADAPTER)
    def test_builds_adapter_loads_and_predicts(self, mock_get_adapter):
        fake_cls, fake_adapter = make_mock_adapter(0.73)
        mock_get_adapter.return_value = fake_cls
        call_order = []
        fake_adapter.load.side_effect = lambda: call_order.append("load")
        fake_adapter.predict.side_effect = lambda _: call_order.append("predict") or 0.73

        result = get_prediction("base_bakta_50", "amikacin", file=sentinel.upload)

        self.assertEqual(result, 0.73)
        mock_get_adapter.assert_called_once_with("base_bakta_50")
        fake_cls.assert_called_once_with(antibiotic="amikacin")
        fake_adapter.predict.assert_called_once_with(sentinel.upload)
        self.assertEqual(call_order, ["load", "predict"])

    @patch(GET_MODEL_ADAPTER, return_value=None)
    def test_unknown_model_raises_with_its_name(self, _):
        with self.assertRaisesRegex(ValueError, "does_not_exist"):
            get_prediction("does_not_exist", "amikacin", file=None)


class PreparePredictionCsvTests(TestCase):
    def test_rounds_values_blanks_missing_and_averages(self):
        matrix = {
            "models": ["a", "b"],
            "antibiotics": ["amikacin", "ampicillin", "colistin"],
            "data": [[0.123456, 0.5], [0.2, "NO_RESULT"], ["NO_RESULT", None]],
        }

        models, rows = prepare_prediction_csv(matrix)

        self.assertEqual(models, ["a", "b"])
        self.assertEqual(rows, [
            ["amikacin", 0.1235, 0.5, 0.3117],
            ["ampicillin", 0.2, "", 0.2],
            ["colistin", "", "", ""],
        ])

    def test_rejects_malformed_matrices(self):
        cases = [
            ("not a dict", []),
            ("missing keys", {"models": ["a"]}),
            ("row count mismatch", {"models": ["a"], "antibiotics": ["x", "y"], "data": [[0.1]]}),
            ("column count mismatch", {"models": ["a", "b"], "antibiotics": ["x"], "data": [[0.1]]}),
        ]
        for label, matrix in cases:
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    prepare_prediction_csv(matrix)
