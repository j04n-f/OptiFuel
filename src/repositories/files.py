from pathlib import Path

from src.schemas import FuelModel


class FileModelRepository:
    """Models as `<model_dir>/<airline>/<version>.json`. JSON, not pickle: loading runs no code."""

    def __init__(self, model_dir: Path) -> None:
        self._dir = model_dir

    def load(self, airline: str, version: str) -> FuelModel:
        path = self._dir / airline / f"{version}.json"
        model = FuelModel.model_validate_json(path.read_bytes())
        # A mis-mounted file must not estimate another airline's fuel.
        if (model.airline, model.version) != (airline, version):
            raise ValueError(f"{path} holds {model.airline} {model.version}")
        return model
