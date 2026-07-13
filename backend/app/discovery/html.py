from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass(slots=True)
class Anchor:
    href: str
    text: str = ""
    image_url: str | None = None
    image_alt: str | None = None


class RecipeHtmlParser(HTMLParser):
    """Small dependency-free parser for structured scripts and semantic fallback."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld: list[str] = []
        self.anchors: list[Anchor] = []
        self.meta: dict[str, str] = {}
        self.h1_parts: list[str] = []
        self.ingredient_parts: list[list[str]] = []
        self._script_parts: list[str] | None = None
        self._anchor: Anchor | None = None
        self._in_h1 = False
        self._ingredient_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag == "script" and values.get("type", "").lower().split(";")[0].strip() == "application/ld+json":
            self._script_parts = []
        elif tag == "a" and values.get("href"):
            self._anchor = Anchor(values["href"])
        elif tag == "img" and self._anchor is not None:
            # Publisher srcset URLs can contain literal commas in resize query
            # values (for example ``resize=372,338``). Treating every comma as
            # a candidate separator produced invalid paths such as ``/338``.
            # The ordinary image URL is lower resolution but consistently valid.
            self._anchor.image_url = (
                values.get("data-src")
                or values.get("data-lazy-src")
                or values.get("src")
                or self._anchor.image_url
                or None
            )
            self._anchor.image_alt = values.get("alt") or self._anchor.image_alt or None
        elif tag == "meta":
            key = values.get("property") or values.get("name") or values.get("itemprop")
            content = values.get("content")
            if key and content:
                self.meta[key.lower()] = content.strip()
        elif tag == "h1":
            self._in_h1 = True

        itemprop = {part.strip().lower() for part in values.get("itemprop", "").split()}
        if "recipeingredient" in itemprop or "ingredients" in itemprop:
            self._ingredient_depth += 1
            self.ingredient_parts.append([])
        elif self._ingredient_depth:
            self._ingredient_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "script" and self._script_parts is not None:
            self.json_ld.append("".join(self._script_parts))
            self._script_parts = None
        elif tag == "a" and self._anchor is not None:
            self._anchor.text = " ".join(self._anchor.text.split())
            self.anchors.append(self._anchor)
            self._anchor = None
        elif tag == "h1":
            self._in_h1 = False
        if self._ingredient_depth:
            self._ingredient_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._script_parts is not None:
            self._script_parts.append(data)
        if self._anchor is not None:
            self._anchor.text += f" {data}"
        if self._in_h1:
            self.h1_parts.append(data)
        if self._ingredient_depth and self.ingredient_parts:
            self.ingredient_parts[-1].append(data)

    @property
    def h1(self) -> str | None:
        value = " ".join(" ".join(self.h1_parts).split())
        return value or None

    @property
    def ingredients(self) -> tuple[str, ...]:
        values = (" ".join(" ".join(parts).split()) for parts in self.ingredient_parts)
        return tuple(dict.fromkeys(value for value in values if value))
