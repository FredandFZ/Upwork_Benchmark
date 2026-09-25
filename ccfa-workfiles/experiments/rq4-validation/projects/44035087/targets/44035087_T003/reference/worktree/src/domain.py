from __future__ import annotations

from copy import deepcopy


class DomainError(ValueError):
    pass


BANDS = (
    ("under_1200_sqft", "Under 1200 sqft", 1, 1200),
    ("1201_2400_sqft", "1201–2400 sqft", 1201, 2400),
    ("2401_3600_sqft", "2401–3600 sqft", 2401, 3600),
    ("3600_plus_sqft", "3600+ sqft", 3601, None),
)
PACKAGE_PRICES = {"basic": [325, 475, 625, 775], "essential": [450, 625, 800, 975], "premium": [575, 775, 975, 1175], "signature": [725, 950, 1175, 1400]}


class CurrentGalleryQuoteService:
    """Predefined package pricing selected by property square-footage band."""

    def __init__(self):
        self.quotes = []

    def routes(self):
        return [
            {"method": "GET", "path": "/api/pricing"},
            {"method": "POST", "path": "/api/quotes"},
        ]

    @staticmethod
    def _category(square_feet):
        try:
            value = int(square_feet)
        except (TypeError, ValueError) as exc:
            raise DomainError("square_feet must be a positive integer") from exc
        if value < 1:
            raise DomainError("square_feet must be a positive integer")
        if value <= 1200:
            return "under_1200_sqft"
        if value <= 2400:
            return "1201_2400_sqft"
        if value <= 3600:
            return "2401_3600_sqft"
        return "3600_plus_sqft"

    def pricing(self):
        categories = [
            {"key": key, "label": label, "minimum_sqft": low, "maximum_sqft": high}
            for key, label, low, high in BANDS
        ]
        packages = []
        for name, prices in PACKAGE_PRICES.items():
            packages.append({
                "id": name,
                "name": name.title(),
                "prices_by_square_footage": {
                    band[0]: int(prices[index]) for index, band in enumerate(BANDS)
                },
            })
        return {"model": "predefined", "categories": categories, "packages": packages}

    def quote(self, square_feet, package="basic", extras=None):
        package_key = str(package).strip().lower()
        if package_key not in PACKAGE_PRICES:
            raise DomainError("unknown package")
        category = self._category(square_feet)
        band_index = [band[0] for band in BANDS].index(category)
        base = int(PACKAGE_PRICES[package_key][band_index])
        quote = {
            "quote_id": len(self.quotes) + 1,
            "package": package_key,
            "square_feet": int(square_feet),
            "category": category,
            "base_price_usd": base,
            "extras": list(extras or []),
            "total_usd": base,
        }
        self.quotes.append(quote)
        return deepcopy(quote)

    def request(self, method, path, payload=None, query=None):
        payload = payload or {}
        if method == "GET" and path == "/api/pricing":
            return {"status": 200, "body": self.pricing()}
        if method == "POST" and path == "/api/quotes":
            return {"status": 201, "body": self.quote(**payload)}
        return {"status": 404, "body": {"error": "route not found"}}


def make_service():
    return CurrentGalleryQuoteService()

