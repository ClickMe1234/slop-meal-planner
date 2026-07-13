from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from ..models import NormalizedFood


class FoodDataProvider(ABC):
    """Provider boundary; network clients may be injected outside normalisation."""

    key: str

    @abstractmethod
    def normalise_record(self, payload: Mapping[str, object]) -> NormalizedFood:
        """Convert one provider response to the application's per-100g model."""
