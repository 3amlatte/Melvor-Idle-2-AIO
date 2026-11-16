"""Read-only cooking database extracted from the client.

Only the **Basic Food** category is modelled for now. Each recipe lists its
ingredients, products, level, XP and cook interval. The client renders the
recipe grid row-major in two columns; ``grid_slot`` records the slot the demo
build uses (locked demo recipes occupy some slots), so the task can click the
right card without OCR.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR

DEFAULT_COOKING_DB_PATH = DATA_DIR / "cooking.json"


@dataclass(frozen=True)
class CookingIngredient:
    id: str
    name: str
    quantity: int


@dataclass(frozen=True)
class CookingProduct:
    id: str
    name: str
    quantity: int
    chance: float


@dataclass(frozen=True)
class CookingRecipe:
    id: str
    name: str
    level: int
    demo_locked: bool
    experience: int
    interval_ms: int
    difficulty: int
    grid_slot: int | None
    ingredients: tuple[CookingIngredient, ...]
    products: tuple[CookingProduct, ...]

    @property
    def product(self) -> CookingProduct | None:
        return self.products[0] if self.products else None

    @property
    def product_name(self) -> str:
        product = self.product
        return product.name if product is not None else self.name

    @property
    def interval_label(self) -> str:
        return f"{self.interval_ms / 1000:.1f}s"

    @property
    def ingredients_label(self) -> str:
        return ", ".join(
            f"{item.quantity}x {item.name}" for item in self.ingredients
        )


@dataclass(frozen=True)
class CookingCategory:
    id: str
    name: str
    subcategory: str
    recipes: tuple[CookingRecipe, ...]

    @property
    def available_recipes(self) -> tuple[CookingRecipe, ...]:
        return tuple(recipe for recipe in self.recipes if not recipe.demo_locked)


@dataclass(frozen=True)
class CookingDatabase:
    game: str
    build: str
    source: str
    generated: str
    categories: tuple[CookingCategory, ...]

    def category(self, query: str) -> CookingCategory | None:
        wanted = query.strip().lower()
        for category in self.categories:
            if category.id.lower() == wanted or category.name.lower() == wanted:
                return category
        return None

    def basic_food(self) -> CookingCategory | None:
        return self.category("Basic Food")

    def recipe(self, query: str) -> CookingRecipe | None:
        wanted = query.strip().lower()
        for category in self.categories:
            for recipe in category.recipes:
                if recipe.id.lower() == wanted or recipe.name.lower() == wanted:
                    return recipe
        return None

    def available_recipes(self) -> tuple[CookingRecipe, ...]:
        recipes: list[CookingRecipe] = []
        for category in self.categories:
            recipes.extend(category.available_recipes)
        return tuple(recipes)

    def product_names(self) -> tuple[str, ...]:
        return tuple(
            recipe.product_name
            for category in self.categories
            for recipe in category.recipes
            if not recipe.demo_locked
        )


def _ingredient(raw: Mapping[str, object]) -> CookingIngredient:
    return CookingIngredient(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        quantity=int(raw.get("quantity", 1)),
    )


def _product(raw: Mapping[str, object]) -> CookingProduct:
    return CookingProduct(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        quantity=int(raw.get("quantity", 1)),
        chance=float(raw.get("chance", 1)),
    )


def _recipe(raw: Mapping[str, object]) -> CookingRecipe:
    slot = raw.get("grid_slot")
    return CookingRecipe(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        level=int(raw.get("level", 1)),
        demo_locked=bool(raw.get("demo_locked", False)),
        experience=int(raw.get("experience", 0)),
        interval_ms=int(raw.get("interval_ms", 0)),
        difficulty=int(raw.get("difficulty", 0)),
        grid_slot=int(slot) if slot is not None else None,
        ingredients=tuple(
            _ingredient(item) for item in raw.get("ingredients", [])  # type: ignore[arg-type]
        ),
        products=tuple(
            _product(item) for item in raw.get("products", [])  # type: ignore[arg-type]
        ),
    )


def _category(raw: Mapping[str, object]) -> CookingCategory:
    return CookingCategory(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        subcategory=str(raw.get("subcategory", "")),
        recipes=tuple(
            _recipe(item) for item in raw.get("recipes", [])  # type: ignore[arg-type]
        ),
    )


@lru_cache(maxsize=4)
def _load(path: str) -> CookingDatabase:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return CookingDatabase(
        game=str(raw.get("game", "")),
        build=str(raw.get("build", "")),
        source=str(raw.get("source", "")),
        generated=str(raw.get("generated", "")),
        categories=tuple(
            _category(item) for item in raw.get("categories", [])
        ),
    )


def load_cooking(path: str | Path | None = None) -> CookingDatabase:
    """Load the cooking database (cached per path)."""
    return _load(str(path or DEFAULT_COOKING_DB_PATH))
